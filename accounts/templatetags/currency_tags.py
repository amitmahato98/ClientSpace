"""
accounts/templatetags/currency_tags.py
───────────────────────────────────────
Django template tags and filters for NPR currency formatting.

ClientSpace is NPR-only.  All monetary values are Nepalese Rupees.

Usage in templates
──────────────────
    {% load currency_tags %}

    {# Format an amount as NPR #}
    {{ project.budget|npr }}
    → "NPR 10,000.00"

    {# Format an amount as NPR (alias, accepts optional arg which is ignored) #}
    {{ project.budget|currency:active_currency }}
    → "NPR 10,000.00"

    {# Just the formatted number without the code #}
    {{ project.budget|currency_number }}
    → "10,000.00"
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template

register = template.Library()


def _to_decimal(amount):
    """Convert amount to a Decimal rounded to 2 decimal places."""
    return Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@register.filter(name="npr")
def npr_filter(amount):
    """
    Format `amount` as an NPR monetary string.

    Usage:
        {{ project.budget|npr }}   → "NPR 10,000.00"
        {{ pay.amount|npr }}       → "NPR 500.00"

    Falls back to "NPR 0.00" on any error.
    """
    try:
        value = _to_decimal(amount)
        return f"NPR {value:,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return "NPR 0.00"


@register.filter(name="currency")
def currency_filter(amount, currency_code=None):
    """
    Format `amount` as an NPR monetary string.

    The `currency_code` argument is accepted for backward compatibility with
    templates that pass `active_currency`, but it is always ignored — the
    result is always NPR because ClientSpace is NPR-only.

    Usage:
        {{ project.budget|currency:active_currency }}   → "NPR 10,000.00"
        {{ pay.amount|currency:"NPR" }}                 → "NPR 500.00"

    Falls back to "NPR 0.00" on any error.
    """
    try:
        value = _to_decimal(amount)
        return f"NPR {value:,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return "NPR 0.00"


@register.filter(name="currency_number")
def currency_number_filter(amount):
    """
    Format `amount` as a number string with thousands separator and 2 decimals.
    No currency prefix is included.

    Usage:
        {{ project.budget|currency_number }}   → "10,000.00"
    """
    try:
        value = _to_decimal(amount)
        return f"{value:,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return "0.00"
