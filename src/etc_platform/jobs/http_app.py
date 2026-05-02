"""FastAPI app exposing the upload/job/download endpoints.

Endpoints
---------

    POST   /uploads                multipart/form-data: file=@payload.json
                                   → 201 {upload_id, expires_at, size_bytes, sha256}

    GET    /uploads/{id}           → 200 Upload public view
    DELETE /uploads/{id}           → 204

    POST   /jobs                   JSON: {upload_id, targets, auto_render_mermaid?}
                                   → 202 {job_id, status, ...}
    GET    /jobs/{id}              → 200 Job public view (poll for status)
    DELETE /jobs/{id}              → 204
    GET    /jobs/{id}/files/{name} → 200 binary stream

    GET    /healthz                → 200 liveness
    GET    /readyz                 → 200 readiness (storage writable)

Auth
----
If env `ETC_PLATFORM_API_KEY` is set, all routes EXCEPT /healthz require header
`X-API-Key` matching it. Used for shared/team deployments. For local dev the
key is simply unset.

Errors
------
All errors are returned as JSON `{error: {code, message}, request_id}` with
the appropriate HTTP status code. Stack traces never leak.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi import (
    Path as PathParam,
)
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from etc_platform.jobs.models import (
    DEFAULT_WORKSPACE_MAX_BYTES,
    DEFAULT_WORKSPACE_MAX_FILES,
    VALID_TARGETS,
    Job,
    JobError,
    JobValidationError,
    UploadTooLarge,
    WorkspaceTooLarge,
)
from etc_platform.jobs.runner import JobRunner, RunnerConfig
from etc_platform.jobs.storage import (
    DEFAULT_JOB_TTL,
    DEFAULT_MAX_UPLOAD_BYTES,
    DEFAULT_UPLOAD_TTL,
    JobStore,
)

log = logging.getLogger("etc-platform.http")


# ─────────────────────────── Settings ───────────────────────────


class HttpSettings(BaseModel):
    """Runtime settings; populated from env in `from_env()`."""

    storage_root: str = Field(default="/data/_jobs")
    api_key: str | None = Field(default=None)
    upload_ttl_seconds: int = Field(default=int(DEFAULT_UPLOAD_TTL.total_seconds()))
    job_ttl_seconds: int = Field(default=int(DEFAULT_JOB_TTL.total_seconds()))
    workspace_ttl_seconds: int = Field(default=24 * 3600)  # 24h: longer than job
    max_upload_bytes: int = Field(default=DEFAULT_MAX_UPLOAD_BYTES)
    max_workspace_bytes: int = Field(default=DEFAULT_WORKSPACE_MAX_BYTES)
    max_workspace_files: int = Field(default=DEFAULT_WORKSPACE_MAX_FILES)
    cors_origins: list[str] = Field(default_factory=list)

    @classmethod
    def from_env(cls) -> HttpSettings:
        import os

        def _env(*names: str, default: str = "") -> str:
            """Read first non-empty env var. Supports legacy ETC_DOCGEN_* aliases."""
            for n in names:
                v = os.environ.get(n)
                if v:
                    return v
            return default

        def _int(name: str, default: int) -> int:
            # Legacy fallback: also try ETC_DOCGEN_X if ETC_PLATFORM_X unset
            legacy = name.replace("ETC_PLATFORM_", "ETC_DOCGEN_")
            raw = os.environ.get(name) or os.environ.get(legacy)
            return int(raw) if raw and raw.isdigit() else default

        cors = _env("ETC_PLATFORM_CORS_ORIGINS", "ETC_DOCGEN_CORS_ORIGINS")
        return cls(
            storage_root=_env(
                "ETC_PLATFORM_JOBS_ROOT", "ETC_DOCGEN_JOBS_ROOT", default="/data/_jobs"
            ),
            api_key=_env("ETC_PLATFORM_API_KEY", "ETC_DOCGEN_API_KEY") or None,
            upload_ttl_seconds=_int(
                "ETC_PLATFORM_UPLOAD_TTL_S", int(DEFAULT_UPLOAD_TTL.total_seconds())
            ),
            job_ttl_seconds=_int("ETC_PLATFORM_JOB_TTL_S", int(DEFAULT_JOB_TTL.total_seconds())),
            workspace_ttl_seconds=_int("ETC_PLATFORM_WORKSPACE_TTL_S", 24 * 3600),
            max_upload_bytes=_int("ETC_PLATFORM_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES),
            max_workspace_bytes=_int(
                "ETC_PLATFORM_MAX_WORKSPACE_BYTES", DEFAULT_WORKSPACE_MAX_BYTES
            ),
            max_workspace_files=_int(
                "ETC_PLATFORM_MAX_WORKSPACE_FILES", DEFAULT_WORKSPACE_MAX_FILES
            ),
            cors_origins=[s.strip() for s in cors.split(",") if s.strip()],
        )


# ─────────────────────────── Schemas ───────────────────────────


class UploadResponse(BaseModel):
    upload_id: str
    size_bytes: int
    sha256: str
    content_type: str
    created_at: str
    expires_at: str
    label: str | None = None


class CreateJobRequest(BaseModel):
    """Job creation request.

    Provide EITHER `workspace_id` (recommended; supports HDSD with screenshots)
    OR `upload_id` (legacy single-file content_data).
    """

    workspace_id: str | None = Field(default=None, min_length=2, max_length=64)
    upload_id: str | None = Field(default=None, min_length=2, max_length=64)
    targets: list[str] = Field(default_factory=lambda: list(VALID_TARGETS))
    auto_render_mermaid: bool = True
    screenshots_upload_id: str | None = None  # DEPRECATED: use workspace screenshots/ instead
    label: str | None = Field(default=None, max_length=128)


class JobResponse(BaseModel):
    job_id: str
    workspace_id: str | None = None
    upload_id: str | None = None
    status: str
    targets: list[str]
    created_at: str
    expires_at: str
    started_at: str | None
    finished_at: str | None
    outputs: list[dict[str, Any]]
    error: dict[str, Any] | None
    label: str | None = None


class WorkspacePartView(BaseModel):
    path: str
    size_bytes: int
    sha256: str
    content_type: str


class WorkspaceResponse(BaseModel):
    workspace_id: str
    sha256: str
    parts: list[WorkspacePartView]
    total_size: int
    file_count: int
    created_at: str
    expires_at: str
    label: str | None = None


# ─────────────────────────── Auth + middleware ───────────────────────────


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Generate a request_id, attach to logs and response headers."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        rid = request.headers.get("X-Request-ID") or secrets.token_urlsafe(8)
        request.state.request_id = rid
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error rid=%s path=%s", rid, request.url.path)
            return JSONResponse(
                status_code=500,
                content={
                    "error": {"code": "INTERNAL_ERROR", "message": "Unhandled server error"},
                    "request_id": rid,
                },
            )
        response.headers["X-Request-ID"] = rid
        return response


def _require_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    expected: str | None = getattr(request.app.state, "api_key", None)
    if not expected:
        return  # auth disabled
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "missing or invalid X-API-Key"},
        )


# ─────────────────────────── Lifespan ───────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Wire JobStore + JobRunner; tear down cleanly."""
    settings: HttpSettings = app.state.settings

    from pathlib import Path

    storage_root = Path(settings.storage_root)
    storage_root.mkdir(parents=True, exist_ok=True)

    store = JobStore(
        root=storage_root,
        upload_ttl=timedelta(seconds=settings.upload_ttl_seconds),
        job_ttl=timedelta(seconds=settings.job_ttl_seconds),
        workspace_ttl=timedelta(seconds=settings.workspace_ttl_seconds),
        max_upload_bytes=settings.max_upload_bytes,
        max_workspace_bytes=settings.max_workspace_bytes,
        max_workspace_files=settings.max_workspace_files,
    )
    runner = JobRunner(store, RunnerConfig.from_env())
    await runner.start()

    app.state.store = store
    app.state.runner = runner
    app.state.api_key = settings.api_key

    # Publish singletons so MCP tools (running in the same process) can share state.
    from etc_platform.jobs.shared import reset_shared, set_shared

    set_shared(store=store, runner=runner)

    log.info(
        "etc-platform http ready: root=%s api_key=%s upload_ttl=%ds job_ttl=%ds max_upload=%dMB",
        settings.storage_root,
        "set" if settings.api_key else "DISABLED",
        settings.upload_ttl_seconds,
        settings.job_ttl_seconds,
        settings.max_upload_bytes // (1024 * 1024),
    )
    try:
        yield
    finally:
        await runner.aclose()
        reset_shared()
        log.info("etc-platform http shutdown complete")


# ─────────────────────────── Error mapping ───────────────────────────


def _job_error_response(exc: JobError, request: Request) -> JSONResponse:
    rid = getattr(request.state, "request_id", "-")
    body: dict[str, Any] = {
        "error": {"code": exc.code, "message": str(exc)},
        "request_id": rid,
    }
    if isinstance(exc, JobValidationError) and exc.report:
        body["error"]["validation"] = exc.report
    return JSONResponse(status_code=exc.http_status, content=body)


# ─────────────────────────── App factory ───────────────────────────


def create_app(settings: HttpSettings | None = None) -> FastAPI:
    settings = settings or HttpSettings.from_env()
    app = FastAPI(
        title="etc-platform async export",
        version="2.0.0",
        description="Job-based file processing API for etc-platform.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(RequestIdMiddleware)

    if settings.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["X-API-Key", "X-Request-ID", "Content-Type"],
        )

    # ─── Error handlers ───

    @app.exception_handler(JobError)
    async def _handle_job_error(request: Request, exc: JobError) -> JSONResponse:
        return _job_error_response(exc, request)

    @app.exception_handler(HTTPException)
    async def _handle_http(request: Request, exc: HTTPException) -> JSONResponse:
        rid = getattr(request.state, "request_id", "-")
        detail = exc.detail
        if isinstance(detail, dict):
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": detail, "request_id": rid},
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": "HTTP_ERROR", "message": str(detail)},
                "request_id": rid,
            },
        )

    # ─── Routes: health ───

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(request: Request) -> dict[str, Any]:
        store: JobStore = request.app.state.store
        runner: JobRunner = request.app.state.runner
        h = await store.health()
        return {
            "status": "ok" if h.get("writable") else "degraded",
            "storage": h,
            "runner": {
                "queue_size": runner.queue_size,
                "inflight": runner.inflight_count,
                "workers": runner.config.workers,
                "queue_max": runner.config.queue_max,
            },
        }

    # ─── Routes: uploads ───

    @app.post(
        "/uploads",
        response_model=UploadResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(_require_api_key)],
    )
    async def create_upload(
        request: Request,
        file: UploadFile = File(...),
        label: str | None = Form(default=None, max_length=128),
    ) -> UploadResponse:
        store: JobStore = request.app.state.store
        # Stream-read but cap at max_upload_bytes + 1 to detect oversize.
        max_bytes = store.max_upload_bytes
        chunks: list[bytes] = []
        total = 0
        # `UploadFile.read()` loads everything; for safety we stream.
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise UploadTooLarge(f"Upload exceeds {max_bytes} bytes")
            chunks.append(chunk)
        data = b"".join(chunks)
        upload = await store.create_upload(
            data,
            content_type=file.content_type or "application/octet-stream",
            label=label,
        )
        return UploadResponse(
            upload_id=upload.upload_id,
            size_bytes=upload.size_bytes,
            sha256=upload.sha256,
            content_type=upload.content_type,
            created_at=upload.to_dict()["created_at"],
            expires_at=upload.to_dict()["expires_at"],
            label=upload.label,
        )

    @app.get(
        "/uploads/{upload_id}",
        dependencies=[Depends(_require_api_key)],
    )
    async def get_upload(
        request: Request,
        upload_id: Annotated[str, PathParam(min_length=2, max_length=64)],
    ) -> dict[str, Any]:
        store: JobStore = request.app.state.store
        u = await store.get_upload(upload_id)
        return u.to_dict()

    @app.delete(
        "/uploads/{upload_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(_require_api_key)],
    )
    async def delete_upload(
        request: Request,
        upload_id: Annotated[str, PathParam(min_length=2, max_length=64)],
    ) -> Response:
        store: JobStore = request.app.state.store
        await store.delete_upload(upload_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ─── Routes: jobs ───

    @app.post(
        "/jobs",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(_require_api_key)],
    )
    async def create_job(request: Request, body: CreateJobRequest) -> JobResponse:
        store: JobStore = request.app.state.store
        runner: JobRunner = request.app.state.runner

        if not (body.workspace_id or body.upload_id):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "MISSING_SOURCE",
                    "message": "Job requires workspace_id (recommended) or upload_id (legacy).",
                },
            )
        if body.workspace_id and body.upload_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "AMBIGUOUS_SOURCE",
                    "message": "Provide workspace_id OR upload_id, not both.",
                },
            )

        invalid = [t for t in body.targets if t not in VALID_TARGETS]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_TARGET",
                    "message": f"Unknown targets: {invalid}. Valid: {sorted(VALID_TARGETS)}",
                },
            )
        # Existence check fails fast with proper 404/410 mapping via JobError handler.
        if body.workspace_id:
            await store.get_workspace(body.workspace_id)
        else:
            await store.get_upload(body.upload_id)

        job = Job.new(
            workspace_id=body.workspace_id,
            upload_id=body.upload_id,
            targets=body.targets,
            ttl=store.job_ttl,
            auto_render_mermaid=body.auto_render_mermaid,
            screenshots_upload_id=body.screenshots_upload_id,
            label=body.label,
        )
        await store.create_job(job)
        try:
            await runner.submit(job.job_id)
        except RuntimeError as exc:
            # Queue full: best-effort transition to failed so the client sees it.
            await store.delete_job(job.job_id)
            raise HTTPException(
                status_code=503,
                detail={"code": "QUEUE_FULL", "message": str(exc)},
            ) from exc
        return JobResponse(**job.public_view())

    @app.get(
        "/jobs/{job_id}",
        response_model=JobResponse,
        dependencies=[Depends(_require_api_key)],
    )
    async def get_job(
        request: Request,
        job_id: Annotated[str, PathParam(min_length=2, max_length=64)],
    ) -> JobResponse:
        store: JobStore = request.app.state.store
        j = await store.get_job(job_id)
        return JobResponse(**j.public_view())

    @app.delete(
        "/jobs/{job_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(_require_api_key)],
    )
    async def delete_job(
        request: Request,
        job_id: Annotated[str, PathParam(min_length=2, max_length=64)],
    ) -> Response:
        store: JobStore = request.app.state.store
        await store.delete_job(job_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/jobs/{job_id}/files/{filename}",
        dependencies=[Depends(_require_api_key)],
    )
    async def download_job_file(
        request: Request,
        job_id: Annotated[str, PathParam(min_length=2, max_length=64)],
        filename: Annotated[str, PathParam(min_length=1, max_length=255)],
    ) -> FileResponse:
        store: JobStore = request.app.state.store
        path = await store.open_job_output(job_id, filename)
        # Pick a sane media type per extension.
        media_type = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".png": "image/png",
            ".pdf": "application/pdf",
        }.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(path=str(path), media_type=media_type, filename=filename)

    # ─── Routes: workspaces ───
    #
    # POST /workspaces accepts multipart/form-data with multiple file parts.
    # Each part must use a `path` (or `path[]`) form field via filename, e.g.:
    #
    #   curl -F "files[content-data.json]=@content-data.json" \
    #        -F "files[screenshots/F-001-step-01.png]=@F-001-step-01.png" \
    #        -F "files[diagrams/architecture.png]=@architecture.png" \
    #        -F "label=customs-stage6" \
    #        http://localhost:8000/workspaces
    #
    # FastAPI exposes form fields prefixed `files[...]` as a list when collected
    # via `Request.form()`. We use that low-level API because the bracket
    # convention encodes the workspace-relative path as part of the field name.

    @app.post(
        "/workspaces",
        response_model=WorkspaceResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(_require_api_key)],
    )
    async def create_workspace(request: Request) -> WorkspaceResponse:
        """Create a content-addressed multi-file workspace.

        Same content uploaded twice produces the same workspace_id; TTL is
        refreshed on dedup hit. Files map to workspace-relative paths via the
        `files[<path>]` form-field convention.
        """
        store: JobStore = request.app.state.store

        form = await request.form()
        files: list[tuple[str, bytes]] = []
        label: str | None = None
        total = 0

        for key, value in form.multi_items():
            if key == "label" and isinstance(value, str):
                label = value[:128]
                continue
            if not key.startswith("files["):
                continue  # ignore unknown fields
            # Extract path from key: files[screenshots/foo.png] → screenshots/foo.png
            if not key.endswith("]"):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "INVALID_FORM_KEY",
                        "message": f"Form key {key!r} must match files[<path>].",
                    },
                )
            ws_path = key[len("files[") : -1]
            if not hasattr(value, "read"):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "EXPECTED_FILE",
                        "message": f"Form key {key!r} must be a file part, not a string.",
                    },
                )
            data = await value.read()  # type: ignore[union-attr]
            total += len(data)
            if total > store.max_workspace_bytes:
                raise WorkspaceTooLarge(
                    f"Streamed total exceeds {store.max_workspace_bytes} bytes; "
                    f"reduce file count or per-file size."
                )
            files.append((ws_path, data))

        if not files:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "EMPTY_WORKSPACE",
                    "message": "Workspace must contain at least one file (use files[<path>] form field).",
                },
            )

        ws = await store.create_workspace(files, label=label)
        return WorkspaceResponse(**ws.public_view())

    @app.get(
        "/workspaces/{workspace_id}",
        response_model=WorkspaceResponse,
        dependencies=[Depends(_require_api_key)],
    )
    async def get_workspace(
        request: Request,
        workspace_id: Annotated[str, PathParam(min_length=2, max_length=64)],
    ) -> WorkspaceResponse:
        store: JobStore = request.app.state.store
        ws = await store.get_workspace(workspace_id)
        return WorkspaceResponse(**ws.public_view())

    @app.delete(
        "/workspaces/{workspace_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(_require_api_key)],
    )
    async def delete_workspace(
        request: Request,
        workspace_id: Annotated[str, PathParam(min_length=2, max_length=64)],
    ) -> Response:
        store: JobStore = request.app.state.store
        await store.delete_workspace(workspace_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


__all__ = ["create_app", "HttpSettings"]
