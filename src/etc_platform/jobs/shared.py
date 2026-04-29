"""Process-wide singletons for the job pipeline.

The HTTP app's lifespan hook populates these; the MCP tools then read them.
This indirection lets MCP tools and HTTP routes share one JobStore + JobRunner
without a global import cycle.

Tests should call `reset_shared()` between cases.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from etc_platform.jobs.runner import JobRunner
from etc_platform.jobs.storage import JobStore


@dataclass(slots=True)
class _Shared:
    store: JobStore | None = None
    runner: JobRunner | None = None


_state = _Shared()
_lock = threading.Lock()


def set_shared(*, store: JobStore, runner: JobRunner) -> None:
    """Install singletons. Called by the HTTP lifespan startup hook."""
    with _lock:
        _state.store = store
        _state.runner = runner


def reset_shared() -> None:
    """Clear singletons. Called on shutdown and in tests."""
    with _lock:
        _state.store = None
        _state.runner = None


def get_shared() -> tuple[JobStore, JobRunner]:
    """Return the configured singletons. Raises if not initialised."""
    with _lock:
        store, runner = _state.store, _state.runner
    if store is None or runner is None:
        raise RuntimeError(
            "Job pipeline is not initialised. The HTTP server must be running "
            "for upload-based MCP tools to work. Start with "
            "`etc-platform-mcp --transport http+mcp` or run the combined ASGI app."
        )
    return store, runner


__all__ = ["set_shared", "reset_shared", "get_shared"]
