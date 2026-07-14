"""
Core Bot Rule engine: the node handler contract and the execution loop that
drives a WhatsAppBotRuleSession from node to node.
"""

# Standard library imports
import logging
from dataclasses import dataclass, field
from typing import Optional

# Third-party imports (Django)
from django.utils import timezone

# Local imports
from .registry import get_handler

logger = logging.getLogger(__name__)

MAX_NODE_VISITS_PER_CALL = 50


@dataclass
class NodeResult:
    """
    What a node handler reports back to the engine after executing.

    status:
      "advance"   - move to the outgoing edge matching `source_handle`
      "wait"      - pause here; the handler already sent a message (or
                    scheduled a resume) and the engine should stop looping
      "completed" - flow finished successfully
      "failed"    - flow could not continue; `error` explains why
    """

    status: str
    source_handle: str = ""
    variables: Optional[dict] = None
    error: Optional[str] = None
    content_type_id: Optional[int] = None
    object_id: Optional[int] = None


class NodeHandler:
    """
    Base class for a node type's runtime behaviour. Subclasses register
    themselves via `@register_node("some_type")` and implement `execute`;
    node types that pause for user input (question/buttons/list/wait) also
    override `resume`.
    """

    def execute(self, session, node):
        """Run this node for the first time. Must return a NodeResult."""
        raise NotImplementedError

    def resume(self, session, node, reply_text, reply_id, flow_answers=None):
        """
        Run this node after the flow paused here and a new inbound message
        arrived. `reply_text` is the raw message body; `reply_id` is the
        selected button/list-row id, if any; `flow_answers` is the parsed
        answers dict from a completed Meta WhatsApp Flow submission
        (nfm_reply), if that's what triggered the resume. Defaults to
        re-running `execute` for node types that never pause.
        """
        return self.execute(session, node)


class FlowEngine:
    """Drives a single WhatsAppBotRuleSession through its flow graph."""

    def __init__(self, session):
        self.session = session

    @classmethod
    def start(cls, flow, conversation):
        """Start a brand-new session for `flow` against `conversation`."""
        from ..models import WhatsAppBotRuleSession

        start_node = flow.get_start_node()
        if not start_node:
            logger.error("Bot flow %s has no start node; cannot start.", flow.pk)
            return None

        session, _created = WhatsAppBotRuleSession.get_or_create_for(
            flow, conversation, current_node_key=start_node.node_key
        )
        engine = cls(session)
        engine._run(first_call=True)
        return session

    def resume(self, reply_text, reply_id=None, flow_answers=None):
        """Resume a session that's paused (status=waiting_input) on an inbound message."""
        session = self.session
        if session.status != "waiting_input" or not session.current_node_key:
            logger.warning(
                "Cannot resume bot flow session %s: status=%s current_node_key=%s",
                session.pk,
                session.status,
                session.current_node_key,
            )
            return

        node = session.flow.nodes.filter(node_key=session.current_node_key).first()
        if not node:
            self._fail(f"Node '{session.current_node_key}' no longer exists.")
            return

        handler = get_handler(node.node_type)
        if not handler:
            self._fail(f"No handler registered for node type '{node.node_type}'.")
            return

        session.status = "running"
        result = handler().resume(session, node, reply_text, reply_id, flow_answers)
        self._apply_result(node, result)
        if session.status == "running":
            self._run(first_call=False)

    def _run(self, first_call):
        """Main loop: execute nodes until the session pauses, completes, or fails."""
        session = self.session
        visits = 0

        if first_call:
            session.status = "running"

        while session.status == "running":
            visits += 1
            if visits > MAX_NODE_VISITS_PER_CALL:
                self._fail(
                    "Exceeded maximum node visits for a single call (possible cycle)."
                )
                return

            node = session.flow.nodes.filter(node_key=session.current_node_key).first()
            if not node:
                self._fail(f"Node '{session.current_node_key}' not found.")
                return

            handler = get_handler(node.node_type)
            if not handler:
                self._fail(f"No handler registered for node type '{node.node_type}'.")
                return

            try:
                result = handler().execute(session, node)
            except (
                Exception
            ) as exc:  # noqa: BLE001 - node failures must not crash the webhook
                logger.exception(
                    "Bot flow node '%s' raised an exception.", node.node_key
                )
                self._fail(str(exc))
                return

            self._apply_result(node, result)

    def _apply_result(self, node, result):
        """Merge a NodeResult into the session and advance/pause/complete/fail it."""
        session = self.session

        if result.variables:
            session.variables.update(result.variables)
        if result.content_type_id is not None or result.object_id is not None:
            if result.content_type_id is not None:
                session.content_type_id = result.content_type_id
            if result.object_id is not None:
                session.object_id = result.object_id
            # GenericForeignKey caches a None lookup result and won't
            # re-resolve just because content_type_id/object_id changed on
            # the same in-memory instance - drop the cache so session.related_to
            # (used by later nodes in this same _run loop, e.g. interpolation's
            # {{record.*}}) reflects the record we just linked.
            session._state.fields_cache.pop("related_to", None)

        if result.status == "wait":
            session.status = "waiting_input"
            session.current_node_key = node.node_key
            session.save()
            return

        if result.status == "failed":
            self._fail(result.error or "Node execution failed.")
            return

        if result.status == "completed":
            session.status = "completed"
            session.current_node_key = None
            session.completed_at = timezone.now()
            session.save()
            return

        # status == "advance"
        edge = node.get_outgoing_edge(result.source_handle)
        if not edge:
            self._fail(
                f"No outgoing edge for node '{node.node_key}' "
                f"branch '{result.source_handle}'."
            )
            return
        session.current_node_key = edge.target_node.node_key
        session.save()

    def _fail(self, message):
        """Mark the session failed and persist the error."""
        session = self.session
        session.status = "failed"
        session.error_message = message
        session.completed_at = timezone.now()
        session.save()
        logger.error("Bot flow session %s failed: %s", session.pk, message)
