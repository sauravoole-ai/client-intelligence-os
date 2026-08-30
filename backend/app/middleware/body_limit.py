from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import PlainTextResponse


Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class RequestBodyLimitMiddleware:
    """Bound buffered API request bodies before downstream request processing."""

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        max_body_bytes: int,
        api_prefix: str,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.api_prefix = api_prefix.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._requires_body_limit(scope):
            await self.app(scope, receive, send)
            return

        content_length = self._content_length(scope)
        if content_length is not None and content_length > self.max_body_bytes:
            await self._reject(scope, receive, send)
            return

        buffered_body = bytearray()
        while True:
            message = await receive()
            message_type = message.get("type")
            if message_type == "http.disconnect":
                return
            if message_type != "http.request":
                return

            chunk = message.get("body", b"")
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                return
            if len(buffered_body) + len(chunk) > self.max_body_bytes:
                await self._reject(scope, receive, send)
                return

            buffered_body.extend(chunk)
            if not message.get("more_body", False):
                break

        canonical_body = bytes(buffered_body)
        del buffered_body
        canonical_body_delivered = False

        async def replay_receive() -> Message:
            nonlocal canonical_body_delivered
            if not canonical_body_delivered:
                canonical_body_delivered = True
                return {
                    "type": "http.request",
                    "body": canonical_body,
                    "more_body": False,
                }
            return await receive()

        await self.app(scope, replay_receive, send)

    def _requires_body_limit(self, scope: Scope) -> bool:
        if scope["type"] != "http":
            return False
        if scope.get("method", "GET").upper() not in {"POST", "PUT", "PATCH"}:
            return False
        path = scope.get("path", "")
        return path == self.api_prefix or path.startswith(f"{self.api_prefix}/")

    @staticmethod
    def _content_length(scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            try:
                return int(value)
            except ValueError:
                return None
        return None

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        await PlainTextResponse("Request body too large.", status_code=413)(
            scope, receive, send
        )
