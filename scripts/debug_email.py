"""Quick debug: run process_inbound_email and inspect the result."""
import sys, django, os
sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.email_channel.models import Mailbox
from apps.email_channel.services import process_inbound_email
from apps.tickets.models import TicketMessage

m = Mailbox.objects.create(address="ops@mhc.local", domain="operational", is_active=True)
r = process_inbound_email(
    from_header="Visitor <visitor@example.com>",
    to_header="ops@mhc.local",
    subject="XSS test",
    body_text="Click here",
    body_html='<p>Hi</p><script>alert(1)</script><a href="javascript:doBad()">link</a>',
    message_id="<xss-debug@example.com>",
)
print("result:", r)
msgs = TicketMessage.objects.filter(external_message_id="<xss-debug@example.com>")
for msg in msgs:
    print("msg.body_html_sanitized:", repr(msg.body_html_sanitized))
