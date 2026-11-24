"""Adjustments applied to the lead demo data while it is loaded."""

from horilla.apps import apps


def prepare_demo_rows(rows):
    """
    Load a converted lead as an ordinary open lead when its contact or
    opportunity was not loaded.

    A converted lead points at the contact and the opportunity created from it.
    Their record counts are chosen separately from the leads', so one of them
    may be missing; the loader then clears the link, and the lead must not keep
    showing as converted without it.
    """
    lead_status = apps.get_model("leads", "LeadStatus")
    first_status = {}
    for item in rows:
        if item.get("model") != "leads.lead":
            continue
        fields = item["fields"]
        if not fields.get("is_convert"):
            continue
        if fields.get("converted_contact") and fields.get("converted_opportunity"):
            continue
        company = fields.get("company")
        if company not in first_status:
            status = (
                lead_status.objects.filter(company_id=company, is_final=False)
                .order_by("order")
                .first()
            )
            first_status[company] = status.pk if status else fields.get("lead_status")
        fields.update(
            is_convert=False,
            converted_contact=None,
            converted_opportunity=None,
            converted_at=None,
            lead_status=first_status[company],
        )
