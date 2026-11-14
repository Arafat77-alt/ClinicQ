"""Pages for the accounts application."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from .forms import ClinicLoginForm, StaffAccountForm
from .models import User
from .permissions import role_required
from .services import STAFF_ROLES, create_staff_account, deactivate_staff_account


class ClinicLoginView(LoginView):
    """Show the login page (the full staff login is finished in AUTH-06)."""

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