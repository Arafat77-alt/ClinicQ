"""Models for the accounts application."""

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q


class UserManager(DjangoUserManager):
    """Create accounts, giving every superuser the clinic administrator role."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        """Create a superuser who is also a clinic administrator (AUTH-05)."""
        extra_fields.setdefault("role", "admin")
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """A person who can log in to ClinicQ.

    Supports AUTH-05 (staff accounts with roles) and SEC-01 (role checks
    on the server for every request).

    Attributes:
        role: What this person is allowed to do in the system.
        must_change_password: True until the person sets their own password
            after the first login (AUTH-05).
    """

    class Role(models.TextChoices):
        """The four roles defined in the requirements."""

        PATIENT = "patient", "Patient"
        RECEPTIONIST = "receptionist", "Receptionist"
        DOCTOR = "doctor", "Doctor"
        ADMIN = "admin", "Clinic administrator"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PATIENT)
    must_change_password = models.BooleanField(default=False)

    objects = UserManager()


mobile_number_validator = RegexValidator(
    regex=r"^\+8801\d{9}$",
    message="Enter a Bangladeshi mobile number in the form +8801XXXXXXXXX.",
)


class Patient(models.Model):
    """A person who receives care at the clinic.

    A dependent (a child or parent managed by someone else) is a Patient
    with a guardian. Appointments always point to exactly one Patient
    (AUTH-04). Mobile numbers identify one patient account (A-10), so the
    number must be unique unless the patient is a dependent, who shares the
    guardian's number.

    Attributes:
        user: The login account, if this patient has registered online.
            Walk-in patients added by reception have no login yet.
        guardian: The patient who manages this dependent, if any.
        full_name: The patient's full name.
        mobile_number: Bangladeshi mobile number in +8801XXXXXXXXX format.
        date_of_birth: Optional, because walk-ins may only give an age.
    """

    user = models.OneToOneField(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="patient"
    )
    guardian = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="dependents"
    )
    full_name = models.CharField(max_length=150)
    mobile_number = models.CharField(max_length=14, validators=[mobile_number_validator])
    date_of_birth = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["mobile_number"],
                condition=Q(guardian__isnull=True),
                name="uniq_mobile_for_non_dependents",
                violation_error_message=(
                    "This mobile number already belongs to another patient. "
                    "Each mobile number can belong to only one patient. "
                    "If this person is a child or parent managed by someone else, "
                    "choose that person in the Guardian field. "
                    "Otherwise, enter a different mobile number."
                ),
            )
        ]

    def __str__(self):
        """Return the name and number, which is how staff search for a patient."""
        return f"{self.full_name} ({self.mobile_number})"