"""API rate limits keyed on the same client address as the login lockout."""

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from horilla.contrib.core.auth_limits import client_ip


class ClientIpAnonRateThrottle(AnonRateThrottle):
    """Anonymous throttle that ignores a caller-supplied forwarded-for header."""

    def get_ident(self, request):
        return client_ip(request)


class ClientIpUserRateThrottle(UserRateThrottle):
    """Authenticated throttle that falls back to the trusted client address."""

    def get_ident(self, request):
        return client_ip(request)


class AuthEndpointThrottle(ClientIpAnonRateThrottle):
    """Tighter limit for endpoints that check a password."""

    scope = "auth"
