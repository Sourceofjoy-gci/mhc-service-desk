"""Canonical internal staff designations and their inherited authority."""

from __future__ import annotations

from dataclasses import dataclass

_OPERATIONAL_AGENT_AUTHORITY = frozenset(
    {"agent-operational", "ops-agents"}
)
_OPERATIONAL_SUPERVISOR_AUTHORITY = frozenset(
    {
        *_OPERATIONAL_AGENT_AUTHORITY,
        "supervisor-operational",
        "ops-supervisors",
    }
)


@dataclass(frozen=True)
class StaffDesignation:
    role_key: str
    display_name: str
    team_label: str
    description: str = ""
    authority_aliases: frozenset[str] = frozenset()


STAFF_DESIGNATIONS: tuple[StaffDesignation, ...] = (
    StaffDesignation(
        "master",
        "Master",
        "Office Leadership",
        "Make final decisions on designated approvals and policy exceptions. "
        "Authority: Full approval authority.",
        _OPERATIONAL_SUPERVISOR_AUTHORITY
        | {"assistant-master", "deputy-master", "master"},
    ),
    StaffDesignation(
        "deputy-master",
        "Deputy Master",
        "Office Leadership",
        "Perform higher-level review; handle exceptions; make escalation "
        "decisions. Authority: Senior approval and oversight.",
        _OPERATIONAL_SUPERVISOR_AUTHORITY
        | {"assistant-master", "deputy-master", "master"},
    ),
    StaffDesignation(
        "assistant-master",
        "Assistant Master",
        "Office Leadership",
        "Supervise reviews; validate recommendations; authorise workflow "
        "progress. Authority: Approve within delegated authority.",
        _OPERATIONAL_SUPERVISOR_AUTHORITY | {"assistant-master"},
    ),
    StaffDesignation("assistant-accountant", "Assistant Accountant", "Finance"),
    StaffDesignation("accountant", "Accountant", "Finance"),
    StaffDesignation("senior-accountant", "Senior Accountant", "Finance"),
    StaffDesignation("principal-accountant", "Principal Accountant", "Finance"),
    StaffDesignation("financial-controller", "Financial Controller", "Finance"),
    # Compatibility titles retained for existing identities and audit history.
    StaffDesignation(
        "estate-examiner",
        "Estate Examiner",
        "Estate Administration",
        authority_aliases=_OPERATIONAL_AGENT_AUTHORITY | {"examiner"},
    ),
    StaffDesignation(
        "examiner",
        "Examiner",
        "Estate Administration",
        "Review estate submissions; verify documents; raise defects; assess "
        "compliance. Authority: Review and recommend.",
        _OPERATIONAL_AGENT_AUTHORITY | {"examiner"},
    ),
    StaffDesignation(
        "records-clerk",
        "Records Clerk",
        "Records and Data",
        authority_aliases=_OPERATIONAL_AGENT_AUTHORITY | {"records-officer"},
    ),
    StaffDesignation(
        "records-officer",
        "Records Officer",
        "Records and Data",
        "Register new estate matters; capture metadata; receive and index "
        "documents; maintain file completeness. Authority: Create and update "
        "case intake records.",
        _OPERATIONAL_AGENT_AUTHORITY | {"records-officer"},
    ),
    StaffDesignation("data-clerk", "Data Clerk", "Records and Data"),
)

STAFF_DESIGNATION_BY_KEY = {
    designation.role_key: designation for designation in STAFF_DESIGNATIONS
}
STAFF_DESIGNATION_ROLE_KEYS = frozenset(STAFF_DESIGNATION_BY_KEY)
