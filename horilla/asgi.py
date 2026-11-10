"""
ASGI config for horilla project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

# import os

# from django.core.asgi import get_asgi_application

# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'horilla.settings')

# application = get_asgi_application()

import importlib
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "horilla.settings")

from django.apps import apps
from django.core.asgi import get_asgi_application

# Runs django.setup(), so the app registry is ready for the discovery below.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

from horilla.utils.asgi import FreshContextMiddleware


def collect_websocket_urlpatterns():
    """
    Gather ``websocket_urlpatterns`` from every installed app's ``routing`` module
    (``<app>/routing.py``), so a new app with WebSockets just ships that file and
    this module never needs editing. Apps without a ``routing`` module, or whose
    module defines no ``websocket_urlpatterns``, are skipped.
    """
    patterns = []
    for app_config in apps.get_app_configs():
        module_name = f"{app_config.name}.routing"
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:  # this app simply has no routing module
                continue
            raise  # the module exists but one of its own imports is broken
        patterns.extend(getattr(module, "websocket_urlpatterns", []))
    return patterns


# Each connection runs in a fresh context so one request's Django
# ThreadSensitiveContext cannot leak into the next request on the same
# keep-alive connection and deadlock the worker (see FreshContextMiddleware).
application = FreshContextMiddleware(
    ProtocolTypeRouter(
        {
            "http": django_asgi_app,
            "websocket": AuthMiddlewareStack(
                URLRouter(collect_websocket_urlpatterns())
            ),
        }
    )
)
