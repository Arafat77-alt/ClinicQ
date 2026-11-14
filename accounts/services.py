"""Business rules for the accounts application."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import User

STAFF_ROLES = [User.Role.RECEPTIONIST, User.Role.DOCTOR, User.Role.ADMIN]


def create_staff_account(
    username, email, role, temporary_password, first_name="", last_name=""
):
    """Create a staff account that must change its password at first login.

    Implements AUTH-05. The password rules come from SEC-02 (at least 8
    characters, stored only as a salted hash).

    Args:
        username: The login name. It must not be used by anyone else.
        email: The staff member's email address.
        role: receptionist, doctor or admin.
        temporary_password: A first password that the person must replace.
        first_name: Optional first name.
        last_name: Optional last name.

    Returns:
        The new User.

    Raises:
        ValidationError: With a plain-language message when the role is not a
            staff role, the username is taken, or the password is too weak.
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