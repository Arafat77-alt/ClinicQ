"""Models for the accounts application."""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """A person who can log in to ClinicQ.

    Supports AUTH-05 (staff accounts with roles) and SEC-01 (role checks
    on the server for every request).

    Attributes:
        role: What this person is allowed to do in the system.
    """

    class Role(models.TextChoices):
        """The four roles defined in the requirements."""

        PATIENT = "patient", "Patient"
        RECEPTIONIST = "receptionist", "Receptionist"
        DOCTOR = "doctor", "Doctor"
        ADMIN = "admin", "Clinic administrator"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PATIENT)