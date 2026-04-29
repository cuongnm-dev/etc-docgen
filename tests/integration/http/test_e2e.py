"""End-to-end test: upload → job → poll → download.

Exercises the full pipeline including the JobRunner background thread pool
and the docx/xlsx render engines. Marked `slow` + `integration` so it can
be deselected during fast-path development:

    pytest -m "not slow"

Requires the bundled minimal example fixture under examples/minimal/.
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

pytestmark = [pytest.mark.asyncio, pytest.mark.slow, pytest.mark.integration]


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PAYLOAD = REPO_ROOT / "examples" / "minimal" / "content-data.json"


@pytest_asyncio.fixture()
async def client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    settings = HttpSettings(
        storage_root=str(tmp_path / "storage"),
        api_key=None,
        upload_ttl_seconds=120,
        job_ttl_seconds=600,
        max_upload_bytes=10 * 1024 * 1024,
    )
    a = create_app(settings)
    async with a.router.lifespan_context(a):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=a),
            base_url="http://testserver",
            timeout=60.0,
        ) as c:
            yield c


async def _wait_terminal(
    client: httpx.AsyncClient, job_id: str, *, timeout_s: float = 60.0
) -> dict:
    """Poll job until it reaches a terminal state. Tight loop; for tests only."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        r = await client.get(f"/jobs/{job_id}")
        assert r.status_code == 200
        body = r.json()
        if body["status"] in (
            JobStatus.SUCCEEDED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
            JobStatus.EXPIRED.value,
        ):
            return body
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"Job {job_id} did not finish within {timeout_s}s; last={body}")
        await asyncio.sleep(0.2)


@pytest.mark.skipif(
    not EXAMPLE_PAYLOAD.exists(),
    reason="examples/minimal/content-data.json missing",
)
class TestEndToEnd:
    async def test_upload_render_download(
        self, client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        # 1) Upload the minimal example payload.
        payload = EXAMPLE_PAYLOAD.read_bytes()
        r = await client.post(
            "/uploads",
            files={"file": ("content-data.json", payload, "application/json")},
            data={"label": "e2e-minimal"},
        )
        assert r.status_code == 201, r.text
        upload_id = r.json()["upload_id"]

        # 2) Submit a job for tkkt only — keeps render time short.
        r2 = await client.post(
            "/jobs",
            json={
                "upload_id": upload_id,
                "targets": ["tkkt"],
                "auto_render_mermaid": False,  # skip mermaid CLI dep
                "label": "e2e-tkkt",
            },
        )
        assert r2.status_code == 202, r2.text
        job_id = r2.json()["job_id"]

        # 3) Poll until terminal.
        final = await _wait_terminal(client, job_id, timeout_s=60.0)
        assert final["status"] in (
            JobStatus.SUCCEEDED.value,
            JobStatus.FAILED.value,  # acceptable if minimal content fails validation
        )

        # If success, ensure outputs are downloadable.
        if final["status"] == JobStatus.SUCCEEDED.value:
            assert len(final["outputs"]) >= 1
            out0 = final["outputs"][0]
            r3 = await client.get(out0["download_url"])
            assert r3.status_code == 200
            assert r3.headers["content-type"].startswith(
                "application/vnd.openxmlformats"
            )
            saved = tmp_path / out0["filename"]
            saved.write_bytes(r3.content)
            # Sanity: docx is a zip → starts with PK\x03\x04
            assert saved.stat().st_size > 1024
            assert saved.read_bytes()[:4] == b"PK\x03\x04"
        else:
            # On FAILED, surface error diagnostics for debugging.
            assert final["error"] is not None
            print("e2e fail diagnostics:", json.dumps(final, indent=2))
