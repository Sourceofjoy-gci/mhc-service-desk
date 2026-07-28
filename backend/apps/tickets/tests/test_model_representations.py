from uuid import UUID

from apps.administration.models import ConfigItem
from apps.audit.models import AuditEvent
from apps.automation.models import AutomationExecution, AutomationRule
from apps.catalogue.models import CustomFieldDefinition, RequestType
from apps.contacts.models import ContactMethod, VerificationToken
from apps.csat.models import CsatResponse
from apps.email_channel.models import EmailDelivery, Mailbox
from apps.files.models import Attachment, AttachmentAccessLog
from apps.integrations.models import IntegrationEvent
from apps.knowledge.models import KnowledgeArticle, KnowledgeUsageLog
from apps.notifications.models import Notification
from apps.sla.models import BusinessCalendar, SlaInstance, SlaPauseHistory, SlaPolicy
from apps.tickets.models import OutboxEvent, TicketLink, TicketMessage, TicketNote, Watcher
from apps.whatsapp.models import WhatsappAccount, WhatsappMessage
from apps.workflow.models import Transition, TransitionHistory

ATTACHMENT_ID = UUID("10000000-0000-0000-0000-000000000001")
ACCESS_LOG_ID = UUID("10000000-0000-0000-0000-000000000002")
CALENDAR_ID = UUID("20000000-0000-0000-0000-000000000001")
POLICY_ID = UUID("20000000-0000-0000-0000-000000000002")
INSTANCE_ID = UUID("20000000-0000-0000-0000-000000000003")
PAUSE_ID = UUID("20000000-0000-0000-0000-000000000004")
TICKET_ID = UUID("30000000-0000-0000-0000-000000000001")
RELATED_TICKET_ID = UUID("30000000-0000-0000-0000-000000000002")
MESSAGE_ID = UUID("30000000-0000-0000-0000-000000000003")
NOTE_ID = UUID("30000000-0000-0000-0000-000000000004")
LINK_ID = UUID("30000000-0000-0000-0000-000000000005")
WATCHER_ID = UUID("30000000-0000-0000-0000-000000000006")
USER_ID = UUID("30000000-0000-0000-0000-000000000007")
OUTBOX_ID = UUID("30000000-0000-0000-0000-000000000008")
CONFIG_ITEM_ID = UUID("40000000-0000-0000-0000-000000000001")
AUDIT_EVENT_ID = UUID("40000000-0000-0000-0000-000000000002")
AUTOMATION_RULE_ID = UUID("40000000-0000-0000-0000-000000000003")
AUTOMATION_EXECUTION_ID = UUID("40000000-0000-0000-0000-000000000004")
REQUEST_TYPE_ID = UUID("40000000-0000-0000-0000-000000000005")
CUSTOM_FIELD_ID = UUID("40000000-0000-0000-0000-000000000006")
CONTACT_METHOD_ID = UUID("40000000-0000-0000-0000-000000000007")
VERIFICATION_TOKEN_ID = UUID("40000000-0000-0000-0000-000000000008")
CSAT_RESPONSE_ID = UUID("40000000-0000-0000-0000-000000000009")
MAILBOX_ID = UUID("40000000-0000-0000-0000-000000000010")
EMAIL_DELIVERY_ID = UUID("40000000-0000-0000-0000-000000000011")
INTEGRATION_EVENT_ID = UUID("40000000-0000-0000-0000-000000000012")
KNOWLEDGE_ARTICLE_ID = UUID("40000000-0000-0000-0000-000000000013")
KNOWLEDGE_USAGE_ID = UUID("40000000-0000-0000-0000-000000000014")
NOTIFICATION_ID = UUID("40000000-0000-0000-0000-000000000015")
WHATSAPP_ACCOUNT_ID = UUID("40000000-0000-0000-0000-000000000016")
WHATSAPP_MESSAGE_ID = UUID("40000000-0000-0000-0000-000000000017")
TRANSITION_ID = UUID("40000000-0000-0000-0000-000000000018")
TRANSITION_HISTORY_ID = UUID("40000000-0000-0000-0000-000000000019")
SERVICE_ID = UUID("50000000-0000-0000-0000-000000000001")
REQUEST_TYPE_PARENT_ID = UUID("50000000-0000-0000-0000-000000000002")
CONTACT_ID = UUID("50000000-0000-0000-0000-000000000003")
TICKET_MESSAGE_ID = UUID("50000000-0000-0000-0000-000000000004")
STATUS_ID = UUID("50000000-0000-0000-0000-000000000005")
NEXT_STATUS_ID = UUID("50000000-0000-0000-0000-000000000006")


def test_file_model_representations_are_stable_and_do_not_expose_storage_details():
    attachment = Attachment(
        id=ATTACHMENT_ID,
        ticket_id=TICKET_ID,
        filename="private-filing.pdf",
        object_key="secret-storage-key",
    )
    access = AttachmentAccessLog(
        id=ACCESS_LOG_ID,
        attachment_id=ATTACHMENT_ID,
        actor_subject="secret-actor-token",
    )

    assert str(attachment) == f"attachment:{ATTACHMENT_ID}"
    assert str(access) == f"attachment-access:{ACCESS_LOG_ID}"
    assert "secret-storage-key" not in str(attachment)
    assert "secret-actor-token" not in str(access)


def test_sla_model_representations_use_operational_identifiers_not_private_details():
    calendar = BusinessCalendar(id=CALENDAR_ID, name="Court business hours")
    policy = SlaPolicy(
        id=POLICY_ID,
        name="Operational P2",
        domain="operational",
        priority="P2",
        calendar_id=CALENDAR_ID,
    )
    instance = SlaInstance(
        id=INSTANCE_ID,
        ticket_id=TICKET_ID,
        policy_id=POLICY_ID,
        kind="resolution",
        state=SlaInstance.State.ACTIVE,
        breach_reason="private escalation details",
    )
    pause = SlaPauseHistory(
        id=PAUSE_ID,
        instance_id=INSTANCE_ID,
        state=SlaInstance.State.PAUSED_INTERNAL,
        reason="private internal dependency",
        actor_subject="secret-actor-token",
    )

    assert str(calendar) == "Court business hours"
    assert str(policy) == "Operational P2 (operational/P2)"
    assert str(instance) == f"resolution:{TICKET_ID} (active)"
    assert str(pause) == f"sla-pause:{INSTANCE_ID} (paused_internal)"
    assert "private escalation details" not in str(instance)
    assert "private internal dependency" not in str(pause)
    assert "secret-actor-token" not in str(pause)


def test_ticket_support_representations_omit_bodies_payloads_and_actor_secrets():
    message = TicketMessage(
        id=MESSAGE_ID,
        ticket_id=TICKET_ID,
        direction=TicketMessage.Direction.INBOUND,
        body_text="private requester message",
    )
    note = TicketNote(
        id=NOTE_ID,
        ticket_id=TICKET_ID,
        author_subject="secret-actor-token",
        body="private internal note",
    )
    link = TicketLink(
        id=LINK_ID,
        from_ticket_id=TICKET_ID,
        to_ticket_id=RELATED_TICKET_ID,
        kind=TicketLink.Kind.RELATED,
    )
    watcher = Watcher(id=WATCHER_ID, ticket_id=TICKET_ID, user_id=USER_ID)
    outbox = OutboxEvent(
        id=OUTBOX_ID,
        aggregate="ticket",
        aggregate_id=str(TICKET_ID),
        event_type="ticket.updated",
        payload={"token": "secret-outbox-token", "body": "private event body"},
    )

    assert str(message) == f"inbound-message:{MESSAGE_ID} ticket:{TICKET_ID}"
    assert str(note) == f"note:{NOTE_ID} ticket:{TICKET_ID}"
    assert str(link) == f"{TICKET_ID} related {RELATED_TICKET_ID}"
    assert str(watcher) == f"watcher:{USER_ID} ticket:{TICKET_ID}"
    assert str(outbox) == f"ticket.updated:ticket/{TICKET_ID}"
    combined = " ".join(str(value) for value in (message, note, link, watcher, outbox))
    assert "private requester message" not in combined
    assert "private internal note" not in combined
    assert "secret-actor-token" not in combined
    assert "secret-outbox-token" not in combined
    assert "private event body" not in combined


def test_administration_and_audit_representations_expose_only_stable_ids():
    config_item = ConfigItem(
        id=CONFIG_ITEM_ID,
        key="private-config-key",
        value={"secret": "private-config-value"},
    )
    audit_event = AuditEvent(
        id=AUDIT_EVENT_ID,
        actor_subject="private-audit-actor",
        action="private.audit.action",
        object_type="private-object-type",
        object_id="private-object-id",
        payload={"secret": "private-audit-payload"},
        payload_hash="private-payload-hash",
    )

    assert str(config_item) == f"config-item:{CONFIG_ITEM_ID}"
    assert str(audit_event) == f"audit-event:{AUDIT_EVENT_ID}"
    combined = f"{config_item} {audit_event}"
    assert "private-config-key" not in combined
    assert "private-config-value" not in combined
    assert "private-audit-actor" not in combined
    assert "private-audit-payload" not in combined
    assert "private-payload-hash" not in combined


def test_automation_and_catalogue_representations_omit_configuration_details():
    rule = AutomationRule(
        id=AUTOMATION_RULE_ID,
        name="private-automation-name",
        description="private-automation-description",
        trigger=AutomationRule.Trigger.TICKET_CREATED,
        conditions={"secret": "private-automation-condition"},
        action=AutomationRule.Action.ADD_NOTE,
        action_params={"body": "private-automation-action"},
    )
    execution = AutomationExecution(
        id=AUTOMATION_EXECUTION_ID,
        rule_id=AUTOMATION_RULE_ID,
        aggregate="private-aggregate",
        aggregate_id="private-aggregate-id",
        success=False,
        detail="private-execution-detail",
    )
    request_type = RequestType(
        id=REQUEST_TYPE_ID,
        service_id=SERVICE_ID,
        code="private-request-code",
        name="private-request-name",
        description="private-request-description",
    )
    custom_field = CustomFieldDefinition(
        id=CUSTOM_FIELD_ID,
        request_type_id=REQUEST_TYPE_PARENT_ID,
        key="private-field-key",
        label="private-field-label",
        kind=CustomFieldDefinition.Kind.TEXT,
        choices=["private-field-choice"],
        help_text="private-field-help",
    )

    assert str(rule) == f"automation-rule:{AUTOMATION_RULE_ID}"
    assert str(execution) == f"automation-execution:{AUTOMATION_EXECUTION_ID}"
    assert str(request_type) == f"request-type:{REQUEST_TYPE_ID}"
    assert str(custom_field) == f"custom-field:{CUSTOM_FIELD_ID}"
    combined = " ".join(str(value) for value in (rule, execution, request_type, custom_field))
    for private_value in (
        "private-automation-name",
        "private-automation-description",
        "private-automation-condition",
        "private-automation-action",
        "private-execution-detail",
        "private-request-description",
        "private-field-choice",
        "private-field-help",
    ):
        assert private_value not in combined


def test_contact_and_csat_representations_omit_contact_and_survey_secrets():
    contact_method = ContactMethod(
        id=CONTACT_METHOD_ID,
        contact_id=CONTACT_ID,
        method="email",
        value="private-contact@example.test",
    )
    verification_token = VerificationToken(
        id=VERIFICATION_TOKEN_ID,
        contact_id=CONTACT_ID,
        token_hash="private-verification-token-hash",
        purpose="private-token-purpose",
    )
    csat_response = CsatResponse(
        id=CSAT_RESPONSE_ID,
        ticket_id=TICKET_ID,
        rating=1,
        comment="private-csat-comment",
        survey_token_hash="private-survey-token-hash",
    )

    assert str(contact_method) == f"contact-method:{CONTACT_METHOD_ID}"
    assert str(verification_token) == f"verification-token:{VERIFICATION_TOKEN_ID}"
    assert str(csat_response) == f"csat-response:{CSAT_RESPONSE_ID}"
    combined = f"{contact_method} {verification_token} {csat_response}"
    assert "private-contact@example.test" not in combined
    assert "private-verification-token-hash" not in combined
    assert "private-csat-comment" not in combined
    assert "private-survey-token-hash" not in combined


def test_channel_and_integration_representations_omit_message_and_provider_secrets():
    mailbox = Mailbox(
        id=MAILBOX_ID,
        address="private-mailbox@example.test",
        domain="operational",
        provider="private-provider",
        secret="private-mailbox-secret",
    )
    delivery = EmailDelivery(
        id=EMAIL_DELIVERY_ID,
        ticket_message_id=TICKET_MESSAGE_ID,
        to_address="private-recipient@example.test",
        from_address="private-sender@example.test",
        subject="private-email-subject",
        body_text="private-email-body",
        message_id="private-email-message-id",
        in_reply_to="private-email-reply-id",
        references="private-email-references",
        status=EmailDelivery.Status.FAILED,
        error="private-email-error",
    )
    integration = IntegrationEvent(
        id=INTEGRATION_EVENT_ID,
        provider="private-integration-provider",
        external_id="private-external-id",
        payload={"secret": "private-integration-payload"},
    )
    account = WhatsappAccount(
        id=WHATSAPP_ACCOUNT_ID,
        phone_number_id="private-phone-number-id",
        display_name="private-whatsapp-name",
        domain="operational",
        access_token="private-whatsapp-access-token",
    )
    message = WhatsappMessage(
        id=WHATSAPP_MESSAGE_ID,
        ticket_id=TICKET_ID,
        account_id=WHATSAPP_ACCOUNT_ID,
        from_number="private-whatsapp-from-number",
        to_number="private-whatsapp-to-number",
        direction=WhatsappMessage.Direction.INBOUND,
        body="private-whatsapp-body",
        external_message_id="private-whatsapp-message-id",
        delivery_status="private-whatsapp-delivery-status",
        raw_payload={"secret": "private-whatsapp-payload"},
    )

    assert str(mailbox) == f"mailbox:{MAILBOX_ID}"
    assert str(delivery) == f"email-delivery:{EMAIL_DELIVERY_ID}"
    assert str(integration) == f"integration-event:{INTEGRATION_EVENT_ID}"
    assert str(account) == f"whatsapp-account:{WHATSAPP_ACCOUNT_ID}"
    assert str(message) == f"whatsapp-message:{WHATSAPP_MESSAGE_ID}"
    combined = " ".join(str(value) for value in (mailbox, delivery, integration, account, message))
    for private_value in (
        "private-mailbox@example.test",
        "private-mailbox-secret",
        "private-recipient@example.test",
        "private-sender@example.test",
        "private-email-body",
        "private-email-error",
        "private-email-message-id",
        "private-integration-payload",
        "private-external-id",
        "private-phone-number-id",
        "private-whatsapp-access-token",
        "private-whatsapp-body",
        "private-whatsapp-from-number",
        "private-whatsapp-to-number",
        "private-whatsapp-payload",
    ):
        assert private_value not in combined


def test_knowledge_notification_and_workflow_representations_omit_private_details():
    article = KnowledgeArticle(
        id=KNOWLEDGE_ARTICLE_ID,
        code="private-article-code",
        title="private-article-title",
        body="private-article-body",
        audience=KnowledgeArticle.Audience.RESTRICTED,
        status=KnowledgeArticle.Status.DRAFT,
        domain="operational",
        owner_subject="private-knowledge-owner",
        approved_by_subject="private-knowledge-approver",
    )
    usage = KnowledgeUsageLog(
        id=KNOWLEDGE_USAGE_ID,
        article_id=KNOWLEDGE_ARTICLE_ID,
        ticket_id=TICKET_ID,
        actor_subject="private-knowledge-actor",
    )
    notification = Notification(
        id=NOTIFICATION_ID,
        channel="private-notification-channel",
        recipient="private-notification-recipient",
        template_key="private-notification-template",
        payload={"secret": "private-notification-payload"},
    )
    transition = Transition(
        id=TRANSITION_ID,
        domain="operational",
        from_status_id=STATUS_ID,
        to_status_id=NEXT_STATUS_ID,
        name="private-transition-name",
        required_role="private-required-role",
        required_fields=["private-required-field"],
    )
    history = TransitionHistory(
        id=TRANSITION_HISTORY_ID,
        ticket_id=TICKET_ID,
        from_status_id=STATUS_ID,
        to_status_id=NEXT_STATUS_ID,
        actor_subject="private-workflow-actor",
        reason="private-workflow-reason",
    )

    assert str(article) == f"knowledge-article:{KNOWLEDGE_ARTICLE_ID}"
    assert str(usage) == f"knowledge-usage:{KNOWLEDGE_USAGE_ID}"
    assert str(notification) == f"notification:{NOTIFICATION_ID}"
    assert str(transition) == f"transition:{TRANSITION_ID}"
    assert str(history) == f"transition-history:{TRANSITION_HISTORY_ID}"
    combined = " ".join(str(value) for value in (article, usage, notification, transition, history))
    for private_value in (
        "private-article-body",
        "private-knowledge-owner",
        "private-knowledge-approver",
        "private-knowledge-actor",
        "private-notification-recipient",
        "private-notification-payload",
        "private-required-field",
        "private-workflow-actor",
        "private-workflow-reason",
    ):
        assert private_value not in combined
