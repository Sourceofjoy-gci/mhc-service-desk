from __future__ import annotations

import pytest

from apps.identity_access.models import User
from apps.organisations.models import Office
from scripts import seed_dev


@pytest.mark.django_db
def test_seed_dev_creates_every_supported_intake_office():
    expected = {
        ("MHC-MBA", "Master's Office — Mbabane (Main)", "Hhohho"),
        ("MHC-MAN", "Master's Office — Manzini", "Manzini"),
        ("MHC-LOB", "Master's Office — Lobamba", "Hhohho"),
        ("MHC-HLA", "Master's Office — Hlathikhulu", "Shiselweni"),
        ("MHC-NHL", "Master's Office — Nhlangano", "Shiselweni"),
        ("MHC-SIT", "Master's Office — Siteki", "Lubombo"),
        ("MHC-SIP", "Master's Office — Siphofaneni", "Lubombo"),
        ("MHC-SIM", "Master's Office — Simunye", "Lubombo"),
        ("MHC-PIG", "Master's Office — Pigg's Peak", "Hhohho"),
    }

    seed_dev.main()

    assert (
        set(
            Office.objects.filter(code__in={code for code, _, _ in expected}).values_list(
                "code", "name", "region__code"
            )
        )
        == expected
    )


@pytest.mark.django_db
def test_local_admin_has_unusable_password_when_dev_password_is_absent(monkeypatch):
    monkeypatch.delenv("DEV_LOCAL_ADMIN_PASSWORD", raising=False)

    user = seed_dev.ensure_local_admin()

    assert user.username == "local-admin"
    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.has_usable_password() is False


@pytest.mark.django_db
def test_local_admin_uses_optional_configured_password_without_printing(monkeypatch, capsys):
    configured_password = "configured-only-for-this-test"
    monkeypatch.setenv("DEV_LOCAL_ADMIN_PASSWORD", configured_password)

    user = seed_dev.ensure_local_admin()

    captured = capsys.readouterr()
    assert user.check_password(configured_password)
    assert configured_password not in captured.out
    assert configured_password not in captured.err


@pytest.mark.django_db
def test_local_admin_seed_is_idempotent(monkeypatch):
    monkeypatch.delenv("DEV_LOCAL_ADMIN_PASSWORD", raising=False)
    first = seed_dev.ensure_local_admin()
    first_password = first.password

    monkeypatch.setenv("DEV_LOCAL_ADMIN_PASSWORD", "later-password")
    second = seed_dev.ensure_local_admin()

    assert second.pk == first.pk
    assert second.password == first_password
    assert User.objects.filter(username="local-admin").count() == 1


@pytest.mark.django_db
def test_pilot_approver_seed_binds_scoped_master_designation():
    seed_dev.main()

    user = User.objects.get(keycloak_subject="dev:pilot-ops")

    from apps.identity_access.models import UserRole

    assignment = UserRole.objects.filter(user=user, role__keycloak_role="master").get()
    assert assignment.office.code == "MHC-MBA"
    assert assignment.expires_at is None


@pytest.mark.django_db
def test_pilot_approver_seed_is_idempotent():
    seed_dev.main()
    seed_dev.ensure_pilot_approver()
    seed_dev.ensure_pilot_approver()

    from apps.identity_access.models import User, UserRole

    user = User.objects.get(keycloak_subject="dev:pilot-ops")
    assert UserRole.objects.filter(user=user).count() == 1
    assert User.objects.filter(keycloak_subject="dev:pilot-ops").count() == 1
