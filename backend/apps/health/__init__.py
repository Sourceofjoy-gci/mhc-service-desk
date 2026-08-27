"""Liveness and readiness probe for the MHC e-Ticketing platform.

The endpoint at ``/api/v1/health`` is the single source of truth for the
deployment target. Each dependency check has its own short timeout so a
slow component never blocks the response.
"""

default_app_config = "apps.health.apps.HealthConfig"
