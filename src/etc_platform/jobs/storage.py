"""Filesystem-backed storage for uploads and jobs.

Layout (under `<root>/`):

    uploads/<upload_id>/
        _meta.json          (Upload.to_dict())
        payload.json        (the uploaded content_data; immutable once written)

    jobs/<job_id>/
        _meta.json          (Job.to_dict())
        output/<filename>   (rendered Office files; written by runner)
        render.log          (optional structured log; aids debugging)

Concurrency model
-----------------
* All write paths use `os.replace` after writing to a temp file in the same dir
  → POSIX atomic on Linux/macOS, "best effort atomic" on Windows.
* Per-resource asyncio.Lock keyed by id; held only across a small critical
  section (read-modify-write of _meta.json).
* The storage instance is a singleton per process.
* Scanning (list / sweep) reads _meta.json without locks; this is acceptable
  because writers replace atomically and we never observe partial files.

TTL eviction
------------
* `sweep_expired()` is called periodically by the HTTP app's lifespan hook.
* It NEVER deletes a job that is currently RUNNING — the runner holds that
  invariant by transitioning to a terminal state before releasing the lock.
* Eviction is by directory rmtree; failures are logged but do not propagate.

Path safety
-----------
* All public methods accept ids only — never raw paths from clients.
* Ids must match `^[A-Za-z0-9_-]{2,64}$`; anything else raises ValueError.
* The storage root MUST resolve inside an allowlist provided at construction
  (typically /data on the Docker mount).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from collections.abc import AsyncIterator, Iterable
from datetime import timedelta
from pathlib import Path
from typing import Any

from etc_platform.jobs.models import (
    DEFAULT_WORKSPACE_MAX_BYTES,
    DEFAULT_WORKSPACE_MAX_FILES,
    DEFAULT_WORKSPACE_PER_FILE_MAX_BYTES,
    Job,
    JobError,
    JobExpired,
    JobNotFound,
    JobOutput,
    JobStatus,
    Upload,
    UploadExpired,
    UploadNotFound,
    UploadTooLarge,
    Workspace,
    WorkspaceExpired,
    WorkspaceInvalidPath,
    WorkspaceNotFound,
    WorkspacePart,
    WorkspaceTooLarge,
    detect_mime,
    validate_workspace_path,
)

log = logging.getLogger("etc-platform.jobs.storage")


# ─────────────────────────── Constants ───────────────────────────

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,64}$")
_META_FILENAME = "_meta.json"

# Max single upload size. 10 MB covers content_data with very large feature catalogs.
DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# TTLs — overridable via constructor args (which themselves come from env).
DEFAULT_UPLOAD_TTL = timedelta(minutes=30)
DEFAULT_JOB_TTL = timedelta(hours=1)


# ─────────────────────────── Helpers ───────────────────────────


def _ensure_id(value: str, *, kind: str) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"Invalid {kind} id: {value!r}")


def _replace_with_retry(
    src: str, dst: Path, *, attempts: int = 8, backoff_seconds: float = 0.005
) -> None:
    """`os.replace` with bounded retries on Windows-only PermissionError.

    Background: on Windows, `os.replace(tmp, target)` fails with WinError 5 if
    a concurrent reader has `target` open at the moment of rename. POSIX has
    no such restriction. Retries are exponential and cap at ~600ms total.
    """
    for n in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if n + 1 == attempts:
                raise
            time.sleep(backoff_seconds * (1 << n))


def _atomic_write_text(path: Path, data: str, *, encoding: str = "utf-8") -> None:
    """Write to a temp file in the target directory, then rename.

    `os.replace` is atomic on POSIX and best-effort on Windows. The destination
    file (if any) is replaced atomically; partial files cannot be observed.
    Concurrent readers are tolerated via short retries on Windows.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fp:
            fp.write(data)
            fp.flush()
            with contextlib.suppress(OSError):
                os.fsync(fp.fileno())
        _replace_with_retry(tmp_name, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(data)
            fp.flush()
            with contextlib.suppress(OSError):
                os.fsync(fp.fileno())
        _replace_with_retry(tmp_name, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def _read_text_with_retry(
    path: Path,
    *,
    encoding: str = "utf-8",
    attempts: int = 5,
    backoff_seconds: float = 0.005,
) -> str:
    """Read a text file, retrying on transient PermissionError/OSError.

    Rationale: on Windows, `os.replace(tmp, target)` is atomic in the
    "no partial bytes observed" sense, but a concurrent reader that opens
    `target` mid-rename may briefly receive `PermissionError`. The window
    is microseconds. POSIX is unaffected. Retries are bounded and short.
    """
    last_exc: BaseException | None = None
    for n in range(attempts):
        try:
            return path.read_text(encoding=encoding)
        except (PermissionError, OSError) as exc:
            last_exc = exc
            if n + 1 == attempts:
                raise
            time.sleep(backoff_seconds * (1 << n))  # exponential
    raise last_exc  # type: ignore[misc]  # unreachable


def _sha256_file(path: Path, *, chunk: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            buf = fp.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _safe_rmtree(path: Path) -> None:
    """rmtree that swallows ENOENT and logs everything else without raising."""
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.warning("rmtree failed for %s: %s", path, exc)


# ─────────────────────────── JobStore ───────────────────────────


class JobStore:
    """Async-friendly storage facade for uploads + jobs.

    All methods returning awaitables run blocking I/O via `asyncio.to_thread`,
    so the event loop stays responsive. Per-resource locks are weakly held
    in a dict; entries are pruned when their resource is deleted.
    """

    def __init__(
        self,
        root: Path,
        *,
        upload_ttl: timedelta = DEFAULT_UPLOAD_TTL,
        job_ttl: timedelta = DEFAULT_JOB_TTL,
        workspace_ttl: timedelta = timedelta(hours=24),  # NEW: longer than job
        max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
        max_workspace_bytes: int = DEFAULT_WORKSPACE_MAX_BYTES,
        max_workspace_files: int = DEFAULT_WORKSPACE_MAX_FILES,
        max_workspace_per_file_bytes: int = DEFAULT_WORKSPACE_PER_FILE_MAX_BYTES,
        allowed_root: Path | None = None,
    ) -> None:
        self._root = root.resolve()
        # Allowlist root — refuse to operate outside it. Defaults to the storage root itself.
        self._allowed_root = (allowed_root or self._root).resolve()
        if not self._is_under_allowed(self._root):
            raise ValueError(
                f"Storage root {self._root} is outside allowed root {self._allowed_root}"
            )
        self._uploads_dir = self._root / "uploads"
        self._jobs_dir = self._root / "jobs"
        self._workspaces_dir = self._root / "workspaces"
        self._uploads_dir.mkdir(parents=True, exist_ok=True)
        self._jobs_dir.mkdir(parents=True, exist_ok=True)
        self._workspaces_dir.mkdir(parents=True, exist_ok=True)
        self._upload_ttl = upload_ttl
        self._job_ttl = job_ttl
        self._workspace_ttl = workspace_ttl
        self._max_upload_bytes = max_upload_bytes
        self._max_workspace_bytes = max_workspace_bytes
        self._max_workspace_files = max_workspace_files
        self._max_workspace_per_file_bytes = max_workspace_per_file_bytes

        # Per-resource locks. Plain dict + global asyncio.Lock for the dict
        # itself — fine because contention is rare and lookup is O(1).
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    # ── Properties (test/inspection) ────────────────────────────────

    @property
    def root(self) -> Path:
        return self._root

    @property
    def upload_ttl(self) -> timedelta:
        return self._upload_ttl

    @property
    def job_ttl(self) -> timedelta:
        return self._job_ttl

    @property
    def max_upload_bytes(self) -> int:
        return self._max_upload_bytes

    @property
    def workspace_ttl(self) -> timedelta:
        return self._workspace_ttl

    @property
    def max_workspace_bytes(self) -> int:
        return self._max_workspace_bytes

    @property
    def max_workspace_files(self) -> int:
        return self._max_workspace_files

    # ── Internal helpers ────────────────────────────────────────────

    def _is_under_allowed(self, p: Path) -> bool:
        try:
            return p.resolve().is_relative_to(self._allowed_root)
        except (ValueError, OSError):
            return False

    def _upload_dir(self, upload_id: str) -> Path:
        _ensure_id(upload_id, kind="upload")
        return self._uploads_dir / upload_id

    def _job_dir(self, job_id: str) -> Path:
        _ensure_id(job_id, kind="job")
        return self._jobs_dir / job_id

    def _workspace_dir(self, workspace_id: str) -> Path:
        _ensure_id(workspace_id, kind="workspace")
        return self._workspaces_dir / workspace_id

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    async def _drop_lock(self, key: str) -> None:
        async with self._locks_guard:
            self._locks.pop(key, None)

    # ── Upload CRUD ─────────────────────────────────────────────────

    async def create_upload(
        self,
        data: bytes,
        *,
        content_type: str = "application/json",
        label: str | None = None,
        validate_json: bool = True,
        ttl: timedelta | None = None,
    ) -> Upload:
        """Persist `data` and return an Upload record. Raises UploadTooLarge on size violation.

        If `validate_json` is True (default), the payload is parsed once to surface
        malformed JSON as a fast 4xx response instead of a 5xx during the job run.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes")
        if len(data) > self._max_upload_bytes:
            raise UploadTooLarge(
                f"Upload size {len(data)} bytes exceeds limit {self._max_upload_bytes}"
            )

        if validate_json:
            try:
                json.loads(data.decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise JobError(f"Upload is not valid UTF-8: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise JobError(f"Upload is not valid JSON: {exc}") from exc

        sha = hashlib.sha256(data).hexdigest()

        def _do_create() -> Upload:
            upload = Upload.new(
                size_bytes=len(data),
                content_type=content_type,
                sha256=sha,
                ttl=ttl or self._upload_ttl,
                label=label,
            )
            up_dir = self._upload_dir(upload.upload_id)
            up_dir.mkdir(parents=True, exist_ok=False)
            _atomic_write_bytes(up_dir / upload.payload_filename, bytes(data))
            _atomic_write_text(
                up_dir / _META_FILENAME,
                json.dumps(upload.to_dict(), ensure_ascii=False, indent=2),
            )
            log.info(
                "upload created id=%s size=%d sha=%s label=%s",
                upload.upload_id,
                upload.size_bytes,
                upload.sha256[:8],
                upload.label,
            )
            return upload

        return await asyncio.to_thread(_do_create)

    async def get_upload(self, upload_id: str) -> Upload:
        _ensure_id(upload_id, kind="upload")

        def _do_read() -> Upload:
            up_dir = self._upload_dir(upload_id)
            meta_path = up_dir / _META_FILENAME
            if not meta_path.exists():
                raise UploadNotFound(f"Upload {upload_id} not found")
            meta = json.loads(_read_text_with_retry(meta_path, encoding="utf-8"))
            upload = Upload.from_dict(meta)
            if upload.is_expired():
                raise UploadExpired(f"Upload {upload_id} expired at {upload.expires_at}")
            return upload

        return await asyncio.to_thread(_do_read)

    async def open_upload_payload(self, upload_id: str) -> bytes:
        """Return the raw bytes of the uploaded payload. Caller parses if needed."""
        upload = await self.get_upload(upload_id)
        path = self._upload_dir(upload_id) / upload.payload_filename
        return await asyncio.to_thread(path.read_bytes)

    async def load_upload_json(self, upload_id: str) -> dict[str, Any]:
        """Convenience: return parsed JSON object from the upload."""
        raw = await self.open_upload_payload(upload_id)
        return json.loads(raw.decode("utf-8"))

    async def delete_upload(self, upload_id: str) -> bool:
        _ensure_id(upload_id, kind="upload")
        up_dir = self._upload_dir(upload_id)

        def _do_delete() -> bool:
            if not up_dir.exists():
                return False
            _safe_rmtree(up_dir)
            log.info("upload deleted id=%s", upload_id)
            return True

        result = await asyncio.to_thread(_do_delete)
        await self._drop_lock(f"upload:{upload_id}")
        return result

    # ── Job CRUD ────────────────────────────────────────────────────

    async def create_job(self, job: Job) -> None:
        """Persist a freshly-built Job (status=QUEUED). Caller owns the Job object."""
        job_dir = self._job_dir(job.job_id)

        def _do_create() -> None:
            if job_dir.exists():
                raise JobError(f"Job {job.job_id} already exists")
            (job_dir / "output").mkdir(parents=True, exist_ok=True)
            _atomic_write_text(
                job_dir / _META_FILENAME,
                json.dumps(job.to_dict(), ensure_ascii=False, indent=2),
            )
            log.info(
                "job created id=%s upload=%s targets=%s",
                job.job_id,
                job.upload_id,
                job.targets,
            )

        await asyncio.to_thread(_do_create)

    async def get_job(self, job_id: str) -> Job:
        _ensure_id(job_id, kind="job")

        def _do_read() -> Job:
            meta_path = self._job_dir(job_id) / _META_FILENAME
            if not meta_path.exists():
                raise JobNotFound(f"Job {job_id} not found")
            meta = json.loads(_read_text_with_retry(meta_path, encoding="utf-8"))
            j = Job.from_dict(meta)
            # Lazy expiry: a job past its TTL is reported as EXPIRED even if the
            # sweeper hasn't yet rmtree'd it. Outputs may still be on disk for a
            # few minutes — readers must treat EXPIRED as "do not download".
            if not j.status.is_terminal and j.is_expired():
                j.status = JobStatus.EXPIRED
            return j

        return await asyncio.to_thread(_do_read)

    async def update_job(self, job: Job) -> None:
        """Persist mutated job state. Should be called under `_lock_for(f"job:{id}")`."""
        meta_path = self._job_dir(job.job_id) / _META_FILENAME

        def _do_write() -> None:
            _atomic_write_text(
                meta_path,
                json.dumps(job.to_dict(), ensure_ascii=False, indent=2),
            )

        await asyncio.to_thread(_do_write)

    async def write_job_output(
        self,
        job_id: str,
        target: str,
        filename: str,
        data: bytes,
    ) -> JobOutput:
        """Write a single rendered output. Returns the JobOutput record (caller must
        attach to the Job and call update_job)."""
        _ensure_id(job_id, kind="job")
        if "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError(f"Invalid output filename: {filename!r}")

        def _do_write() -> JobOutput:
            out_dir = self._job_dir(job_id) / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / filename
            _atomic_write_bytes(out_path, data)
            return JobOutput(
                target=target,
                filename=filename,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                download_url=f"/jobs/{job_id}/files/{filename}",
            )

        return await asyncio.to_thread(_do_write)

    async def open_job_output(self, job_id: str, filename: str) -> Path:
        """Resolve a download path. Validates job exists, is not expired, and the
        filename is one of the recorded outputs (no arbitrary path traversal)."""
        _ensure_id(job_id, kind="job")
        if "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError(f"Invalid filename: {filename!r}")

        job = await self.get_job(job_id)
        if job.status == JobStatus.EXPIRED:
            raise JobExpired(f"Job {job_id} expired")
        if not any(o.filename == filename for o in job.outputs):
            raise JobNotFound(f"Output {filename!r} not registered on job {job_id}")
        path = self._job_dir(job_id) / "output" / filename
        if not await asyncio.to_thread(path.is_file):
            raise JobNotFound(f"Output {filename!r} missing on disk for job {job_id}")
        return path

    async def delete_job(self, job_id: str) -> bool:
        _ensure_id(job_id, kind="job")
        job_dir = self._job_dir(job_id)

        def _do_delete() -> bool:
            if not job_dir.exists():
                return False
            _safe_rmtree(job_dir)
            log.info("job deleted id=%s", job_id)
            return True

        result = await asyncio.to_thread(_do_delete)
        await self._drop_lock(f"job:{job_id}")
        return result

    # ── Listing ─────────────────────────────────────────────────────

    async def list_uploads(self) -> list[Upload]:
        def _do_list() -> list[Upload]:
            out: list[Upload] = []
            if not self._uploads_dir.exists():
                return out
            for entry in self._uploads_dir.iterdir():
                if not entry.is_dir():
                    continue
                meta = entry / _META_FILENAME
                if not meta.exists():
                    continue
                try:
                    data = json.loads(_read_text_with_retry(meta, encoding="utf-8"))
                    out.append(Upload.from_dict(data))
                except (OSError, json.JSONDecodeError, KeyError) as exc:
                    log.warning("Skipping corrupt upload meta %s: %s", meta, exc)
            return out

        return await asyncio.to_thread(_do_list)

    async def list_jobs(
        self,
        *,
        statuses: Iterable[JobStatus] | None = None,
        apply_lazy_expiry: bool = True,
    ) -> list[Job]:
        """List all jobs.

        Args:
            statuses: filter by these statuses. None = all.
            apply_lazy_expiry: when True (default), non-terminal jobs whose
                TTL has passed are reported as EXPIRED. Set False inside the
                sweeper, which needs to observe the on-disk status (RUNNING
                jobs must NOT be evicted even when past TTL).
        """
        wanted = set(statuses) if statuses else None

        def _do_list() -> list[Job]:
            out: list[Job] = []
            if not self._jobs_dir.exists():
                return out
            for entry in self._jobs_dir.iterdir():
                if not entry.is_dir():
                    continue
                meta = entry / _META_FILENAME
                if not meta.exists():
                    continue
                try:
                    data = json.loads(_read_text_with_retry(meta, encoding="utf-8"))
                    j = Job.from_dict(data)
                except (OSError, json.JSONDecodeError, KeyError) as exc:
                    log.warning("Skipping corrupt job meta %s: %s", meta, exc)
                    continue
                if apply_lazy_expiry and not j.status.is_terminal and j.is_expired():
                    j.status = JobStatus.EXPIRED
                if wanted is None or j.status in wanted:
                    out.append(j)
            return out

        return await asyncio.to_thread(_do_list)

    # ── Workspace CRUD ──────────────────────────────────────────────

    async def create_workspace(
        self,
        files: list[tuple[str, bytes]],
        *,
        label: str | None = None,
        ttl: timedelta | None = None,
    ) -> Workspace:
        """Persist a multi-file bundle as a content-addressed workspace.

        `files` is a list of (path, bytes) tuples. The path is workspace-relative
        and validated via `validate_workspace_path`. Bytes are stored verbatim;
        MIME is auto-detected from magic bytes.

        Content-addressed dedup: workspace_id is derived from a sha256 of the
        sorted manifest. Re-uploading identical files returns the same workspace
        (lifecycle reset to a fresh TTL). This means clients can safely retry
        without bloating storage.

        Raises:
            WorkspaceTooLarge: total size or file count exceeds limits.
            WorkspaceInvalidPath: any path violates the validator.
        """
        if not files:
            raise JobError("Workspace requires at least one file")
        if len(files) > self._max_workspace_files:
            raise WorkspaceTooLarge(
                f"Workspace has {len(files)} files > {self._max_workspace_files} limit"
            )
        total_bytes = sum(len(b) for _, b in files)
        if total_bytes > self._max_workspace_bytes:
            raise WorkspaceTooLarge(
                f"Workspace size {total_bytes} bytes > {self._max_workspace_bytes} limit"
            )
        for path, data in files:
            if len(data) > self._max_workspace_per_file_bytes:
                raise WorkspaceTooLarge(
                    f"File {path!r} is {len(data)} bytes > "
                    f"{self._max_workspace_per_file_bytes} per-file limit"
                )

        # Validate paths and dedup within the bundle.
        seen: set[str] = set()
        parts: list[WorkspacePart] = []
        for raw_path, data in files:
            canonical = validate_workspace_path(raw_path)
            if canonical in seen:
                raise WorkspaceInvalidPath(f"Duplicate path in bundle: {canonical!r}")
            seen.add(canonical)
            file_sha = hashlib.sha256(data).hexdigest()
            mime = detect_mime(canonical, data[:32])
            parts.append(
                WorkspacePart(
                    path=canonical,
                    size_bytes=len(data),
                    sha256=file_sha,
                    content_type=mime,
                )
            )

        workspace = Workspace.new(parts=parts, ttl=ttl or self._workspace_ttl, label=label)

        def _do_create() -> Workspace:
            ws_dir = self._workspace_dir(workspace.workspace_id)
            # Content-addressed dedup: if the workspace already exists with the
            # same sha256, refresh its TTL and return the existing record. This
            # is safe because the bundle is content-addressed — same id ⇒ same
            # bytes already on disk.
            meta_path = ws_dir / _META_FILENAME
            if meta_path.exists():
                try:
                    existing = Workspace.from_dict(json.loads(_read_text_with_retry(meta_path)))
                    if existing.sha256 == workspace.sha256:
                        # Refresh TTL: write same record with new expiry.
                        refreshed = Workspace(
                            workspace_id=existing.workspace_id,
                            sha256=existing.sha256,
                            parts=existing.parts,
                            total_size=existing.total_size,
                            created_at=existing.created_at,
                            expires_at=workspace.expires_at,
                            label=label or existing.label,
                        )
                        _atomic_write_text(
                            meta_path,
                            json.dumps(refreshed.to_dict(), ensure_ascii=False, indent=2),
                        )
                        log.info(
                            "workspace dedup hit id=%s parts=%d size=%d (TTL refreshed)",
                            refreshed.workspace_id,
                            len(refreshed.parts),
                            refreshed.total_size,
                        )
                        return refreshed
                except (OSError, json.JSONDecodeError, KeyError) as exc:
                    log.warning("Stale workspace meta at %s: %s — recreating", meta_path, exc)
                    _safe_rmtree(ws_dir)

            ws_dir.mkdir(parents=True, exist_ok=True)
            files_dir = ws_dir / "files"
            files_dir.mkdir(parents=True, exist_ok=True)
            for (raw_path, data), part in zip(files, parts, strict=True):
                target = files_dir / part.path
                target.parent.mkdir(parents=True, exist_ok=True)
                # Defense in depth: ensure target stays inside files_dir even
                # though path is validated. resolve() catches any symlink games.
                if not target.resolve().is_relative_to(files_dir.resolve()):
                    raise WorkspaceInvalidPath(f"Resolved path escapes workspace: {raw_path!r}")
                _atomic_write_bytes(target, data)
            _atomic_write_text(
                ws_dir / _META_FILENAME,
                json.dumps(workspace.to_dict(), ensure_ascii=False, indent=2),
            )
            log.info(
                "workspace created id=%s parts=%d total=%d sha=%s label=%s",
                workspace.workspace_id,
                len(parts),
                total_bytes,
                workspace.sha256[:12],
                label,
            )
            return workspace

        return await asyncio.to_thread(_do_create)

    async def get_workspace(self, workspace_id: str) -> Workspace:
        _ensure_id(workspace_id, kind="workspace")

        def _do_read() -> Workspace:
            ws_dir = self._workspace_dir(workspace_id)
            meta_path = ws_dir / _META_FILENAME
            if not meta_path.exists():
                raise WorkspaceNotFound(f"Workspace {workspace_id} not found")
            data = json.loads(_read_text_with_retry(meta_path))
            ws = Workspace.from_dict(data)
            if ws.is_expired():
                raise WorkspaceExpired(f"Workspace {workspace_id} expired at {ws.expires_at}")
            return ws

        return await asyncio.to_thread(_do_read)

    async def open_workspace_file(self, workspace_id: str, path: str) -> bytes:
        """Read a single file from the workspace. Validates path."""
        ws = await self.get_workspace(workspace_id)
        canonical = validate_workspace_path(path)
        if not ws.find_part(canonical):
            raise WorkspaceNotFound(f"File {canonical!r} not in workspace {workspace_id}")
        target = self._workspace_dir(workspace_id) / "files" / canonical
        return await asyncio.to_thread(target.read_bytes)

    async def materialize_workspace(self, workspace_id: str, into_dir: Path) -> dict[str, Any]:
        """Copy workspace files into `into_dir`, preserving the manifest layout.

        Used by the runner to set up a per-job temp directory. Returns a small
        report so callers know `content_data_path` (canonical first JSON file)
        and `screenshots_dir` (if any path begins with 'screenshots/').

        Idempotent: callers typically use a fresh temp dir per job.
        """
        ws = await self.get_workspace(workspace_id)
        src_root = self._workspace_dir(workspace_id) / "files"

        def _do_materialize() -> dict[str, Any]:
            into_dir.mkdir(parents=True, exist_ok=True)
            content_data_path: Path | None = None
            screenshots_dir: Path | None = None
            diagrams_dir: Path | None = None

            for part in ws.parts:
                src = src_root / part.path
                dst = into_dir / part.path
                dst.parent.mkdir(parents=True, exist_ok=True)
                # shutil.copy2 preserves mtime; cheap on local FS, copy-on-write
                # on btrfs/zfs/refs. Symlink would be faster but breaks Docker
                # mounts on Windows.
                shutil.copy2(src, dst)

                # Heuristic: identify content_data + screenshots/ + diagrams/.
                base = part.path.rsplit("/", 1)[-1].lower()
                if base in ("content-data.json", "content_data.json") and content_data_path is None:
                    content_data_path = dst
                if part.path.startswith("screenshots/") and screenshots_dir is None:
                    screenshots_dir = into_dir / "screenshots"
                if part.path.startswith("diagrams/") and diagrams_dir is None:
                    diagrams_dir = into_dir / "diagrams"

            return {
                "into_dir": str(into_dir),
                "content_data_path": str(content_data_path) if content_data_path else None,
                "screenshots_dir": str(screenshots_dir) if screenshots_dir else None,
                "diagrams_dir": str(diagrams_dir) if diagrams_dir else None,
                "file_count": len(ws.parts),
                "total_size": ws.total_size,
            }

        return await asyncio.to_thread(_do_materialize)

    async def delete_workspace(self, workspace_id: str) -> bool:
        _ensure_id(workspace_id, kind="workspace")
        ws_dir = self._workspace_dir(workspace_id)

        def _do_delete() -> bool:
            if not ws_dir.exists():
                return False
            _safe_rmtree(ws_dir)
            log.info("workspace deleted id=%s", workspace_id)
            return True

        result = await asyncio.to_thread(_do_delete)
        await self._drop_lock(f"workspace:{workspace_id}")
        return result

    async def list_workspaces(self) -> list[Workspace]:
        def _do_list() -> list[Workspace]:
            out: list[Workspace] = []
            if not self._workspaces_dir.exists():
                return out
            for entry in self._workspaces_dir.iterdir():
                if not entry.is_dir():
                    continue
                meta = entry / _META_FILENAME
                if not meta.exists():
                    continue
                try:
                    data = json.loads(_read_text_with_retry(meta, encoding="utf-8"))
                    out.append(Workspace.from_dict(data))
                except (OSError, json.JSONDecodeError, KeyError) as exc:
                    log.warning("Skipping corrupt workspace meta %s: %s", meta, exc)
            return out

        return await asyncio.to_thread(_do_list)

    # ── Locking ─────────────────────────────────────────────────────

    @contextlib.asynccontextmanager
    async def lock_job(self, job_id: str) -> AsyncIterator[None]:
        lock = await self._lock_for(f"job:{job_id}")
        async with lock:
            yield

    @contextlib.asynccontextmanager
    async def lock_upload(self, upload_id: str) -> AsyncIterator[None]:
        lock = await self._lock_for(f"upload:{upload_id}")
        async with lock:
            yield

    @contextlib.asynccontextmanager
    async def lock_workspace(self, workspace_id: str) -> AsyncIterator[None]:
        lock = await self._lock_for(f"workspace:{workspace_id}")
        async with lock:
            yield

    # ── TTL eviction ────────────────────────────────────────────────

    async def sweep_expired(self) -> dict[str, int]:
        """Evict expired uploads + jobs + workspaces. Returns counts.

        Safe to call repeatedly; idempotent. RUNNING jobs are NEVER evicted —
        the runner is responsible for transitioning them to a terminal state.
        Workspaces referenced by RUNNING jobs are protected by their longer TTL
        (24h workspace vs 1h job by default).
        """
        t0 = time.monotonic()
        uploads_removed = 0
        jobs_removed = 0
        workspaces_removed = 0

        for u in await self.list_uploads():
            if u.is_expired() and await self.delete_upload(u.upload_id):
                uploads_removed += 1

        # Sweep MUST observe on-disk status, not lazy-expired status — otherwise
        # a RUNNING job past its TTL would be seen as EXPIRED and evicted while
        # the worker is still rendering.
        for j in await self.list_jobs(apply_lazy_expiry=False):
            if j.status == JobStatus.RUNNING:
                continue  # runner will resolve
            if (j.is_expired() or j.status == JobStatus.EXPIRED) and await self.delete_job(
                j.job_id
            ):
                jobs_removed += 1

        for ws in await self.list_workspaces():
            if ws.is_expired() and await self.delete_workspace(ws.workspace_id):
                workspaces_removed += 1

        elapsed = time.monotonic() - t0
        if uploads_removed or jobs_removed or workspaces_removed:
            log.info(
                "sweep: uploads=%d jobs=%d workspaces=%d elapsed=%.3fs",
                uploads_removed,
                jobs_removed,
                workspaces_removed,
                elapsed,
            )
        return {
            "uploads": uploads_removed,
            "jobs": jobs_removed,
            "workspaces": workspaces_removed,
        }

    # ── Diagnostics ─────────────────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        """Lightweight readiness probe: writable storage + readable counts."""

        def _do_health() -> dict[str, Any]:
            probe = self._root / ".healthz"
            try:
                _atomic_write_text(probe, "ok")
                probe.unlink()
                writable = True
            except OSError as exc:
                log.warning("health probe write failed: %s", exc)
                writable = False
            uploads_n = (
                sum(1 for _ in self._uploads_dir.iterdir()) if self._uploads_dir.exists() else 0
            )
            jobs_n = sum(1 for _ in self._jobs_dir.iterdir()) if self._jobs_dir.exists() else 0
            workspaces_n = (
                sum(1 for _ in self._workspaces_dir.iterdir())
                if self._workspaces_dir.exists()
                else 0
            )
            return {
                "writable": writable,
                "uploads": uploads_n,
                "jobs": jobs_n,
                "workspaces": workspaces_n,
                "max_upload_bytes": self._max_upload_bytes,
                "max_workspace_bytes": self._max_workspace_bytes,
                "max_workspace_files": self._max_workspace_files,
                "upload_ttl_seconds": int(self._upload_ttl.total_seconds()),
                "job_ttl_seconds": int(self._job_ttl.total_seconds()),
                "workspace_ttl_seconds": int(self._workspace_ttl.total_seconds()),
            }

        return await asyncio.to_thread(_do_health)


# ─────────────────────────── Public exports ───────────────────────────

__all__ = [
    "JobStore",
    "DEFAULT_MAX_UPLOAD_BYTES",
    "DEFAULT_UPLOAD_TTL",
    "DEFAULT_JOB_TTL",
]
