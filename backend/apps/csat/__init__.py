"""Customer satisfaction (CSAT) survey data model and endpoints (FR-070).

After eligible closure, a single CSAT invitation is queued. The requester
fills it via the magic link or a one-time survey URL.
"""
default_app_config = "apps.csat.apps.CsatConfig"
