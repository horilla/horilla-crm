"""
Registry for the Bot Rule engine's node type handlers.
"""

NODE_HANDLERS = {}


def register_node(node_type):
    """
    Class decorator: registers a NodeHandler subclass for `node_type`.

    Usage:
        @register_node("message")
        class MessageNode(NodeHandler):
            ...
    """

    def wrapper(handler_cls):
        if node_type in NODE_HANDLERS:
            raise ValueError(f"Node type '{node_type}' is already registered.")
        NODE_HANDLERS[node_type] = handler_cls
        return handler_cls

    return wrapper


def get_handler(node_type):
    """Return the NodeHandler class registered for `node_type`, or None."""
    return NODE_HANDLERS.get(node_type)
