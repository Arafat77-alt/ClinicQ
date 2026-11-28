"""Pages for the accounts application."""

import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    LoginView,
    PasswordChangeView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from .forms import (
    ClinicLoginForm,
    OtpVerificationForm,
    PatientLoginRequestForm,
    PatientRegistrationRequestForm,
    StaffAccountForm,
)
from .middleware import LAST_ACTIVITY_SESSION_KEY
from .models import User
from .patients import normalize_mobile_number
from .permissions import role_required
from .services import STAFF_ROLES, create_staff_account, deactivate_staff_account
from .services.patient_auth import (
    complete_registration_with_otp,
    request_login_otp,
    request_registration_otp,
    verify_login_otp,
)

PENDING_REG_SESSION_KEY = "clinicq_pending_registration"
PENDING_LOGIN_SESSION_KEY = "clinicq_pending_patient_login"


def _sign_in_patient(request, user):
    """Attach the authenticated patient user to the session (AUTH-01, AUTH-02)."""
    login(request, user, backend="accounts.backends.EmailOrUsernameBackend")
    request.session[LAST_ACTIVITY_SESSION_KEY] = time.time()


class ClinicLoginView(LoginView):
    """Show the staff login page (AUTH-06)."""

    template_name = "accounts/login.html"
    authentication_form = ClinicLoginForm
    redirect_authenticated_user = True


class FirstPasswordChangeView(PasswordChangeView):
    """Let a person replace a temporary password (AUTH-05)."""

    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:home")

    def form_valid(self, form):
        """Save the new password and remember that it is no longer temporary."""
        response = super().form_valid(form)
        self.request.user.must_change_password = False
        self.request.user.save(update_fields=["must_change_password"])
        return response


class ClinicPasswordResetView(PasswordResetView):
    """Ask for an email address and send a reset link (AUTH-06)."""

    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class ClinicPasswordResetDoneView(PasswordResetDoneView):
    """Tell the person to check their email (AUTH-06)."""

    template_name = "accounts/password_reset_done.html"


class ClinicPasswordResetConfirmView(PasswordResetConfirmView):
    """Let the person choose a new password from the emailed link (AUTH-06).

    The link works once and for 30 minutes (PASSWORD_RESET_TIMEOUT in the
    settings). Choosing a new password also removes any lock.
    """

    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        """Save the new password, and clear the lock and the temporary flag."""
        response = super().form_valid(form)
        user = self.user
        user.must_change_password = False
        user.failed_login_count = 0
        user.locked_until = None
        user.save(update_fields=["must_change_password", "failed_login_count", "locked_until"])
        return response


class ClinicPasswordResetCompleteView(PasswordResetCompleteView):
    """Confirm that the password was changed (AUTH-06)."""

    template_name = "accounts/password_reset_complete.html"


def patient_register(request):
    """Step 1 of patient self-registration: collect details and send OTP (AUTH-01)."""
    if request.user.is_authenticated:
        return redirect("accounts:home")

    form = PatientRegistrationRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            challenge = request_registration_otp(data["mobile_number"])
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        else:
            dob = data["date_of_birth"]
            request.session[PENDING_REG_SESSION_KEY] = {
                "full_name": data["full_name"].strip(),
                "mobile_number": challenge.mobile_number,
                "date_of_birth": dob.isoformat() if dob else None,
            }
            if settings.DEBUG:
                request.session["demo_otp"] = challenge.code
            messages.success(
                request,
                f"We sent a 6-digit verification code to {challenge.mobile_number}.",
            )
            return redirect("accounts:patient_register_verify")

    return render(request, "accounts/patient_register.html", {"form": form})


def patient_register_verify(request):
    """Step 2 of patient self-registration: verify OTP and log in (AUTH-01)."""
    if request.user.is_authenticated:
        return redirect("accounts:home")

    pending = request.session.get(PENDING_REG_SESSION_KEY)
    if not pending:
        messages.info(request, "Please enter your details first to receive a code.")
        return redirect("accounts:patient_register")

    form = OtpVerificationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        from datetime import date

        dob_raw = pending.get("date_of_birth")
        dob = date.fromisoformat(dob_raw) if dob_raw else None
        try:
            user = complete_registration_with_otp(
                full_name=pending["full_name"],
                mobile_number=pending["mobile_number"],
                entered_code=form.cleaned_data["code"],
                date_of_birth=dob,
            )
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        else:
            request.session.pop(PENDING_REG_SESSION_KEY, None)
            request.session.pop("demo_otp", None)
            _sign_in_patient(request, user)
            messages.success(request, "Your patient account is ready and you are logged in.")
            return redirect("accounts:home")

    return render(
        request,
        "accounts/patient_register_verify.html",
        {"form": form, "mobile_number": pending["mobile_number"]},
    )


def patient_login(request):
    """Step 1 of patient login: ask for mobile number and send OTP (AUTH-02)."""
    if request.user.is_authenticated:
        return redirect("accounts:home")

    form = PatientLoginRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        raw_number = form.cleaned_data["mobile_number"]
        try:
            challenge = request_login_otp(raw_number)
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        else:
            request.session[PENDING_LOGIN_SESSION_KEY] = normalize_mobile_number(
                challenge.mobile_number
            )
            if settings.DEBUG:
                request.session["demo_otp"] = challenge.code
            messages.success(
                request,
                f"We sent a 6-digit login code to {challenge.mobile_number}.",
            )
            return redirect("accounts:patient_login_verify")

    return render(request, "accounts/patient_login.html", {"form": form})


def patient_login_verify(request):
    """Step 2 of patient login: verify OTP and open the patient dashboard (AUTH-02)."""
    if request.user.is_authenticated:
        return redirect("accounts:home")

    mobile_number = request.session.get(PENDING_LOGIN_SESSION_KEY)
    if not mobile_number:
        messages.info(request, "Enter your mobile number first to receive a login code.")
        return redirect("accounts:patient_login")

    form = OtpVerificationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = verify_login_otp(
                mobile_number=mobile_number,
                entered_code=form.cleaned_data["code"],
            )
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        else:
            request.session.pop(PENDING_LOGIN_SESSION_KEY, None)
            request.session.pop("demo_otp", None)
            _sign_in_patient(request, user)
            messages.success(request, "You are now logged in.")
            return redirect("accounts:home")

    return render(
        request,
        "accounts/patient_login_verify.html",
        {"form": form, "mobile_number": mobile_number},
    )


@login_required
def home(request):
    """Show a simple start page that depends on the person's role."""
    return render(request, "accounts/home.html")


@role_required(User.Role.ADMIN)
def staff_list(request):
    """List staff accounts for the clinic administrator (AUTH-05)."""
    staff = User.objects.filter(role__in=STAFF_ROLES).order_by("username")
    return render(request, "accounts/staff_list.html", {"staff": staff})


@role_required(User.Role.ADMIN)
def staff_create(request):
    """Let the clinic administrator create a staff account (AUTH-05)."""
    form = StaffAccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            create_staff_account(
                username=data["username"],
                email=data["email"],
                role=data["role"],
                temporary_password=data["temporary_password"],
                first_name=data["first_name"],
                last_name=data["last_name"],
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(
                request,
                f"The account '{data['username']}' was created. "
                "Give the person their temporary password. "
                "They will be asked to choose a new one at first login.",
            )
            return redirect("accounts:staff_list")
    return render(request, "accounts/staff_form.html", {"form": form})


@role_required(User.Role.ADMIN)
@require_POST
def staff_deactivate(request, user_id):
    """Deactivate a staff account while keeping its records (AUTH-05)."""
    account = get_object_or_404(User, pk=user_id)
    try:
        deactivate_staff_account(account, acting_user=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(
            request,
            f"The account '{account.username}' was deactivated. "
            "The person can no longer log in, and their past records are kept.",
        )
    return redirect("accounts:staff_list")
