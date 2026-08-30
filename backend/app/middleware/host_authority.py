from collections.abc import Awaitable, Callable
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse


Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class HostAuthorityMiddleware:
    """Reject malformed Host authorities before hostname allowlist checks."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        if not self._has_valid_authority(scope):
            if scope["type"] == "http":
                await PlainTextResponse("Invalid host header", status_code=400)(
                    scope, receive, send
                )
            else:
                await send({"type": "websocket.close", "code": 1008})
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _has_valid_authority(scope: Scope) -> bool:
        host_values = [
            value for name, value in scope.get("headers", []) if name.lower() == b"host"
        ]
        if len(host_values) != 1:
            return False
        try:
            authority = host_values[0].decode("ascii")
        except UnicodeDecodeError:
            return False
        if not authority or authority != authority.strip():
            return False

        try:
            parsed = urlsplit(f"//{authority}")
            port = parsed.port
        except ValueError:
            return False
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or authority.endswith(":")
            or (port is not None and not 1 <= port <= 65_535)
        ):
            return False
        return HostAuthorityMiddleware._has_valid_hostname_form(
            parsed.hostname, authority
        )

    @staticmethod
    def _has_valid_hostname_form(hostname: str, authority: str) -> bool:
        try:
            address = ip_address(hostname)
        except ValueError:
            if all(character.isdigit() or character == "." for character in hostname):
                return False
            return (
                ":" not in hostname
                and all(
                    label
                    and not label.startswith("-")
                    and not label.endswith("-")
                    and all(character.isalnum() or character == "-" for character in label)
                    for label in hostname.rstrip(".").split(".")
                )
            )
        return address.version != 6 or authority.startswith("[")
