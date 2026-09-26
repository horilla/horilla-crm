"""
Helper methods for Activity modules
"""


def get_related_record_url(related, user):
    """Return the related record's detail URL if the user may open it, else ""."""
    from horilla.contrib.generics.views.details import check_record_access

    get_detail_url = getattr(related, "get_detail_url", None)
    if not callable(get_detail_url) or not user or not user.is_authenticated:
        return ""
    if not check_record_access(user, related):
        return ""
    return str(get_detail_url())


def get_related_record_context(activity, user):
    """Summarise the record an activity is related to (e.g. a Lead), or None."""
    related = activity.related_object
    if related is None:
        return None
    return {
        "type_label": related._meta.verbose_name,
        "name": str(related),
        "detail_url": get_related_record_url(related, user),
    }
