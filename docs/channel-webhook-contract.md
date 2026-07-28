# Channel webhook trust contract

The email and WhatsApp webhook routes are public network endpoints, but every
state-changing request is authenticated before its JSON body is parsed.

## Normalized email adapter

`POST /api/v1/integrations/email/events/` and
`POST /api/v1/integrations/email/bounce/` require these headers:

- `X-MHC-Webhook-Timestamp`: Unix time in seconds.
- `X-MHC-Webhook-Event-Id`: stable, unique identifier for the provider event.
- `X-MHC-Webhook-Signature`: `sha256=<lowercase hex digest>`.

Calculate the digest with HMAC-SHA256 using `EMAIL_WEBHOOK_SECRET`. The signed
bytes are the UTF-8 encoding of `<timestamp>.<event-id>.` followed immediately
by the exact HTTP request-body bytes. Do not re-serialize the JSON between
signing and sending it.

The normalized payload may set `sender_verified` to JSON `true` only after the
adapter has validated the envelope sender and the deployment's SPF/DKIM/DMARC
policy. Unverified messages can create a new ticket but cannot thread into an
existing requester ticket. Unknown or inactive destination mailboxes are
rejected.

Requests are rejected when the secret is not configured, the signature is
invalid, or the timestamp differs from server time by more than
`CHANNEL_WEBHOOK_MAX_AGE_SECONDS` (300 seconds by default). A successfully
claimed event ID cannot be replayed. Nonblank provider message IDs are also
claimed at the database boundary where applicable. Reply threading is limited
to the resolved mailbox domain and the same requester; a subject token or
message reference cannot cross either boundary.

## Meta WhatsApp

`POST /api/v1/integrations/whatsapp/webhook/` follows Meta's native
`X-Hub-Signature-256` contract: HMAC-SHA256 of the exact request-body bytes
using `WHATSAPP_APP_SECRET`, formatted as `sha256=<lowercase hex digest>`.
Inbound message timestamps must also be within the configured age window.

Meta's `GET` verification challenge requires `WHATSAPP_VERIFY_TOKEN`. The
signed payload's `metadata.phone_number_id` must match an active local
WhatsApp account before any ticket or message is created.

All entries, changes, messages, and delivery statuses in a signed Meta batch
are validated before the batch is processed. Each provider message ID is
claimed independently. Delivery-status updates are account-bound, ordered by
their signed timestamp, and emit matching audit and transactional-outbox
events. An unknown account/message combination returns `503` so Meta can retry
after an outbound provider ID has been linked.

## Outbound WhatsApp capability

Authenticated users send an approved template by posting `ticket_number`,
`template_name`, `language`, and string `parameters` to
`POST /api/v1/integrations/whatsapp/send/`. The service derives the recipient
and sending account from the authorized ticket. It rejects out-of-domain,
roleless, auditor, opted-out, unconsented, unconfigured-account, and
unapproved-template requests before calling Meta.

Each `WhatsappAccount` stores its own Meta business/WABA ID. Template discovery
always uses that account's WABA ID and access token; no global business ID is
used across Operational and IT domains.

An authorized outbound message, delivery attempt, audit record, and outbox
event are committed with `pending` delivery state before the provider request
is made. The provider result then advances both message records and emits a
delivery-update event. This preserves a durable retry/reconciliation record if
the provider is unavailable or final persistence fails.

## Known pilot-readiness blocker

Outbound dispatch is still synchronous after the pending transaction commits.
There is not yet a leased, idempotent dispatch command and retry worker. A
process crash in that narrow window leaves a truthful pending record for
manual reconciliation, but automatic recovery and API-retry deduplication must
be implemented before production activation.

Never place webhook secrets, access tokens, complete webhook payloads, or
requester message bodies in application logs.
