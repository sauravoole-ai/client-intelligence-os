"""Small, process-local admission controls for the one-worker V1 contract."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
import math
import threading
import time
from collections.abc import Callable, Iterable


@dataclass(frozen=True)
class RatePolicy:
    limit: int
    window_seconds: int

    def __post_init__(self) -> None:
        if self.limit < 1 or self.window_seconds < 1:
            raise ValueError("Rate policies require positive limits and windows.")


class RateLimitExceeded(RuntimeError):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, retry_after)
        super().__init__("Request rate is temporarily limited.")


@dataclass
class _Counter:
    started_at: float
    used: int


class FixedWindowLimiter:
    """Bounded per-key fixed-window state guarded by a short thread lock."""

    def __init__(
        self,
        *,
        max_keys: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_keys < 1:
            raise ValueError("Rate limiter key capacity must be positive.")
        self._max_keys = max_keys
        self._clock = clock
        self._entries: dict[str, dict[RatePolicy, _Counter]] = {}
        self._lock = threading.Lock()

    @property
    def tracked_key_count(self) -> int:
        with self._lock:
            self._prune(self._clock())
            return len(self._entries)

    def remaining(self, key: str, policy: RatePolicy) -> int:
        with self._lock:
            now = self._clock()
            self._prune(now)
            counter = self._entries.get(key, {}).get(policy)
            return policy.limit if counter is None else max(0, policy.limit - counter.used)

    def consume(self, key: str, policy: RatePolicy) -> None:
        self.consume_many(key, (policy,))

    def consume_many(self, key: str, policies: Iterable[RatePolicy]) -> None:
        requested = tuple(policies)
        if not requested:
            return
        with self._lock:
            now = self._clock()
            self._prune(now)
            counters = self._entries.get(key)
            if counters is None:
                if len(self._entries) >= self._max_keys:
                    raise RateLimitExceeded(1)
                counters = {}

            blocked_after = 0
            for policy in requested:
                counter = counters.get(policy)
                if counter is not None and counter.used >= policy.limit:
                    seconds = math.ceil(counter.started_at + policy.window_seconds - now)
                    blocked_after = max(blocked_after, max(1, seconds))
            if blocked_after:
                raise RateLimitExceeded(blocked_after)

            if key not in self._entries:
                self._entries[key] = counters
            for policy in requested:
                counter = counters.get(policy)
                if counter is None:
                    counters[policy] = _Counter(started_at=now, used=1)
                else:
                    counter.used += 1

    def _prune(self, now: float) -> None:
        for key, counters in tuple(self._entries.items()):
            for policy, counter in tuple(counters.items()):
                if now >= counter.started_at + policy.window_seconds:
                    del counters[policy]
            if not counters:
                del self._entries[key]


class InferenceLease(AbstractContextManager["InferenceLease"]):
    def __init__(self, controller: "InferenceAdmissionController", workspace_id: str) -> None:
        self._controller = controller
        self._workspace_id = workspace_id
        self._released = False

    def __enter__(self) -> "InferenceLease":
        return self

    def __exit__(self, *_: object) -> None:
        self.release()

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._controller._release(self._workspace_id)


class InferenceAdmissionController:
    """Non-blocking, process-local capacity reservation with no historical keys."""

    def __init__(self, *, workspace_limit: int, global_limit: int) -> None:
        if workspace_limit < 1 or global_limit < 1:
            raise ValueError("Inference limits must be positive.")
        self._workspace_limit = workspace_limit
        self._global_limit = global_limit
        self._active = 0
        self._workspaces: dict[str, int] = {}
        self._lock = threading.Lock()

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active

    @property
    def active_workspace_count(self) -> int:
        with self._lock:
            return len(self._workspaces)

    def acquire(self, workspace_id: str) -> InferenceLease | None:
        with self._lock:
            if (
                self._active >= self._global_limit
                or self._workspaces.get(workspace_id, 0) >= self._workspace_limit
            ):
                return None
            self._active += 1
            self._workspaces[workspace_id] = self._workspaces.get(workspace_id, 0) + 1
        return InferenceLease(self, workspace_id)

    def acquire_or_raise(self, workspace_id: str) -> InferenceLease:
        lease = self.acquire(workspace_id)
        if lease is None:
            raise RuntimeError("Inference capacity is unavailable.")
        return lease

    def _release(self, workspace_id: str) -> None:
        with self._lock:
            self._active -= 1
            current = self._workspaces[workspace_id] - 1
            if current:
                self._workspaces[workspace_id] = current
            else:
                del self._workspaces[workspace_id]


@dataclass(frozen=True)
class AdmissionPolicies:
    login: RatePolicy
    callback: RatePolicy
    workspace_read: RatePolicy
    workspace_mutation: RatePolicy
    analysis_short: RatePolicy
    analysis_daily: RatePolicy


@dataclass
class AppAdmissionControls:
    """Independent state pools prevent public IP churn from starving tenants."""

    enabled: bool
    auth_login: FixedWindowLimiter
    auth_callback: FixedWindowLimiter
    workspace_read: FixedWindowLimiter
    workspace_mutation: FixedWindowLimiter
    analysis_short: FixedWindowLimiter
    analysis_daily: FixedWindowLimiter
    inference: InferenceAdmissionController
    policies: AdmissionPolicies


def create_app_admission_controls(settings: object) -> AppAdmissionControls:
    max_keys = getattr(settings, "rate_limiter_max_keys")
    policies = AdmissionPolicies(
        login=RatePolicy(getattr(settings, "auth_login_rate_limit"), getattr(settings, "auth_login_rate_window_seconds")),
        callback=RatePolicy(getattr(settings, "auth_callback_rate_limit"), getattr(settings, "auth_callback_rate_window_seconds")),
        workspace_read=RatePolicy(getattr(settings, "workspace_read_rate_limit"), getattr(settings, "workspace_read_rate_window_seconds")),
        workspace_mutation=RatePolicy(getattr(settings, "workspace_mutation_rate_limit"), getattr(settings, "workspace_mutation_rate_window_seconds")),
        analysis_short=RatePolicy(getattr(settings, "analysis_short_rate_limit"), getattr(settings, "analysis_short_rate_window_seconds")),
        analysis_daily=RatePolicy(getattr(settings, "analysis_daily_rate_limit"), getattr(settings, "analysis_daily_rate_window_seconds")),
    )
    return AppAdmissionControls(
        enabled=getattr(settings, "application_abuse_controls_enabled"),
        auth_login=FixedWindowLimiter(max_keys=max_keys),
        auth_callback=FixedWindowLimiter(max_keys=max_keys),
        workspace_read=FixedWindowLimiter(max_keys=max_keys),
        workspace_mutation=FixedWindowLimiter(max_keys=max_keys),
        analysis_short=FixedWindowLimiter(max_keys=max_keys),
        analysis_daily=FixedWindowLimiter(max_keys=max_keys),
        inference=InferenceAdmissionController(
            workspace_limit=getattr(settings, "inference_workspace_concurrency"),
            global_limit=getattr(settings, "inference_global_concurrency"),
        ),
        policies=policies,
    )
