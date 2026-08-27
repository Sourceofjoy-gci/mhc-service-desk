"""Runtime contracts for audit background tasks."""

from __future__ import annotations

from apps.audit.tasks import rotate_export_artefacts


def test_rotate_export_task_keeps_stable_registration_and_result() -> None:
    assert rotate_export_artefacts.name == "apps.audit.tasks.rotate_export_artefacts"
    assert rotate_export_artefacts.run() == 0
