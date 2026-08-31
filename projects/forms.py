from django import forms

from .models import Project


class ProjectForm(forms.ModelForm):
    """
    ModelForm for creating (and later editing) a Project.

    Fields exposed to the manager:
        name, description, client, status, priority,
        budget, start_date, deadline

    Fields intentionally excluded (set server-side):
        created_by, created_at, updated_at
    """

    class Meta:
        model = Project
        fields = [
            "name",
            "description",
            "client",
            "status",
            "priority",
            "budget",
            "start_date",
            "deadline",
        ]
        widgets = {
            "name": forms.TextInput(attrs={
                "placeholder": "e.g. Website redesign",
                "class": (
                    "w-full px-3.5 py-2.5 text-sm rounded-lg border border-gray-200 "
                    "bg-white focus:outline-none focus:ring-2 focus:ring-[#d4a373]/30 "
                    "focus:border-[#d4a373] transition"
                ),
            }),
            "description": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Anything the team should know...",
                "class": (
                    "w-full px-3.5 py-2.5 text-sm rounded-lg border border-gray-200 "
                    "bg-white focus:outline-none focus:ring-2 focus:ring-[#d4a373]/30 "
                    "focus:border-[#d4a373] transition resize-none"
                ),
            }),
            "client": forms.Select(attrs={
                "class": (
                    "w-full px-3.5 py-2.5 text-sm rounded-lg border border-gray-200 "
                    "bg-white focus:outline-none focus:ring-2 focus:ring-[#d4a373]/30 "
                    "focus:border-[#d4a373] transition"
                ),
            }),
            "status": forms.Select(attrs={
                "class": (
                    "w-full px-3.5 py-2.5 text-sm rounded-lg border border-gray-200 "
                    "bg-white focus:outline-none focus:ring-2 focus:ring-[#d4a373]/30 "
                    "focus:border-[#d4a373] transition"
                ),
            }),
            "priority": forms.Select(attrs={
                "class": (
                    "w-full px-3.5 py-2.5 text-sm rounded-lg border border-gray-200 "
                    "bg-white focus:outline-none focus:ring-2 focus:ring-[#d4a373]/30 "
                    "focus:border-[#d4a373] transition"
                ),
            }),
            "budget": forms.NumberInput(attrs={
                "min": "0",
                "step": "0.01",
                "placeholder": "0.00",
                "class": (
                    "w-full px-3.5 py-2.5 text-sm rounded-lg border border-gray-200 "
                    "bg-white focus:outline-none focus:ring-2 focus:ring-[#d4a373]/30 "
                    "focus:border-[#d4a373] transition"
                ),
            }),
            "start_date": forms.DateInput(attrs={
                "type": "date",
                "class": (
                    "w-full px-3.5 py-2.5 text-sm rounded-lg border border-gray-200 "
                    "bg-white focus:outline-none focus:ring-2 focus:ring-[#d4a373]/30 "
                    "focus:border-[#d4a373] transition"
                ),
            }),
            "deadline": forms.DateInput(attrs={
                "type": "date",
                "class": (
                    "w-full px-3.5 py-2.5 text-sm rounded-lg border border-gray-200 "
                    "bg-white focus:outline-none focus:ring-2 focus:ring-[#d4a373]/30 "
                    "focus:border-[#d4a373] transition"
                ),
            }),
        }
        labels = {
            "name":        "Project name",
            "description": "Description (optional)",
            "client":      "Client",
            "status":      "Status",
            "priority":    "Priority",
            "budget":      "Budget ($)",
            "start_date":  "Start date",
            "deadline":    "Deadline",
        }
