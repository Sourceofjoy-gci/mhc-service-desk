"""Email channel — inbound and outbound.

Inbound: a webhook (Microsoft Graph, Mailgun, SendGrid inbound, etc.) posts
the parsed message to `/api/v1/integrations/email/events/`. We:

  1. Validate the source (signature — adapter-specific, stubbed here)
  2. Normalise contact data
  3. Apply idempotency via the provider's `Message-ID`
  4. Match an existing conversation via `In-Reply-To` / `References`
  5. Update the correct ticket or create a new one
  6. Add the message to the ticket timeline

Outbound: ticket replies can be queued via the email dispatcher. The
delivered message and its `Message-ID` are recorded on the TicketMessage.
"""

default_app_config = "apps.email_channel.apps.EmailChannelConfig"
