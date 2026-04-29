"""Data models for the async job pipeline.

Pure data + (de)serialisation; NO I/O. Storage / runner concerns live elsewhere.
"""

from __future__ import annotations

import enum
import re
import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

# ─────────────────────────── Exceptions ───────────────────────────


class JobError(Exception):
    """Base for job-pipeline errors. Subclasses map to HTTP status codes."""

    http_status: int = 500
    code: str = "INTERNAL_ERROR"


class UploadNotFound(JobError):
    http_status = 404
    code = "UPLOAD_NOT_FOUND"


class JobNotFound(JobError):
    http_status = 404
    code = "JOB_NOT_FOUND"


class JobValidationError(JobError):
    """Validation failed before/during processing — payload is the validation report."""

    http_status = 422
    code = "VALIDATION_FAILED"

    def __init__(self, message: str, *, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = report or {}


class UploadTooLargeError(JobError):
    http_status = 413
    code = "UPLOAD_TOO_LARGE"


class UploadExpiredError(JobError):
    http_status = 410
    code = "UPLOAD_EXPIRED"


class JobExpiredError(JobError):
    http_status = 410
    code = "JOB_EXPIRED"


class WorkspaceNotFound(JobError):
    http_status = 404
    code = "WORKSPACE_NOT_FOUND"


class WorkspaceExpiredError(JobError):
    http_status = 410
    code = "WORKSPACE_EXPIRED"


class WorkspaceTooLargeError(JobError):
    http_status = 413
    code = "WORKSPACE_TOO_LARGE"


class WorkspaceInvalidPathError(JobError):
    http_status = 400
    code = "WORKSPACE_INVALID_PATH"


class UnsupportedMediaTypeError(JobError):
    http_status = 415
    code = "UNSUPPORTED_MEDIA_TYPE"


UploadTooLarge = UploadTooLargeError
UploadExpired = UploadExpiredError
JobExpired = JobExpiredError
WorkspaceExpired = WorkspaceExpiredError
WorkspaceTooLarge = WorkspaceTooLargeError
WorkspaceInvalidPath = WorkspaceInvalidPathError
UnsupportedMediaType = UnsupportedMediaTypeError


# ─────────────────────────── Constants ───────────────────────────

# Length of base32-encoded random IDs (~25 bits per char → 100 bits @ 20 chars).
_ID_LENGTH = 20

VALID_TARGETS: frozenset[str] = frozenset({"xlsx", "hdsd", "tkkt", "tkcs", "tkct"})


def new_id(prefix: str = "") -> str:
    """Generate a URL-safe random ID. Prefix is for human grepping, not security."""
    raw = secrets.token_urlsafe(15)[:_ID_LENGTH]
    return f"{prefix}{raw}" if prefix else raw


def utcnow() -> datetime:
    """Timezone-aware UTC now — tests can monkeypatch this if needed."""
    return datetime.now(UTC)


def to_iso(dt: datetime) -> str:
    """Serialise datetime to RFC 3339 / ISO 8601 UTC. Always Z-suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def from_iso(s: str) -> datetime:
    """Parse RFC 3339 / ISO 8601 string → tz-aware datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


# ─────────────────────────── Upload ───────────────────────────


@dataclass(slots=True)
class Upload:
    """A single uploaded content_data payload, awaiting one or more export jobs.

    Lifecycle:
        - created via POST /uploads (HTTP layer)
        - referenced by 0..N jobs (each job opens it read-only)
        - evicted at expires_at OR explicit DELETE /uploads/{id}

    The actual JSON payload lives at `<storage_root>/uploads/<id>/payload.json`.
    Parsed dict is NEVER held in memory long-term — only at job start.
    """

    upload_id: str
    size_bytes: int
    content_type: str
    sha256: str
    created_at: datetime
    expires_at: datetime
    # Optional client-supplied label for human grepping (e.g. project slug).
    label: str | None = None
    # File-relative path under the upload dir. "payload.json" by default;
    # may be e.g. "screenshots.zip" for image bundles in future.
    payload_filename: str = "payload.json"

    # ── Constructors ──

    @classmethod
    def new(
        cls,
        *,
        size_bytes: int,
        content_type: str,
        sha256: str,
        ttl: timedelta,
        label: str | None = None,
        payload_filename: str = "payload.json",
    ) -> Upload:
        now = utcnow()
        return cls(
            upload_id=new_id("u_"),
            size_bytes=size_bytes,
            content_type=content_type,
            sha256=sha256,
            created_at=now,
            expires_at=now + ttl,
            label=label,
            payload_filename=payload_filename,
        )

    # ── (De)serialisation — JSON-friendly form for _meta.json on disk ──

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["created_at"] = to_iso(self.created_at)
        d["expires_at"] = to_iso(self.expires_at)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Upload:
        return cls(
            upload_id=d["upload_id"],
            size_bytes=int(d["size_bytes"]),
            content_type=d["content_type"],
            sha256=d["sha256"],
            created_at=from_iso(d["created_at"]),
            expires_at=from_iso(d["expires_at"]),
            label=d.get("label"),
            payload_filename=d.get("payload_filename", "payload.json"),
        )

    # ── Lifecycle helpers ──

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or utcnow()) >= self.expires_at


# ─────────────────────────── Job ───────────────────────────


class JobStatus(enum.StrEnum):
    """States in the job lifecycle. Linear progression except cancelled."""

    QUEUED = "queued"  # created, not yet picked by worker
    RUNNING = "running"  # worker has it; rendering in progress
    SUCCEEDED = "succeeded"  # all targets rendered, outputs available
    FAILED = "failed"  # error during validation/render
    CANCELLED = "cancelled"  # user requested cancel before completion
    EXPIRED = "expired"  # passed TTL; outputs purged

    @property
    def is_terminal(self) -> bool:
        return self in (
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.EXPIRED,
        )


@dataclass(slots=True)
class JobOutput:
    """A single rendered file produced by a job."""

    target: str  # xlsx | hdsd | tkkt | tkcs | tkct
    filename: str  # e.g. "thiet-ke-kien-truc.docx"
    size_bytes: int
    sha256: str
    download_url: str  # relative URL, e.g. "/jobs/<id>/files/<filename>"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> JobOutput:
        return cls(**d)


@dataclass(slots=True)
class Job:
    """An async export request. Lifecycle is owned by the JobStore + runner.

    Validation (cheap) runs synchronously at job creation; if it fails the
    job is rejected with HTTP 422 and never enters the queue. Heavy rendering
    runs in the worker thread pool.
    """

    job_id: str
    targets: list[str]
    auto_render_mermaid: bool
    status: JobStatus
    created_at: datetime
    expires_at: datetime
    # Source bundle reference. Exactly one of workspace_id / upload_id is set:
    #   workspace_id — multi-file workspace (recommended; supports HDSD with screenshots)
    #   upload_id    — single-file legacy upload (deprecated; auto-wrapped as workspace internally)
    workspace_id: str | None = None
    upload_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Outputs populated on SUCCEEDED.
    outputs: list[JobOutput] = field(default_factory=list)
    # Validation report from the Pydantic schema + quality checks (kept for forensics).
    validation_report: dict[str, Any] | None = None
    # Error info on FAILED.
    error_code: str | None = None
    error_message: str | None = None
    # Diagnostics for the runner — engine versions, render durations, screenshots embed counts.
    metrics: dict[str, Any] = field(default_factory=dict)
    # DEPRECATED: kept for back-compat with v2.0 single-purpose screenshot uploads.
    # New code uses workspace_id pointing to a multi-file workspace.
    screenshots_upload_id: str | None = None
    label: str | None = None

    # ── Constructors ──

    @classmethod
    def new(
        cls,
        *,
        targets: list[str],
        ttl: timedelta,
        workspace_id: str | None = None,
        upload_id: str | None = None,
        auto_render_mermaid: bool = True,
        screenshots_upload_id: str | None = None,
        label: str | None = None,
    ) -> Job:
        if not (workspace_id or upload_id):
            raise ValueError("Job.new requires workspace_id or upload_id (legacy)")
        if workspace_id and upload_id:
            raise ValueError("Job.new accepts workspace_id OR upload_id, not both")
        now = utcnow()
        return cls(
            job_id=new_id("j_"),
            workspace_id=workspace_id,
            upload_id=upload_id,
            targets=list(targets),
            auto_render_mermaid=auto_render_mermaid,
            status=JobStatus.QUEUED,
            created_at=now,
            expires_at=now + ttl,
            screenshots_upload_id=screenshots_upload_id,
            label=label,
        )

    # ── (De)serialisation ──

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "workspace_id": self.workspace_id,
            "upload_id": self.upload_id,
            "targets": list(self.targets),
            "auto_render_mermaid": self.auto_render_mermaid,
            "status": self.status.value,
            "created_at": to_iso(self.created_at),
            "expires_at": to_iso(self.expires_at),
            "started_at": to_iso(self.started_at) if self.started_at else None,
            "finished_at": to_iso(self.finished_at) if self.finished_at else None,
            "outputs": [o.to_dict() for o in self.outputs],
            "validation_report": self.validation_report,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "metrics": dict(self.metrics),
            "screenshots_upload_id": self.screenshots_upload_id,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Job:
        return cls(
            job_id=d["job_id"],
            workspace_id=d.get("workspace_id"),
            upload_id=d.get("upload_id"),
            targets=list(d.get("targets", [])),
            auto_render_mermaid=bool(d.get("auto_render_mermaid", True)),
            status=JobStatus(d["status"]),
            created_at=from_iso(d["created_at"]),
            expires_at=from_iso(d["expires_at"]),
            started_at=from_iso(d["started_at"]) if d.get("started_at") else None,
            finished_at=from_iso(d["finished_at"]) if d.get("finished_at") else None,
            outputs=[JobOutput.from_dict(o) for o in d.get("outputs", [])],
            validation_report=d.get("validation_report"),
            error_code=d.get("error_code"),
            error_message=d.get("error_message"),
            metrics=dict(d.get("metrics") or {}),
            screenshots_upload_id=d.get("screenshots_upload_id"),
            label=d.get("label"),
        )

    # ── Lifecycle helpers ──

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or utcnow()) >= self.expires_at

    def public_view(self) -> dict[str, Any]:
        """Stable JSON shape returned to clients. Omits engine internals."""
        return {
            "job_id": self.job_id,
            "workspace_id": self.workspace_id,
            "upload_id": self.upload_id,
            "status": self.status.value,
            "targets": list(self.targets),
            "created_at": to_iso(self.created_at),
            "expires_at": to_iso(self.expires_at),
            "started_at": to_iso(self.started_at) if self.started_at else None,
            "finished_at": to_iso(self.finished_at) if self.finished_at else None,
            "outputs": [o.to_dict() for o in self.outputs],
            "error": (
                {"code": self.error_code, "message": self.error_message}
                if self.error_code
                else None
            ),
            "label": self.label,
        }


# ─────────────────────────── Workspace ───────────────────────────

# Path validation: relative POSIX paths only, no traversal, max depth 4.
# Allows letters/digits/Vietnamese diacritics removed from filename for portability —
# upload PNG must use ASCII path even if its label is Vietnamese (encoding the label
# in JSON metadata is fine).
_WORKSPACE_PATH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-./]{0,254}$")
_MAX_PATH_DEPTH = 4

# MIME magic bytes — first N bytes per type. We trust magic over extension.
_MAGIC_BYTES: dict[str, list[bytes]] = {
    "application/json": [],  # JSON has no fixed magic; sniff at content-type only
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/svg+xml": [b"<?xml", b"<svg "],
    "application/pdf": [b"%PDF-"],
}

# Default workspace constraints (override via env in storage layer).
DEFAULT_WORKSPACE_MAX_FILES = 200
DEFAULT_WORKSPACE_MAX_BYTES = 100 * 1024 * 1024  # 100 MB
DEFAULT_WORKSPACE_PER_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file


def validate_workspace_path(path: str) -> str:
    """Normalize and validate a workspace-relative path.

    Returns the canonical form. Raises WorkspaceInvalidPath on:
      - absolute paths or paths starting with `/`
      - traversal segments (`..`)
      - backslashes (Windows-style)
      - depth > _MAX_PATH_DEPTH
      - characters outside [A-Za-z0-9_-./]
      - empty / whitespace-only
    """
    if not isinstance(path, str) or not path.strip():
        raise WorkspaceInvalidPath(f"Path must be a non-empty string, got {path!r}")
    p = path.replace("\\", "/").strip()
    if p.startswith("/"):
        raise WorkspaceInvalidPath(f"Absolute paths not allowed: {path!r}")
    # Filter out empty and '.' segments during canonicalisation.
    parts = [seg for seg in p.split("/") if seg and seg != "."]
    if any(seg == ".." for seg in parts):
        raise WorkspaceInvalidPath(f"Traversal segments not allowed: {path!r}")
    if not parts:
        raise WorkspaceInvalidPath(f"Path resolves to empty: {path!r}")
    if len(parts) > _MAX_PATH_DEPTH:
        raise WorkspaceInvalidPath(f"Path depth {len(parts)} > {_MAX_PATH_DEPTH}: {path!r}")
    canonical = "/".join(parts)
    if not _WORKSPACE_PATH_RE.fullmatch(canonical):
        raise WorkspaceInvalidPath(
            f"Path contains invalid characters; allowed pattern "
            f"^[A-Za-z0-9_][A-Za-z0-9_\\-./]*$: {path!r}"
        )
    return canonical


def detect_mime(filename: str, head: bytes) -> str:
    """Sniff MIME type from magic bytes; fall back to extension hint.

    `head` should be at least 16 bytes from the start of the file.
    """
    for mime, magics in _MAGIC_BYTES.items():
        for m in magics:
            if head.startswith(m):
                return mime
    # Extension fallbacks for types without magic bytes (.json, .txt).
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "json":
        return "application/json"
    if ext in ("txt", "md"):
        return "text/plain"
    return "application/octet-stream"


@dataclass(slots=True)
class WorkspacePart:
    """A single file within a workspace."""

    path: str  # canonical workspace-relative path (validated)
    size_bytes: int
    sha256: str
    content_type: str  # detected via magic bytes when possible

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkspacePart:
        return cls(**d)


@dataclass(slots=True)
class Workspace:
    """An immutable, content-addressed bundle of files used by render jobs.

    Workspaces are the v3+ replacement for Upload. They support:
      - multi-file bundles (content_data.json + screenshots/* + diagrams/*)
      - content-addressed dedup (same files → same workspace_id, no double storage)
      - manifest-based audit trail
      - longer TTL than jobs so re-render does not require re-upload

    Lifecycle:
      - created via POST /workspaces (multipart, multi-file)
      - referenced by 0..N jobs (each job materializes the bundle into temp dir)
      - evicted at expires_at OR explicit DELETE /workspaces/{id}

    Storage layout:
      <root>/workspaces/<id>/
        _meta.json           — Workspace.to_dict()
        files/<part.path>    — actual file bytes (each WorkspacePart)
    """

    workspace_id: str
    sha256: str  # sha256 over sorted manifest (path+sha256 pairs) — content-addressed
    parts: list[WorkspacePart]
    total_size: int
    created_at: datetime
    expires_at: datetime
    label: str | None = None

    # ── Constructors ──

    @classmethod
    def new(
        cls,
        *,
        parts: list[WorkspacePart],
        ttl: timedelta,
        label: str | None = None,
    ) -> Workspace:
        # Compute content-addressed bundle sha256 over sorted manifest.
        import hashlib

        h = hashlib.sha256()
        for p in sorted(parts, key=lambda x: x.path):
            h.update(p.path.encode("utf-8"))
            h.update(b"\x00")
            h.update(p.sha256.encode("ascii"))
            h.update(b"\x00")
        bundle_sha = h.hexdigest()

        now = utcnow()
        return cls(
            workspace_id="ws_" + bundle_sha[:18],
            sha256=bundle_sha,
            parts=list(parts),
            total_size=sum(p.size_bytes for p in parts),
            created_at=now,
            expires_at=now + ttl,
            label=label,
        )

    # ── (De)serialisation ──

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "sha256": self.sha256,
            "parts": [p.to_dict() for p in self.parts],
            "total_size": self.total_size,
            "created_at": to_iso(self.created_at),
            "expires_at": to_iso(self.expires_at),
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Workspace:
        return cls(
            workspace_id=d["workspace_id"],
            sha256=d["sha256"],
            parts=[WorkspacePart.from_dict(p) for p in d.get("parts", [])],
            total_size=int(d["total_size"]),
            created_at=from_iso(d["created_at"]),
            expires_at=from_iso(d["expires_at"]),
            label=d.get("label"),
        )

    # ── Lifecycle helpers ──

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or utcnow()) >= self.expires_at

    def find_part(self, path: str) -> WorkspacePart | None:
        canonical = validate_workspace_path(path)
        for p in self.parts:
            if p.path == canonical:
                return p
        return None

    def public_view(self) -> dict[str, Any]:
        """Manifest-only view returned to clients (no internal flags)."""
        return {
            "workspace_id": self.workspace_id,
            "sha256": self.sha256,
            "parts": [
                {
                    "path": p.path,
                    "size_bytes": p.size_bytes,
                    "sha256": p.sha256,
                    "content_type": p.content_type,
                }
                for p in self.parts
            ],
            "total_size": self.total_size,
            "file_count": len(self.parts),
            "created_at": to_iso(self.created_at),
            "expires_at": to_iso(self.expires_at),
            "label": self.label,
        }
