"""Business rules for completing a consultation or skipping a patient (QUE-08, BR-10)."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from booking.models import Appointment

from .models import ACTIVE_STATES, MAX_SKIPS, QueueEntry


def consultation_duration_minutes(entry):
    """Return how many minutes a completed consultation lasted (QUE-08, BR-12).

    Args:
        entry: A QueueEntry with started_at and completed_at timestamps.

    Returns:
        Duration in minutes as a non-negative float, or None when timestamps
        are missing.
    """
    if entry.started_at is None or entry.completed_at is None:
        return None
    elapsed = (entry.completed_at - entry.started_at).total_seconds() / 60.0
    return max(0.0, elapsed)


def complete_consultation(entry, now=None):
    """Finish a doctor's active consultation and record its duration (QUE-08).

    Marks the queue entry as Completed, records completed_at (setting
    started_at from called_at or now if not already set), and updates the
    linked appointment status to Completed.

    Args:
        entry: The active QueueEntry (state Called or In consultation).
        now: Optional timezone-aware completion time. Defaults to current time.

    Returns:
        The consultation duration in minutes as a non-negative float.

    Raises:
        ValidationError: With a plain-language message if the patient is not
            currently called or in consultation.
    """
    if entry.state not in ACTIVE_STATES:
        raise ValidationError(
            "Only a patient who has been called or is in consultation can be "
            "marked as completed. Call the patient first."
        )
    current_time = now or timezone.now()
    with transaction.atomic():
        if entry.started_at is None:
            entry.started_at = entry.called_at or current_time
        entry.completed_at = current_time
        entry.state = QueueEntry.State.COMPLETED
        entry.save(update_fields=["started_at", "completed_at", "state"])

        appointment = entry.appointment
        appointment.status = Appointment.Status.COMPLETED
        appointment.save(update_fields=["status", "updated_at"])

    return consultation_duration_minutes(entry)


def skip_patient(entry, now=None):
    """Skip a called patient who does not respond (QUE-08, BR-10).

    On the first skip, the patient returns to Waiting with effective_time set
    to now so they move behind all current waiters. On the second skip, the
    doctor cannot skip them again and their state becomes Reception to decide
    (QUE-10). A third skip is refused with a plain-language message.

    Args:
        entry: The active QueueEntry (state Called or In consultation).
        now: Optional timezone-aware time of the skip. Defaults to current time.

    Returns:
        The updated QueueEntry.

    Raises:
        ValidationError: With a plain-language message if the patient has
            already been skipped 2 times or is not currently called/active.
    """
    if entry.skip_count >= MAX_SKIPS or entry.state == QueueEntry.State.RECEPTION_TO_DECIDE:
        raise ValidationError(
            "This patient has already been skipped 2 times and cannot be skipped "
            "again. Ask reception to decide whether to return them to the queue "
            "or remove them."
        )
    if entry.state not in ACTIVE_STATES:
        raise ValidationError(
            "Only a patient who has been called or is in consultation can be "
            "skipped. Call the patient first."
        )

    current_time = now or timezone.now()
    with transaction.atomic():
        entry.skip_count += 1
        entry.called_at = None
        entry.started_at = None
        if entry.skip_count >= MAX_SKIPS:
            entry.state = QueueEntry.State.RECEPTION_TO_DECIDE
        else:
            entry.state = QueueEntry.State.WAITING
            entry.effective_time = current_time
        entry.save(
            update_fields=[
                "skip_count",
                "called_at",
                "started_at",
                "state",
                "effective_time",
            ]
        )

        appointment = entry.appointment
        appointment.status = Appointment.Status.CHECKED_IN
        appointment.save(update_fields=["status", "updated_at"])

    return entry
