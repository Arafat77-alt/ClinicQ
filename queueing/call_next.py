"""Business rules for calling the next patient (QUE-07, BR-11, BR-08)."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from booking.models import Appointment

from .models import ACTIVE_STATES, QueueEntry
from .services import waiting_queue

ACTIVE_MESSAGE = (
    "A patient is already in consultation. Complete or skip that patient "
    "before calling the next one."
)
EMPTY_MESSAGE = "Nobody is waiting right now. New patients will appear here automatically."


def call_next_patient(doctor, now=None):
    """Move the first waiting patient into consultation for their own doctor.

    The patient is chosen by waiting_queue, so BR-08 stays in one place. BR-11
    is checked before and after locking the entry. The one-click action goes
    straight to In consultation and fills called_at and started_at so the
    existing completion, skip and live-status services keep working.

    Args:
        doctor: The logged-in doctor's profile.
        now: Optional timezone-aware current time for deterministic tests.

    Returns:
        The QueueEntry that was called.

    Raises:
        ValidationError: With a plain-language message when someone is already
            active or nobody is waiting.
    """
    current_time = now or timezone.now()
    queue_date = timezone.localdate(current_time)
    with transaction.atomic():
        active = list(
            QueueEntry.objects.select_for_update().filter(
                doctor=doctor, queue_date=queue_date, state__in=ACTIVE_STATES
            )
        )
        if active:
            raise ValidationError(ACTIVE_MESSAGE)

        entries = waiting_queue(doctor, queue_date)
        if not entries:
            raise ValidationError(EMPTY_MESSAGE)

        entry = QueueEntry.objects.select_for_update().get(pk=entries[0].pk)
        other_active = (
            QueueEntry.objects.filter(
                doctor=doctor, queue_date=queue_date, state__in=ACTIVE_STATES
            )
            .exclude(pk=entry.pk)
            .exists()
        )
        if other_active:
            raise ValidationError(ACTIVE_MESSAGE)

        entry.state = QueueEntry.State.IN_CONSULTATION
        entry.called_at = current_time
        entry.started_at = current_time
        entry.save(update_fields=["state", "called_at", "started_at"])

        appointment = entry.appointment
        appointment.status = Appointment.Status.IN_CONSULTATION
        appointment.save(update_fields=["status", "updated_at"])

    return entry
