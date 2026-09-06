from django import forms
from staff.models import Staff,StaffAssignment
from accounts.models import User


class Add_staffForm(forms.ModelForm):

    class Meta:
        model = Staff
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
        ]

    def clean_email(self):
        email = self.cleaned_data["email"]

        if Staff.objects.filter(email=email).exists():
            raise forms.ValidationError(
                "A staff member with this email already exists."
            )

        return email



class StaffSetupForm(forms.Form):

    username = forms.CharField(
        max_length=150,
        required=True,
        label="Username"
    )

    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput,
        label="Password"
    )

    confirm_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput,
        label="Confirm Password"
    )

    role = forms.ChoiceField(
        choices=Staff.ROLE_CHOICES,
        required=True,
        label="Job Role"
    )

    def clean_username(self):
        username = self.cleaned_data["username"]

        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(
                "This username is already taken."
            )

        return username

    def clean(self):
        cleaned_data = super().clean()

        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password:
            if password != confirm_password:
                raise forms.ValidationError(
                    "Passwords do not match."
                )

        return cleaned_data


class StaffAssignmentForm(forms.ModelForm):

    class Meta:
        model = StaffAssignment
        fields = [
            "staff",
            "project",
            "work",
        ]

        widgets = {
            "work": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Describe the work to be completed..."
                }
            ),
        }