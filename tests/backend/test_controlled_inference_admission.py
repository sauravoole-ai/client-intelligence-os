import os
import asyncio
import threading
from pathlib import Path
from collections.abc import Generator
from uuid import uuid4

import httpx
import pytest
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from fastapi import HTTPException
from starlette.requests import Request
from types import SimpleNamespace

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.api.routes import auth as auth_route
from backend.app.security.admission import (
    FixedWindowLimiter,
    InferenceAdmissionController,
    RateLimitExceeded,
    RatePolicy,
)
from backend.app.security.admission import create_app_admission_controls
from backend.app.api.admission import admit_analysis
from backend.app.db.session import Base, get_db_session
from backend.app.api.routes import analyses as analyses_route
from backend.app.models.action_item import ActionItemRecord
from backend.app.security.sessions import session_cookie_name
from backend.app.services.analysis_service import analyse_conversation
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from tests.backend.auth_helpers import authenticate_test_client


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


@pytest.fixture
def controlled_api(tmp_path: Path) -> Generator[tuple[TestClient, object], None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'controlled-api.sqlite').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session)
    app = create_app(Settings(application_abuse_controls_enabled=True))
    def override() -> Generator[Session, None, None]:
        with factory() as session:
            yield session
    app.dependency_overrides[get_db_session] = override
    client = TestClient(app)
    authenticate_test_client(client, factory)
    yield client, app
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def controlled_app_factory(tmp_path: Path):
    engines = []

    def build(**setting_overrides: object):
        engine = create_engine(f"sqlite:///{(tmp_path / f'{uuid4()}.sqlite').as_posix()}")
        engines.append(engine)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, class_=Session)
        app = create_app(Settings(application_abuse_controls_enabled=True, **setting_overrides))

        def override() -> Generator[Session, None, None]:
            with factory() as session:
                yield session

        app.dependency_overrides[get_db_session] = override
        return app, factory

    yield build
    for engine in engines:
        engine.dispose()


def authenticated_client(app: object, factory: sessionmaker[Session]) -> tuple[TestClient, str]:
    client = TestClient(app)
    _, workspace_id = authenticate_test_client(client, factory)
    return client, workspace_id


def asynchronous_auth_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(session_cookie_name())
    assert token is not None
    return {
        "Cookie": f"{session_cookie_name()}={token}",
        "X-CSRF-Token": client.headers["X-CSRF-Token"],
    }


ANALYSIS_PAYLOAD = {
    "conversation": "Day 1\nClient: I slept seven hours and drank enough water today.\nCoach: Keep tracking sleep and hydration every day.",
    "engine_mode": "deterministic",
}


def assert_capacity_response(response: httpx.Response) -> None:
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert response.json() == {"detail": "Analysis capacity is temporarily unavailable."}


def test_fixed_window_accepts_exact_limit_then_returns_retry_after() -> None:
    clock = Clock()
    limiter = FixedWindowLimiter(max_keys=4, clock=clock)
    policy = RatePolicy(limit=2, window_seconds=10)

    limiter.consume("workspace-a", policy)
    limiter.consume("workspace-a", policy)

    with pytest.raises(RateLimitExceeded) as blocked:
        limiter.consume("workspace-a", policy)

    assert blocked.value.retry_after == 10


def test_fixed_window_expiry_reclaims_allowance_and_expired_state() -> None:
    clock = Clock()
    limiter = FixedWindowLimiter(max_keys=2, clock=clock)
    policy = RatePolicy(limit=1, window_seconds=10)
    limiter.consume("one", policy)
    limiter.consume("two", policy)
    assert limiter.tracked_key_count == 2

    clock.value = 10
    limiter.consume("three", policy)

    assert limiter.tracked_key_count == 1


def test_full_state_fails_closed_without_allocating_new_key() -> None:
    limiter = FixedWindowLimiter(max_keys=1, clock=Clock())
    policy = RatePolicy(limit=1, window_seconds=60)
    limiter.consume("first", policy)

    with pytest.raises(RateLimitExceeded) as blocked:
        limiter.consume("new", policy)

    assert blocked.value.retry_after == 1
    assert limiter.tracked_key_count == 1


def test_analysis_windows_charge_atomically_only_when_both_can_admit() -> None:
    clock = Clock()
    limiter = FixedWindowLimiter(max_keys=4, clock=clock)
    short = RatePolicy(limit=2, window_seconds=600)
    daily = RatePolicy(limit=1, window_seconds=86400)
    limiter.consume_many("workspace-a", (short, daily))

    with pytest.raises(RateLimitExceeded):
        limiter.consume_many("workspace-a", (short, daily))

    # A failed daily check must not consume the remaining short-window slot.
    assert limiter.remaining("workspace-a", short) == 1


def test_inference_lease_limits_workspace_and_global_then_cleans_up() -> None:
    controller = InferenceAdmissionController(workspace_limit=1, global_limit=2)
    first = controller.acquire("workspace-a")
    second = controller.acquire("workspace-b")

    assert first is not None
    assert second is not None
    assert controller.acquire("workspace-a") is None
    assert controller.acquire("workspace-c") is None

    first.release()
    second.release()

    assert controller.active_count == 0
    assert controller.active_workspace_count == 0


def test_inference_lease_releases_after_exception() -> None:
    controller = InferenceAdmissionController(workspace_limit=1, global_limit=1)

    with pytest.raises(RuntimeError):
        with controller.acquire_or_raise("workspace-a"):
            raise RuntimeError("provider failed")

    assert controller.acquire("workspace-a") is not None


def test_controller_never_holds_lock_while_lease_is_active() -> None:
    controller = InferenceAdmissionController(workspace_limit=1, global_limit=1)
    lease = controller.acquire("workspace-a")
    assert lease is not None
    finished = threading.Event()

    def release() -> None:
        lease.release()
        finished.set()

    thread = threading.Thread(target=release)
    thread.start()
    thread.join(timeout=1)
    assert finished.is_set()


def test_invalid_completion_ceiling_is_rejected_by_settings() -> None:
    with pytest.raises(ValueError, match="groq_max_completion_tokens"):
        Settings(groq_max_completion_tokens=0)


def test_production_rejects_disabled_abuse_controls() -> None:
    with pytest.raises(ValueError, match="APPLICATION_ABUSE_CONTROLS_ENABLED"):
        Settings(
            environment="production",
            auth_cookie_secure=True,
            database_url="postgresql+psycopg://user:pass@db.example/app",
            trusted_hosts=["app.example"],
            app_origin="https://app.example",
            auth_callback_url="https://app.example/api/v1/auth/callback",
            application_abuse_controls_enabled=False,
        )


def test_login_rate_limit_uses_asgi_client_not_spoofed_xff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OAuthClient:
        async def authorize_redirect(self, *_: object) -> RedirectResponse:
            return RedirectResponse("https://identity.example/authorize")

    monkeypatch.setattr(auth_route, "_oauth_client", lambda: OAuthClient())
    app = create_app(Settings(application_abuse_controls_enabled=True))
    with TestClient(app) as client:
        for _ in range(5):
            assert client.get("/api/v1/auth/login", follow_redirects=False).status_code == 307
        response = client.get(
            "/api/v1/auth/login",
            headers={"X-Forwarded-For": "203.0.113.9"},
            follow_redirects=False,
        )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "600"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_production_runner_explicitly_pins_one_worker_and_proxy_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app import run_production

    captured: dict[str, object] = {}
    monkeypatch.setattr(run_production.settings, "port", 8010)
    monkeypatch.setattr(run_production.settings, "trusted_proxy_ips", ["10.0.0.0/8"])
    monkeypatch.setattr(run_production.uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))

    run_production.run()

    assert captured == {
        "host": "0.0.0.0",
        "port": 8010,
        "workers": 1,
        "reload": False,
        "server_header": False,
        "access_log": False,
        "proxy_headers": True,
        "forwarded_allow_ips": "10.0.0.0/8",
    }


def test_concurrency_rejection_charges_short_attempt_but_not_daily_quota() -> None:
    settings = Settings(application_abuse_controls_enabled=True)
    controls = create_app_admission_controls(settings)
    app = SimpleNamespace(state=SimpleNamespace(admission_controls=controls, settings=settings))
    request = Request({"type": "http", "app": app, "headers": [], "method": "POST", "path": "/"})
    held = controls.inference.acquire("workspace-a")
    assert held is not None

    with pytest.raises(HTTPException) as rejected:
        with admit_analysis(request, "workspace-a"):
            raise AssertionError("must not enter")

    assert rejected.value.status_code == 503
    assert controls.analysis_short.remaining("workspace-a", controls.policies.analysis_short) == 5
    assert controls.analysis_daily.remaining("workspace-a", controls.policies.analysis_daily) == 30


def test_daily_rejection_releases_reserved_inference_capacity() -> None:
    settings = Settings(application_abuse_controls_enabled=True, analysis_daily_rate_limit=1)
    controls = create_app_admission_controls(settings)
    controls.analysis_daily.consume("workspace-a", controls.policies.analysis_daily)
    app = SimpleNamespace(state=SimpleNamespace(admission_controls=controls, settings=settings))
    request = Request({"type": "http", "app": app, "headers": [], "method": "POST", "path": "/"})

    with pytest.raises(HTTPException) as rejected:
        with admit_analysis(request, "workspace-a"):
            raise AssertionError("must not enter")

    assert rejected.value.status_code == 429
    assert controls.inference.active_count == 0
    assert controls.inference.active_workspace_count == 0


def test_public_auth_pool_exhaustion_does_not_starve_workspace_pool() -> None:
    settings = Settings(application_abuse_controls_enabled=True, rate_limiter_max_keys=2)
    controls = create_app_admission_controls(settings)
    controls.auth_login.consume("198.51.100.1", controls.policies.login)
    controls.auth_login.consume("198.51.100.2", controls.policies.login)
    with pytest.raises(RateLimitExceeded):
        controls.auth_login.consume("198.51.100.3", controls.policies.login)

    controls.workspace_read.consume("workspace-new", controls.policies.workspace_read)
    assert controls.auth_login.tracked_key_count == 2
    assert controls.workspace_read.tracked_key_count == 1


@pytest.mark.parametrize(
    ("full_pool", "full_policy", "independent_pool", "independent_policy"),
    [
        ("workspace_read", "workspace_read", "workspace_mutation", "workspace_mutation"),
        ("workspace_mutation", "workspace_mutation", "workspace_read", "workspace_read"),
        ("analysis_short", "analysis_short", "analysis_daily", "analysis_daily"),
        ("analysis_daily", "analysis_daily", "analysis_short", "analysis_short"),
    ],
)
def test_full_policy_pool_does_not_starve_independent_policy_pool(
    full_pool: str,
    full_policy: str,
    independent_pool: str,
    independent_policy: str,
) -> None:
    controls = create_app_admission_controls(
        Settings(application_abuse_controls_enabled=True, rate_limiter_max_keys=2)
    )
    full_limiter = getattr(controls, full_pool)
    full_rate = getattr(controls.policies, full_policy)
    independent_limiter = getattr(controls, independent_pool)
    independent_rate = getattr(controls.policies, independent_policy)
    full_limiter.consume("one", full_rate)
    full_limiter.consume("two", full_rate)
    assert full_limiter.tracked_key_count == 2
    with pytest.raises(RateLimitExceeded):
        full_limiter.consume("three", full_rate)

    independent_limiter.consume("three", independent_rate)
    assert independent_limiter.tracked_key_count == 1


def test_missing_client_source_uses_single_bounded_fallback_key() -> None:
    settings = Settings(application_abuse_controls_enabled=True, auth_login_rate_limit=2)
    controls = create_app_admission_controls(settings)
    app = SimpleNamespace(state=SimpleNamespace(admission_controls=controls))
    request = Request({"type": "http", "app": app, "headers": [], "method": "GET", "path": "/"})
    assert auth_route._source_ip(request) == "unknown-source"
    controls.auth_login.consume(auth_route._source_ip(request), controls.policies.login)
    controls.auth_login.consume(auth_route._source_ip(request), controls.policies.login)
    with pytest.raises(RateLimitExceeded):
        controls.auth_login.consume(auth_route._source_ip(request), controls.policies.login)
    assert controls.auth_login.tracked_key_count == 1


def test_app_factories_do_not_share_limiter_or_inference_state() -> None:
    first = create_app(Settings(application_abuse_controls_enabled=True))
    second = create_app(Settings(application_abuse_controls_enabled=True))
    first_controls = first.state.admission_controls
    second_controls = second.state.admission_controls
    first_controls.workspace_read.consume("workspace-a", first_controls.policies.workspace_read)
    lease = first_controls.inference.acquire("workspace-a")

    assert second_controls.workspace_read.tracked_key_count == 0
    assert second_controls.inference.active_count == 0
    assert lease is not None
    lease.release()


@pytest.mark.parametrize("proxy", ["203.0.113.7", "203.0.113.0/24", "2001:db8::1", "2001:db8::/64"])
def test_production_accepts_explicit_proxy_ip_or_network(proxy: str) -> None:
    configured = Settings(
        environment="production", auth_cookie_secure=True,
        database_url="postgresql+psycopg://user:pass@db.example/app",
        trusted_hosts=["app.example"], app_origin="https://app.example",
        auth_callback_url="https://app.example/api/v1/auth/callback",
        application_abuse_controls_enabled=True, trusted_proxy_ips=[proxy],
    )
    assert configured.trusted_proxy_ips == [proxy]


@pytest.mark.parametrize("proxy", [[], ["*"], ["not-a-network"]])
def test_production_rejects_unsafe_proxy_configuration(proxy: list[str]) -> None:
    with pytest.raises(ValueError):
        Settings(
            environment="production", auth_cookie_secure=True,
            database_url="postgresql+psycopg://user:pass@db.example/app",
            trusted_hosts=["app.example"], app_origin="https://app.example",
            auth_callback_url="https://app.example/api/v1/auth/callback",
            application_abuse_controls_enabled=True, trusted_proxy_ips=proxy,
        )


def test_runner_ignores_ambient_worker_and_forwarded_proxy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app import run_production
    captured: dict[str, object] = {}
    monkeypatch.setenv("WEB_CONCURRENCY", "99")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    monkeypatch.setattr(run_production.settings, "trusted_proxy_ips", ["10.0.0.0/8"])
    monkeypatch.setattr(run_production.uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))
    run_production.run()
    assert captured["workers"] == 1
    assert captured["forwarded_allow_ips"] == "10.0.0.0/8"


def test_analysis_uses_analysis_quota_not_workspace_mutation_quota(controlled_api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, app = controlled_api
    controls = app.state.admission_controls
    calls = 0
    def provider(_: object):
        nonlocal calls
        calls += 1
        raise ValueError("invalid transcript")
    monkeypatch.setattr(analyses_route, "run_analysis", provider)
    response = client.post("/api/v1/analyses", json={"conversation": "Day 1\nClient: I slept seven hours and drank enough water today.\nCoach: Keep tracking sleep and hydration every day.", "engine_mode": "deterministic"})
    workspace = client._test_workspace_id  # type: ignore[attr-defined]
    assert response.status_code == 422
    assert calls == 1
    assert controls.workspace_mutation.remaining(workspace, controls.policies.workspace_mutation) == 30
    assert controls.analysis_short.remaining(workspace, controls.policies.analysis_short) == 5


def test_health_routes_do_not_consume_workspace_limiters(controlled_api) -> None:
    client, app = controlled_api
    controls = app.state.admission_controls
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health/ready").status_code in {200, 503}
    assert controls.workspace_read.tracked_key_count == 0
    assert controls.workspace_mutation.tracked_key_count == 0
    assert controls.analysis_short.tracked_key_count == 0
    assert controls.analysis_daily.tracked_key_count == 0


@pytest.mark.parametrize("policy_name", ["analysis_short", "analysis_daily"])
def test_analysis_quota_rejection_never_calls_provider_and_has_security_headers(controlled_api, monkeypatch, policy_name: str) -> None:
    client, app = controlled_api
    controls = app.state.admission_controls
    workspace = client._test_workspace_id  # type: ignore[attr-defined]
    policy = getattr(controls.policies, policy_name)
    limiter = getattr(controls, policy_name)
    for _ in range(policy.limit):
        limiter.consume(workspace, policy)
    calls = 0
    def provider(_: object):
        nonlocal calls
        calls += 1
        raise AssertionError("rejected request reached provider")
    monkeypatch.setattr(analyses_route, "run_analysis", provider)
    response = client.post("/api/v1/analyses", json={"conversation": "Day 1\nClient: I slept seven hours and drank enough water today.\nCoach: Keep tracking sleep and hydration every day.", "engine_mode": "deterministic"})
    assert response.status_code == 429
    assert calls == 0
    assert int(response.headers["retry-after"]) >= 1
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("held_workspaces", [("workspace-a",), ("workspace-a", "workspace-b")])
def test_api_concurrency_rejection_never_calls_provider_or_daily_quota(controlled_api, monkeypatch, held_workspaces: tuple[str, ...]) -> None:
    client, app = controlled_api
    controls = app.state.admission_controls
    workspace = client._test_workspace_id  # type: ignore[attr-defined]
    leases = [controls.inference.acquire(workspace if len(held_workspaces) == 1 else item) for item in held_workspaces]
    assert all(leases)
    daily_before = controls.analysis_daily.remaining(workspace, controls.policies.analysis_daily)
    calls = 0
    def provider(_: object):
        nonlocal calls
        calls += 1
        raise AssertionError("rejected request reached provider")
    monkeypatch.setattr(analyses_route, "run_analysis", provider)
    response = client.post("/api/v1/analyses", json={"conversation": "Day 1\nClient: I slept seven hours and drank enough water today.\nCoach: Keep tracking sleep and hydration every day.", "engine_mode": "deterministic"})
    for lease in leases:
        lease.release()
    assert response.status_code == 503
    assert calls == 0
    assert response.headers["retry-after"] == "5"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert controls.analysis_daily.remaining(workspace, controls.policies.analysis_daily) == daily_before


def test_exhausted_attacker_cannot_turn_foreign_client_analysis_into_rate_or_provider_oracle(
    controlled_app_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, factory = controlled_app_factory(analysis_short_rate_limit=1)
    attacker, attacker_workspace = authenticated_client(app, factory)
    victim, _ = authenticated_client(app, factory)
    provider_calls = 0

    def provider(payload: object):
        nonlocal provider_calls
        provider_calls += 1
        return analyse_conversation(payload)

    monkeypatch.setattr(analyses_route, "run_analysis", provider)

    victim_client = victim.post("/api/v1/clients", json={"display_name": "Victim", "external_reference": "victim-1"})
    assert victim_client.status_code == 201
    assert attacker.post("/api/v1/analyses", json=ANALYSIS_PAYLOAD).status_code == 201
    controls = app.state.admission_controls
    short = controls.policies.analysis_short
    assert controls.analysis_short.remaining(attacker_workspace, short) == 0

    foreign = attacker.post(
        "/api/v1/analyses",
        json={**ANALYSIS_PAYLOAD, "client_id": victim_client.json()["id"]},
    )
    assert foreign.status_code == 404
    assert provider_calls == 1
    assert controls.analysis_short.remaining(attacker_workspace, short) == 0
    assert attacker.post("/api/v1/analyses", json=ANALYSIS_PAYLOAD).status_code == 429


def test_exhausted_attacker_cannot_turn_foreign_analysis_review_into_quota_or_conflict_oracle(
    controlled_app_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, factory = controlled_app_factory(workspace_mutation_rate_limit=2)
    attacker, attacker_workspace = authenticated_client(app, factory)
    victim, _ = authenticated_client(app, factory)
    monkeypatch.setattr(analyses_route, "run_analysis", analyse_conversation)

    victim_analysis = victim.post("/api/v1/analyses", json=ANALYSIS_PAYLOAD)
    attacker_analysis = attacker.post("/api/v1/analyses", json=ANALYSIS_PAYLOAD)
    assert victim_analysis.status_code == attacker_analysis.status_code == 201
    victim_id = victim_analysis.json()["analysis_id"]
    assert victim.put(f"/api/v1/analyses/{victim_id}/review", json={"review_status": "approved", "expected_version": 1}).status_code == 200
    assert victim.put(
        f"/api/v1/analyses/{victim_id}/review",
        json={"review_status": "changes_requested", "review_note": "stale", "expected_version": 1},
    ).status_code == 409

    for reference in ("attacker-1", "attacker-2"):
        assert attacker.post("/api/v1/clients", json={"display_name": reference, "external_reference": reference}).status_code == 201
    controls = app.state.admission_controls
    mutation = controls.policies.workspace_mutation
    assert controls.workspace_mutation.remaining(attacker_workspace, mutation) == 0
    own = attacker.put(
        f"/api/v1/analyses/{attacker_analysis.json()['analysis_id']}/review",
        json={"review_status": "approved", "expected_version": 1},
    )
    foreign = attacker.put(
        f"/api/v1/analyses/{victim_id}/review",
        json={"review_status": "approved", "expected_version": 2},
    )
    assert own.status_code == 429
    assert foreign.status_code == 404
    assert controls.workspace_mutation.remaining(attacker_workspace, mutation) == 0


def test_exhausted_attacker_cannot_turn_foreign_action_status_into_quota_or_conflict_oracle(
    controlled_app_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, factory = controlled_app_factory(workspace_mutation_rate_limit=4)
    attacker, attacker_workspace = authenticated_client(app, factory)
    victim, _ = authenticated_client(app, factory)
    monkeypatch.setattr(analyses_route, "run_analysis", analyse_conversation)

    victim_analysis = victim.post("/api/v1/analyses", json=ANALYSIS_PAYLOAD)
    attacker_analysis = attacker.post("/api/v1/analyses", json=ANALYSIS_PAYLOAD)
    assert victim_analysis.status_code == attacker_analysis.status_code == 201
    victim_id = victim_analysis.json()["analysis_id"]
    assert victim.put(f"/api/v1/analyses/{victim_id}/review", json={"review_status": "approved", "expected_version": 1}).status_code == 200
    materialized = victim.post(
        f"/api/v1/analyses/{victim_id}/actions",
        json={"source_action_ids": [victim_analysis.json()["recommended_actions"][0]["action_id"]]},
    )
    assert materialized.status_code == 201
    victim_action = materialized.json()["items"][0]["id"]
    assert victim.put(f"/api/v1/actions/{victim_action}/status", json={"status": "in_progress", "expected_version": 1}).status_code == 200
    assert victim.put(f"/api/v1/actions/{victim_action}/status", json={"status": "completed", "expected_version": 1}).status_code == 409

    for reference in ("attacker-1", "attacker-2", "attacker-3", "attacker-4"):
        assert attacker.post("/api/v1/clients", json={"display_name": reference, "external_reference": reference}).status_code == 201
    controls = app.state.admission_controls
    mutation = controls.policies.workspace_mutation
    assert controls.workspace_mutation.remaining(attacker_workspace, mutation) == 0
    with factory() as session:
        analysis_id = attacker_analysis.json()["analysis_id"]
        action = ActionItemRecord(
            id=str(uuid4()), analysis_id=analysis_id, client_id=None, workspace_id=attacker_workspace,
            source_action_id="attacker-action", title="Attacker action", description="Own action control",
            priority=1, status="open", linked_finding_ids=[], due_at=None, completed_at=None,
        )
        session.add(action)
        session.commit()
        attacker_action = action.id
    own = attacker.put(f"/api/v1/actions/{attacker_action}/status", json={"status": "in_progress", "expected_version": 1})
    foreign = attacker.put(f"/api/v1/actions/{victim_action}/status", json={"status": "completed", "expected_version": 2})
    assert own.status_code == 429
    assert foreign.status_code == 404
    assert controls.workspace_mutation.remaining(attacker_workspace, mutation) == 0


def test_held_provider_real_http_workspace_concurrency_preserves_quota_and_releases_capacity(
    controlled_app_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, factory = controlled_app_factory()
    client, workspace_id = authenticated_client(app, factory)
    headers = asynchronous_auth_headers(client)
    entered = threading.Event()
    release = threading.Event()
    calls: list[int] = []
    call_lock = threading.Lock()

    def provider(payload: object):
        with call_lock:
            call_number = len(calls) + 1
            calls.append(call_number)
        if call_number == 1:
            entered.set()
            assert release.wait(timeout=5)
        return analyse_conversation(payload)

    monkeypatch.setattr(analyses_route, "run_analysis", provider)

    async def request() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.post("/api/v1/analyses", json=ANALYSIS_PAYLOAD, headers=headers)

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        first_task = asyncio.create_task(request())
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            controls = app.state.admission_controls
            daily_before = controls.analysis_daily.remaining(workspace_id, controls.policies.analysis_daily)
            short_before = controls.analysis_short.remaining(workspace_id, controls.policies.analysis_short)
            second = await request()
            assert_capacity_response(second)
            assert calls == [1]
            assert controls.analysis_daily.remaining(workspace_id, controls.policies.analysis_daily) == daily_before
            assert controls.analysis_short.remaining(workspace_id, controls.policies.analysis_short) == short_before - 1
        finally:
            release.set()
        first = await first_task
        assert first.status_code == 201
        assert app.state.admission_controls.inference.active_count == 0
        assert app.state.admission_controls.inference.active_workspace_count == 0
        third = await request()
        assert third.status_code == 201
        assert app.state.admission_controls.analysis_daily.remaining(workspace_id, app.state.admission_controls.policies.analysis_daily) == daily_before - 1
        return first, second, third

    first, second, third = asyncio.run(exercise())
    assert first.status_code == 201
    assert second.status_code == 503
    assert third.status_code == 201
    assert calls == [1, 2]


def test_held_provider_real_http_global_concurrency_preserves_quota_and_releases_capacity(
    controlled_app_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, factory = controlled_app_factory()
    client_a, workspace_a = authenticated_client(app, factory)
    client_b, workspace_b = authenticated_client(app, factory)
    client_c, workspace_c = authenticated_client(app, factory)
    headers = [asynchronous_auth_headers(client) for client in (client_a, client_b, client_c)]
    entered = [threading.Event(), threading.Event()]
    releases = [threading.Event(), threading.Event()]
    calls: list[int] = []
    call_lock = threading.Lock()

    def provider(payload: object):
        with call_lock:
            call_number = len(calls) + 1
            calls.append(call_number)
        if call_number <= 2:
            entered[call_number - 1].set()
            assert releases[call_number - 1].wait(timeout=5)
        return analyse_conversation(payload)

    monkeypatch.setattr(analyses_route, "run_analysis", provider)

    async def request(header: dict[str, str]) -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.post("/api/v1/analyses", json=ANALYSIS_PAYLOAD, headers=header)

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response, httpx.Response]:
        first_task = asyncio.create_task(request(headers[0]))
        second_task: asyncio.Task[httpx.Response] | None = None
        try:
            assert await asyncio.to_thread(entered[0].wait, 5)
            second_task = asyncio.create_task(request(headers[1]))
            assert await asyncio.to_thread(entered[1].wait, 5)
            controls = app.state.admission_controls
            assert controls.inference.active_count == 2
            daily_before = controls.analysis_daily.remaining(workspace_c, controls.policies.analysis_daily)
            short_before = controls.analysis_short.remaining(workspace_c, controls.policies.analysis_short)
            third_rejected = await request(headers[2])
            assert_capacity_response(third_rejected)
            assert calls == [1, 2]
            assert controls.analysis_daily.remaining(workspace_c, controls.policies.analysis_daily) == daily_before
            assert controls.analysis_short.remaining(workspace_c, controls.policies.analysis_short) == short_before - 1
            releases[0].set()
            first = await first_task
            assert first.status_code == 201
            assert controls.inference.active_count == 1
            third_admitted = await request(headers[2])
            assert third_admitted.status_code == 201
            assert controls.analysis_daily.remaining(workspace_c, controls.policies.analysis_daily) == daily_before - 1
        finally:
            for release in releases:
                release.set()
        second = await second_task
        assert second.status_code == 201
        assert app.state.admission_controls.inference.active_count == 0
        assert app.state.admission_controls.inference.active_workspace_count == 0
        return first, second, third_rejected, third_admitted

    first, second, rejected, admitted = asyncio.run(exercise())
    assert first.status_code == second.status_code == admitted.status_code == 201
    assert rejected.status_code == 503
    assert calls == [1, 2, 3]
