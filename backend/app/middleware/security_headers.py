from collections.abc import Awaitable, Callable
from typing import Any

from starlette.datastructures import MutableHeaders


Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class ApiSecurityHeadersMiddleware:
    """Apply API-safe response headers without claiming to secure frontend HTML."""

    _headers = (
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        (
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        ),
        ("Content-Security-Policy", "frame-ancestors 'none'"),
    )

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message.setdefault("headers", []))
                for name, value in self._headers:
                    if name.lower() not in headers:
                        headers.append(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)
