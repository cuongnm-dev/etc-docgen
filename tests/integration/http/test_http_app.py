"""Integration tests for the FastAPI job app.

Uses ASGI lifespan via httpx.AsyncClient + ASGITransport so the JobStore +
JobRunner are wired up exactly as in production.

The tests exercise:
    * /healthz  + /readyz
    * /uploads  CRUD (happy path, oversize, invalid JSON, missing)
    * /jobs     create + poll + cancel
    * /jobs/{id}/files/{name}  download flow (small fake content_data)
    * Auth: with and without X-API-Key
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from etc_platform.jobs.http_app import HttpSettings, create_app
from etc_platform.jobs.models import JobStatus

pytestmark = pytest.mark.asyncio


# ─────────────────────────── Fixtures ───────────────────────────


@pytest_asyncio.fixture()
async def client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    """Build app + drive lifespan via FastAPI's router context. httpx's
    ASGITransport does not run lifespan events by default; we do it manually
    to keep the test runtime free of extra dependencies (asgi-lifespan)."""
    settings = HttpSettings(
        storage_root=str(tmp_path / "storage"),
        api_key=None,
        upload_ttl_seconds=60,
        job_ttl_seconds=300,
        max_upload_bytes=1024 * 1024,
    )
    a = create_app(settings)
    async with a.router.lifespan_context(a):
        transport = httpx.ASGITransport(app=a)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


# ─────────────────────────── Tests ───────────────────────────


class TestHealth:
    async def test_healthz(self, client: httpx.AsyncClient) -> None:
        r = await client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    async def test_readyz(self, client: httpx.AsyncClient) -> None:
        r = await client.get("/readyz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "storage" in body and "runner" in body
        assert body["runner"]["queue_max"] >= 1


class TestUpload:
    async def test_create_then_get(self, client: httpx.AsyncClient) -> None:
        payload = json.dumps({"hello": "world"}).encode()
        r = await client.post(
            "/uploads",
            files={"file": ("content-data.json", payload, "application/json")},
            data={"label": "proj-x"},
        )
        assert r.status_code == 201
        body = r.json()
        upload_id = body["upload_id"]
        assert body["size_bytes"] == len(payload)
        assert body["label"] == "proj-x"

        r2 = await client.get(f"/uploads/{upload_id}")
        assert r2.status_code == 200
        assert r2.json()["upload_id"] == upload_id

    async def test_invalid_json_rejected(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            "/uploads",
            files={"file": ("content-data.json", b"{bad", "application/json")},
        )
        assert r.status_code == 500 or r.status_code == 422 or r.status_code == 400
        # JobError handler maps to whatever code the JobError subclass declares.

    async def test_oversize_rejected(self, client: httpx.AsyncClient) -> None:
        big = b"A" * (1024 * 1024 + 10)  # exceeds 1 MB
        r = await client.post(
            "/uploads", files={"file": ("big.json", big, "application/json")}
        )
        assert r.status_code == 413

    async def test_get_unknown_returns_404(self, client: httpx.AsyncClient) -> None:
        r = await client.get("/uploads/u_doesnotexist1234")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "UPLOAD_NOT_FOUND"

    async def test_delete(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            "/uploads",
            files={"file": ("c.json", b'{"a":1}', "application/json")},
        )
        upload_id = r.json()["upload_id"]
        r2 = await client.delete(f"/uploads/{upload_id}")
        assert r2.status_code == 204
        r3 = await client.get(f"/uploads/{upload_id}")
        assert r3.status_code == 404


class TestJobLifecycle:
    async def test_create_invalid_targets(self, client: httpx.AsyncClient) -> None:
        # First create an upload
        r = await client.post(
            "/uploads", files={"file": ("c.json", b'{"a":1}', "application/json")}
        )
        upload_id = r.json()["upload_id"]
        r2 = await client.post(
            "/jobs",
            json={"upload_id": upload_id, "targets": ["bogus"]},
        )
        assert r2.status_code == 400
        assert r2.json()["error"]["code"] == "INVALID_TARGET"

    async def test_create_unknown_upload_404(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            "/jobs", json={"upload_id": "u_unknownXYZabc", "targets": ["tkkt"]}
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "UPLOAD_NOT_FOUND"

    async def test_create_then_get_then_cancel(self, client: httpx.AsyncClient) -> None:
        # Upload junk JSON — validation will fail, so we cancel before runner picks it up.
        r = await client.post(
            "/uploads", files={"file": ("c.json", b'{"a":1}', "application/json")}
        )
        upload_id = r.json()["upload_id"]

        r2 = await client.post(
            "/jobs",
            json={"upload_id": upload_id, "targets": ["tkkt"], "label": "test"},
        )
        assert r2.status_code == 202
        job_id = r2.json()["job_id"]
        assert r2.json()["status"] == JobStatus.QUEUED.value
        assert r2.json()["label"] == "test"

        # Get
        r3 = await client.get(f"/jobs/{job_id}")
        assert r3.status_code == 200

        # Delete — should always succeed (idempotent)
        r4 = await client.delete(f"/jobs/{job_id}")
        assert r4.status_code == 204

    async def test_download_unknown_file_404(self, client: httpx.AsyncClient) -> None:
        r = await client.post(
            "/uploads", files={"file": ("c.json", b'{"a":1}', "application/json")}
        )
        upload_id = r.json()["upload_id"]
        r2 = await client.post(
            "/jobs", json={"upload_id": upload_id, "targets": ["tkkt"]}
        )
        job_id = r2.json()["job_id"]
        r3 = await client.get(f"/jobs/{job_id}/files/nope.docx")
        # 404 either because file isn't registered or hasn't rendered yet
        assert r3.status_code in (404, 410)


class TestAuth:
    async def test_api_key_required_when_set(self, tmp_path: Path) -> None:
        settings = HttpSettings(
            storage_root=str(tmp_path / "s"),
            api_key="secret-token",
            upload_ttl_seconds=60,
            job_ttl_seconds=300,
            max_upload_bytes=1024 * 1024,
        )
        a = create_app(settings)
        async with a.router.lifespan_context(a), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=a), base_url="http://testserver"
        ) as c:
            # /healthz is open
            r = await c.get("/healthz")
            assert r.status_code == 200
            # /uploads requires header
            r2 = await c.post(
                "/uploads", files={"file": ("c.json", b'{"a":1}', "application/json")}
            )
            assert r2.status_code == 401
            r3 = await c.post(
                "/uploads",
                files={"file": ("c.json", b'{"a":1}', "application/json")},
                headers={"X-API-Key": "wrong"},
            )
            assert r3.status_code == 401
            r4 = await c.post(
                "/uploads",
                files={"file": ("c.json", b'{"a":1}', "application/json")},
                headers={"X-API-Key": "secret-token"},
            )
            assert r4.status_code == 201
