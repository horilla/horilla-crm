"""
Unit tests for the Horilla utilities module.

This file contains test cases for validating the functionality of the
utilities provided in the Horilla application.
"""

# Standard library imports
import asyncio
import contextvars
import gc
import itertools
import json
import subprocess
import sys
import threading
import time
import warnings

# Third party imports
from asgiref.sync import SyncToAsync, ThreadSensitiveContext

# Third-party imports (Django)
from django.conf import settings
from django.http import JsonResponse
from django.test import SimpleTestCase
from django.urls import path

# First party imports (Horilla)
from horilla.contrib.utils.middlewares import get_current_request
from horilla.utils.asgi import FreshContextMiddleware

_leaky_var = contextvars.ContextVar("leaky_var")

THREAD_LOCAL_MIDDLEWARE = "horilla.contrib.utils.middlewares.ThreadLocalMiddleware"


def _http_scope(request_path="/"):
    """Return a minimal ASGI HTTP scope for ``request_path``."""
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": request_path,
        "raw_path": request_path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }


class FreshContextMiddlewareTests(SimpleTestCase):
    """Each ASGI call must start from an empty context and otherwise be transparent."""

    def call(self, app, setup=None, scope=None):
        """Await ``app`` once, from a context prepared by ``setup``, and return its result."""

        async def main():
            if setup:
                setup()
            return await app(scope or _http_scope(), None, None)

        return asyncio.run(main())

    def test_context_vars_of_the_caller_are_not_visible(self):
        """A context variable the server's task holds does not reach the app."""
        seen = {}

        async def app(scope, receive, send):
            seen["value"] = _leaky_var.get("unset")

        self.call(FreshContextMiddleware(app), setup=lambda: _leaky_var.set("previous"))
        self.assertEqual(seen["value"], "unset")

    def test_context_changes_of_the_app_do_not_reach_the_caller(self):
        """What the app sets stays inside it, so the server's task stays clean."""

        async def app(scope, receive, send):
            _leaky_var.set("set by the app")

        async def main(wrapped):
            await (FreshContextMiddleware(app) if wrapped else app)(
                _http_scope(), None, None
            )
            return _leaky_var.get("unset")

        self.assertEqual(asyncio.run(main(wrapped=True)), "unset")
        # Guard: a plain await shares the caller's context, which is the leak.
        self.assertEqual(asyncio.run(main(wrapped=False)), "set by the app")

    def test_a_call_started_inside_another_call_gets_its_own_context(self):
        """uvicorn starts the next request from inside the previous one's task."""
        seen = {}

        async def second(scope, receive, send):
            seen["second"] = _leaky_var.get("unset")

        async def first(scope, receive, send):
            _leaky_var.set("first request")
            await FreshContextMiddleware(second)(scope, receive, send)
            seen["first"] = _leaky_var.get("unset")

        self.call(FreshContextMiddleware(first))
        self.assertEqual(seen, {"second": "unset", "first": "first request"})

    def test_leaked_thread_sensitive_context_is_not_reused(self):
        """A request opens its own ThreadSensitiveContext, not the leaked one.

        Reusing the previous request's context queues this request on that
        request's sync thread, which is what deadlocks the worker.
        """
        seen = {}
        leaked = ThreadSensitiveContext()

        async def app(scope, receive, send):
            seen["on_entry"] = SyncToAsync.thread_sensitive_context.get(None)
            async with ThreadSensitiveContext() as own:
                seen["inside"] = SyncToAsync.thread_sensitive_context.get()
                seen["own"] = own

        self.call(
            FreshContextMiddleware(app),
            setup=lambda: SyncToAsync.thread_sensitive_context.set(leaked),
        )
        self.assertIsNone(seen["on_entry"])
        self.assertIsNot(seen["inside"], leaked)
        self.assertIs(seen["inside"], seen["own"])

    def test_without_the_middleware_the_thread_sensitive_context_leaks(self):
        """Guard for the test above: without the wrapper the leaked one is reused."""
        seen = {}
        leaked = ThreadSensitiveContext()

        async def app(scope, receive, send):
            async with ThreadSensitiveContext():
                seen["inside"] = SyncToAsync.thread_sensitive_context.get()

        self.call(app, setup=lambda: SyncToAsync.thread_sensitive_context.set(leaked))
        self.assertIs(seen["inside"], leaked)

    def test_scope_receive_and_send_are_passed_through_unchanged(self):
        """The wrapper hands the app the very same scope, receive and send."""
        seen = {}
        scope = _http_scope("/given/")

        async def receive():
            return {"type": "http.request"}

        async def send(message):
            return None

        async def app(app_scope, app_receive, app_send):
            seen.update(scope=app_scope, receive=app_receive, send=app_send)

        async def main():
            await FreshContextMiddleware(app)(scope, receive, send)

        asyncio.run(main())
        self.assertIs(seen["scope"], scope)
        self.assertIs(seen["receive"], receive)
        self.assertIs(seen["send"], send)

    def seen_by_app(self, scope_type):
        """Return the scope type and leaked variable a wrapped app sees."""
        seen = {}

        async def app(scope, receive, send):
            seen["type"] = scope["type"]
            seen["value"] = _leaky_var.get("unset")

        self.call(
            FreshContextMiddleware(app),
            setup=lambda: _leaky_var.set("previous"),
            scope={"type": scope_type},
        )
        return seen

    def test_every_scope_type_is_wrapped(self):
        """HTTP, WebSocket and lifespan calls all start from an empty context."""
        for scope_type in ("http", "websocket", "lifespan"):
            with self.subTest(scope_type=scope_type):
                self.assertEqual(
                    self.seen_by_app(scope_type),
                    {"type": scope_type, "value": "unset"},
                )

    def test_return_value_passes_through(self):
        """The app's return value is returned to the server."""

        async def app(scope, receive, send):
            await asyncio.sleep(0)
            return "done"

        self.assertEqual(self.call(FreshContextMiddleware(app)), "done")

    def test_the_same_exception_object_reaches_the_server(self):
        """An error from the app is re-raised as is, after the app has awaited."""
        error = ValueError("boom")

        async def app(scope, receive, send):
            await asyncio.sleep(0)
            raise error

        with self.assertRaises(ValueError) as caught:
            self.call(FreshContextMiddleware(app))
        self.assertIs(caught.exception, error)

    def test_cancellation_reaches_the_app_and_waits_for_its_cleanup(self):
        """Cancelling the call cancels the app and returns only after it cleaned up."""
        state = {}

        async def app(scope, receive, send):
            state["started"] = True
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                await asyncio.sleep(0.01)
                state["cleaned_up"] = True
                raise

        async def main():
            task = asyncio.ensure_future(
                FreshContextMiddleware(app)(_http_scope(), None, None)
            )
            while not state.get("started"):
                await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            state["cleaned_up_before_return"] = state.get("cleaned_up", False)

        asyncio.run(main())
        self.assertTrue(state["cleaned_up_before_return"])

    def test_cancellation_before_the_app_starts(self):
        """A call cancelled before the app runs raises cleanly and leaves no warning."""
        state = {}

        async def app(scope, receive, send):
            state["started"] = True

        async def main():
            task = asyncio.ensure_future(
                FreshContextMiddleware(app)(_http_scope(), None, None)
            )
            # One loop pass: the wrapper creates the app task and waits on it,
            # but the app task has not taken its first step yet.
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            asyncio.run(main())
            gc.collect()
        self.assertNotIn("started", state)
        self.assertEqual(
            [str(w.message) for w in caught if w.category is RuntimeWarning], []
        )

    def test_an_app_that_absorbs_cancellation_behaves_as_without_the_wrapper(self):
        """If the app swallows the cancellation, the server sees the same outcome."""

        async def app(scope, receive, send):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                return "absorbed"

        async def outcome(callable_app):
            task = asyncio.ensure_future(callable_app(_http_scope(), None, None))
            await asyncio.sleep(0.01)
            task.cancel()
            try:
                return ("returned", await task)
            except asyncio.CancelledError:
                return ("cancelled", None)

        self.assertEqual(
            asyncio.run(outcome(FreshContextMiddleware(app))),
            asyncio.run(outcome(app)),
        )

    def test_project_asgi_application_is_wrapped(self):
        """horilla.asgi.application is the router wrapped in FreshContextMiddleware."""
        # Third party imports
        from channels.routing import ProtocolTypeRouter

        from horilla.asgi import application

        self.assertIsInstance(application, FreshContextMiddleware)
        self.assertIsInstance(application.app, ProtocolTypeRouter)


# ---------------------------------------------------------------------------
# Pipelined requests through Django's real ASGIHandler.
#
# The harness serves requests the way uvicorn does: the next request on a
# keep-alive connection is started from inside the previous request's final
# send(), so it inherits that request's context. Without FreshContextMiddleware
# this deadlocks the event loop, so the scenarios run in a child process and
# each one in its own thread with a deadline; a regression then fails the
# tests instead of hanging the test run.
# ---------------------------------------------------------------------------

_context_tags = itertools.count(1)


def _echo_view(request, number):
    """Report the request the thread-local middleware stored and the sync context."""
    current = get_current_request()
    context = SyncToAsync.thread_sensitive_context.get(None)
    if context is not None and not hasattr(context, "test_tag"):
        context.test_tag = next(_context_tags)
    return JsonResponse(
        {
            "path": request.path,
            "thread_local_path": getattr(current, "path", None),
            "context_tag": getattr(context, "test_tag", None),
        }
    )


def _slow_view(request):
    """Take long enough for the client to go away first."""
    time.sleep(0.3)
    return JsonResponse({"path": request.path})


urlpatterns = [
    path("echo/<int:number>/", _echo_view),
    path("slow/", _slow_view),
]


def _decode_body(body):
    """Decode a JSON response body; keep the start of anything else for the report."""
    try:
        return json.loads(body)
    except ValueError:
        return {"raw": body[:300].decode(errors="replace")}


async def _keep_alive_connection(app, paths, disconnect_after=None):
    """Serve ``paths`` as pipelined requests on one connection, like uvicorn.

    Returns one dict per request with its status and decoded JSON body; a
    request that sent no response has an empty dict.
    """
    loop = asyncio.get_running_loop()
    responses = [{} for _ in paths]
    tasks = []

    def receive_for():
        body_sent = False

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": b"", "more_body": False}
            # Django now waits for a disconnect while the view runs.
            await asyncio.sleep(60 if disconnect_after is None else disconnect_after)
            return {"type": "http.disconnect"}

        return receive

    def send_for(index):
        chunks = []

        async def send(message):
            if message["type"] == "http.response.start":
                responses[index]["status"] = message["status"]
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    responses[index]["body"] = _decode_body(b"".join(chunks))
                    if index + 1 < len(paths):
                        # uvicorn's on_response_complete: the next pipelined
                        # request starts from inside this request's task.
                        start(index + 1)

        return send

    def start(index):
        tasks.append(
            loop.create_task(
                app(_http_scope(paths[index]), receive_for(), send_for(index))
            )
        )

    start(0)
    while pending := [task for task in tasks if not task.done()]:
        await asyncio.wait(pending)
    for task in tasks:
        task.result()
    return responses


def _run_with_deadline(make_coroutine, timeout):
    """Run a coroutine on its own loop in a daemon thread; report a hang instead of hanging."""
    outcome = {}

    def target():
        try:
            outcome["value"] = asyncio.run(make_coroutine())
        except BaseException as exc:
            outcome["error"] = repr(exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    return {"hung": thread.is_alive(), **outcome}


def run_pipelined_scenarios():
    """Run every pipelined scenario and return their outcomes (child process only)."""
    # Third-party imports (Django)
    from django.core.handlers.asgi import ASGIHandler
    from django.test.utils import override_settings

    from horilla.asgi import application as project_application

    # Every scenario runs on its own event loop, and a handler's async_to_sync
    # adapters keep the loop they first ran on, so each scenario builds its own
    # handler. horilla.asgi.application is used once, by the first scenario.
    def thread_local_handler():
        """Django's handler with only Horilla's sync-only ThreadLocalMiddleware."""
        with override_settings(MIDDLEWARE=[THREAD_LOCAL_MIDDLEWARE]):
            return ASGIHandler()

    def wrapped_handler():
        return FreshContextMiddleware(thread_local_handler())

    echo_paths = [f"/echo/{number}/" for number in range(5)]
    results = {}
    with override_settings(ALLOWED_HOSTS=["testserver"]):
        results["project_wrapped"] = _run_with_deadline(
            lambda: _project_health(project_application), timeout=30
        )
        with override_settings(ROOT_URLCONF=__name__):
            results["minimal_wrapped"] = _run_with_deadline(
                lambda: _keep_alive_connection(wrapped_handler(), echo_paths),
                timeout=30,
            )
            results["concurrent_wrapped"] = _run_with_deadline(
                lambda: _concurrent_connections(wrapped_handler()), timeout=30
            )
            results["disconnect_wrapped"] = _run_with_deadline(
                lambda: _disconnect_then_request(wrapped_handler()), timeout=30
            )
            # Guards last: each leaves a deadlocked thread behind.
            results["minimal_unwrapped"] = _run_with_deadline(
                lambda: _keep_alive_connection(thread_local_handler(), echo_paths),
                timeout=3,
            )
        # The project's full middleware stack, as horilla.asgi builds it, but
        # without FreshContextMiddleware.
        results["project_unwrapped"] = _run_with_deadline(
            lambda: _project_health(ASGIHandler()), timeout=3
        )
    return results


async def _project_health(app):
    """Five pipelined /health/ requests, then one on a new connection."""
    pipelined = await _keep_alive_connection(app, ["/health/"] * 5)
    fresh = await _keep_alive_connection(app, ["/health/"])
    return {"pipelined": pipelined, "fresh": fresh}


async def _concurrent_connections(app, connections=8, per_connection=4):
    """Several keep-alive connections pipelining at the same time."""
    return await asyncio.gather(
        *(
            _keep_alive_connection(
                app,
                [
                    f"/echo/{connection * 100 + number}/"
                    for number in range(per_connection)
                ],
            )
            for connection in range(connections)
        )
    )


async def _disconnect_then_request(app):
    """A client leaves during a slow view; the next request is still served."""
    aborted = await _keep_alive_connection(app, ["/slow/"], disconnect_after=0.05)
    after = await _keep_alive_connection(app, ["/echo/1/"])
    return {"aborted": aborted, "after": after}


_CHILD_SCRIPT = """
import json, os, sys
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "horilla.settings")
django.setup()
from horilla.contrib.utils.tests import run_pipelined_scenarios
sys.stdout.write("RESULT " + json.dumps(run_pipelined_scenarios()) + "\\n")
sys.stdout.flush()
os._exit(0)  # deadlocked guard threads must not block interpreter shutdown
"""


class PipelinedRequestTests(SimpleTestCase):
    """Pipelined and keep-alive requests must never deadlock a worker."""

    @classmethod
    def setUpClass(cls):
        """Run all scenarios once, in a child process that a deadlock cannot hang."""
        super().setUpClass()
        completed = subprocess.run(
            [sys.executable, "-c", _CHILD_SCRIPT],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        lines = [
            line for line in completed.stdout.splitlines() if line.startswith("RESULT ")
        ]
        if not lines:
            raise AssertionError(
                "The pipelined-request child process gave no result.\n"
                f"exit code: {completed.returncode}\n"
                f"stderr:\n{completed.stderr[-4000:]}"
            )
        cls.results = json.loads(lines[-1][len("RESULT ") :])

    def outcome(self, name):
        """Return a scenario's value, failing clearly on a hang or an error."""
        result = self.results[name]
        self.assertFalse(result["hung"], f"{name}: the event loop deadlocked")
        self.assertNotIn("error", result, f"{name}: {result.get('error')}")
        return result["value"]

    def assert_echo_responses(self, responses, paths):
        """Each response is a 200 for its own path, in order."""
        self.assertEqual(len(responses), len(paths))
        for response, request_path in zip(responses, paths):
            self.assertEqual(response.get("status"), 200, response)
            self.assertEqual(response["body"]["path"], request_path)

    def test_pipelined_requests_all_get_a_response(self):
        """Five pipelined requests on one connection are all answered, in order."""
        responses = self.outcome("minimal_wrapped")
        self.assert_echo_responses(responses, [f"/echo/{n}/" for n in range(5)])

    def test_each_pipelined_request_gets_its_own_sync_context(self):
        """No request runs in a ThreadSensitiveContext inherited from another one."""
        responses = self.outcome("minimal_wrapped")
        tags = [response["body"]["context_tag"] for response in responses]
        self.assertNotIn(None, tags)
        self.assertEqual(len(set(tags)), len(tags), tags)

    def test_thread_local_request_matches_each_pipelined_request(self):
        """ThreadLocalMiddleware still exposes the right request to sync code."""
        for response in self.outcome("minimal_wrapped"):
            body = response["body"]
            self.assertEqual(body["thread_local_path"], body["path"])

    def test_project_application_survives_pipelined_requests(self):
        """The real project stack answers pipelined /health/ and stays healthy."""
        value = self.outcome("project_wrapped")
        self.assertEqual(
            [response.get("status") for response in value["pipelined"]], [200] * 5
        )
        self.assertEqual([response.get("status") for response in value["fresh"]], [200])

    def test_concurrent_keep_alive_connections(self):
        """Eight connections pipelining four requests each are all answered."""
        connections = self.outcome("concurrent_wrapped")
        self.assertEqual(len(connections), 8)
        tags = []
        for connection, responses in enumerate(connections):
            paths = [f"/echo/{connection * 100 + n}/" for n in range(4)]
            self.assert_echo_responses(responses, paths)
            for response in responses:
                body = response["body"]
                self.assertEqual(body["thread_local_path"], body["path"])
                tags.append(body["context_tag"])
        self.assertEqual(len(set(tags)), 32, "a sync context was shared")

    def test_client_disconnect_still_aborts_and_the_worker_recovers(self):
        """A disconnect mid-view aborts that request and the next one is served."""
        value = self.outcome("disconnect_wrapped")
        self.assertEqual(value["aborted"], [{}], "the aborted request got a response")
        self.assert_echo_responses(value["after"], ["/echo/1/"])

    def test_the_reproduction_deadlocks_without_the_middleware(self):
        """Guard: the same scenarios hang without FreshContextMiddleware.

        If this fails, the harness no longer reproduces the bug (or Django,
        asgiref or asyncio fixed the leak), and the tests above prove nothing.
        """
        for name in ("minimal_unwrapped", "project_unwrapped"):
            with self.subTest(scenario=name):
                self.assertTrue(
                    self.results[name]["hung"],
                    f"{name} no longer deadlocks without FreshContextMiddleware",
                )
