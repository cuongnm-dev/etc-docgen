"""Background runner that consumes Job records and renders outputs.

Architecture
------------
* `JobRunner` owns an asyncio.Queue of job_ids and a small worker pool.
* Workers pop from the queue, transition the Job through its state machine,
  and persist progress through the JobStore.
* CPU-bound rendering (docxtpl, openpyxl) runs in `asyncio.to_thread` so the
  loop stays responsive.
* The runner is started by the HTTP app's lifespan; on shutdown it waits for
  in-flight jobs to finish (with a timeout) before returning.

State machine
-------------
    QUEUED → RUNNING → SUCCEEDED
                    ↘ FAILED
    QUEUED → CANCELLED  (only if cancelled before pickup)
    *      → EXPIRED    (set lazily by JobStore.get_job; sweeper deletes dirs)

Retries
-------
* Validation failure → no retry, status FAILED with code VALIDATION_FAILED.
  This is a deterministic content problem; retrying without changes is futile.
* Engine error      → no automatic retry. Surface to caller; the caller can
  re-submit a fresh job (likely after fixing inputs). Auto-retry has been
  evaluated and rejected — most engine failures are deterministic
  template/content issues, and silent retry hides root causes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from etc_platform.jobs.models import (
    JobStatus,
)
from etc_platform.jobs.storage import JobStore

log = logging.getLogger("etc-platform.jobs.runner")


# ─────────────────────────── Configuration ───────────────────────────


@dataclass(slots=True, frozen=True)
class RunnerConfig:
    """Tunables for the job runner.

    Defaults are appropriate for a single-host deployment with a few writers.
    Override via env in `from_env()`.
    """

    workers: int = 2  # concurrent rendering jobs
    queue_max: int = 100  # backpressure: refuse new jobs above this
    job_timeout_seconds: float = 300.0  # hard ceiling per job (5 min)
    shutdown_grace_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> RunnerConfig:
        import os
        from dataclasses import fields

        # `dataclass(slots=True)` makes class-level attribute access return a
        # member_descriptor; the actual defaults live in the dataclass field
        # metadata. Read them through `fields(cls)` to be slots-safe.
        defaults = {f.name: f.default for f in fields(cls)}

        def _int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            return int(raw) if raw and raw.isdigit() else default

        def _float(name: str, default: float) -> float:
            raw = os.environ.get(name)
            try:
                return float(raw) if raw else default
            except ValueError:
                return default

        return cls(
            workers=_int("ETC_PLATFORM_RUNNER_WORKERS", defaults["workers"]),
            queue_max=_int("ETC_PLATFORM_RUNNER_QUEUE_MAX", defaults["queue_max"]),
            job_timeout_seconds=_float(
                "ETC_PLATFORM_RUNNER_TIMEOUT_S", defaults["job_timeout_seconds"]
            ),
            shutdown_grace_seconds=_float(
                "ETC_PLATFORM_RUNNER_SHUTDOWN_S", defaults["shutdown_grace_seconds"]
            ),
        )


# ─────────────────────────── Render core (sync) ───────────────────────────

# Target → (template filename, output filename, engine)
_TARGET_SPEC: dict[str, tuple[str, str, str]] = {
    "xlsx": ("test-case.xlsx", "kich-ban-kiem-thu.xlsx", "xlsx"),
    "hdsd": ("huong-dan-su-dung.docx", "huong-dan-su-dung.docx", "docx"),
    "tkkt": ("thiet-ke-kien-truc.docx", "thiet-ke-kien-truc.docx", "docx"),
    "tkcs": ("thiet-ke-co-so.docx", "thiet-ke-co-so.docx", "docx"),
    "tkct": ("thiet-ke-chi-tiet.docx", "thiet-ke-chi-tiet.docx", "docx"),
}


def _render_one_target(
    *,
    target: str,
    data_path: Path,
    out_dir: Path,
    screenshots_dir: Path | None,
    diagrams_dir: Path | None,
) -> dict[str, Any]:
    """Render one document. Synchronous — call inside `asyncio.to_thread`.

    Returns a dict shaped like:
        {target, success, filename, bytes, warnings, errors,
         screenshots_embedded?, screenshots_missing?}
    """
    from etc_platform.engines import docx as docx_engine
    from etc_platform.engines import xlsx as xlsx_engine
    from etc_platform.paths import schema as schema_path
    from etc_platform.paths import template

    if target not in _TARGET_SPEC:
        return {"target": target, "success": False, "error": f"Unknown target: {target}"}

    tpl_name, output_name, engine = _TARGET_SPEC[target]
    try:
        tpl_path = template(tpl_name)
    except FileNotFoundError as exc:
        return {"target": target, "success": False, "error": f"Template missing: {exc}"}

    out_path = out_dir / output_name

    try:
        if engine == "xlsx":
            report = xlsx_engine.fill(
                tpl_path,
                schema_path("test-case.xlsx.schema.yaml"),
                data_path,
                out_path,
            )
            success = not report.validator_failures
            return {
                "target": target,
                "success": success,
                "filename": output_name,
                "bytes": out_path.read_bytes() if success and out_path.exists() else None,
                "warnings": report.validator_failures[:5] if report.validator_failures else [],
            }
        # docx
        ss = screenshots_dir if (screenshots_dir and target == "hdsd") else None
        report = docx_engine.render(
            tpl_path,
            data_path,
            out_path,
            screenshots_dir=ss,
            diagrams_dir=diagrams_dir,
        )
        success = not report.errors and out_path.exists()
        return {
            "target": target,
            "success": success,
            "filename": output_name,
            "bytes": out_path.read_bytes() if success else None,
            "screenshots_embedded": getattr(report, "screenshots_embedded", 0),
            "screenshots_missing": getattr(report, "screenshots_missing", 0),
            "warnings": list(getattr(report, "warnings", []))[:5],
            "errors": list(getattr(report, "errors", []))[:5],
        }
    except Exception as exc:  # noqa: BLE001 — engine errors are heterogeneous
        log.exception("render failed for target=%s", target)
        return {"target": target, "success": False, "error": f"{type(exc).__name__}: {exc}"}


def _render_diagrams(content_data: dict, out_dir: Path) -> tuple[Path | None, dict | None]:
    """Pre-render diagrams declared in `content_data.diagrams`.

    Returns (diagrams_dir_or_None, render_report_or_None). On failure, returns
    (None, {status: "failed", ...}) — the caller decides whether to abort.
    """
    if not content_data.get("diagrams"):
        return None, None
    try:
        from etc_platform.engines import diagram as diagram_engine

        target_dir = out_dir / "diagrams"
        report = diagram_engine.render_all(content_data, target_dir)
        return (target_dir if report.rendered else None), report.to_dict()
    except Exception as exc:  # noqa: BLE001
        log.exception("diagram render failed")
        return None, {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}


# ─────────────────────────── Validation gate ───────────────────────────


def _validate_content(content_data: dict) -> dict[str, Any]:
    """Run Pydantic + quality validation. Returns the result dict.

    The caller decides whether errors block job execution. Standard policy:
    `errors` non-empty → reject; `warnings` informational only.
    """
    from etc_platform.data.validation import validate_content_data

    result = validate_content_data(content_data)
    return result.to_dict()


# ─────────────────────────── JobRunner ───────────────────────────


class JobRunner:
    """Async pool that processes Jobs in the background.

    Lifecycle:
        runner = JobRunner(store, RunnerConfig())
        await runner.start()           # spawn workers + sweeper
        await runner.submit(job_id)    # enqueue (raises if queue full)
        await runner.aclose()          # graceful shutdown
    """

    def __init__(self, store: JobStore, config: RunnerConfig | None = None) -> None:
        self._store = store
        self._config = config or RunnerConfig()
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self._config.queue_max)
        self._workers: list[asyncio.Task[None]] = []
        self._sweeper: asyncio.Task[None] | None = None
        self._closed = False
        self._started = False
        # Track in-flight job_ids so `aclose` can wait deterministically.
        self._inflight: set[str] = set()

    @property
    def config(self) -> RunnerConfig:
        return self._config

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def inflight_count(self) -> int:
        return len(self._inflight)

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for i in range(self._config.workers):
            self._workers.append(asyncio.create_task(self._worker_loop(i), name=f"job-worker-{i}"))
        self._sweeper = asyncio.create_task(self._sweep_loop(), name="job-sweeper")
        log.info(
            "runner started: workers=%d queue_max=%d", self._config.workers, self._config.queue_max
        )

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True

        # Stop accepting new work; signal workers to drain.
        for _ in self._workers:
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(_SENTINEL)

        # Wait for queue drain with timeout; cancel workers if it's stuck.
        try:
            await asyncio.wait_for(
                self._queue.join(),
                timeout=self._config.shutdown_grace_seconds,
            )
        except TimeoutError:
            log.warning(
                "shutdown timeout after %.1fs; cancelling workers",
                self._config.shutdown_grace_seconds,
            )
            for w in self._workers:
                w.cancel()

        for w in self._workers:
            with contextlib.suppress(asyncio.CancelledError):
                await w
        if self._sweeper:
            self._sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sweeper
        log.info("runner closed")

    # ── Submission ──────────────────────────────────────────────────

    async def submit(self, job_id: str) -> None:
        if self._closed:
            raise RuntimeError("Runner is closed; cannot submit new jobs")
        try:
            self._queue.put_nowait(job_id)
        except asyncio.QueueFull as exc:
            raise RuntimeError(
                f"Job queue full ({self._config.queue_max}); try again shortly"
            ) from exc

    # ── Worker loop ─────────────────────────────────────────────────

    async def _worker_loop(self, worker_id: int) -> None:
        log.debug("worker %d started", worker_id)
        try:
            while True:
                job_id = await self._queue.get()
                try:
                    if job_id is _SENTINEL:  # type: ignore[comparison-overlap]
                        return
                    self._inflight.add(job_id)
                    try:
                        await self._process(job_id)
                    finally:
                        self._inflight.discard(job_id)
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            log.debug("worker %d cancelled", worker_id)
            raise

    async def _process(self, job_id: str) -> None:
        try:
            await asyncio.wait_for(
                self._process_inner(job_id),
                timeout=self._config.job_timeout_seconds,
            )
        except TimeoutError:
            await self._mark_failed(
                job_id,
                code="TIMEOUT",
                message=f"Job exceeded {self._config.job_timeout_seconds:.0f}s timeout",
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("unexpected error processing job=%s", job_id)
            await self._mark_failed(
                job_id,
                code="INTERNAL_ERROR",
                message=f"{type(exc).__name__}: {exc}",
            )

    async def _process_inner(self, job_id: str) -> None:
        # Re-read job under lock to observe status transitions atomically.
        async with self._store.lock_job(job_id):
            job = await self._store.get_job(job_id)
            if job.status != JobStatus.QUEUED:
                log.info("skip job=%s in non-queued status=%s", job_id, job.status.value)
                return
            from etc_platform.jobs.models import utcnow

            job.status = JobStatus.RUNNING
            job.started_at = utcnow()
            await self._store.update_job(job)

        log.info(
            "job %s start: targets=%s ws=%s upload=%s",
            job_id,
            job.targets,
            job.workspace_id,
            job.upload_id,
        )
        t0 = time.monotonic()

        # 3) Render in a temp workspace; outputs are streamed into JobStore on success.
        #    Two source modes:
        #      A) workspace_id (recommended): materialize bundle (content-data + screenshots + diagrams)
        #      B) upload_id (legacy): single-file content-data, no screenshots
        with tempfile.TemporaryDirectory(prefix=f"etc-job-{job_id}-") as tmpdir:
            tmp = Path(tmpdir)
            data_path: Path | None = None
            screenshots_dir: Path | None = None
            workspace_diagrams_dir: Path | None = None  # pre-rendered diagrams from workspace
            content_data: dict[str, Any] | None = None
            materialize_report: dict[str, Any] | None = None

            if job.workspace_id:
                try:
                    materialize_report = await self._store.materialize_workspace(
                        job.workspace_id, tmp
                    )
                except Exception as exc:  # noqa: BLE001
                    await self._mark_failed(
                        job_id,
                        code="WORKSPACE_UNREADABLE",
                        message=f"Failed to materialize workspace: {type(exc).__name__}: {exc}",
                    )
                    return
                cdp = materialize_report.get("content_data_path")
                if not cdp:
                    await self._mark_failed(
                        job_id,
                        code="WORKSPACE_MISSING_CONTENT_DATA",
                        message="Workspace has no content-data.json — cannot render",
                    )
                    return
                data_path = Path(cdp)
                if materialize_report.get("screenshots_dir"):
                    screenshots_dir = Path(materialize_report["screenshots_dir"])
                if materialize_report.get("diagrams_dir"):
                    workspace_diagrams_dir = Path(materialize_report["diagrams_dir"])
                try:
                    content_data = json.loads(data_path.read_text(encoding="utf-8"))
                except Exception as exc:  # noqa: BLE001
                    await self._mark_failed(
                        job_id,
                        code="CONTENT_DATA_UNREADABLE",
                        message=f"Workspace content-data.json invalid: {type(exc).__name__}: {exc}",
                    )
                    return
            elif job.upload_id:
                try:
                    content_data = await self._store.load_upload_json(job.upload_id)
                except Exception as exc:  # noqa: BLE001
                    await self._mark_failed(
                        job_id,
                        code="UPLOAD_UNREADABLE",
                        message=f"Failed to read upload: {type(exc).__name__}: {exc}",
                    )
                    return
                data_path = tmp / "content-data.json"
                data_path.write_text(
                    json.dumps(content_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            else:
                await self._mark_failed(
                    job_id,
                    code="NO_SOURCE",
                    message="Job has neither workspace_id nor upload_id",
                )
                return

            # 2) Validation gate (after we've loaded content_data).
            try:
                v_report = await asyncio.to_thread(_validate_content, content_data)
            except Exception as exc:  # noqa: BLE001
                await self._mark_failed(
                    job_id,
                    code="VALIDATION_CRASH",
                    message=f"{type(exc).__name__}: {exc}",
                )
                return
            async with self._store.lock_job(job_id):
                job = await self._store.get_job(job_id)
                job.validation_report = v_report
                await self._store.update_job(job)
            if v_report.get("errors"):
                await self._mark_failed(
                    job_id,
                    code="VALIDATION_FAILED",
                    message=f"{len(v_report['errors'])} schema error(s)",
                )
                return

            # Pre-render Mermaid/SVG diagrams declared in content_data.diagrams.
            # If the workspace already supplied a `diagrams/` dir, server-side
            # render is additive (engine merges both — workspace wins on conflict).
            engine_diagrams_dir, diagram_report = (
                await asyncio.to_thread(_render_diagrams, content_data, tmp)
                if job.auto_render_mermaid
                else (None, None)
            )
            # Prefer workspace-provided diagrams over engine output if both exist.
            diagrams_dir = workspace_diagrams_dir or engine_diagrams_dir

            # Render targets in parallel via to_thread; bound by min(targets, workers*2).
            results = await asyncio.gather(
                *(
                    asyncio.to_thread(
                        _render_one_target,
                        target=t,
                        data_path=data_path,
                        out_dir=tmp,
                        screenshots_dir=screenshots_dir,
                        diagrams_dir=diagrams_dir,
                    )
                    for t in job.targets
                ),
                return_exceptions=False,
            )

            # 4) Persist outputs + finalize job state under lock.
            async with self._store.lock_job(job_id):
                j = await self._store.get_job(job_id)
                any_failure = False
                for r in results:
                    if not r.get("success"):
                        any_failure = True
                        continue
                    payload: bytes | None = r.get("bytes")
                    fname: str | None = r.get("filename")
                    if not payload or not fname:
                        any_failure = True
                        continue
                    out = await self._store.write_job_output(
                        job_id, target=r["target"], filename=fname, data=payload
                    )
                    j.outputs.append(out)

                # Embed metrics for forensics
                j.metrics["targets_report"] = [
                    {k: v for k, v in r.items() if k != "bytes"} for r in results
                ]
                j.metrics["diagram_report"] = diagram_report
                j.metrics["materialize_report"] = materialize_report
                j.metrics["render_seconds"] = round(time.monotonic() - t0, 3)

                if any_failure and not j.outputs:
                    j.status = JobStatus.FAILED
                    j.error_code = "RENDER_FAILED"
                    j.error_message = "All targets failed; see metrics.targets_report"
                elif any_failure:
                    # Partial success — some targets rendered, some failed.
                    j.status = JobStatus.SUCCEEDED  # outputs available
                    j.error_code = "PARTIAL_SUCCESS"
                    j.error_message = "Some targets failed; see metrics.targets_report"
                else:
                    j.status = JobStatus.SUCCEEDED

                from etc_platform.jobs.models import utcnow

                j.finished_at = utcnow()
                await self._store.update_job(j)

        log.info(
            "job %s done: status=%s outputs=%d elapsed=%.3fs",
            job_id,
            j.status.value,
            len(j.outputs),
            j.metrics.get("render_seconds", 0.0),
        )

    async def _mark_failed(self, job_id: str, *, code: str, message: str) -> None:
        async with self._store.lock_job(job_id):
            try:
                j = await self._store.get_job(job_id)
            except Exception:
                log.exception("cannot reload job=%s while marking failed", job_id)
                return
            from etc_platform.jobs.models import utcnow

            j.status = JobStatus.FAILED
            j.error_code = code
            j.error_message = message
            j.finished_at = utcnow()
            await self._store.update_job(j)
        log.warning("job %s failed: code=%s message=%s", job_id, code, message)

    # ── Sweeper ─────────────────────────────────────────────────────

    async def _sweep_loop(self) -> None:
        # Period chosen so that a 30-min upload TTL evicts within ~5 min of expiry.
        interval = 300.0
        try:
            while not self._closed:
                try:
                    await self._store.sweep_expired()
                except Exception:  # noqa: BLE001
                    log.exception("sweep failed; will retry")
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            log.debug("sweeper cancelled")
            raise


# Sentinel object used to signal worker shutdown.
_SENTINEL: Any = object()


__all__ = ["JobRunner", "RunnerConfig"]
