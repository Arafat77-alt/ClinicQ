"""Forms for the accounts application."""

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from .services import (
    STAFF_ROLES,
    find_account,
    is_locked,
    lock_message,
    record_failed_login,
    record_successful_login,
)


class ClinicLoginForm(AuthenticationForm):
    """Login form with a lock after 5 wrong passwords and plain messages (AUTH-06)."""

    error_messages = {
        "invalid_login": (
            "The email or password is not correct. "
            "Check both and try again. Passwords are case sensitive."
        ),
        "inactive": (
            "This account has been deactivated. "
            "Please contact the clinic administrator."
        ),
    }

    def __init__(self, *args, **kwargs):
        """Label the first field as an email address."""
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email"

    def clean(self):
        """Check the lock, then the password, and count wrong passwords (SEC-04)."""
        identifier = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if identifier is not None and password:
            account = find_account(identifier)
            if account is not None and is_locked(account):
                raise ValidationError(lock_message(account), code="locked")
            self.user_cache = authenticate(self.request, username=identifier, password=password)
            if self.user_cache is None:
                if account is not None:
                    record_failed_login(account)
                    if is_locked(account):
                        raise ValidationError(lock_message(account), code="locked")
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)
            record_successful_login(self.user_cache)
        return self.cleaned_data


class StaffAccountForm(forms.Form):
    """Details the administrator enters to create a staff account (AUTH-05)."""

    username = forms.CharField(max_length=150)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(help_text="The person logs in with this email address.")
    role = forms.ChoiceField(choices=[(role.value, role.label) for role in STAFF_ROLES])
    temporary_password = forms.CharField(
        widget=forms.PasswordInput,
        help_text="The person must replace this password the first time they log in.",
    )


class PatientRegistrationRequestForm(forms.Form):
    """Step 1 of patient registration: enter name, mobile number, and DOB (AUTH-01)."""

    full_name = forms.CharField(
        max_length=150,
        label="Full name",
    )
    mobile_number = forms.CharField(
        max_length=17,
        label="Mobile number",
        help_text="Enter your Bangladeshi mobile number, for example +8801712345678.",
    )
    date_of_birth = forms.DateField(
        required=False,
        label="Date of birth (optional)",
        widget=forms.DateInput(attrs={"type": "date"}),
    )


class PatientLoginRequestForm(forms.Form):
    """Step 1 of patient login: enter registered mobile number to receive OTP (AUTH-02)."""

    mobile_number = forms.CharField(
        max_length=17,
        label="Mobile number",
        help_text="Enter your registered mobile number, for example +8801712345678.",
    )


class OtpVerificationForm(forms.Form):
    """Step 2 of patient registration or login: enter the 6-digit SMS code (AUTH-01, AUTH-02)."""

    code = forms.CharField(
        max_length=10,
        min_length=6,
        label="6-digit verification code",
        help_text="Enter the 6-digit code sent to your mobile number. It expires in 5 minutes.",
    )