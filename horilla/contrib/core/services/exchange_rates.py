"""Refresh a company's currency rates from the exchange rate APIs."""

import logging
from decimal import Decimal

from horilla.auth.models import User
from horilla.utils import timezone
from horilla.utils.translation import gettext as _

from ..models import DatedConversionRate, MultipleCurrency
from ..utils import fetch_exchange_rates_bulk_with_source

logger = logging.getLogger(__name__)


def _alert_admins(company, changes, threshold):
    """Notify company admins about rates that moved more than the threshold."""
    from horilla.contrib.notifications.methods import create_notification

    lines = ", ".join(
        f"{code}: {old} → {new} ({pct:+.1f}%)" for code, old, new, pct in changes
    )
    message = _("Exchange rate moved by more than %(t)s%%: %(lines)s") % {
        "t": threshold,
        "lines": lines,
    }
    for user in User.objects.filter(company=company, is_active=True):
        if user.is_superuser or user.has_perm("core.change_company"):
            create_notification(user=user, message=message)


def ensure_rate_baseline(currency):
    """
    Make sure a non-default currency has at least one dated rate, so rate history
    starts from its current rate even if the rate never changes afterwards.
    Does nothing when the company does not keep rate history.
    """
    company = currency.company
    if (
        not company
        or not company.keep_rate_history
        or currency.is_default
        or currency.conversion_rate is None
    ):
        return False
    if DatedConversionRate.all_objects.filter(currency=currency).exists():
        return False
    DatedConversionRate.all_objects.create(
        company=company,
        currency=currency,
        start_date=timezone.now().date(),
        conversion_rate=currency.conversion_rate,
        source=DatedConversionRate.SOURCE_AUTO,
    )
    return True


def refresh_company_rates(company):
    """
    Fetch fresh rates for every non-default currency of ``company`` and save
    them (each save goes through the model, so rate history is recorded).

    Returns (updated_count, source_name or None).
    """
    default = MultipleCurrency.all_objects.filter(
        company=company, is_default=True
    ).first()
    if not default:
        return 0, None
    others = list(
        MultipleCurrency.all_objects.filter(company=company, is_default=False)
    )
    if not others:
        return 0, None

    rates, source = fetch_exchange_rates_bulk_with_source(
        default.currency,
        [c.currency for c in others],
        company.exchange_rate_source,
    )
    if not rates:
        return 0, None

    threshold = company.rate_change_alert_percent or 0
    updated = 0
    big_changes = []
    for curr in others:
        new_rate = rates.get(curr.currency)
        if new_rate is None:
            continue
        if new_rate == curr.conversion_rate:
            ensure_rate_baseline(curr)  # unchanged, but history should still start
            continue
        old_rate = curr.conversion_rate
        curr.conversion_rate = new_rate
        curr.save()
        updated += 1
        if threshold and old_rate:
            pct = (new_rate - old_rate) / old_rate * Decimal("100")
            if abs(pct) > threshold:
                big_changes.append((curr.currency, old_rate, new_rate, float(pct)))

    company.rates_last_refreshed = timezone.now()
    company.save(update_fields=["rates_last_refreshed"])
    if big_changes:
        _alert_admins(company, big_changes, threshold)
    return updated, source
