"""Role checks that run on the server for every request (SEC-01)."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


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