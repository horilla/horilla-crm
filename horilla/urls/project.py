"""
URL configuration for horilla project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

from horilla import settings


def health_check(request):
    """Return JSON ``{"status": "ok"}`` for load balancer or uptime probes."""
    return JsonResponse({"status": "ok"}, status=200)


urlpatterns = [
    path("health/", health_check),
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    path("summernote/", include("django_summernote.urls")),
    path("api/", include("horilla.api_urls")),
]

if settings.DEBUG:
    # Uploads stay on protected_media. django.views.static would return the
    # file with no login check whenever DEBUG is on.
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Compose extensions once the app registry is fully populated.
#
# This module is imported by whichever app's AppLauncher._register_urls()
# happens to run first (commonly an early app such as horilla.contrib.core),
# which happens *during* AppConfig.ready() — before every app has finished
# loading, so django.apps.apps.ready is still False and extension apps that
# load later (e.g. field_management) have not
# registered anything yet. Because this module is only ever imported once,
# calling bootstrap_extensions() directly here would silently no-op forever
# for any extension registered by a later-loading app.
#
# django.core.signals.request_started only fires once django.setup() has
# fully completed (a request cannot happen before app loading finishes), so
# it is a reliable "everything is actually ready" hook that works uniformly
# across WSGI, ASGI, and the test client.
from django.core.signals import request_started

from horilla.extension.bootstrap import bootstrap_extensions

bootstrap_extensions()


def _bootstrap_extensions_on_first_request(sender, **kwargs):
    bootstrap_extensions()
    request_started.disconnect(_bootstrap_extensions_on_first_request)


request_started.connect(_bootstrap_extensions_on_first_request, weak=False)
