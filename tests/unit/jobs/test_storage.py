"""Tests for JobStore — atomic CRUD, TTL eviction, concurrency, path safety."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path

import pytest

from etc_platform.jobs.models import (
    Job,
    JobNotFound,
    JobOutput,
    JobStatus,
    Upload,
    UploadExpired,
    UploadNotFound,
    UploadTooLarge,
)
from etc_platform.jobs.storage import JobStore

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "jobs-root"


@pytest.fixture()
def store(store_root: Path) -> JobStore:
    return JobStore(
        root=store_root,
        upload_ttl=timedelta(seconds=60),
        job_ttl=timedelta(minutes=10),
        max_upload_bytes=1024 * 1024,
    )


# ─────────────────────────── Upload CRUD ───────────────────────────


class TestUploadCRUD:
    async def test_create_and_read(self, store: JobStore) -> None:
        data = json.dumps({"hello": "world"}).encode()
        u = await store.create_upload(data, content_type="application/json", label="t")
        assert u.size_bytes == len(data)
        assert u.label == "t"
        loaded = await store.get_upload(u.upload_id)
        assert loaded.upload_id == u.upload_id
        assert loaded.sha256 == u.sha256

    async def test_load_json(self, store: JobStore) -> None:
        payload = {"x": 1, "y": ["a", "b"]}
        u = await store.create_upload(json.dumps(payload).encode())
        got = await store.load_upload_json(u.upload_id)
        assert got == payload

    async def test_reject_invalid_json_when_validating(self, store: JobStore) -> None:
        from etc_platform.jobs.models import JobError

        with pytest.raises(JobError):
            await store.create_upload(b"{not-json", validate_json=True)

    async def test_reject_oversize(self, store: JobStore) -> None:
        big = b"A" * (store.max_upload_bytes + 1)
        with pytest.raises(UploadTooLarge):
            await store.create_upload(big, validate_json=False)

    async def test_get_missing(self, store: JobStore) -> None:
        with pytest.raises(UploadNotFound):
            await store.get_upload("u_missing12345")

    async def test_invalid_id_rejected(self, store: JobStore) -> None:
        with pytest.raises(ValueError):
            await store.get_upload("../etc/passwd")
        with pytest.raises(ValueError):
            await store.get_upload("a")  # too short

    async def test_delete_idempotent(self, store: JobStore) -> None:
        u = await store.create_upload(b'{"a":1}')
        assert await store.delete_upload(u.upload_id) is True
        assert await store.delete_upload(u.upload_id) is False  # already gone

    async def test_expired_read_raises(self, store_root: Path) -> None:
        s = JobStore(
            root=store_root,
            upload_ttl=timedelta(seconds=-1),
            job_ttl=timedelta(minutes=10),
        )
        u = await s.create_upload(b'{"a":1}')
        with pytest.raises(UploadExpired):
            await s.get_upload(u.upload_id)


# ─────────────────────────── Job CRUD ───────────────────────────


class TestJobCRUD:
    async def test_create_and_read(self, store: JobStore) -> None:
        u = await store.create_upload(b'{"a":1}')
        j = Job.new(upload_id=u.upload_id, targets=["tkkt"], ttl=store.job_ttl)
        await store.create_job(j)
        loaded = await store.get_job(j.job_id)
        assert loaded.job_id == j.job_id
        assert loaded.status == JobStatus.QUEUED

    async def test_update_persists(self, store: JobStore) -> None:
        u = await store.create_upload(b'{"a":1}')
        j = Job.new(upload_id=u.upload_id, targets=["tkkt"], ttl=store.job_ttl)
        await store.create_job(j)
        async with store.lock_job(j.job_id):
            j2 = await store.get_job(j.job_id)
            j2.status = JobStatus.RUNNING
            await store.update_job(j2)
        again = await store.get_job(j.job_id)
        assert again.status == JobStatus.RUNNING

    async def test_lazy_expiry(self, store_root: Path) -> None:
        s = JobStore(
            root=store_root,
            upload_ttl=timedelta(minutes=1),
            job_ttl=timedelta(seconds=-1),  # already expired
        )
        u = await s.create_upload(b'{"a":1}')
        j = Job.new(upload_id=u.upload_id, targets=["tkkt"], ttl=s.job_ttl)
        await s.create_job(j)
        loaded = await s.get_job(j.job_id)
        assert loaded.status == JobStatus.EXPIRED

    async def test_get_missing(self, store: JobStore) -> None:
        with pytest.raises(JobNotFound):
            await store.get_job("j_missing12345")

    async def test_write_and_open_output(self, store: JobStore) -> None:
        u = await store.create_upload(b'{"a":1}')
        j = Job.new(upload_id=u.upload_id, targets=["tkkt"], ttl=store.job_ttl)
        await store.create_job(j)

        payload = b"binary-bytes" * 1024
        out = await store.write_job_output(
            j.job_id, target="tkkt", filename="report.docx", data=payload
        )
        # Attach + persist outputs to job (simulating runner)
        async with store.lock_job(j.job_id):
            jj = await store.get_job(j.job_id)
            jj.outputs.append(out)
            jj.status = JobStatus.SUCCEEDED
            await store.update_job(jj)

        path = await store.open_job_output(j.job_id, "report.docx")
        assert path.read_bytes() == payload

    async def test_open_output_rejects_traversal(self, store: JobStore) -> None:
        u = await store.create_upload(b'{"a":1}')
        j = Job.new(upload_id=u.upload_id, targets=["tkkt"], ttl=store.job_ttl)
        await store.create_job(j)
        with pytest.raises(ValueError):
            await store.open_job_output(j.job_id, "../../etc/passwd")


# ─────────────────────────── TTL sweeper ───────────────────────────


class TestSweep:
    async def test_sweep_evicts_expired(self, store_root: Path) -> None:
        s = JobStore(
            root=store_root,
            upload_ttl=timedelta(seconds=-1),
            job_ttl=timedelta(seconds=-1),
        )
        u = await s.create_upload(b'{"a":1}')
        j = Job.new(upload_id=u.upload_id, targets=["tkkt"], ttl=s.job_ttl)
        await s.create_job(j)
        report = await s.sweep_expired()
        assert report["uploads"] == 1
        assert report["jobs"] == 1
        # second sweep is a no-op
        again = await s.sweep_expired()
        # workspaces key added in v3 alongside uploads + jobs.
        assert again == {"uploads": 0, "jobs": 0, "workspaces": 0}

    async def test_sweep_skips_running_jobs(self, store_root: Path) -> None:
        s = JobStore(
            root=store_root,
            upload_ttl=timedelta(minutes=10),
            job_ttl=timedelta(seconds=-1),
        )
        u = await s.create_upload(b'{"a":1}')
        j = Job.new(upload_id=u.upload_id, targets=["tkkt"], ttl=s.job_ttl)
        j.status = JobStatus.RUNNING
        await s.create_job(j)
        report = await s.sweep_expired()
        # Running jobs are NEVER swept regardless of TTL.
        assert report["jobs"] == 0
        assert (s.root / "jobs" / j.job_id).exists()


# ─────────────────────────── Concurrency ───────────────────────────


class TestConcurrency:
    async def test_lock_serialises_updates(self, store: JobStore) -> None:
        u = await store.create_upload(b'{"a":1}')
        j = Job.new(upload_id=u.upload_id, targets=["tkkt"], ttl=store.job_ttl)
        await store.create_job(j)

        # Two concurrent updaters incrementing a shared counter must serialise.
        async def increment(times: int) -> None:
            for _ in range(times):
                async with store.lock_job(j.job_id):
                    jj = await store.get_job(j.job_id)
                    jj.metrics["count"] = int(jj.metrics.get("count", 0)) + 1
                    await store.update_job(jj)

        await asyncio.gather(increment(20), increment(20))
        final = await store.get_job(j.job_id)
        assert final.metrics["count"] == 40

    async def test_atomic_write_no_partial(self, store: JobStore, tmp_path: Path) -> None:
        # Indirect: create + read meta many times under contention; meta should always parse.
        u = await store.create_upload(b'{"a":1}')
        j = Job.new(upload_id=u.upload_id, targets=["tkkt"], ttl=store.job_ttl)
        await store.create_job(j)

        meta_path = store.root / "jobs" / j.job_id / "_meta.json"

        async def writer() -> None:
            for _ in range(50):
                async with store.lock_job(j.job_id):
                    jj = await store.get_job(j.job_id)
                    jj.metrics["w"] = jj.metrics.get("w", 0) + 1
                    await store.update_job(jj)

        from etc_platform.jobs.storage import _read_text_with_retry

        async def reader() -> None:
            for _ in range(50):
                # Outside the lock — must observe a complete file, never partial.
                # On Windows, concurrent rename briefly blocks reads; the helper
                # retries to absorb that <1ms window.
                raw = _read_text_with_retry(meta_path)
                json.loads(raw)
                await asyncio.sleep(0)

        await asyncio.gather(writer(), reader(), reader())
        assert (await store.get_job(j.job_id)).metrics["w"] == 50


# ─────────────────────────── Path safety ───────────────────────────


class TestPathSafety:
    async def test_storage_root_outside_allowed(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            JobStore(
                root=tmp_path / "outside",
                allowed_root=tmp_path / "allowed",  # different tree
            )


# ─────────────────────────── Health ───────────────────────────


class TestHealth:
    async def test_health_writable(self, store: JobStore) -> None:
        h = await store.health()
        assert h["writable"] is True
        assert h["uploads"] == 0
        assert h["jobs"] == 0
