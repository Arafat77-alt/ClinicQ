"""Middleware for the accounts application."""

import time

from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

from .models import User
from .services.patient_auth import (
    PATIENT_SESSION_TIMEOUT_SECONDS,
    STAFF_SESSION_TIMEOUT_SECONDS,
)

LAST_ACTIVITY_SESSION_KEY = "clinicq_last_activity_ts"


class ForcePasswordChangeMiddleware:
    """Send people to the password page until they replace a temporary password.

    Implements the first AUTH-05 confirmation: a new staff member must set a
    new password at first login.
    """

    def __init__(self, get_response):
        """Remember the next step in the request chain."""
        self.get_response = get_response

    def __call__(self, request):
        """Redirect people who still have a temporary password."""
        user = request.user
        if user.is_authenticated and user.must_change_password:
            allowed = {reverse("accounts:password_change"), reverse("accounts:logout")}
            if request.path not in allowed and not request.path.startswith("/static/"):
                return redirect("accounts:password_change")
        return self.get_response(request)


class SessionInactivityTimeoutMiddleware:
    """Log out inactive users after 30 minutes (patients) or 15 minutes (staff).

    Implements AUTH-02 (criterion 2: 30-minute patient inactivity timeout) and
    SEC-05 (30 minutes for patients, 15 minutes for staff).
    """

    def __init__(self, get_response):
        """Remember the next step in the request chain."""
        self.get_response = get_response

    def __call__(self, request):
        """Check elapsed time since the user's previous request."""
        if request.user.is_authenticated:
            now_ts = time.time()
            last_ts = request.session.get(LAST_ACTIVITY_SESSION_KEY)
            timeout = (
                PATIENT_SESSION_TIMEOUT_SECONDS
                if request.user.role == User.Role.PATIENT
                else STAFF_SESSION_TIMEOUT_SECONDS
            )
            if last_ts is not None and (now_ts - float(last_ts)) > timeout:
                was_patient = request.user.role == User.Role.PATIENT
                logout(request)
                messages.info(
                    request,
                    "You were logged out after a period of inactivity. Please log in again.",
                )
                target = "accounts:patient_login" if was_patient else "accounts:login"
                return redirect(target)
            request.session[LAST_ACTIVITY_SESSION_KEY] = now_ts
        return self.get_response(request)