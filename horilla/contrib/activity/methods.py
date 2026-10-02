"""
Helper methods for Activity modules
"""


def is_related_record_visible(related):
    """
    Return True if ``related`` is in its model's default (company-filtered)
    queryset, i.e. its own detail page and Details tab would find it.
    """
    return related.__class__._default_manager.filter(pk=related.pk).exists()


def get_related_record_url(related, user):
    """Return the related record's detail URL if the user may open it, else ""."""
    return get_related_record_urls({None: related}, user)[None]


def get_related_record_urls(records, user):
    """
    Batch form of get_related_record_url() for views that link many records at
    once, such as the calendar's event feed.

    ``records`` maps any key to a related record. Returns the same keys mapped
    to what get_related_record_url() returns for each record. The queries run
    per related model, not per record: the owner fields check_record_access()
    reads are prefetched, and visibility is one ``pk__in`` query on the
    model's default (company-filtered) manager.
    """
    from horilla.contrib.generics.views.details import check_record_access
    from horilla.contrib.utils.methods import get_section_info_for_model

    urls = dict.fromkeys(records, "")
    if not user or not user.is_authenticated:
        return urls
    records_by_model = {}
    for key, related in records.items():
        if callable(getattr(related, "get_detail_url", None)):
            records_by_model.setdefault(related.__class__, {})[key] = related
    for model, model_records in records_by_model.items():
        _prefetch_owner_fields(model, list(model_records.values()), user)
        allowed = {
            key: related
            for key, related in model_records.items()
            if check_record_access(user, related)
        }
        if not allowed:
            continue
        visible_pks = set(
            model._default_manager.filter(
                pk__in={related.pk for related in allowed.values()}
            ).values_list("pk", flat=True)
        )
        # Open the record's own module in the side menu, like detail breadcrumbs do.
        section = get_section_info_for_model(model).get("section")
        for key, related in allowed.items():
            if related.pk not in visible_pks:
                continue
            url = str(related.get_detail_url())
            if section:
                url = f"{url}{'&' if '?' in url else '?'}section={section}"
            urls[key] = url
    return urls


def _prefetch_owner_fields(model, records, user):
    """
    Prefetch the OWNER_FIELDS relations of ``records`` when check_record_access()
    will read them, i.e. for a user who may only view their own records of
    ``model``. Otherwise each record loads its owner with a query of its own.
    """
    from horilla.core.exceptions import FieldDoesNotExist
    from horilla.db.models import prefetch_related_objects

    app_label, model_name = model._meta.app_label, model._meta.model_name
    if user.is_superuser or user.has_perm(f"{app_label}.view_{model_name}"):
        return
    if not user.has_perm(f"{app_label}.view_own_{model_name}"):
        return
    relations = []
    for field_name in getattr(model, "OWNER_FIELDS", []):
        try:
            if model._meta.get_field(field_name).is_relation:
                relations.append(field_name)
        except FieldDoesNotExist:
            continue
    prefetch_related_objects(records, *relations)


def get_related_record_detail_url_name(related):
    """
    Return the ``detail_url_name`` the related record's own detail page passes
    to its Details tab (e.g. ``leads_detail``), so the Related To tab shows the
    same saved field selection. Returns "" when it can't be resolved.
    """
    from horilla.urls import resolve

    get_detail_url = getattr(related, "get_detail_url", None)
    if not callable(get_detail_url):
        return ""
    try:
        resolved = resolve(str(get_detail_url()))
    except Exception:
        return ""
    url_name = resolved.url_name or ""
    view_class = getattr(resolved.func, "view_class", None)
    get_scope = getattr(view_class, "get_detail_field_visibility_scope", None)
    if url_name and callable(get_scope):
        try:
            scope = view_class().get_detail_field_visibility_scope(related)
        except Exception:
            scope = ""
        if scope:
            url_name = f"{url_name}:{scope}"
    return url_name
