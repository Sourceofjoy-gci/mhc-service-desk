"""Runtime contracts for SLA background tasks."""

from __future__ import annotations

from unittest.mock import patch

from apps.sla.tasks import evaluate_open_slas_task


def test_evaluate_slas_task_keeps_stable_registration_and_delegation() -> None:
    with patch("apps.sla.tasks.evaluate_open_slas", return_value=7) as evaluate:
        result = evaluate_open_slas_task.run()

    assert evaluate_open_slas_task.name == "apps.sla.tasks.evaluate_open_slas"
    assert result == 7
    evaluate.assert_called_once_with()
