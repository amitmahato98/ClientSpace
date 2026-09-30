"""
accounts/currency.py
────────────────────
Currency configuration for ClientSpace.

ClientSpace is NPR-only.
All monetary values are stored and displayed in Nepalese Rupees (NPR).

There is no multi-currency support, no exchange-rate conversion, and no
foreign-currency input.  Every amount entered by a user represents NPR.

This module is intentionally kept simple so that a future Khalti Sandbox
integration can consume NPR amounts directly without any conversion step.
"""

from decimal import Decimal, ROUND_HALF_UP


# ─────────────────────────────────────────────────────────────────────────────
# Currency constant
# ─────────────────────────────────────────────────────────────────────────────

CURRENCY_CODE  = "NPR"
CURRENCY_LABEL = "NPR — Nepalese Rupee"
CURRENCY_NAME  = "Nepalese Rupee"

# Kept as a dict so existing code that does CURRENCY_LABELS["NPR"] keeps working.
CURRENCY_LABELS = {
    "NPR": CURRENCY_LABEL,
}


# ─────────────────────────────────────────────────────────────────────────────
# Public helpers
# ─────────────────────────────────────────────────────────────────────────────

def format_amount(amount) -> str:
    """
    Return a consistently formatted NPR monetary string.

    Examples:
        format_amount(10000)    →  "NPR 10,000.00"
        format_amount(25000)    →  "NPR 25,000.00"
        format_amount(1250000)  →  "NPR 1,250,000.00"

    The "NPR" prefix always precedes the number, separated by a single space.
    Thousands separators are included.  Two decimal places are always shown.
    """
    try:
        value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return "NPR 0.00"

    formatted_number = f"{value:,.2f}"
    return f"NPR {formatted_number}"


def get_currency_label() -> str:
    """Return the human-readable label for NPR."""
    return CURRENCY_LABEL
