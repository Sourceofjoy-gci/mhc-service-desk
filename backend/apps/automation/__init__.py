"""Automation rules (FR-091).

A rule is a small data record: trigger, condition, action, priority.
The engine executes them in order; arbitrary code execution is forbidden
(PRD §30).
"""

default_app_config = "apps.automation.apps.AutomationConfig"
