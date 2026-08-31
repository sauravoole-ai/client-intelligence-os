"""Explicit one-worker production server entry point.

This process-local admission contract is valid only for one app process and
one app instance; deployment must enforce the latter separately.
"""

import uvicorn

from backend.app.core.config import settings


def run() -> None:
    forwarded_allow_ips = ",".join(settings.trusted_proxy_ips)
    uvicorn.run(
        "backend.app.main:app",
        host="0.0.0.0",
        port=settings.port,
        workers=1,
        reload=False,
        server_header=False,
        access_log=False,
        proxy_headers=bool(settings.trusted_proxy_ips),
        forwarded_allow_ips=forwarded_allow_ips,
    )


if __name__ == "__main__":
    run()
