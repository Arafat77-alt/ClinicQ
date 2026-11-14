"""Forms for the accounts application."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .services import STAFF_ROLES


class ClinicLoginForm(AuthenticationForm):
    """Login form with plain-language error messages (USAB-06)."""

    error_messages = {
        "invalid_login": (
            "The username or password is not correct. "
            "Check both and try again. Passwords are case sensitive."
        ),
        "inactive": (
            "This account has been deactivated. "
            "Please contact the clinic administrator."
        ),
    }


class StaffAccountForm(forms.Form):
    """Details the administrator enters to create a staff account (AUTH-05)."""

    username = forms.CharField(max_length=150)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField()
    role = forms.ChoiceField(choices=[(role.value, role.label) for role in STAFF_ROLES])
    temporary_password = forms.CharField(
        widget=forms.PasswordInput,
        help_text="The person must replace this password the first time they log in.",
    )