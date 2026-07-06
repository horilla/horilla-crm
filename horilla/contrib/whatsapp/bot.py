"""
Horilla Bot: entry point dispatching inbound WhatsApp messages to the
configurable Bot Rule engine, plus conversation assignment shared by the
webhook.

Linking a conversation to a CRM (or other) record and auto-creating one
when no match exists are both modeled as ordinary Bot Rule nodes
(search_record, create_record - see engine/nodes/record_actions.py), not
hardcoded here, since the whatsapp app is generic and not CRM-specific.
Wire those nodes into a flow if you want that behavior.
"""

import re


def route_bot_message(account, conversation, bot_reply_value, flow_answers=None):
    """
    Dispatch one inbound message to the Bot Rule engine: resumes an
    in-progress session, or starts a matching one for a new conversation.

    `flow_answers` carries the parsed answers dict from a completed Meta
    WhatsApp Flow submission (nfm_reply), if that's what triggered this call,
    so a paused "send_meta_flow" Bot Rule node can pick them up.
    """
    if not account.bot_enabled:
        return

    from .engine.base import FlowEngine
    from .models import WhatsAppBotRuleSession

    active_session = (
        WhatsAppBotRuleSession.objects.filter(
            conversation=conversation, status="waiting_input"
        )
        .order_by("-created_at")
        .first()
    )
    if active_session:
        FlowEngine(active_session).resume(
            bot_reply_value, reply_id=bot_reply_value, flow_answers=flow_answers
        )
        return

    if flow_answers is not None:
        # A Flow submission isn't a greeting/keyword trigger; with no waiting
        # session to resume there is nothing for the bot to do.
        return

    rule = _match_rule(account, conversation, bot_reply_value)
    if rule and _is_in_cooldown(rule, conversation):
        return
    if rule:
        FlowEngine.start(rule, conversation)


def _is_in_cooldown(rule, conversation):
    """
    True if `rule` last finished (completed or failed) for `conversation`
    within its retrigger cooldown window - prevents an inbound message that
    still matches the same trigger from restarting the flow from scratch
    right after it just ran.
    """
    cooldown = rule.retrigger_cooldown_timedelta()
    if not cooldown:
        return False

    from django.utils import timezone

    from .models import WhatsAppBotRuleSession

    last_session = (
        WhatsAppBotRuleSession.objects.filter(
            flow=rule, conversation=conversation, completed_at__isnull=False
        )
        .order_by("-completed_at")
        .first()
    )
    if not last_session:
        return False

    return timezone.now() - last_session.completed_at < cooldown


def _match_rule(account, conversation, message_body):
    """
    Return the first active keyword-triggered rule matching the message, or
    account.default_bot_rule.

    Rules with content_type set are only considered for conversations linked
    to that same model (via GenericForeignKey content_type/object_id); rules
    with content_type=None are General and considered for every
    conversation, matching WhatsAppTemplate's General-vs-specific-model
    pattern. account.default_bot_rule is likewise only used when it's
    General or matches the conversation's model.
    """
    from django.db.models import Q

    from .models import WhatsAppBotRule

    model_filter = Q(content_type__isnull=True)
    if conversation.content_type_id:
        model_filter |= Q(content_type_id=conversation.content_type_id)

    text = (message_body or "").lower()
    if text:
        rules = WhatsAppBotRule.objects.filter(
            model_filter, account=account, is_active=True, trigger_type="keyword"
        )
        for rule in rules:
            keywords = [
                keyword.strip().lower()
                for keyword in (rule.trigger_keywords or "").split(",")
                if keyword.strip()
            ]
            if keywords and any(
                re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in keywords
            ):
                return rule

    default_rule = account.default_bot_rule
    if (
        default_rule
        and default_rule.is_active
        and (
            default_rule.content_type_id is None
            or default_rule.content_type_id == conversation.content_type_id
        )
    ):
        return default_rule

    inbound_rule = (
        WhatsAppBotRule.objects.filter(
            model_filter,
            account=account,
            is_active=True,
            trigger_type="inbound_message",
        )
        .order_by("-created_at")
        .first()
    )
    return inbound_rule


def assign_conversation(conversation):
    """
    Assign the conversation to a human agent for follow-up.

    v1 simplification: simple round-robin over users who can change WhatsApp
    conversations. Reusing horilla_crm's Lead assignment rules directly is a
    natural follow-up once this flow is validated end-to-end.
    """
    if conversation.assigned_to:
        return

    from django.contrib.auth import get_user_model

    User = get_user_model()
    candidates = User.objects.filter(
        company=conversation.company,
        groups__permissions__codename="change_whatsappconversation",
    ).distinct()
    agent = candidates.order_by("?").first()
    if agent:
        conversation.assigned_to = agent
        conversation.save(update_fields=["assigned_to"])
