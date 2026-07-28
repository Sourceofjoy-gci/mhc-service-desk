from __future__ import annotations

from datetime import timedelta

import pytest
from botocore.exceptions import ClientError
from django.utils import timezone


def _event(tmp_path):
    from apps.administration.models import DisposalEvent

    return DisposalEvent.objects.create(
        policy_snapshot={"ticket": {"days": 30}},
        policy_hash="a" * 64,
        summary=[{"table": "ticket", "rows_disposed": 1}],
        summary_hash="b" * 64,
        certificate_path=str(tmp_path / "certificate.json"),
    )


def test_retention_side_effect_worker_has_stable_default_queue_registration():
    from django.conf import settings

    from apps.administration.tasks import process_retention_side_effects

    assert (
        process_retention_side_effects.name
        == "apps.administration.tasks.process_retention_side_effects"
    )
    assert settings.CELERY_BEAT_SCHEDULE["retention-side-effects"] == {
        "task": "apps.administration.tasks.process_retention_side_effects",
        "schedule": 60.0,
    }
    assert "apps.administration.tasks.*" not in settings.CELERY_TASK_ROUTES


@pytest.mark.django_db(transaction=True)
def test_cleanup_worker_deletes_exact_version_and_publishes_after_completion(
    monkeypatch, tmp_path
):
    from apps.administration.tasks import process_retention_side_effects
    from apps.files.models import ObjectDeleteJob

    event = _event(tmp_path)
    job = ObjectDeleteJob.objects.create(
        disposal_event=event,
        source_attachment_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        bucket="attachments",
        object_key="retention/exact.txt",
        version_id="version-1",
        etag="etag-1",
        next_attempt_at=timezone.now(),
    )
    deleted = []
    monkeypatch.setattr(
        "apps.administration.tasks.delete_from_minio",
        lambda *, stored_object: deleted.append(stored_object),
    )

    result = process_retention_side_effects()

    job.refresh_from_db()
    event.refresh_from_db()
    assert result == {"completed": 1, "failed": 0, "published": 1}
    assert job.completed_at is not None
    assert event.object_cleanup_completed_at is not None
    assert event.certificate_exported_at is not None
    assert (
        deleted[0].bucket,
        deleted[0].key,
        deleted[0].version_id,
        deleted[0].etag,
    ) == ("attachments", "retention/exact.txt", "version-1", "etag-1")
    assert (tmp_path / "certificate.json").exists()


@pytest.mark.django_db(transaction=True)
def test_cleanup_worker_keeps_transient_failure_retriable(monkeypatch, tmp_path):
    from apps.administration.tasks import process_retention_side_effects
    from apps.files.models import ObjectDeleteJob

    event = _event(tmp_path)
    job = ObjectDeleteJob.objects.create(
        disposal_event=event,
        source_attachment_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        bucket="attachments",
        object_key="retention/retry.txt",
        version_id="version-2",
        next_attempt_at=timezone.now(),
    )
    monkeypatch.setattr(
        "apps.administration.tasks.delete_from_minio",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("secret details")),
    )
    before = timezone.now()

    result = process_retention_side_effects()

    job.refresh_from_db()
    event.refresh_from_db()
    assert result == {"completed": 0, "failed": 1, "published": 0}
    assert job.completed_at is None
    assert job.attempts == 1
    assert job.next_attempt_at >= before + timedelta(seconds=1)
    assert job.last_error_code == "RuntimeError"
    assert event.object_cleanup_completed_at is None
    assert event.certificate_exported_at is None
    assert not (tmp_path / "certificate.json").exists()


@pytest.mark.django_db(transaction=True)
def test_cleanup_worker_treats_missing_exact_version_as_idempotent_success(
    monkeypatch, tmp_path
):
    from apps.administration.tasks import process_retention_side_effects
    from apps.files.models import ObjectDeleteJob

    event = _event(tmp_path)
    job = ObjectDeleteJob.objects.create(
        disposal_event=event,
        source_attachment_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        bucket="attachments",
        object_key="retention/already-gone.txt",
        version_id="version-3",
        next_attempt_at=timezone.now(),
    )
    error = ClientError(
        {"Error": {"Code": "NoSuchVersion", "Message": "missing"}},
        "DeleteObject",
    )
    monkeypatch.setattr(
        "apps.administration.tasks.delete_from_minio",
        lambda **_kwargs: (_ for _ in ()).throw(error),
    )

    process_retention_side_effects()

    job.refresh_from_db()
    assert job.completed_at is not None
