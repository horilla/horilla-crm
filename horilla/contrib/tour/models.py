"""
Models for the tour app.

The only thing remembered is which tours have already started by themselves for
a user, so an automatic tour runs once (on first login) and never again on its
own. It is stored in the database, not ``localStorage``, because browser storage
is wiped at logout. Replaying a tour from the profile menu needs no state at all.
"""

# Third-party imports (Django)
from django.conf import settings

# First party imports (Horilla)
from horilla.db import models
from horilla.utils.translation import gettext_lazy as _


class TourSeen(models.Model):
    """A tour that has already started automatically for a user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tours_seen",
        verbose_name=_("User"),
    )
    tour_key = models.CharField(max_length=100, verbose_name=_("Tour"))

    class Meta:
        """Django model options for tours already shown."""

        verbose_name = _("Tour Shown")
        verbose_name_plural = _("Tours Shown")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "tour_key"], name="tour_seen_unique_user_tour"
            )
        ]

    def __str__(self):
        return f"{self.user}: {self.tour_key}"
