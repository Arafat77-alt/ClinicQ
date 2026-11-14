"""Models for the scheduling application."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models

from accounts.models import User

doctor_code_validator = RegexValidator(
    regex=r"^D\d{1,3}$",
    message="Enter a doctor code that starts with D followed by a number, for example D2.",
)


class Doctor(models.Model):
    """A doctor who sees patients at the clinic.

    Supports SCH-01 (doctor profiles). The code is used in queue tokens such
    as D2-014 (BR-14). A doctor is deactivated and never deleted, so that past
    appointments keep their history.

    Attributes:
        user: The login account of this doctor. It must have the doctor role.
        code: Short unique code such as D2, shown on tokens and the display.
        specialty: Area of medicine, used when patients search (BKG-01).
        room: Consulting room, shown on the waiting-room display.
        default_slot_minutes: Length of one appointment slot (default 15).
        is_active: False when the doctor no longer takes appointments.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="doctor",
        limit_choices_to={"role": User.Role.DOCTOR},
    )
    code = models.CharField(
        max_length=4,
        unique=True,
        validators=[doctor_code_validator],
        error_messages={
            "unique": (
                "This doctor code is already used by another doctor. "
                "Each doctor needs a different code, for example D2 or D3."
            )
        },
    )
    specialty = models.CharField(max_length=100)
    room = models.CharField(max_length=20)
    default_slot_minutes = models.PositiveSmallIntegerField(
        default=15, validators=[MinValueValidator(5)]
    )
    is_active = models.BooleanField(default=True)

    def clean(self):
        """Check that the linked account has the doctor role (SEC-01)."""
        if self.user_id and self.user.role != User.Role.DOCTOR:
            raise ValidationError(
                {
                    "user": (
                        "This account does not have the doctor role. "
                        "Change the account's role to Doctor first, "
                        "or choose a different account."
                    )
                }
            )

    def __str__(self):
        """Return the name, code and specialty, which is how staff pick a doctor."""
        name = self.user.get_full_name() or self.user.username
        return f"Dr. {name} ({self.code}, {self.specialty})"