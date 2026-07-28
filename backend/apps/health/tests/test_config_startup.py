from __future__ import annotations

import importlib
import logging
from unittest.mock import patch

import pytest
from django.test import override_settings

from config.apps import ConfigConfig


def _config_app() -> ConfigConfig:
    return ConfigConfig("config", importlib.import_module("config"))


@override_settings(DEBUG=True, ENVIRONMENT="development")
def test_development_hook_failure_is_logged_without_blocking_startup(caplog):
    with (
        patch(
            "config.settings.dev._patch_dev_auth",
            side_effect=RuntimeError("dev auth hook failed"),
        ),
        caplog.at_level(logging.ERROR, logger="config.apps"),
    ):
        result = _config_app().ready()

    assert result is None
    records = [
        record
        for record in caplog.records
        if record.getMessage() == "Development auth hook setup failed"
    ]
    assert len(records) == 1
    assert records[0].exc_info is not None
    assert records[0].exc_info[0] is RuntimeError


@pytest.mark.parametrize(
    ("debug", "environment"),
    [(False, "development"), (True, "production")],
)
def test_auth_hook_is_not_installed_outside_debug_development(debug, environment):
    with (
        override_settings(DEBUG=debug, ENVIRONMENT=environment),
        patch("config.settings.dev._patch_dev_auth") as patch_dev_auth,
    ):
        _config_app().ready()

    patch_dev_auth.assert_not_called()
