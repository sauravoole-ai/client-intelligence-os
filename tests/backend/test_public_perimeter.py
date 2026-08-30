import asyncio
import importlib
from collections.abc import AsyncIterator, Callable, Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.core.config import Settings, settings
from backend.app.db.session import get_db_session
from backend.app.api.routes import analyses as analyses_route
from backend.app.schemas.client_intelligence import AnalysisRequest
from backend.app.schemas.llm_analysis import LLMAnalysisDraft
from backend.app.security.sessions import CurrentPrincipal, get_current_principal, require_csrf
from backend.app.services import intelligence_orchestrator as orchestrator
from backend.app.services.groq_intelligence_service import groq_transport_schema


VALID_CONVERSATION = "Day 1\nClient: I slept well and completed my planned walk today."
BODY_LIMIT = 131_072
API_SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "content-security-policy": "frame-ancestors 'none'",
}


def assert_api_security_headers(response: object) -> None:
    headers = getattr(response, "headers")
    for name, value in API_SECURITY_HEADERS.items():
        assert headers[name] == value
    assert "strict-transport-security" not in headers


def body_guard(
    app: Callable[..., Any], *, max_body_bytes: int = BODY_LIMIT
) -> Callable[..., Any]:
    try:
        module = importlib.import_module("backend.app.middleware.body_limit")
    except ModuleNotFoundError:
        pytest.fail("The public API request-body guard is not implemented.")
    middleware = getattr(module, "RequestBodyLimitMiddleware", None)
    assert middleware is not None, "The public API request-body guard is not implemented."
    return middleware(app, max_body_bytes=max_body_bytes, api_prefix="/api/v1")


def host_authority_guard(app: Callable[..., Any]) -> Callable[..., Any]:
    try:
        module = importlib.import_module("backend.app.middleware.host_authority")
    except ModuleNotFoundError:
        pytest.fail("The Host authority validation middleware is not implemented.")
    middleware = getattr(module, "HostAuthorityMiddleware", None)
    assert middleware is not None, "The Host authority validation middleware is not implemented."
    return middleware(app)


async def call_asgi(
    app: Callable[..., Any],
    *,
    headers: list[tuple[bytes, bytes]],
    chunks: list[bytes],
    path: str = "/api/v1/analyses",
) -> list[dict[str, Any]]:
    events = iter(
        [
            {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
            for index, chunk in enumerate(chunks)
        ]
    )
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        try:
            return next(events)
        except StopIteration:
            return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "root_path": "",
    }
    await app(scope, receive, send)
    return sent


def test_body_limit_accepts_an_exactly_sized_stream() -> None:
    received: list[bytes] = []

    async def endpoint(_: dict[str, Any], receive: Callable[[], Any], send: Callable[[dict[str, Any]], Any]) -> None:
        while True:
            event = await receive()
            received.append(event.get("body", b""))
            if not event.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    events = asyncio.run(
        call_asgi(
            body_guard(endpoint),
            headers=[],
            chunks=[b"a" * 65_536, b"b" * 65_536],
        )
    )

    assert events[0]["status"] == 204
    assert b"".join(received) == b"a" * 65_536 + b"b" * 65_536


@pytest.mark.parametrize(
    ("headers", "chunks"),
    [
        ([(b"content-length", b"131073")], [b"a"]),
        ([], [b"a" * 65_536, b"b" * 65_537]),
        ([(b"content-length", b"1")], [b"a" * 65_536, b"b" * 65_537]),
    ],
    ids=["declared-oversize", "missing-content-length", "false-content-length"],
)
def test_body_limit_rejects_oversize_before_the_downstream_endpoint(
    headers: list[tuple[bytes, bytes]], chunks: list[bytes]
) -> None:
    calls = 0

    async def endpoint(_: dict[str, Any], _receive: Callable[[], Any], _send: Callable[[dict[str, Any]], Any]) -> None:
        nonlocal calls
        calls += 1

    events = asyncio.run(call_asgi(body_guard(endpoint), headers=headers, chunks=chunks))

    assert events[0]["status"] == 413
    assert calls == 0


def test_body_limit_discards_empty_frames_and_replays_one_canonical_body() -> None:
    empty_frame_count = 5_000
    payload = b"small legitimate final body"

    def event_stream() -> Generator[dict[str, Any], None, None]:
        for _ in range(empty_frame_count):
            yield {"type": "http.request", "body": b"", "more_body": True}
        yield {"type": "http.request", "body": payload, "more_body": False}

    incoming_events = event_stream()
    downstream_events: list[dict[str, Any]] = []
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        try:
            return next(incoming_events)
        except StopIteration:
            return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def endpoint(_: dict[str, Any], downstream_receive: Callable[[], Any], send: Callable[[dict[str, Any]], Any]) -> None:
        downstream_events.append(await downstream_receive())
        downstream_events.append(await downstream_receive())
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/analyses",
        "raw_path": b"/api/v1/analyses",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "root_path": "",
    }

    asyncio.run(body_guard(endpoint)(scope, receive, send))

    assert sent[0]["status"] == 204
    assert downstream_events == [
        {"type": "http.request", "body": payload, "more_body": False},
        {"type": "http.disconnect"},
    ]


def test_body_limit_does_not_invoke_downstream_after_disconnect() -> None:
    calls = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def endpoint(_: dict[str, Any], _receive: Callable[[], Any], _send: Callable[[dict[str, Any]], Any]) -> None:
        nonlocal calls
        calls += 1

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/analyses",
        "raw_path": b"/api/v1/analyses",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "root_path": "",
    }

    asyncio.run(body_guard(endpoint)(scope, receive, send))

    assert calls == 0
    assert sent == []


@pytest.mark.parametrize(
    "authority",
    [
        b"app.example.test:not-a-port",
        b"app.example.test:99999",
        b"app.example.test:-1",
        b"app.example.test:+443",
        b"app.example.test:443abc",
        b"app.example.test:",
        b":443",
        b"[::1",
        b"::1",
    ],
)
def test_host_authority_guard_rejects_malformed_authorities(authority: bytes) -> None:
    calls = 0

    async def endpoint(_: dict[str, Any], _receive: Callable[[], Any], _send: Callable[[dict[str, Any]], Any]) -> None:
        nonlocal calls
        calls += 1

    events = asyncio.run(
        call_asgi(
            host_authority_guard(endpoint),
            headers=[(b"host", authority)],
            chunks=[],
        )
    )

    assert events[0]["status"] == 400
    assert calls == 0


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"host", b"app.example.test"), (b"host", b"attacker.example")],
    ],
    ids=["missing-host", "duplicate-host"],
)
def test_host_authority_guard_rejects_missing_or_duplicate_host_headers(
    headers: list[tuple[bytes, bytes]],
) -> None:
    calls = 0

    async def endpoint(_: dict[str, Any], _receive: Callable[[], Any], _send: Callable[[dict[str, Any]], Any]) -> None:
        nonlocal calls
        calls += 1

    events = asyncio.run(call_asgi(host_authority_guard(endpoint), headers=headers, chunks=[]))

    assert events[0]["status"] == 400
    assert calls == 0


def test_host_authority_guard_accepts_syntactically_valid_bracketed_ipv6() -> None:
    calls = 0
    sent: list[dict[str, Any]] = []

    async def endpoint(_: dict[str, Any], _receive: Callable[[], Any], send: Callable[[dict[str, Any]], Any]) -> None:
        nonlocal calls
        calls += 1
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/analyses",
        "raw_path": b"/api/v1/analyses",
        "query_string": b"",
        "headers": [(b"host", b"[2001:db8::1]:443")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "root_path": "",
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    asyncio.run(host_authority_guard(endpoint)(scope, receive, send))

    assert sent[0]["status"] == 204
    assert calls == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("conversation", "x" * 32_001),
        ("client_reference", "x" * 256),
        ("analysis_period", "x" * 256),
    ],
)
def test_analysis_request_rejects_over_bound_input_fields(field: str, value: str) -> None:
    payload = {"conversation": VALID_CONVERSATION, field: value}

    with pytest.raises(ValidationError):
        AnalysisRequest.model_validate(payload)


def test_analysis_request_accepts_the_exact_conversation_limit() -> None:
    messages = ["Client: " + "x" * 3_990 for _ in range(8)]
    conversation = "\n".join(messages)
    conversation += " " * (32_000 - len(conversation))

    payload = AnalysisRequest(conversation=conversation)

    assert len(payload.conversation) == 32_000


@pytest.mark.parametrize(
    ("conversation", "reason"),
    [
        ("\n".join(f"Client: update {index}" for index in range(251)), "message count"),
        ("Client: " + "x" * 4_001, "message length"),
    ],
)
def test_over_bound_parsed_transcripts_do_not_invoke_the_provider(
    conversation: str,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_calls = 0

    def provider(*_: object) -> object:
        nonlocal provider_calls
        provider_calls += 1
        return object()

    monkeypatch.setattr(settings, "ai_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    monkeypatch.setattr(orchestrator, "_run_provider", provider)

    with pytest.raises(ValueError, match=reason):
        orchestrator.run_analysis(AnalysisRequest(conversation=conversation, engine_mode="llm"))

    assert provider_calls == 0


def draft_finding() -> dict[str, object]:
    return {
        "finding_id": "finding-1",
        "category": "sleep",
        "title": "Sleep",
        "statement": "The client reported a sleep update.",
        "classification": "client_reported_information",
        "confidence": 0.9,
        "evidence_message_ids": ["msg-001"],
    }


def draft_payload() -> dict[str, object]:
    return {
        "analysis_period": "Day 1",
        "weekly_summary": draft_finding(),
        "findings": [draft_finding()],
        "risk_flags": [],
        "recommended_actions": [],
        "missing_information": [],
    }


def test_llm_draft_rejects_more_than_twenty_findings() -> None:
    payload = draft_payload()
    payload["findings"] = [draft_finding() for _ in range(21)]

    with pytest.raises(ValidationError):
        LLMAnalysisDraft.model_validate(payload)


def test_llm_draft_rejects_more_than_ten_evidence_ids() -> None:
    payload = draft_payload()
    weekly_summary = dict(draft_finding())
    weekly_summary["evidence_message_ids"] = [f"msg-{index:03d}" for index in range(11)]
    payload["weekly_summary"] = weekly_summary

    with pytest.raises(ValidationError):
        LLMAnalysisDraft.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("risk_flags", [{
            "risk_id": f"risk-{index}", "title": "Risk", "severity": "low",
            "rationale": "A bounded risk rationale.", "classification": "ai_generated_inference",
            "confidence": 0.5, "evidence_message_ids": [],
        } for index in range(11)]),
        ("recommended_actions", [{
            "action_id": f"action-{index}", "priority": 1, "action": "Follow up.",
            "rationale": "A bounded action rationale.", "classification": "ai_generated_inference",
            "linked_finding_ids": [], "evidence_message_ids": [],
        } for index in range(11)]),
        ("missing_information", [f"Missing detail {index}" for index in range(21)]),
    ],
)
def test_llm_draft_rejects_over_bound_output_lists(field: str, value: object) -> None:
    payload = draft_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        LLMAnalysisDraft.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("analysis_period", "x" * 256),
        ("weekly_summary", {**draft_finding(), "title": "x" * 256}),
        ("weekly_summary", {**draft_finding(), "statement": "x" * 2_001}),
    ],
)
def test_llm_draft_rejects_over_bound_output_strings(field: str, value: object) -> None:
    payload = draft_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        LLMAnalysisDraft.model_validate(payload)


def test_groq_transport_schema_includes_the_llm_output_bounds() -> None:
    schema = groq_transport_schema()
    properties = schema["properties"]

    assert properties["findings"]["maxItems"] == 20
    assert properties["risk_flags"]["maxItems"] == 10
    assert properties["recommended_actions"]["maxItems"] == 10
    assert properties["missing_information"]["maxItems"] == 20


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "auth_cookie_secure": True,
        "database_url": "postgresql+psycopg://user:password@db.example.test/client_intelligence",
        "app_origin": "https://app.example.test",
        "auth_callback_url": "https://app.example.test/api/v1/auth/callback",
        "trusted_hosts": ["app.example.test"],
    }
    values.update(overrides)
    return Settings(**values)


def public_app(app_settings: Settings):
    main_module = importlib.import_module("backend.app.main")
    factory = getattr(main_module, "create_app", None)
    assert callable(factory), "The application factory is not implemented."
    return factory(app_settings)


def test_production_settings_require_https_origins_and_non_wildcard_hosts() -> None:
    with pytest.raises(ValidationError, match="APP_ORIGIN"):
        production_settings(app_origin="http://app.example.test")
    with pytest.raises(ValidationError, match="AUTH_CALLBACK_URL"):
        production_settings(auth_callback_url="http://app.example.test/api/v1/auth/callback")
    with pytest.raises(ValidationError, match="APP_ORIGIN"):
        production_settings(app_origin="https://app.example.test:not-a-port")
    with pytest.raises(ValidationError, match="TRUSTED_HOSTS"):
        production_settings(trusted_hosts=["*"])


@pytest.mark.parametrize(
    ("field", "value", "trusted_host"),
    [
        ("app_origin", "https://localhost", "localhost"),
        ("app_origin", "https://LOCALHOST", "localhost"),
        ("app_origin", "https://foo.localhost", "foo.localhost"),
        ("app_origin", "https://127.0.0.1", "127.0.0.1"),
        ("app_origin", "https://127.0.0.2", "127.0.0.2"),
        ("app_origin", "https://[::1]", "::1"),
        ("app_origin", "https://0.0.0.0", "0.0.0.0"),
        ("app_origin", "https://169.254.10.20", "169.254.10.20"),
        ("app_origin", "https://10.10.10.10", "10.10.10.10"),
        ("app_origin", "https://192.168.10.10", "192.168.10.10"),
        ("app_origin", "https://172.16.10.10", "172.16.10.10"),
        ("auth_callback_url", "https://localhost/api/v1/auth/callback", "localhost"),
        ("auth_callback_url", "https://foo.localhost/api/v1/auth/callback", "foo.localhost"),
        ("auth_callback_url", "https://127.0.0.1/api/v1/auth/callback", "127.0.0.1"),
        ("auth_callback_url", "https://[::1]/api/v1/auth/callback", "::1"),
    ],
)
def test_production_settings_reject_local_and_non_public_url_hosts(
    field: str, value: str, trusted_host: str
) -> None:
    with pytest.raises(ValidationError, match=field.upper()):
        production_settings(**{field: value, "trusted_hosts": ["app.example.test", trusted_host]})


@pytest.mark.parametrize(
    ("app_origin", "expected_origin"),
    [
        ("https://app.example.com", "https://app.example.com"),
        ("https://app.example.com/", "https://app.example.com"),
        ("https://app.example.com:8443", "https://app.example.com:8443"),
    ],
)
def test_production_settings_accept_and_normalize_a_true_public_app_origin(
    app_origin: str, expected_origin: str
) -> None:
    configured = production_settings(
        app_origin=app_origin,
        auth_callback_url=f"{expected_origin}/api/v1/auth/callback",
        trusted_hosts=["app.example.com"],
    )

    assert configured.app_origin == expected_origin


@pytest.mark.parametrize(
    "app_origin",
    [
        "https://app.example.com/path",
        "https://app.example.com/?query=1",
        "https://app.example.com/#fragment",
        "https://user@app.example.com",
        "https://user:pass@app.example.com",
    ],
)
def test_production_settings_reject_non_origin_app_urls(app_origin: str) -> None:
    with pytest.raises(ValidationError, match="APP_ORIGIN"):
        production_settings(
            app_origin=app_origin,
            auth_callback_url="https://app.example.com/api/v1/auth/callback",
            trusted_hosts=["app.example.com"],
        )


def test_production_settings_require_the_callback_to_use_the_app_origin() -> None:
    with pytest.raises(ValidationError, match="AUTH_CALLBACK_URL"):
        production_settings(
            app_origin="https://app.example.com",
            auth_callback_url="https://api.example.com/api/v1/auth/callback",
            trusted_hosts=["app.example.com", "api.example.com"],
        )


def test_development_settings_preserve_local_urls() -> None:
    configured = Settings(
        environment="development",
        app_origin="http://localhost:3000",
        auth_callback_url="http://localhost:8000/api/v1/auth/callback",
    )

    assert configured.app_origin == "http://localhost:3000"


def test_invalid_host_rejection_includes_api_security_headers() -> None:
    app = public_app(production_settings())
    client = TestClient(app, base_url="https://app.example.test")
    response = client.get("/api/v1/health", headers={"Host": "attacker.example"})

    assert response.status_code == 400
    assert_api_security_headers(response)


@pytest.mark.parametrize(
    "host",
    [
        "app.example.test:not-a-port",
        "app.example.test:99999",
        "app.example.test:-1",
        "app.example.test:+443",
        "app.example.test:443abc",
        "app.example.test:",
        ":443",
        "[::1",
        "::1",
    ],
)
def test_malformed_host_authority_is_rejected_before_the_application(host: str) -> None:
    client = TestClient(public_app(production_settings()), base_url="https://app.example.test")
    response = client.post(
        "/api/v1/health",
        content=b"x" * (BODY_LIMIT + 1),
        headers={"Host": host},
    )

    assert response.status_code == 400
    assert_api_security_headers(response)


def test_trusted_host_accepts_a_valid_configured_authority_with_port() -> None:
    client = TestClient(public_app(production_settings()), base_url="https://app.example.test")

    assert client.get("/api/v1/health", headers={"Host": "app.example.test:443"}).status_code == 200
    assert client.get("/api/v1/health", headers={"Host": "app.example.test:8443"}).status_code == 200


def test_body_limit_rejection_includes_api_security_headers() -> None:
    client = TestClient(public_app(production_settings()), base_url="https://app.example.test")
    response = client.post("/api/v1/health", content=b"x" * (BODY_LIMIT + 1))

    assert response.status_code == 413
    assert_api_security_headers(response)


def test_production_runtime_middleware_stack_wraps_early_perimeter_rejections() -> None:
    app = public_app(production_settings(oidc_state_secret="test-state-secret"))
    middleware_names: list[str] = []
    current = app.build_middleware_stack()

    while hasattr(current, "app"):
        middleware_names.append(type(current).__name__)
        current = current.app

    assert middleware_names[:7] == [
        "ServerErrorMiddleware",
        "ApiSecurityHeadersMiddleware",
        "HostAuthorityMiddleware",
        "TrustedHostMiddleware",
        "RequestBodyLimitMiddleware",
        "SessionMiddleware",
        "ExceptionMiddleware",
    ]


@pytest.mark.parametrize(
    "host",
    ["localhost", "localhost:3000", "localhost:8000", "127.0.0.1", "127.0.0.1:8000", "testserver"],
)
def test_development_localhost_is_an_allowed_host(host: str) -> None:
    app = public_app(Settings(environment="development"))

    assert TestClient(app, base_url="http://localhost:8000").get(
        "/api/v1/health", headers={"Host": host}
    ).status_code == 200


@pytest.mark.parametrize("host", ["localhost:notaport", "127.0.0.1:99999"])
def test_development_rejects_malformed_host_authorities(host: str) -> None:
    response = TestClient(public_app(Settings(environment="development"))).get(
        "/api/v1/health", headers={"Host": host}
    )

    assert response.status_code == 400
    assert_api_security_headers(response)


def test_default_body_limit_is_configured_to_128_kib() -> None:
    assert Settings(environment="development").max_api_request_body_bytes == BODY_LIMIT


def test_production_disables_docs_openapi_and_debug() -> None:
    app = public_app(production_settings())
    client = TestClient(app, base_url="https://app.example.test")

    assert app.debug is False
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert "docs" not in client.get("/").json()


def test_development_docs_remain_available() -> None:
    client = TestClient(public_app(Settings(environment="development")))

    assert client.get("/docs").status_code == 200


def test_cors_is_absent_in_production_and_restricted_for_development() -> None:
    production_client = TestClient(public_app(production_settings()), base_url="https://app.example.test")
    production_response = production_client.options(
        "/api/v1/health",
        headers={"Origin": "https://other.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in production_response.headers

    development_client = TestClient(public_app(Settings(environment="development")))
    development_response = development_client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert development_response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert development_response.headers["access-control-allow-methods"] == "GET, POST, PUT, OPTIONS"
    assert development_response.headers["access-control-allow-headers"] == "Accept, Accept-Language, Content-Language, Content-Type, X-CSRF-Token"


def test_api_responses_include_the_safe_security_headers() -> None:
    response = TestClient(public_app(Settings(environment="development"))).get("/api/v1/health")

    assert_api_security_headers(response)


def test_handled_not_found_response_includes_api_security_headers() -> None:
    response = TestClient(public_app(Settings(environment="development"))).get("/api/v1/not-found")

    assert response.status_code == 404
    assert_api_security_headers(response)


def test_liveness_does_not_require_a_database_dependency() -> None:
    app = public_app(Settings(environment="development"))

    def unavailable_database() -> Generator[object, None, None]:
        raise AssertionError("liveness must not resolve a database session")
        yield object()

    app.dependency_overrides[get_db_session] = unavailable_database
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_database_success_with_a_minimal_response() -> None:
    app = public_app(Settings(environment="development"))

    class AvailableSession:
        def execute(self, statement: object) -> object:
            assert str(statement) == "SELECT 1"
            return object()

    def database_session() -> Generator[AvailableSession, None, None]:
        yield AvailableSession()

    app.dependency_overrides[get_db_session] = database_session
    response = TestClient(app).get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_hides_database_failure_details() -> None:
    app = public_app(Settings(environment="development"))

    class UnavailableSession:
        def execute(self, _: object) -> object:
            raise SQLAlchemyError("postgresql://secret-host/internal")

    def database_session() -> Generator[UnavailableSession, None, None]:
        yield UnavailableSession()

    app.dependency_overrides[get_db_session] = database_session
    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "secret-host" not in response.text
    assert_api_security_headers(response)


def test_trusted_host_runs_before_the_body_guard() -> None:
    app = public_app(production_settings())
    client = TestClient(app, base_url="https://app.example.test")
    body = b"x" * (BODY_LIMIT + 1)

    invalid_host = client.post("/api/v1/health", content=body, headers={"Host": "attacker.example"})
    oversized = client.post("/api/v1/health", content=body)

    assert invalid_host.status_code == 400
    assert oversized.status_code == 413


def test_rejected_api_body_never_reaches_analysis_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    app = public_app(Settings(environment="development"))
    principal = CurrentPrincipal("user", "workspace", "owner", "session", "token")
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[require_csrf] = lambda: principal
    provider_calls = 0

    def provider(_: object) -> object:
        nonlocal provider_calls
        provider_calls += 1
        return object()

    monkeypatch.setattr(analyses_route, "run_analysis", provider)
    response = TestClient(app).post(
        "/api/v1/analyses",
        json={"conversation": "Day 1\nClient: " + "x" * BODY_LIMIT},
    )

    assert response.status_code == 413
    assert provider_calls == 0
