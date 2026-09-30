"""
accounts/context_processors.py
───────────────────────────────
Injects NPR currency constants into every template.

ClientSpace is NPR-only.  These context variables are provided so templates
can reference the currency code and label without hard-coding strings.

Variables injected into every template
───────────────────────────────────────
  active_currency        — always "NPR"
  active_currency_label  — always "NPR — Nepalese Rupee"

Registered in ClientSpace/settings.py under
TEMPLATES[0]["OPTIONS"]["context_processors"].
"""

from accounts.currency import CURRENCY_CODE, CURRENCY_LABEL


def workspace_currency(request):
    """
    Inject NPR currency constants into every template context.

    ClientSpace does not support multiple currencies.  All monetary values
    are NPR.  This processor exists so templates can reference
    {{ active_currency }} consistently rather than hard-coding the string.
    """
    return {
        "active_currency":       CURRENCY_CODE,   # "NPR"
        "active_currency_label": CURRENCY_LABEL,  # "NPR — Nepalese Rupee"
    }
