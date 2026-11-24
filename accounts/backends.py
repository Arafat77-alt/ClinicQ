"""Login rules that let staff use their email address (AUTH-06)."""

from django.contrib.auth.backends import ModelBackend

from .models import User
from .services import find_account


class EmailOrUsernameBackend(ModelBackend):
    """Check a password for an email address or a username.

    A deactivated account is never allowed to stay logged in (AUTH-05). The
    login form shows a clear "deactivated" message before this check runs.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """Return the account when the identifier and password are correct."""
        if username is None or password is None:
            return None
        account = find_account(username)
        if account is None:
            # Hash anyway, so that unknown names take as long as known ones.
            User().set_password(password)
            return None
        if account.check_password(password):
            return account
        return None

    def user_can_authenticate(self, user):
        """Let deactivated accounts reach the form, which explains the problem."""
        return True

    def get_user(self, user_id):
        """Drop the session of an account that was deactivated while logged in."""
        user = super().get_user(user_id)
        if user is not None and not user.is_active:
            return None
        return user
