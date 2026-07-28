from __future__ import annotations

import pytest

from apps.identity_access.models import User
from scripts import seed_dev


@pytest.mark.django_db
def test_local_admin_has_unusable_password_when_dev_password_is_absent(monkeypatch):
    monkeypatch.delenv("DEV_LOCAL_ADMIN_PASSWORD", raising=False)

    user = seed_dev.ensure_local_admin()

    assert user.username == "local-admin"
    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.has_usable_password() is False


@pytest.mark.django_db
def test_local_admin_uses_optional_configured_password_without_printing(
    monkeypatch, capsys
):
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
