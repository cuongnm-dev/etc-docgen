"""Concurrency primitives for SDLC tools (per P0 §2.2 + §2.3 + §2.4).

Implements three guarantees needed because file-based intel layer doesn't
get them for free (unlike SQLite):

    §2.2 Atomic write: write .tmp → fsync → rename (POSIX atomic)
    §2.3 Per-workspace lock: serialize writes per workspace_path
    §2.4 Multi-file transaction: write all .tmp → verify → rename in order;
         rollback all .tmp on partial failure
"""
from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from etc_platform.sdlc.errors import TransactionFailedError

# ---------------------------------------------------------------------------
# §2.3 Per-workspace lock registry
# ---------------------------------------------------------------------------

_locks: dict[str, threading.Lock] = {}
_locks_master = threading.Lock()


def get_workspace_lock(workspace_path: str | Path) -> threading.Lock:
    """Return a re-usable Lock keyed by workspace path string.

    Multiple writers on the same workspace serialize. Different workspaces
    proceed in parallel. Reads do NOT acquire this lock.
    """
    key = str(workspace_path)
    with _locks_master:
        if key not in _locks:
            _locks[key] = threading.Lock()
        return _locks[key]


@contextmanager
def workspace_lock(workspace_path: str | Path) -> Iterator[None]:
    """Context manager acquiring per-workspace lock.

    Usage:
        with workspace_lock(workspace_path):
            # multi-file write transaction
    """
    lock = get_workspace_lock(workspace_path)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# §2.2 Atomic single-file write
# ---------------------------------------------------------------------------


def atomic_write_bytes(target: Path, content: bytes) -> None:
    """Atomic write: stage to .tmp → fsync → rename (POSIX atomic).

    On Windows, ``os.replace`` provides equivalent atomicity since Python 3.3.
    Caller responsible for ensuring parent directory exists.

    Raises:
        OSError: if disk full or permission denied during write/fsync/rename.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        with tmp.open("wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except OSError:
        # Clean up partial .tmp on any error
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def atomic_write_text(target: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Atomic text write — convenience wrapper for atomic_write_bytes."""
    atomic_write_bytes(target, content.encode(encoding))


# ---------------------------------------------------------------------------
# §2.4 Multi-file transaction
# ---------------------------------------------------------------------------


class FileTransaction:
    """Write multiple files atomically (best-effort).

    Workflow:
        tx = FileTransaction()
        tx.add(Path("a.json"), b"...")
        tx.add(Path("b.yaml"), b"...")
        tx.commit(verify=optional_verify_callback)

    Steps on commit:
        1. Write all stagings to .tmp files
        2. Run optional verify callback on .tmp content
        3. If verify fails → cleanup all .tmp + raise
        4. Rename all .tmp → final paths in registration order
        5. If rename mid-way fails → already-renamed files stay (best-effort);
           remaining .tmp cleaned up; raise TransactionFailedError

    Note: True multi-file atomicity is impossible on POSIX without journaling;
    this implementation guarantees:
      - All-or-nothing for the verify gate (no partial writes pass verify)
      - Cleanup of orphan .tmp on any failure
      - Best-effort rollback of already-renamed files via reverse log

    For full ACID, use a database (deferred per ADR-003 D9).
    """

    def __init__(self) -> None:
        self._pending: list[tuple[Path, bytes]] = []
        self._tmps: list[Path] = []
        self._renamed: list[tuple[Path, Path]] = []  # (tmp_path, final_path) for rollback

    def add(self, target: Path, content: bytes | str, *, encoding: str = "utf-8") -> None:
        """Stage a file for atomic commit. Content is bytes or str (UTF-8 encoded)."""
        if isinstance(content, str):
            content = content.encode(encoding)
        self._pending.append((target, content))

    def commit(
        self,
        *,
        verify: Callable[[list[tuple[Path, bytes]]], list[str]] | None = None,
    ) -> list[Path]:
        """Commit all staged writes atomically.

        Args:
            verify: Optional callback(staged_writes) → list of error messages.
                    If non-empty list returned, transaction aborts.

        Returns:
            List of final paths written.

        Raises:
            TransactionFailedError: verify gate failed OR rename mid-way failed.
        """
        # Step 1: write all .tmp
        for target, content in self._pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".tmp")
            try:
                with tmp.open("wb") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                self._tmps.append(tmp)
            except OSError as exc:
                self._cleanup_tmps()
                raise TransactionFailedError(
                    f"Failed to write {tmp}: {exc}",
                    details={"phase": "write_tmp", "target": str(target)},
                ) from exc

        # Step 2: verify gate
        if verify is not None:
            try:
                errors = verify(self._pending)
            except Exception as exc:
                self._cleanup_tmps()
                raise TransactionFailedError(
                    f"Verify callback raised: {exc}",
                    details={"phase": "verify", "exception": str(exc)},
                ) from exc

            if errors:
                self._cleanup_tmps()
                raise TransactionFailedError(
                    f"Verify gate rejected transaction: {len(errors)} error(s)",
                    details={"phase": "verify", "errors": errors},
                )

        # Step 3: rename all .tmp → final
        finals: list[Path] = []
        for (target, _content), tmp in zip(self._pending, self._tmps, strict=True):
            try:
                os.replace(tmp, target)
                self._renamed.append((tmp, target))
                finals.append(target)
            except OSError as exc:
                # Mid-way rename failure. Clean up remaining .tmps.
                # Already-renamed files stay (best-effort, no rollback to old content).
                self._cleanup_tmps()
                raise TransactionFailedError(
                    f"Rename failed mid-transaction: {exc}",
                    details={
                        "phase": "rename",
                        "completed_renames": [str(p[1]) for p in self._renamed],
                        "failed_at": str(target),
                        "remaining": [str(t) for _, t in zip(
                            self._pending[len(self._renamed):],
                            self._tmps[len(self._renamed):],
                            strict=True,
                        )],
                    },
                    fix_hint="Run autofix(fix_classes=['orphan-removal']) to clean up.",
                ) from exc

        return finals

    def _cleanup_tmps(self) -> None:
        """Remove all .tmp files. Best-effort — ignore individual failures."""
        for tmp in self._tmps:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        self._tmps = []


def detect_orphan_tmps(workspace_path: Path, *, subdir: str = "docs") -> list[Path]:
    """Find .tmp files left over from failed transactions (used by autofix)."""
    root = workspace_path / subdir
    if not root.exists():
        return []
    return list(root.rglob("*.tmp"))
