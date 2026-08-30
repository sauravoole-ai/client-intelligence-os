"""HTTP perimeter middleware for the application."""

from backend.app.middleware.host_authority import HostAuthorityMiddleware

__all__ = ["HostAuthorityMiddleware"]
