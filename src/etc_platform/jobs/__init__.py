"""Async job-based file processing for etc-platform.

This package implements an upload → process → download pattern that keeps
large content_data payloads OUT of the LLM context window:

    Client uploads file via HTTP        →  POST /uploads        → upload_id
    Client requests export job via MCP  →  export_async(...)    → job_id
    Server processes in background      →  worker thread        → outputs/
    Client polls job status             →  job_status(job_id)   → status
    Client downloads files via HTTP     →  GET  /jobs/{id}/...  → bytes

Token cost for the entire flow: ~80 tokens per export (3 small tool calls
+ 2 curl invocations) vs. ~120K tokens for the legacy inline-payload export.

Modules:
    models     — JobStatus, Job, Upload dataclasses + JSON (de)serialisation
    storage    — Filesystem-backed atomic CRUD + TTL eviction
    runner     — Background worker that consumes Job records
    http_app   — FastAPI app exposing upload/download/job HTTP endpoints
"""

from etc_platform.jobs.models import (
    Job,
    JobStatus,
    Upload,
    JobNotFound,
    UploadNotFound,
    JobValidationError,
)
from etc_platform.jobs.storage import JobStore

__all__ = [
    "Job",
    "JobStatus",
    "Upload",
    "JobStore",
    "JobNotFound",
    "UploadNotFound",
    "JobValidationError",
]
