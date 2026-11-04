"""Token login with the same failure limits as the HTML sign-in page."""

from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.views import TokenObtainPairView

from horilla.contrib.core.auth_limits import (
    CredentialStoreUnavailable,
    clear_login_failures,
    login_blocked,
    record_login_failure,
    signin_unavailable_message,
)
from horilla.contrib.core.throttling import AuthEndpointThrottle


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """
    Issue a JWT pair after counting a wrong password.

    DRF authenticates before it throttles, so Basic authentication cannot be
    the place this limit is applied. This view checks the shared lockout
    before it calls ``authenticate``.
    """

    throttle_classes = [AuthEndpointThrottle]

    def post(self, request, *args, **kwargs):
        username = _submitted_username(request)
        try:
            blocked = login_blocked(request, username)
        except CredentialStoreUnavailable:
            return Response(
                {"detail": signin_unavailable_message()},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if blocked:
            return Response(
                {"detail": blocked},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0])
        except (ValidationError, AuthenticationFailed):
            try:
                blocked = record_login_failure(request, username)
            except CredentialStoreUnavailable:
                return Response(
                    {"detail": signin_unavailable_message()},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            if blocked:
                return Response(
                    {"detail": blocked}, status=status.HTTP_429_TOO_MANY_REQUESTS
                )
            raise

        user = getattr(serializer, "user", None)
        signed_in_as = username
        if user is not None and hasattr(user, "get_username"):
            signed_in_as = user.get_username()
        clear_login_failures(request, signed_in_as)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


def _submitted_username(request):
    data = getattr(request, "data", None)
    if not hasattr(data, "get"):
        return ""
    return str(data.get("username") or "")
