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

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

import calls.routing
import horilla.contrib.notifications.routing
from horilla.utils.asgi import FreshContextMiddleware

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "horilla.settings")

# Each connection runs in a fresh context so one request's Django
# ThreadSensitiveContext cannot leak into the next request on the same
# keep-alive connection and deadlock the worker (see FreshContextMiddleware).
application = FreshContextMiddleware(
    ProtocolTypeRouter(
        {
            "http": get_asgi_application(),
            "websocket": AuthMiddlewareStack(
                URLRouter(
                    horilla.contrib.notifications.routing.websocket_urlpatterns
                    + calls.routing.websocket_urlpatterns
                )
            ),
        }
    )
)
