from apps.reporting.models import Dashboard


def test_dashboard_string_uses_human_readable_title():
    dashboard = Dashboard(
        code="operational-overview",
        title="Operational overview",
        domain="operational",
    )

    assert str(dashboard) == "Operational overview"
