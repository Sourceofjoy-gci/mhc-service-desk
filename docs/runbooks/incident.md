# Incident Response Runbook (P0)

## Severity ladder

| Sev | Definition | Initial response | Cadence |
|---|---|---|---|
| SEV-1 | Production fully down or data loss | Page on-call + 15 min sync | Every 30 min |
| SEV-2 | Major degradation, multi-user | Page on-call + 1 h sync | Every 2 h |
| SEV-3 | Single feature or user | Ticket only | Daily |
| SEV-4 | Cosmetic / minor | Backlog | Weekly |

## First 15 minutes

1. Confirm scope: `curl http://api/api/v1/health` and inspect each dependency
2. Open an incident ticket: `IT-INC-…` (use the platform if reachable)
3. Capture: timestamp, affected service, symptom, blast radius, recent changes
4. Roll back the most recent change if it correlates

## Communication

- Internal status: post in the on-call channel
- External status page (P2): update before messaging requesters
- Major incidents: notify the Service Owner per the PRD §17.4 escalation rule

## After action

Within 5 business days, write a blameless post-mortem covering: timeline,
root cause, contributing factors, customer impact, what worked, what to fix.
Track fixes in the backlog with owners and due dates.

## Break-glass

For restricted content during an incident, follow the procedure in PRD §23.3:
request, approval, time-bound access, session banner, full audit, automatic
expiry, post-incident review.
