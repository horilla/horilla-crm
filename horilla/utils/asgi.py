"""ASGI helpers for running Horilla under an ASGI server."""

# Standard library imports
import asyncio
import contextvars


class FreshContextMiddleware:
    """Run every ASGI call in its own empty ``contextvars.Context``.

    asyncio can leak context variables from one task into the next
    (https://github.com/python/cpython/issues/140947). uvicorn starts a
    keep-alive or pipelined request, and re-arms the socket reader, from
    inside the previous request's task, so the new request inherits the
    previous request's context.

    Django keeps the per-request ``ThreadSensitiveContext`` in a context
    variable. A request that inherits one does not open its own, so its sync
    code is queued on the previous request's thread. When the previous request
    ends, ``ThreadSensitiveContext.__aexit__`` joins that thread on the event
    loop, while the inherited request, running in that thread, waits in
    ``async_to_sync`` for the same loop. The worker then hangs for good,
    ``/health/`` included.

    Starting each call (one HTTP request or one WebSocket connection) from an
    empty context gives every request its own ``ThreadSensitiveContext``,
    whichever ASGI server runs Horilla.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # Awaiting the task passes a cancellation of this call on to the app
        # and returns only once the app has finished handling it.
        return await asyncio.create_task(
            self.app(scope, receive, send), context=contextvars.Context()
        )
