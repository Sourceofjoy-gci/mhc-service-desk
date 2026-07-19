"""Settings package.

The active settings module is selected via ``DJANGO_SETTINGS_MODULE``:

* ``config.settings.dev``     — local development with auto-reload, dev auth bypass
* ``config.settings.staging`` — staging-like profile: DEBUG=False, real auth, fake secrets
* ``config.settings.prod``    — production: HTTPS, hardened cookies, strict checks

Each profile imports from ``base`` and overrides what it needs.
"""
default_app_config = "config.apps.ConfigConfig"
