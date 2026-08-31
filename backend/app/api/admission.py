"""Route-level adapters for app-scoped, process-local admission controls."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from fastapi import HTTPException, Request, status

from backend.app.security.admission import InferenceLease, RateLimitExceeded


def _controls(request: Request):
    return getattr(request.app.state, "admission_controls", None)


def admit_workspace_read(request: Request, workspace_id: str) -> None:
    controls = _controls(request)
    if controls is not None and controls.enabled:
        _consume(controls.workspace_read, workspace_id, controls.policies.workspace_read)


def admit_workspace_mutation(request: Request, workspace_id: str) -> None:
    controls = _controls(request)
    if controls is not None and controls.enabled:
        _consume(controls.workspace_mutation, workspace_id, controls.policies.workspace_mutation)


@contextmanager
def admit_analysis(request: Request, workspace_id: str) -> Iterator[None]:
    controls = _controls(request)
    lease: InferenceLease | None = None
    if controls is not None and controls.enabled:
        _consume(controls.analysis_short, workspace_id, controls.policies.analysis_short)
        lease = controls.inference.acquire(workspace_id)
        if lease is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Analysis capacity is temporarily unavailable.",
                headers={"Retry-After": str(request.app.state.settings.inference_capacity_retry_after_seconds)},
            )
    try:
        if lease is not None:
            _consume(controls.analysis_daily, workspace_id, controls.policies.analysis_daily)
        yield
    finally:
        if lease is not None:
            lease.release()


def _consume(limiter: object, key: str, policy: object) -> None:
    try:
        if isinstance(policy, tuple):
            limiter.consume_many(key, policy)
        else:
            limiter.consume(key, policy)
    except RateLimitExceeded as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Request rate is temporarily limited.",
            headers={"Retry-After": str(error.retry_after)},
        ) from None
