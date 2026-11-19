"""Role checks that run on the server for every request (SEC-01)."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse_lazy

from .models import User


def role_required(*roles):
    """Allow a page only for people with one of the given roles.

    Args:
        *roles: The roles that may open the page, for example User.Role.ADMIN.

    Returns:
        A decorator. Anonymous visitors are sent to the login page. People
        with another role see a plain-language "not allowed" page (403).
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.user.role not in roles:
                return render(request, "accounts/forbidden.html", status=403)
            return view(request, *args, **kwargs)

        return login_required(wrapper)

    return decorator


def patient_required(view):
    """Allow a page only for logged-in patients (AUTH-02, SEC-01).

    Anonymous visitors are sent to the patient OTP login page; staff accounts
    receive a plain-language 403 page.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.user.role != User.Role.PATIENT or not hasattr(request.user, "patient"):
            return render(request, "accounts/forbidden.html", status=403)
        return view(request, *args, **kwargs)

    return login_required(wrapper, login_url=reverse_lazy("accounts:patient_login"))