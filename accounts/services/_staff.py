"""Business rules for the accounts application."""

from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import User

STAFF_ROLES = [User.Role.RECEPTIONIST, User.Role.DOCTOR, User.Role.ADMIN]

# SEC-04: after 5 wrong passwords the account is locked for 15 minutes.
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15


def create_staff_account(
    username, email, role, temporary_password, first_name="", last_name=""
):
    """Create a staff account that must change its password at first login.

    Implements AUTH-05. The password rules come from SEC-02 (at least 8
    characters, stored only as a salted hash).

    Args:
        username: The login name. It must not be used by anyone else.
        email: The staff member's email address. Staff log in with it (AUTH-06),
            so it must not be used by anyone else.
        role: receptionist, doctor or admin.
        temporary_password: A first password that the person must replace.
        first_name: Optional first name.
        last_name: Optional last name.

    Returns:
        The new User.

    Raises:
        ValidationError: With a plain-language message when the role is not a
            staff role, the username or email is taken, or the password is too weak.
    """
    if role not in STAFF_ROLES:
        raise ValidationError(
            "Staff accounts can only have the receptionist, doctor or "
            "administrator role. Choose one of these roles and try again."
        )
    if User.objects.filter(username__iexact=username).exists():
        raise ValidationError(
            f"The username '{username}' is already used by another account. "
            "Choose a different username."
        )
    if email and User.objects.filter(email__iexact=email).exists():
        raise ValidationError(
            f"The email address '{email}' is already used by another account. "
            "Each person logs in with their own email address, so enter a "
            "different one."
        )
    validate_password(temporary_password)
    return User.objects.create_user(
        username=username,
        email=email,
        password=temporary_password,
        role=role,
        first_name=first_name,
        last_name=last_name,
        must_change_password=True,
    )


def deactivate_staff_account(user, acting_user):
    """Stop a staff account from logging in while keeping its history.

    Implements AUTH-05. The account is never deleted, so past records that
    point to it stay complete.

    Args:
        user: The staff account to deactivate.
        acting_user: The administrator doing it.

    Returns:
        The deactivated User.

    Raises:
        ValidationError: If the administrator tries to deactivate their own
            account, or the account is not a staff account.
    """
    if user.pk == acting_user.pk:
        raise ValidationError(
            "You cannot deactivate your own account, because you would be "
            "locked out. Ask another administrator to do it."
        )
    if user.role not in STAFF_ROLES:
        raise ValidationError(
            "Only staff accounts can be deactivated here. "
            "Patient accounts are managed from the patient record."
        )
    user.is_active = False
    user.save(update_fields=["is_active"])
    return user


def find_account(identifier):
    """Find the account a person is trying to log in to (AUTH-06).

    Staff log in with their email address. The username also works, so that
    accounts created without an email can still be used.

    Args:
        identifier: The email address or username that was typed.

    Returns:
        The matching User, or None when nobody matches.
    """
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    by_email = User.objects.filter(email__iexact=identifier).order_by("pk").first()
    if by_email is not None:
        return by_email
    return User.objects.filter(username__iexact=identifier).order_by("pk").first()


def is_locked(user, now=None):
    """Tell whether an account is locked after too many wrong passwords.

    Args:
        user: The account to check.
        now: The current time. Only tests pass this.

    Returns:
        True while the lock has not run out (SEC-04).
    """
    now = now or timezone.now()
    return user.locked_until is not None and user.locked_until > now


def lock_message(user):
    """Explain a lock in plain language and say when it ends (USAB-06).

    Args:
        user: A locked account.

    Returns:
        A message with the time, in the clinic's time zone, when login works again.
    """
    ends = timezone.localtime(user.locked_until).strftime("%I:%M %p")
    return (
        f"Too many wrong passwords were entered, so this account is locked "
        f"for {LOCK_MINUTES} minutes. You can try again at {ends}. "
        "If you forgot your password, use 'Forgot your password?' to choose a new one."
    )


def record_failed_login(user, now=None):
    """Count a wrong password and lock the account after 5 in a row (SEC-04).

    Args:
        user: The account the wrong password was tried on.
        now: The current time. Only tests pass this.
    """
    now = now or timezone.now()
    if user.locked_until is not None and user.locked_until <= now:
        user.failed_login_count = 0
        user.locked_until = None
    user.failed_login_count += 1
    if user.failed_login_count >= MAX_FAILED_LOGINS:
        user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
        user.failed_login_count = 0
    user.save(update_fields=["failed_login_count", "locked_until"])


def record_successful_login(user):
    """Forget earlier wrong passwords after a correct login (AUTH-06).

    Args:
        user: The account that just logged in.
    """
    if user.failed_login_count or user.locked_until:
        user.failed_login_count = 0
        user.locked_until = None
        user.save(update_fields=["failed_login_count", "locked_until"])