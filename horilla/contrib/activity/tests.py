"""
Tests for the activity app
"""

# Third-party imports (Django)
from auditlog.models import LogEntry
from django.test import TestCase

# First party imports (Horilla)
from horilla.contrib.activity.models import Activity
from horilla.contrib.core.models import Company
from horilla.contrib.generics.templatetags.horilla_tags.history_display import (
    create_status_display,
    create_type_display,
)
from horilla.utils.translation import override


class ActivityHistoryCreateRowTests(TestCase):
    """An activity's creation row on a related record's History tab shows the
    activity as it was created, not as it is now."""

    def test_creation_row_shows_status_and_type_at_creation(self):
        """A task created "In Progress" and completed since still reads
        "Status: In Progress" on its creation row."""
        company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        activity = Activity.objects.create(
            subject="Follow up",
            activity_type="task",
            status="in_progress",
            company=company,
        )
        activity.status = "completed"
        activity.activity_type = "meeting"
        activity.save()

        created = LogEntry.objects.get_for_object(activity).get(
            action=LogEntry.Action.CREATE
        )
        with override("en"):
            self.assertEqual(create_status_display(created, "company"), "In Progress")
            self.assertEqual(create_type_display(created), "New Task created")
