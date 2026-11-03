"""
Business logic for bidirectional Google Calendar sync.

Horilla → Google:  push_activity_to_google, push_unavailability_to_google
Google → Horilla:  pull_google_events_to_horilla
"""

# Standard library imports
import logging
import threading
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from horilla.contrib.activity.models import Activity

# First party imports (Horilla)
from horilla.utils import timezone

# Local imports
from ..models import GoogleCalendarConfig, GoogleIntegrationSetting
from .service import (
    delete_event_from_google,
    delete_task_from_google_tasks,
    list_google_events,
    list_google_tasks,
    push_event_to_google,
    push_task_to_google_tasks,
)

# Thread-local flag set during Google-pull saves to suppress the push-back signal.
_google_pull_local = threading.local()


def is_pulling_from_google():
    """Return True if the current thread is inside a Google pull operation."""
    return getattr(_google_pull_local, "active", False)


logger = logging.getLogger(__name__)


def user_has_google_access(user):
    """True when the company's Google integration is on and ``user`` is allowed to sync."""
    company = getattr(user, "company", None)
    return bool(company and GoogleIntegrationSetting.user_can_access(user, company))


# ---- helpers for Google Tasks pull ----------------------------------------


def _parse_google_task_due(due_str):
    """Parse Google Tasks 'due' field (RFC3339 date-time string) to aware datetime."""
    if not due_str:
        return None
    try:
        return datetime.fromisoformat(due_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def _strip_legacy_task_prefix(title):
    """Remove legacy '[Horilla] ' prefix from older sync versions (no product name in titles)."""
    if title.startswith("[Horilla] "):
        return title[10:]
    return title


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_datetime(dt):
    """Return RFC3339 string for a datetime (Google Calendar API requirement)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Assume UTC for naive datetimes
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt.isoformat()


def _parse_google_datetime(google_dt_dict):
    """
    Parse a Google dateTime or date dict into an aware datetime.

    Google sends either {"dateTime": "..."} or {"date": "YYYY-MM-DD"}.
    """
    if not google_dt_dict:
        return timezone.now()
    if "dateTime" in google_dt_dict:
        dt_str = google_dt_dict["dateTime"]
        try:
            return datetime.fromisoformat(dt_str)
        except ValueError:
            return timezone.now()
    if "date" in google_dt_dict:
        from datetime import date as _date

        d = _date.fromisoformat(google_dt_dict["date"])
        return datetime(d.year, d.month, d.day, tzinfo=dt_timezone.utc)
    return timezone.now()


def activity_to_google_event(activity):
    """
    Convert a activity.Activity to a Google Calendar Events resource.

    Sets colorId so each Horilla type (task/event/meeting) has a distinct colour
    in Google Calendar matching the Horilla calendar legend.

    Uses extendedProperties.private to tag the event with the Horilla record ID
    so that pulled events can be recognised as Horilla-originated and skipped.
    """
    # Determine start/end datetimes
    start_dt = activity.start_datetime or activity.due_datetime
    end_dt = activity.end_datetime or activity.due_datetime or start_dt

    if start_dt and end_dt and end_dt < start_dt:
        end_dt = start_dt

    # Google Calendar renders events as dots when duration is 0.
    # Ensure a minimum 1-hour block so the event shows as a proper coloured block.
    if start_dt and end_dt and not activity.is_all_day and end_dt == start_dt:
        end_dt = start_dt + timedelta(hours=1)

    if activity.is_all_day and start_dt:
        start_block = {"date": start_dt.date().isoformat()}
        end_block = {"date": (end_dt or start_dt).date().isoformat()}
    else:
        # dateTime already carries a correct UTC offset, so the absolute instant
        # is right either way — but Google Calendar API events are documented to
        # require a "timeZone" alongside "dateTime" for the event to be treated
        # as zone-aware (e.g. for recurrence/DST); the organizer's (meeting host's,
        # falling back to the owner's) IANA zone is used, mirroring the same
        # host-first fallback used for invite emails.
        organizer = activity.meeting_host or activity.owner
        event_tz = getattr(organizer, "time_zone", None) or "UTC"
        start_block = (
            {"dateTime": _format_datetime(start_dt), "timeZone": event_tz}
            if start_dt
            else None
        )
        end_block = (
            {"dateTime": _format_datetime(end_dt), "timeZone": event_tz}
            if end_dt
            else None
        )

    if start_block is None:
        # No date at all — skip sync
        return None

    if end_block is None:
        end_block = start_block

    summary = activity.subject or activity.title or str(activity.activity_type)

    # Build a readable prefix so the Horilla type is visible in Google Calendar
    type_prefix = {
        "task": "[Task]",
        "event": "[Event]",
        "meeting": "[Meeting]",
        "log_call": "[Call]",
    }.get(activity.activity_type, "")

    description = activity.description or ""
    location = activity.location or ""

    event_data = {
        "summary": f"{type_prefix} {summary}".strip(),
        "description": description,
        "location": location,
        "start": start_block,
        "end": end_block,
        "extendedProperties": {
            "private": {
                "activity_id": str(activity.pk),
                "horilla_event_type": activity.activity_type,
            }
        },
    }

    if getattr(activity, "is_online", False):
        provider = getattr(activity, "meeting_provider", None)
        meeting_url = activity.meeting_url or ""
        if provider == "google_meet" and not activity.google_event_id:
            # No Google event exists for this meeting yet — ask Google to mint a
            # fresh Meet link on this same (real, persisted) event so Calendar
            # shows it as a video-conferencing meeting, not a plain block.
            event_data["conferenceData"] = {
                "createRequest": {
                    "requestId": f"horilla-meet-{activity.pk}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
        elif meeting_url:
            # Zoom / Teams / an already-generated Meet link: Calendar's native
            # conferenceData can't carry arbitrary third-party URLs, so surface
            # the join link via location + description instead.
            event_data["location"] = meeting_url
            if meeting_url not in description:
                joiner = "\n\n" if description else ""
                event_data["description"] = f"{description}{joiner}Join: {meeting_url}"

    return event_data


def push_activity_to_google(activity, user):
    """
    Push a single Activity to Google for a specific user.

    Routing:
      task     → Google Tasks API  (appears as a checkbox task in Google Calendar)
      event    → Google Calendar Events API  (coloured block)
      meeting  → Google Calendar Events API  (coloured block)
      log_call → Google Calendar Events API  (coloured block)

    Silently skips if the user has no configured / connected GoogleCalendarConfig.
    Saves the returned Google ID back to activity.google_event_id.
    """
    if not user_has_google_access(user):
        return
    try:
        config = GoogleCalendarConfig.all_objects.get(user=user)
    except GoogleCalendarConfig.DoesNotExist:
        return
    if not config.is_connected():
        return
    # Push is allowed for both sync directions (one-way and two-way both push outward)
    if config.sync_direction not in ("horilla_to_google", "both"):
        return

    try:
        if activity.activity_type == "task":
            gid = push_task_to_google_tasks(config, activity)
            # Mark Horilla platform-pushed tasks so pull can sync completion only (no title overwrite),
            # without embedding a product name in the Google Tasks title.
            ai = activity.additional_info
            if not isinstance(ai, dict):
                ai = {}
            else:
                ai = {**ai}
            ai["google_task_pushed_from_horilla"] = True
            updates = {"additional_info": ai}
            if activity.google_event_id != gid:
                updates["google_event_id"] = gid
            type(activity).objects.filter(pk=activity.pk).update(**updates)
        else:
            event_data = activity_to_google_event(activity)
            if event_data is None:
                return
            event_data["google_event_id"] = activity.google_event_id or None
            requesting_meet_link = "conferenceData" in event_data
            result = push_event_to_google(
                config, event_data, return_full=requesting_meet_link
            )
            gid = result["id"] if requesting_meet_link else result

            updates = {}
            if activity.google_event_id != gid:
                updates["google_event_id"] = gid
            if requesting_meet_link:
                hangout_link = result.get("hangoutLink") or ""
                if not hangout_link:
                    for ep in result.get("conferenceData", {}).get("entryPoints", []):
                        if ep.get("entryPointType") == "video":
                            hangout_link = ep.get("uri", "")
                            break
                if hangout_link and hangout_link != activity.meeting_url:
                    updates["meeting_url"] = hangout_link
            if updates:
                type(activity).objects.filter(pk=activity.pk).update(**updates)
    except Exception as exc:
        logger.error(
            "Google push failed for activity %s (user %s): %s",
            activity.pk,
            user,
            exc,
        )


def push_unavailability_to_google(ua):
    """
    Push a UserAvailability block to the user's Google Calendar.

    Saves the returned Google event ID back to ua.google_event_id.
    """
    if not user_has_google_access(ua.user):
        return
    try:
        config = GoogleCalendarConfig.all_objects.get(user=ua.user)
    except GoogleCalendarConfig.DoesNotExist:
        return
    if not config.is_connected():
        return
    if config.sync_direction not in ("horilla_to_google", "both"):
        return

    event_data = {
        "summary": f"Unavailable: {ua.reason}",
        "start": {"dateTime": _format_datetime(ua.from_datetime)},
        "end": {"dateTime": _format_datetime(ua.to_datetime)},
        "extendedProperties": {
            "private": {
                "horilla_unavailability_id": str(ua.pk),
            }
        },
        "google_event_id": ua.google_event_id or None,
    }

    try:
        gid = push_event_to_google(config, event_data)
        if ua.google_event_id != gid:
            type(ua).objects.filter(pk=ua.pk).update(google_event_id=gid)
    except Exception as exc:
        logger.error(
            "Google Calendar push failed for unavailability %s (user %s): %s",
            ua.pk,
            ua.user,
            exc,
        )


def delete_activity_google_event(activity, user):
    """Delete the Google Calendar event/task for an activity (called on post_delete).

    Routes: task → Google Tasks API; others → Google Calendar Events API.
    """
    if not activity.google_event_id:
        return
    try:
        config = GoogleCalendarConfig.all_objects.get(user=user)
    except GoogleCalendarConfig.DoesNotExist:
        return
    if not config.is_connected():
        return
    try:
        if activity.activity_type == "task":
            delete_task_from_google_tasks(config, activity.google_event_id)
        else:
            delete_event_from_google(config, activity.google_event_id)
    except Exception as exc:
        logger.error(
            "Google Calendar delete failed for activity %s (user %s): %s",
            activity.pk,
            user,
            exc,
        )


def delete_unavailability_google_event(ua):
    """Delete the Google Calendar event for a UserAvailability (called on post_delete)."""
    if not ua.google_event_id:
        return
    try:
        config = GoogleCalendarConfig.all_objects.get(user=ua.user)
    except GoogleCalendarConfig.DoesNotExist:
        return
    if not config.is_connected():
        return
    try:
        delete_event_from_google(config, ua.google_event_id)
    except Exception as exc:
        logger.error(
            "Google Calendar delete failed for unavailability %s (user %s): %s",
            ua.pk,
            ua.user,
            exc,
        )


_GOOGLE_EVENT_TYPE_MAP = {
    "default": "event",
    "focusTime": "task",
    "outOfOffice": "task",
    "workingLocation": "task",
}

# Summary prefixes written by Horilla → strip them on pull so subject is clean
_HORILLA_SUMMARY_PREFIXES = ("[Task] ", "[Event] ", "[Meeting] ", "[Call] ")

# eventTypes that are not useful to import into Horilla (birthday, etc.)
_GOOGLE_SKIP_EVENT_TYPES = {"birthday", "fromGmail"}


def _strip_horilla_prefix(summary):
    """Remove the [Task]/[Event]/[Meeting]/[Call] prefix added by Horilla on push."""
    for prefix in _HORILLA_SUMMARY_PREFIXES:
        if summary.startswith(prefix):
            return summary[len(prefix) :]
    return summary


def _upsert_activity_from_google(gevent, config):
    """
    Create or update a Horilla Activity from a Google Calendar event.

    Type mapping priority:
      1. extendedProperties.private.horilla_event_type  (set by Horilla on push — exact match)
      2. Google eventType field:
           default        → event
           focusTime      → task
           outOfOffice    → task
           birthday/etc   → skipped (handled by caller)
    """

    google_event_id = gevent["id"]
    extended_private = gevent.get("extendedProperties", {}).get("private", {})
    # Priority 1: use Horilla-tagged type if present
    activity_type = extended_private.get("horilla_event_type")
    # Priority 2: map from Google eventType
    if not activity_type:
        event_type = gevent.get("eventType", "default")
        activity_type = _GOOGLE_EVENT_TYPE_MAP.get(event_type, "event")

    raw_summary = gevent.get("summary") or "Google Calendar Event"
    summary = _strip_horilla_prefix(raw_summary)
    description = gevent.get("description") or ""
    location = gevent.get("location") or ""

    start = gevent.get("start", {})
    end = gevent.get("end", {})
    is_all_day = "date" in start and "dateTime" not in start

    start_dt = _parse_google_datetime(start)
    end_dt = _parse_google_datetime(end)

    if is_all_day and start_dt:
        start_dt = start_dt.replace(hour=9, minute=0, second=0, microsecond=0)
        end_dt = start_dt.replace(hour=10, minute=0, second=0, microsecond=0)
        is_all_day = False

    end_dt = max(end_dt, start_dt)

    # Preserve "completed" status for existing activities.
    # Google Calendar Events have no "completed" concept — only Google Tasks do.
    # Without this check, every pull resets activities marked complete in Horilla
    # back to "scheduled".
    existing = (
        Activity.objects.filter(google_event_id=google_event_id).only("status").first()
    )
    preserved_status = (
        existing.status if existing and existing.status == "completed" else "scheduled"
    )

    defaults = {
        "subject": summary[:100],
        "description": description,
        "location": location[:100],
        "activity_type": activity_type,
        "status": preserved_status,
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "is_all_day": is_all_day,
        "owner": config.user,
        "company": config.user.company,
    }
    if activity_type == "task":
        defaults["due_datetime"] = end_dt

    _google_pull_local.active = True
    try:
        activity, created = Activity.objects.update_or_create(
            google_event_id=google_event_id,
            defaults=defaults,
        )
    finally:
        _google_pull_local.active = False

    activity._from_google = True
    return activity, created


def pull_google_events_to_horilla(config, initial_sync_only=False):
    """
    Pull events from Google Calendar and tasks from Google Tasks,
    then upsert them as Horilla Activities.

    Calendar event mapping:
      Google eventType "default"   → Horilla Activity type "event"
      Google eventType "focusTime" → Horilla Activity type "task"
      Google eventType "birthday"  → skipped
      Horilla-originated events (have activity_id in extendedProperties) → skipped

    Google Tasks mapping:
      Tasks → Horilla Activity type "task"; Google status maps to Horilla status
      (completed ↔ completed, otherwise scheduled).
      update status only (no duplicate import / field overwrite).

    Uses incremental sync (google_sync_token) for calendar events after the first full pull.
    Saves the nextSyncToken back to config for the next run.

    initial_sync_only: When True and no sync token exists yet, only fetch and save the
    nextSyncToken without importing any events. This bootstraps incremental sync without
    flooding Horilla with all existing Google Calendar history.
    """
    # Only pull from Google when the user has chosen two-way sync.
    # One-way (horilla_to_google) skips the pull entirely.
    if not user_has_google_access(config.user):
        logger.debug("Skipping pull for user=%s: no Google access", config.user)
        return
    if config.sync_direction != "both":
        logger.debug(
            "Skipping pull for user=%s: sync_direction=%r",
            config.user,
            config.sync_direction,
        )
        return

    logger.info("Pulling Google events for user=%s", config.user)

    # ---- Bootstrap: on the very first pull (no sync token), just capture the
    # nextSyncToken so future incremental syncs only see *new* changes — do NOT
    # import the user's entire Google Calendar history. This prevents a flood of
    # old events appearing in Horilla the first time a task/event is pushed out.
    if initial_sync_only and not config.google_sync_token:
        try:
            _, next_sync_token = list_google_events(config, sync_token=None)
            if next_sync_token:
                config.google_sync_token = next_sync_token
                config.last_synced_at = timezone.now()
                config.save(update_fields=["google_sync_token", "last_synced_at"])
                logger.info(
                    "Bootstrap complete for user=%s: sync_token captured", config.user
                )
        except Exception as exc:
            logger.error(
                "Google Calendar bootstrap failed for user %s: %s", config.user, exc
            )
        return

    # ---- Pull Google Calendar events ----------------------------------------
    try:
        events, next_sync_token = list_google_events(
            config, sync_token=config.google_sync_token
        )
    except Exception as exc:
        logger.error("Google Calendar list failed for user %s: %s", config.user, exc)
        return

    logger.debug("Google returned %d event(s) for user=%s", len(events), config.user)

    for gevent in events:
        google_event_id = gevent.get("id")
        status = gevent.get("status")
        event_type = gevent.get("eventType", "default")
        extended = gevent.get("extendedProperties", {}).get("private", {})

        logger.debug(
            "Processing event id=%s type=%r status=%r",
            google_event_id,
            event_type,
            status,
        )

        # Skip Horilla-originated events entirely (they are already in the Horilla)
        if extended.get("activity_id") or extended.get("horilla_unavailability_id"):
            logger.debug("Skipping Horilla-originated event id=%s", google_event_id)
            continue

        # Skip event types that don't map to Horilla activities
        if event_type in _GOOGLE_SKIP_EVENT_TYPES:
            logger.debug(
                "Skipping event id=%s (event_type=%r)", google_event_id, event_type
            )
            continue

        # Handle deletions
        if status == "cancelled":
            Activity.objects.filter(
                google_event_id=google_event_id,
            ).delete()
            logger.debug("Deleted activity for google_event_id=%s", google_event_id)
            continue

        try:
            activity, created = _upsert_activity_from_google(gevent, config)
            logger.debug(
                "%s Activity pk=%s subject=%r",
                "Created" if created else "Updated",
                activity.pk,
                activity.subject,
            )
        except Exception as exc:
            logger.error(
                "Failed to upsert Google event %s for user %s: %s",
                google_event_id,
                config.user,
                exc,
                exc_info=True,
            )

    if next_sync_token:
        config.google_sync_token = next_sync_token

    # ---- Pull Google Tasks --------------------------------------------------
    try:
        gtasks = list_google_tasks(config)
    except Exception as exc:
        logger.error("Google Tasks list failed for user %s: %s", config.user, exc)
        gtasks = []

    for gtask in gtasks:
        google_task_id = gtask.get("id")
        if not google_task_id:
            continue

        raw_title = gtask.get("title") or "Google Task"
        task_status = gtask.get("status", "needsAction")

        existing_task_activity = Activity.objects.filter(
            google_event_id=google_task_id
        ).first()
        ai = existing_task_activity.additional_info if existing_task_activity else None
        horilla_pushed = (
            isinstance(ai, dict) and ai.get("google_task_pushed_from_horilla") is True
        )
        # Legacy: titles used to be prefixed with "[Horilla] " to mark Horilla platform-originated tasks.
        legacy_prefix = raw_title.startswith("[Horilla] ")

        # Tasks pushed from this Horilla platform: only sync completion (avoid overwriting subject/body).
        if existing_task_activity and (horilla_pushed or legacy_prefix):
            horilla_status = "completed" if task_status == "completed" else "scheduled"
            try:
                _google_pull_local.active = True
                try:
                    updated = Activity.objects.filter(
                        google_event_id=google_task_id,
                    ).update(status=horilla_status)
                finally:
                    _google_pull_local.active = False
                if not updated:
                    logger.debug(
                        "Google task %s marked Horilla platform-owned but no matching Activity row",
                        google_task_id,
                    )
            except Exception as exc:
                logger.error(
                    "Failed to sync status from Google task %s for user %s: %s",
                    google_task_id,
                    config.user,
                    exc,
                )
            continue

        subject = _strip_legacy_task_prefix(raw_title)[:100]
        due_dt = _parse_google_task_due(gtask.get("due"))
        description = gtask.get("notes") or ""

        defaults = {
            "subject": subject,
            "description": description,
            "activity_type": "task",
            "status": ("completed" if task_status == "completed" else "scheduled"),
            "owner": config.user,
            "company": config.user.company,
        }
        if due_dt:
            defaults["due_datetime"] = due_dt
            defaults["start_datetime"] = due_dt
            defaults["end_datetime"] = due_dt

        try:
            _google_pull_local.active = True
            try:
                activity, _ = Activity.objects.update_or_create(
                    google_event_id=google_task_id,
                    defaults=defaults,
                )
            finally:
                _google_pull_local.active = False
            activity._from_google = True
        except Exception as exc:
            logger.error(
                "Failed to upsert Google task %s for user %s: %s",
                google_task_id,
                config.user,
                exc,
            )

    config.last_synced_at = timezone.now()
    config.save(update_fields=["google_sync_token", "last_synced_at"])


# Alias for backward compatibility
