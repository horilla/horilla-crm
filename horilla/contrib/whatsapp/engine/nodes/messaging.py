"""
Node handlers for plain messaging: message, question, buttons, list,
send_template, end.
"""

from .. import senders
from ..base import NodeHandler, NodeResult
from ..interpolation import interpolate
from ..registry import register_node


@register_node("message")
class MessageNode(NodeHandler):
    """Sends a plain text message, then advances immediately (no pause)."""

    def execute(self, session, node):
        body = interpolate(node.config.get("body", ""), session)
        senders.send_text(session, body)
        return NodeResult(status="advance")


@register_node("question")
class QuestionNode(NodeHandler):
    """
    Asks a free-text question, pausing until the next inbound message; the
    reply is stored under config["variable_name"].
    """

    def execute(self, session, node):
        body = interpolate(node.config.get("prompt", ""), session)
        senders.send_text(session, body)
        return NodeResult(status="wait")

    def resume(self, session, node, reply_text, reply_id, flow_answers=None):
        variable_name = node.config.get("variable_name")
        variables = {variable_name: reply_text} if variable_name else None
        return NodeResult(status="advance", variables=variables)


@register_node("buttons")
class ButtonsNode(NodeHandler):
    """
    Sends up to 3 reply buttons, pausing until the user taps one. The
    selected option id becomes the outgoing edge's source_handle.
    """

    def execute(self, session, node):
        body = interpolate(node.config.get("body", ""), session)
        options = node.config.get("options", [])
        senders.send_buttons(session, body, options)
        return NodeResult(status="wait")

    def resume(self, session, node, reply_text, reply_id, flow_answers=None):
        options = node.config.get("options", [])
        option_ids = {opt["id"] for opt in options}
        selected = reply_id if reply_id in option_ids else None

        if not selected:
            # Not a recognized button tap (e.g. free text) - re-prompt.
            body = interpolate(node.config.get("body", ""), session)
            senders.send_buttons(session, body, options)
            return NodeResult(status="wait")

        variable_name = node.config.get("variable_name")
        variables = (
            {variable_name: selected} if variable_name else {"_last_reply_id": selected}
        )
        variables = variables or {}
        variables["_last_reply_id"] = selected
        return NodeResult(status="advance", source_handle=selected, variables=variables)


@register_node("list")
class ListNode(NodeHandler):
    """
    Sends a list message (up to 10 rows), pausing until the user selects a
    row. The selected row id becomes the outgoing edge's source_handle.
    """

    def execute(self, session, node):
        body = interpolate(node.config.get("body", ""), session)
        options = node.config.get("options", [])
        button_text = node.config.get("button_text", "Choose an option")
        senders.send_list(session, body, options, button_text)
        return NodeResult(status="wait")

    def resume(self, session, node, reply_text, reply_id, flow_answers=None):
        options = node.config.get("options", [])
        option_ids = {opt["id"] for opt in options}
        selected = reply_id if reply_id in option_ids else None

        if not selected:
            body = interpolate(node.config.get("body", ""), session)
            button_text = node.config.get("button_text", "Choose an option")
            senders.send_list(session, body, options, button_text)
            return NodeResult(status="wait")

        variable_name = node.config.get("variable_name")
        variables = {variable_name: selected} if variable_name else {}
        variables["_last_reply_id"] = selected
        return NodeResult(status="advance", source_handle=selected, variables=variables)


@register_node("send_meta_flow")
class SendMetaFlowNode(NodeHandler):
    """
    Sends an existing static Meta WhatsApp Flow (a WhatsAppFlow reference)
    and pauses until the user completes it. The submitted answers are
    flattened into session variables as "<variable_prefix>.<field>" (or
    "meta_flow.<field>" if no prefix is configured), so later nodes can
    reference them via {{variables.<prefix>.<field>}}.
    """

    def execute(self, session, node):
        from ...models import WhatsAppFlow

        flow_id = node.config.get("flow_id")
        meta_flow = WhatsAppFlow.objects.filter(pk=flow_id, is_active=True).first()
        if not meta_flow:
            return NodeResult(
                status="failed", error=f"WhatsApp Flow {flow_id} not found."
            )
        senders.send_meta_flow(session, meta_flow)
        return NodeResult(status="wait")

    def resume(self, session, node, reply_text, reply_id, flow_answers=None):
        if flow_answers is None:
            # A plain text/button reply arrived instead of a Flow submission
            # (e.g. the user typed something instead of completing the
            # Flow) - re-send nothing, just keep waiting.
            return NodeResult(status="wait")

        prefix = node.config.get("variable_prefix", "meta_flow")
        variables = {f"{prefix}.{key}": value for key, value in flow_answers.items()}
        return NodeResult(status="advance", variables=variables)


@register_node("send_template")
class SendTemplateNode(NodeHandler):
    """Sends an approved WhatsAppTemplate by name, then advances immediately."""

    def execute(self, session, node):
        from ...models import WhatsAppTemplate

        template_id = node.config.get("template_id")
        template = WhatsAppTemplate.objects.filter(pk=template_id).first()
        if not template:
            return NodeResult(
                status="failed", error=f"Template {template_id} not found."
            )
        senders.send_template(session, template)
        return NodeResult(status="advance")


@register_node("end")
class EndNode(NodeHandler):
    """Terminates the flow successfully."""

    def execute(self, session, node):
        return NodeResult(status="completed")
