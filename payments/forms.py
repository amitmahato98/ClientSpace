"""
payments/forms.py
─────────────────
Forms for the Payment Request workflow.
"""

from django import forms

from .models import PaymentRequest


class PaymentRequestForm(forms.ModelForm):
    """
    Used by Managers to create a new PaymentRequest for a project.

    The `project` and `client` fields are set server-side from the URL
    and project data — they are excluded from the form so they cannot
    be tampered with via POST.
    """

    class Meta:
        model = PaymentRequest
        fields = ["title", "description", "amount", "due_date"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": (
                    "w-full px-3 py-2 text-sm rounded-lg border border-[#e8dccc] "
                    "focus:outline-none focus:border-[#d4a373] bg-white"
                ),
                "placeholder": 'e.g. "Initial Payment", "Milestone 1 — Design"',
            }),
            "description": forms.Textarea(attrs={
                "class": (
                    "w-full px-3 py-2 text-sm rounded-lg border border-[#e8dccc] "
                    "focus:outline-none focus:border-[#d4a373] bg-white resize-none"
                ),
                "rows": 3,
                "placeholder": "Optional: describe what this payment covers…",
            }),
            "amount": forms.NumberInput(attrs={
                "class": (
                    "w-full px-3 py-2 text-sm rounded-lg border border-[#e8dccc] "
                    "focus:outline-none focus:border-[#d4a373] bg-white"
                ),
                "placeholder": "0.00",
                "step": "0.01",
                "min": "0.01",
            }),
            "due_date": forms.DateInput(attrs={
                "class": (
                    "w-full px-3 py-2 text-sm rounded-lg border border-[#e8dccc] "
                    "focus:outline-none focus:border-[#d4a373] bg-white"
                ),
                "type": "date",
            }),
        }
        labels = {
            "title": "Payment Title",
            "description": "Description (optional)",
            "amount": "Amount (NPR)",
            "due_date": "Due Date (optional)",
        }

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is not None and amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount


class PaymentStatusForm(forms.Form):
    """
    Minimal form used by Managers to update the status of a PaymentRequest.
    Only PAID, OVERDUE, and CANCELLED are valid transitions from the UI.
    """
    STATUS_CHOICES = [
        (PaymentRequest.Status.PAID,      "Mark as Paid"),
        (PaymentRequest.Status.OVERDUE,   "Mark as Overdue"),
        (PaymentRequest.Status.CANCELLED, "Mark as Cancelled"),
        (PaymentRequest.Status.PENDING,   "Reset to Pending"),
    ]
    status = forms.ChoiceField(choices=STATUS_CHOICES)
