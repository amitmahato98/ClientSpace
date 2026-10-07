"""
payments/forms.py
─────────────────
Forms for the Payment Request workflow.

Phase 4 changes
───────────────
PaymentRequestForm now accepts an optional `max_amount` kwarg (Decimal).
When provided, clean_amount() enforces:

    0 < amount <= max_amount

This is the server-side enforcement of the over-request guard.
`max_amount` is always computed server-side in the view from the DB —
it is never read from the form POST data.

The form also accepts an optional `initial_amount` kwarg so the view
can pre-populate the amount field with the current available balance.
"""

from decimal import Decimal

from django import forms

from .models import PaymentRequest


_WIDGET_CLASS = (
    "w-full px-3 py-2 text-sm rounded-lg border border-[#e8dccc] "
    "focus:outline-none focus:border-[#d4a373] bg-white"
)


class PaymentRequestForm(forms.ModelForm):
    """
    Used by Managers to create a new PaymentRequest for a project.

    The `project` and `client` fields are set server-side from the URL
    and project data — they are excluded from the form so they cannot
    be tampered with via POST.

    Parameters (passed as kwargs to __init__)
    ─────────────────────────────────────────
    max_amount    — Decimal; if provided, amount must be <= this value.
                    Derived server-side from the available project balance.
                    Never read from POST data.
    initial_amount — Decimal; pre-fills the amount field (the default
                     shown to the manager is the full available balance).
    """

    class Meta:
        model  = PaymentRequest
        fields = ["title", "description", "amount", "due_date"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class":       _WIDGET_CLASS,
                "placeholder": 'e.g. "Milestone 1 — Design", "Final Payment"',
            }),
            "description": forms.Textarea(attrs={
                "class":   _WIDGET_CLASS + " resize-none",
                "rows":    3,
                "placeholder": "Optional: describe what this payment covers…",
            }),
            "amount": forms.NumberInput(attrs={
                "class":       _WIDGET_CLASS,
                "placeholder": "0.00",
                "step":        "0.01",
                "min":         "0.01",
            }),
            "due_date": forms.DateInput(attrs={
                "class": _WIDGET_CLASS,
                "type":  "date",
            }),
        }
        labels = {
            "title":       "Payment Title",
            "description": "Description (optional)",
            "amount":      "Amount (NPR)",
            "due_date":    "Due Date (optional)",
        }

    def __init__(self, *args, max_amount: Decimal = None, initial_amount: Decimal = None, **kwargs):
        super().__init__(*args, **kwargs)
        # Store max_amount for use in clean_amount().
        # Deliberately NOT placed in the form's field or widget so it
        # cannot be extracted from or influenced by the rendered HTML.
        self._max_amount = max_amount

        # Pre-populate the amount field with the available balance so
        # managers see the right default without having to calculate it.
        if initial_amount is not None and not self.data:
            # Only set the initial when the form is unbound (GET).
            # When bound (POST), leave `data` as-is.
            self.initial["amount"] = initial_amount

        # Attach max to the widget's HTML `max` attribute for UX only —
        # the real enforcement is in clean_amount().
        if max_amount is not None:
            self.fields["amount"].widget.attrs["max"] = str(max_amount)

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is None:
            return amount

        if amount <= Decimal("0.00"):
            raise forms.ValidationError("Amount must be greater than zero.")

        if self._max_amount is not None:
            if amount > self._max_amount:
                raise forms.ValidationError(
                    f"Amount cannot exceed the available project balance of "
                    f"NPR {self._max_amount:,.2f}. "
                    f"You entered NPR {amount:,.2f}."
                )

        return amount


class PaymentStatusForm(forms.Form):
    """
    Minimal form used by Managers to update the status of a PaymentRequest.
    """
    STATUS_CHOICES = [
        (PaymentRequest.Status.PAID,      "Mark as Paid"),
        (PaymentRequest.Status.OVERDUE,   "Mark as Overdue"),
        (PaymentRequest.Status.CANCELLED, "Mark as Cancelled"),
        (PaymentRequest.Status.PENDING,   "Reset to Pending"),
    ]
    status = forms.ChoiceField(choices=STATUS_CHOICES)
