"""Models for the queueing application."""

from django.conf import settings
from django.db import models
from django.db.models import Q

# BR-10: after 2 skips only reception can return a patient or remove them.
MAX_SKIPS = 2

# BR-11: a doctor has at most one patient who is called or in consultation.
ACTIVE_STATES = ["called", "in_consultation"]


class QueueEntry(models.Model):
    """One patient's place in one doctor's queue for one day.

    Supports QUE-01 to QUE-10. An entry is created when a patient checks in
    (or a walk-in is registered) and ends as Completed or Removed. The rules
    that the SRS demands are written as database constraints, so that no
    screen or script can break them: tokens are unique per doctor per day
    (BR-14), a doctor has one active patient at a time (BR-11), a patient is
    skipped at most twice (BR-10), and emergencies and removals need a reason
    (BR-09, QUE-10).

    Attributes:
        appointment: The appointment this entry belongs to (walk-ins have one too).
        doctor: The doctor whose queue this is.
        queue_date: The clinic day, in Dhaka time.
        token_number: 1, 2, 3 ... for this doctor on this day.
        check_in_time: When the patient arrived.
        effective_time: The time used to order the queue (BR-08).
        is_emergency: True when reception or the doctor flagged an emergency.
        emergency_reason: Why the patient is an emergency (required).
        emergency_flagged_by: Who flagged the emergency.
        emergency_flagged_at: When it was flagged.
        state: Where the patient is in the queue (SDS queue entry diagram).
        skip_count: How many times the doctor skipped this patient.
        called_at: When the doctor called the patient.
        started_at: When the consultation began.
        completed_at: When the consultation ended.
        removal_reason: Why the patient was removed (required when removed).
        removed_by: Who removed the patient.
    """

    class State(models.TextChoices):
        """The states of the queue entry diagram in the SDS."""

        WAITING = "waiting", "Waiting"
        CALLED = "called", "Called"
        IN_CONSULTATION = "in_consultation", "In consultation"
        RECEPTION_TO_DECIDE = "reception_to_decide", "Reception to decide"
        COMPLETED = "completed", "Completed"
        REMOVED = "removed", "Removed"

    appointment = models.OneToOneField(
        "booking.Appointment", on_delete=models.PROTECT, related_name="queue_entry"
    )
    doctor = models.ForeignKey(
        "scheduling.Doctor", on_delete=models.PROTECT, related_name="queue_entries"
    )
    queue_date = models.DateField()
    token_number = models.PositiveSmallIntegerField()
    check_in_time = models.DateTimeField()
    effective_time = models.DateTimeField()
    is_emergency = models.BooleanField(default=False)
    emergency_reason = models.CharField(max_length=255, blank=True)
    emergency_flagged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="emergencies_flagged",
    )
    emergency_flagged_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=24, choices=State.choices, default=State.WAITING)
    skip_count = models.PositiveSmallIntegerField(default=0)
    called_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    removal_reason = models.CharField(max_length=255, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="queue_entries_removed",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["queue_date", "doctor", "token_number"]
        verbose_name_plural = "queue entries"
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "queue_date", "token_number"],
                name="uniq_token_per_doctor_per_day",
                violation_error_message=(
                    "This token number is already used for this doctor today. "
                    "Try again and a new token number will be chosen."
                ),
            ),
            models.UniqueConstraint(
                fields=["doctor", "queue_date"],
                condition=Q(state__in=ACTIVE_STATES),
                name="one_active_patient_per_doctor",
                violation_error_message=(
                    "This doctor already has a patient who is called or in consultation. "
                    "Complete or skip that patient before calling the next one."
                ),
            ),
            models.CheckConstraint(
                check=Q(skip_count__lte=MAX_SKIPS),
                name="skip_count_at_most_two",
                violation_error_message=(
                    "A patient can be skipped at most 2 times. After that, reception "
                    "decides whether the patient returns to the queue or is removed."
                ),
            ),
            models.CheckConstraint(
                check=Q(is_emergency=False) | ~Q(emergency_reason=""),
                name="emergency_needs_a_reason",
                violation_error_message=(
                    "An emergency needs a reason. Write why this patient is urgent."
                ),
            ),
            models.CheckConstraint(
                check=~Q(state="removed") | ~Q(removal_reason=""),
                name="removal_needs_a_reason",
                violation_error_message=(
                    "Removing a patient needs a reason. Write why the patient is being "
                    "removed, for example: left the clinic."
                ),
            ),
        ]

    @property
    def token(self):
        """Return the token patients see, for example D2-014 (BR-14)."""
        return f"{self.doctor.code}-{self.token_number:03d}"

    def __str__(self):
        """Return the token and the patient's name."""
        return f"{self.token} {self.appointment.patient.full_name}"
