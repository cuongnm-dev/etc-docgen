"""Unified ASGI entry point: MCP (streamable-http) + HTTP job API in one process.

Layout:

    /                  → FastAPI job API (uploads, jobs, downloads, healthz)
    /mcp               → FastMCP streamable-http transport
    /sse               → FastMCP SSE transport (legacy clients)

Single uvicorn process, single port, shared lifespan. The HTTP lifespan
publishes the JobStore + JobRunner singletons; MCP tools then read them via
`etc_platform.jobs.shared.get_shared()`.

Run:
    etc-platform-server --host 0.0.0.0 --port 8000

or via Docker (default):
    docker compose up -d
"""

from __future__ import annotations

import argparse
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Mount

from etc_platform.jobs.http_app import HttpSettings, create_app
from etc_platform.mcp_server import mcp

log = logging.getLogger("etc-platform.server")


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def build_asgi_app(settings: HttpSettings | None = None) -> Starlette:
    """Build the combined ASGI app: HTTP API + MCP transports."""
    http_app = create_app(settings)

    # FastMCP already namespaces these transports internally (`/mcp`, `/sse`,
    # `/messages`). Re-mounting them under another prefix duplicates the path
    # (`/mcp/mcp`) and makes the documented endpoints 404.
    mcp_streamable_app = mcp.streamable_http_app()
    mcp_sse_app = mcp.sse_app()

    # The HTTP app already has its own lifespan that wires JobStore+JobRunner.
    # FastMCP transports may also have lifespans (session managers, etc.); we
    # combine them so both run on startup/shutdown.
    @asynccontextmanager
    async def combined_lifespan(app: Starlette) -> Any:
        async with (
            http_app.router.lifespan_context(http_app),
            mcp_streamable_app.router.lifespan_context(mcp_streamable_app),
            mcp_sse_app.router.lifespan_context(mcp_sse_app),
        ):
            yield

    return Starlette(
        routes=[
            *mcp_streamable_app.routes,
            *mcp_sse_app.routes,
            Mount("/", app=http_app),
        ],
        lifespan=combined_lifespan,
    )


def main() -> None:
    _configure_logging()

    parser = argparse.ArgumentParser(
        description="etc-platform unified server (HTTP job API + MCP)",
        prog="etc-platform-server",
    )
    parser.add_argument("--host", default=os.environ.get("ETC_PLATFORM_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("ETC_PLATFORM_PORT", "8000"))
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (development only).",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "info").lower(),
        choices=["critical", "error", "warning", "info", "debug", "trace"],
    )

    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "uvicorn not installed. Install with: pip install 'etc-platform[serve]'"
        ) from exc

    if args.reload:
        # uvicorn requires an importable target string for reload mode.
        uvicorn.run(
            "etc_platform.server:build_asgi_app",
            host=args.host,
            port=args.port,
            reload=True,
            factory=True,
            log_level=args.log_level,
        )
    else:
        app = build_asgi_app()
        uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
