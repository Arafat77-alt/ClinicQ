"""Middleware for the accounts application."""

from django.shortcuts import redirect
from django.urls import reverse


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