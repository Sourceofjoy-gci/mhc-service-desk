# Agent guide - pilot workspace

This guide describes the implemented staff workflow. Your identity and the
server decide which domains, tickets, fields, and actions are available. A
hidden control is not a workaround request: ask a supervisor when your role
does not provide the action you need.

## 1. Sign in and choose a queue

1. Sign in through the staff login page.
2. Open **Tickets**.
3. Choose an admitted domain if your role has more than one.
4. Narrow the queue by status, priority, search text, and sort order.
5. Use **Next** and **Previous** to follow the server's opaque cursor links.

The URL stores the current filters. Changing a filter or sort clears the old
cursor so you do not land on the wrong page. Keep or share the filtered URL
only with authorized colleagues; it does not grant access by itself.

Security responders see restricted queues in both domains but do not receive
ordinary tickets unless another assigned group grants that domain. Auditors
can read both domains but cannot change tickets.

## 2. Open the ticket workspace

Open a ticket card from the queue. The workspace retains the queue path, so
**Back to queue** returns to the filters you were using. An invalid or unsafe
return path falls back to `/tickets`.

Read the workspace from top to bottom:

1. Ticket number, title, requester, classification, priority, channel, status,
   age, and description.
2. Server-approved lifecycle actions.
3. Activity and the reply/internal-note composer.
4. Operations, SLA clocks, relationships, attachments, requester details, and
   classification context.

On a small screen, lifecycle and activity stay before secondary operations so
the current work remains the first focus.

## 3. Triage, assign, and plan the next action

Use **Operations** only when the server exposes the capability:

- **Assign to me** appears for an eligible unassigned ticket.
- Reassignment and confidentiality controls are limited to supervisors, IT
  leads, and system administrators with matching ticket authority.
- Team, waiting reason, blocked reason, next action, and next-action date are
  saved only when changed.

The assignee list is filtered for the ticket's domain and excludes inactive
users and auditors. If the list cannot be loaded, reassignment is unavailable;
do not treat a blank choice as an unassigned result.

Use a concrete next action and date. A waiting or blocked state without useful
follow-up information makes handover and SLA management harder.

## 4. Move the lifecycle

Only transitions returned by the server are shown. Select the required action
and supply any displayed fields:

- A transition may require a reason.
- Resolving requires both a resolution code and summary.
- Reopening clears active resolution fields but keeps the previous resolution
  in the activity history.

While a transition is being sent, its controls remain disabled. The workspace
does not add an optimistic transition: it replaces the ticket only with the
refreshed server response.

## 5. Handle a stale-ticket conflict

Every work-state and transition request includes the ticket version you
opened. If another person changed the ticket first, the server returns
`409 stale_ticket` and does not apply your change.

1. Read the stale-ticket message.
2. Choose **Reload** in the affected panel.
3. Review the refreshed assignment, work state, status, activity, and available
   actions.
4. Re-enter or adjust your change only if it is still correct, then submit it
   again.

Do not repeatedly resubmit without reloading; that can overwrite your own
understanding of the current work even though the server blocks the stale
mutation.

## 6. Communicate and record internal work

The activity stream combines requester messages, internal notes, status
changes, work-state changes, relationships, and attachments in server order.

- Use **Reply** for requester-visible communication.
- Use **Internal note** for staff-only context.
- The two drafts are separate. A failed send keeps the draft so it can be
  corrected or retried.
- The activity stream refreshes after the server confirms a send; no temporary
  optimistic entry is inserted.

A requester must never receive an internal note. Avoid secrets and unnecessary
personal data in either channel.

## 7. Use attachments safely

The attachment panel loads the current file list independently from uploads.
Each file shows its name, size, type, uploader, date, and scan state.

| Scan state | Agent action |
|---|---|
| Scanning | Wait; download is unavailable |
| Ready/clean | Use **Download**; the server creates a short-lived signed URL only after the click |
| Quarantined/infected | Do not request or distribute the file; follow the security process |
| Scan failed | Escalate to support; do not treat the file as clean |

If an upload fails, the selected files stay listed for review and retry. A
successful upload clears the selection and refreshes both attachments and
activity. Never use an object-store URL copied from logs or another user.

## 8. Work across Operational and IT

Operational and IT content remain separately scoped. An out-of-domain ticket
normally appears as `404`, not as a confirmation that it exists. Domain
dashboards return `403` when your role lacks unrestricted authority.

The backend implements a sanitized IT-child operation and the activity stream
shows authorized relationships. The current workspace does not expose an
agent-facing create-IT-child control; use the approved escalation procedure or
authorized integration until that UI is delivered. Never copy unrestricted
Operational notes or attachments into an IT ticket manually.

## 9. Understand error states

| State | Meaning and next step |
|---|---|
| `401` Authentication required | Sign in again; protected content remains hidden |
| `403` Access denied | Your identity is known but lacks this action/domain; contact the appropriate lead if the assignment is wrong |
| `404` Not found/unavailable | Check the reference; the response may intentionally hide an out-of-scope ticket |
| `400` Validation error | Correct the named fields and retain the rest of your work |
| `409 stale_ticket` | Reload, review the newer ticket, and decide whether to resubmit |
| Unexpected failure | Retry only when safe and give support the displayed correlation reference |

Do not send bearer tokens, raw response bodies, or requester content in a
support message. The correlation reference is the safe diagnostic handle.

## Hard rules

- A requester never sees an internal note.
- Do not disclose content from another domain or a restricted ticket.
- A ticket is not a formal filing; tell the requester when that distinction
  matters.
- MFA and individual accounts are mandatory. Never share passwords or tokens.
- Audit/activity history is the source of truth for actions that the server
  accepted.
- A clean automated component test is not a substitute for current UAT or
  browser accessibility approval; follow the published readiness decision.
