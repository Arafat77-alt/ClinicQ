"""Models for the booking application."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from .services import generate_reference_number

# BR-01: only these statuses occupy a slot.
ACTIVE_STATUSES = ["booked", "checked_in", "in_consultation"]


class Appointment(models.Model):
    """A reserved time with one doctor for one patient.

    Supports BKG-03 (booking) and BR-01 / REL-02 (a slot holds at most one
    active appointment, enforced by the database and not only by code).

    Attributes:
        reference_number: Unique code shown to the patient. Created automatically.
        patient: The person who will be seen. A dependent is a Patient too.
        doctor: The doctor who will see the patient.
        slot_start: Start of the booked time. Empty only for walk-ins.
        slot_end: End of the booked time. Empty only for walk-ins.
        type: How the appointment was made.
        status: Where the appointment is in its life (SRS section 3.3).
        reason: Optional reason for the visit, written by the patient or reception.
        created_by: The account that created the appointment.
    """

    class Type(models.TextChoices):
        """How the appointment was made."""

        ONLINE = "online", "Online"
        RECEPTION = "reception", "Reception"
        WALKIN = "walkin", "Walk-in"
        FOLLOWUP = "followup", "Follow-up"

    class Status(models.TextChoices):
        """The appointment lifecycle from the SRS."""

        BOOKED = "booked", "Booked"
        NEEDS_RESCHEDULING = "needs_rescheduling", "Needs rescheduling"
        CHECKED_IN = "checked_in", "Checked in"
        IN_CONSULTATION = "in_consultation", "In consultation"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        NO_SHOW = "no_show", "No-show"

    reference_number = models.CharField(
        max_length=12, unique=True, blank=True, editable=False
    )
    patient = models.ForeignKey(
        "accounts.Patient", on_delete=models.PROTECT, related_name="appointments"
    )
    doctor = models.ForeignKey(
        "scheduling.Doctor", on_delete=models.PROTECT, related_name="appointments"
    )
    slot_start = models.DateTimeField(null=True, blank=True)
    slot_end = models.DateTimeField(null=True, blank=True)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.ONLINE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.BOOKED)
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="appointments_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["slot_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "slot_start"],
                condition=Q(status__in=ACTIVE_STATUSES),
                name="uniq_active_slot_per_doctor",
                violation_error_message=(
                    "This doctor already has an active appointment at this time. "
                    "A time slot can hold only one appointment. "
                    "Choose a different time or a different doctor, "
                    "or cancel the existing appointment first."
                ),
            ),
            models.CheckConstraint(
                check=(
                    Q(slot_start__isnull=True)
                    | Q(slot_end__isnull=True)
                    | Q(slot_end__gt=F("slot_start"))
                ),
                name="slot_end_after_slot_start",
                violation_error_message=(
                    "The appointment must end after it starts. "
                    "Check the start and end times and try again."
                ),
            ),
        ]

    def clean(self):
        """Check the time rules that need more than one field."""
        needs_slot = self.type != self.Type.WALKIN
        if needs_slot and (self.slot_start is None or self.slot_end is None):
            raise ValidationError(
                {
                    "slot_start": (
                        "This appointment needs a start and end time. "
                        "Only walk-in patients can be added without a time slot."
                    )
                }
            )

    def save(self, *args, **kwargs):
        """Give the appointment a unique reference number the first time it is saved."""
        if not self.reference_number:
            reference = generate_reference_number()
            while Appointment.objects.filter(reference_number=reference).exists():
                reference = generate_reference_number()
            self.reference_number = reference
        super().save(*args, **kwargs)

    def __str__(self):
        """Return the reference number and the people involved."""
        return f"{self.reference_number}: {self.patient.full_name} with {self.doctor.code}"