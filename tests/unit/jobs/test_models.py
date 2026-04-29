"""Tests for job/upload data models — focus on (de)serialisation and lifecycle."""

from __future__ import annotations

from datetime import timedelta

import pytest

from etc_platform.jobs.models import (
    Job,
    JobOutput,
    JobStatus,
    Upload,
    VALID_TARGETS,
    from_iso,
    new_id,
    to_iso,
    utcnow,
)


class TestIdGeneration:
    def test_new_id_default_length(self) -> None:
        assert len(new_id()) == 20

    def test_new_id_with_prefix(self) -> None:
        i = new_id("u_")
        assert i.startswith("u_")
        assert len(i) == 22

    def test_new_id_uniqueness(self) -> None:
        # Strong probabilistic — 100 ids should never collide.
        ids = {new_id() for _ in range(100)}
        assert len(ids) == 100


class TestTimeRoundTrip:
    def test_to_iso_z_suffix(self) -> None:
        s = to_iso(utcnow())
        assert s.endswith("Z")

    def test_round_trip_preserves_instant(self) -> None:
        before = utcnow()
        after = from_iso(to_iso(before))
        # Microsecond precision survives.
        assert before == after


class TestUpload:
    def test_new_sets_ttl(self) -> None:
        u = Upload.new(
            size_bytes=100,
            content_type="application/json",
            sha256="a" * 64,
            ttl=timedelta(seconds=60),
        )
        delta = u.expires_at - u.created_at
        assert 59 <= delta.total_seconds() <= 61
        assert u.upload_id.startswith("u_")

    def test_round_trip_dict(self) -> None:
        u = Upload.new(
            size_bytes=42,
            content_type="application/json",
            sha256="b" * 64,
            ttl=timedelta(minutes=5),
            label="proj-a",
        )
        u2 = Upload.from_dict(u.to_dict())
        assert u2.upload_id == u.upload_id
        assert u2.size_bytes == u.size_bytes
        assert u2.label == "proj-a"
        assert u2.created_at == u.created_at

    def test_is_expired_negative_ttl(self) -> None:
        u = Upload.new(
            size_bytes=1,
            content_type="application/json",
            sha256="c" * 64,
            ttl=timedelta(seconds=-1),
        )
        assert u.is_expired()


class TestJob:
    def test_new_defaults(self) -> None:
        j = Job.new(
            upload_id="u_test",
            targets=["tkkt", "tkct"],
            ttl=timedelta(hours=1),
        )
        assert j.status == JobStatus.QUEUED
        assert j.targets == ["tkkt", "tkct"]
        assert j.auto_render_mermaid is True
        assert j.outputs == []

    def test_round_trip_with_outputs(self) -> None:
        j = Job.new(upload_id="u_x", targets=["tkkt"], ttl=timedelta(hours=1))
        j.outputs.append(
            JobOutput(
                target="tkkt",
                filename="thiet-ke-kien-truc.docx",
                size_bytes=12345,
                sha256="d" * 64,
                download_url=f"/jobs/{j.job_id}/files/thiet-ke-kien-truc.docx",
            )
        )
        j.status = JobStatus.SUCCEEDED
        roundtrip = Job.from_dict(j.to_dict())
        assert roundtrip.outputs[0].filename == "thiet-ke-kien-truc.docx"
        assert roundtrip.status == JobStatus.SUCCEEDED

    def test_public_view_omits_internal(self) -> None:
        j = Job.new(upload_id="u_x", targets=["tkkt"], ttl=timedelta(hours=1))
        j.metrics["secret_internal"] = "hide-me"
        v = j.public_view()
        assert "metrics" not in v
        assert "validation_report" not in v
        assert v["job_id"] == j.job_id

    def test_status_terminal(self) -> None:
        for s in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.EXPIRED):
            assert s.is_terminal
        for s in (JobStatus.QUEUED, JobStatus.RUNNING):
            assert not s.is_terminal


class TestTargets:
    @pytest.mark.parametrize("t", ["xlsx", "hdsd", "tkkt", "tkcs", "tkct"])
    def test_known_targets(self, t: str) -> None:
        assert t in VALID_TARGETS

    def test_no_extra_targets(self) -> None:
        assert len(VALID_TARGETS) == 5
