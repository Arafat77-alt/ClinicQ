"""Fixing the queue by hand: emergencies, removals and returns (QUE-09, QUE-10).

Every action locks the queue entry row while it works (select_for_update), so
that a receptionist and a doctor pressing buttons at the same moment cannot
undo each other's change, for example removing a patient the doctor has just
called.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import User
from scheduling.models import Doctor

from .models import QueueEntry
from .services import waiting_queue

REASON_MAX_LENGTH = 255


def _clean_reason(reason, what):
    """Return the trimmed reason, or explain in plain words what is missing.

    Args:
        reason: The text the person typed.
        what: Words that finish the sentence "Write why ...".

    Returns:
        The reason without spaces at the start and end.

    Raises:
        ValidationError: When the reason is empty or too long.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError(f"A reason is required. Write why {what}.")
    if len(reason) > REASON_MAX_LENGTH:
        raise ValidationError(
            f"The reason is too long. Keep it under {REASON_MAX_LENGTH} characters."
        )
    return reason


def _locked(entry):
    """Read the entry again and lock its row until the transaction ends."""
    return QueueEntry.objects.select_for_update().select_related("doctor").get(pk=entry.pk)


def flag_emergency(entry, flagged_by, reason):
    """Mark a waiting patient as an emergency, with a reason (QUE-09, BR-09).

    The patient moves to the front of the doctor's queue. When several
    patients are emergencies, the one flagged first is called first (BR-08),
    because waiting_queue sorts emergencies by the time they were flagged.
    Who flagged it, when and why are stored on the entry (SAFE-02).

    Args:
        entry: The QueueEntry to flag.
        flagged_by: The account pressing the button.
        reason: Why the patient is urgent, for example: chest pain.

    Returns:
        The updated QueueEntry.

    Raises:
        ValidationError: With a plain-language message when the reason is
            missing, the person may not flag emergencies, or the patient is
            not waiting.
    """
    reason = _clean_reason(reason, "this patient is an emergency, for example: chest pain")
    if flagged_by.role not in (User.Role.RECEPTIONIST, User.Role.DOCTOR):
        raise ValidationError("Only a receptionist or a doctor can flag an emergency.")
    with transaction.atomic():
        entry = _locked(entry)
        if flagged_by.role == User.Role.DOCTOR and entry.doctor.user_id != flagged_by.pk:
            raise ValidationError(
                "You can flag emergencies only in your own queue. Ask reception to flag "
                "patients who are waiting for another doctor."
            )
        if entry.state != QueueEntry.State.WAITING:
            raise ValidationError(
                f"Only a waiting patient can be flagged as an emergency. Token {entry.token} "
                f"is {entry.get_state_display().lower()}."
            )
        if entry.is_emergency:
            raise ValidationError(
                f"Token {entry.token} is already flagged as an emergency, so it is already "
                "at the front of the queue."
            )
        entry.is_emergency = True
        entry.emergency_reason = reason
        entry.emergency_flagged_by = flagged_by
        entry.emergency_flagged_at = timezone.now()
        entry.save(
            update_fields=[
                "is_emergency",
                "emergency_reason",
                "emergency_flagged_by",
                "emergency_flagged_at",
            ]
        )
    return entry


def remove_from_queue(entry, removed_by, reason):
    """Take a patient out of the queue, with a reason (QUE-10, BR-10).

    Used for a patient who left the clinic, or a patient skipped twice whom
    reception decides not to return. The appointment becomes Cancelled
    (SRS 3.3: Checked-In can change to Cancelled when the patient leaves the
    queue). The patients behind move up by themselves, because positions are
    worked out from the waiting list every time (see services.patients_ahead).

    Args:
        entry: The QueueEntry to remove.
        removed_by: The receptionist's account.
        reason: Why the patient is removed, for example: left the clinic.

    Returns:
        The updated QueueEntry.

    Raises:
        ValidationError: With a plain-language message when the reason is
            missing, the person is not a receptionist, or the patient is
            already with the doctor or finished.
    """
    reason = _clean_reason(reason, "the patient is removed, for example: left the clinic")
    if removed_by.role != User.Role.RECEPTIONIST:
        raise ValidationError("Only a receptionist can remove a patient from the queue.")
    removable = (QueueEntry.State.WAITING, QueueEntry.State.RECEPTION_TO_DECIDE)
    with transaction.atomic():
        entry = _locked(entry)
        if entry.state not in removable:
            raise ValidationError(
                f"Token {entry.token} is {entry.get_state_display().lower()}, so it cannot be "
                "removed here. Only waiting patients and patients marked Reception to "
                "decide can be removed."
            )
        entry.state = QueueEntry.State.REMOVED
        entry.removal_reason = reason
        entry.removed_by = removed_by
        entry.save(update_fields=["state", "removal_reason", "removed_by"])
        appointment = entry.appointment
        appointment.status = appointment.Status.CANCELLED
        appointment.save(update_fields=["status", "updated_at"])
    return entry


def return_to_queue(entry, returned_by):
    """Put a patient who was skipped twice back in the queue (QUE-10, BR-10).

    The patient waits again behind everyone who is waiting now (effective
    time = now, as BR-10 says for a skipped patient). The skip count is kept,
    so the doctor still cannot skip this patient a third time (QUE-08).

    Args:
        entry: The QueueEntry marked Reception to decide.
        returned_by: The receptionist's account.

    Returns:
        The updated QueueEntry.

    Raises:
        ValidationError: With a plain-language message when the person is not
            a receptionist or the patient is not marked Reception to decide.
    """
    if returned_by.role != User.Role.RECEPTIONIST:
        raise ValidationError("Only a receptionist can return a patient to the queue.")
    with transaction.atomic():
        entry = _locked(entry)
        if entry.state != QueueEntry.State.RECEPTION_TO_DECIDE:
            raise ValidationError(
                f"Token {entry.token} is {entry.get_state_display().lower()}. Only patients "
                "marked Reception to decide can be returned to the queue."
            )
        entry.state = QueueEntry.State.WAITING
        entry.effective_time = timezone.now()
        entry.save(update_fields=["state", "effective_time"])
    return entry


def emergency_alerts(doctor, queue_date=None):
    """List the waiting emergencies a doctor must be alerted about (QUE-09).

    Person B's doctor queue page (QUE-06) can show these at the top.

    Args:
        doctor: The Doctor.
        queue_date: The clinic day. Defaults to today.

    Returns:
        A list of QueueEntry, the earliest flagged first.
    """
    queue_date = queue_date or timezone.localdate()
    return [entry for entry in waiting_queue(doctor, queue_date) if entry.is_emergency]


def queue_board(queue_date=None, doctor=None):
    """Collect today's queues for the reception board (QUE-09, QUE-10).

    Args:
        queue_date: The clinic day. Defaults to today.
        doctor: Show only this doctor's queue (for a doctor's own view).

    Returns:
        A list of dictionaries, one per doctor, ordered by doctor code, with:
        doctor, current (the called or in-consultation entry, or None),
        waiting (in calling order, BR-08), to_decide (skipped twice, BR-10)
        and alerts (waiting emergencies).
    """
    queue_date = queue_date or timezone.localdate()
    if doctor is not None:
        doctors = [doctor]
    else:
        with_entries = QueueEntry.objects.filter(queue_date=queue_date).values("doctor_id")
        doctors = (
            Doctor.objects.filter(Q(is_active=True) | Q(pk__in=with_entries))
            .select_related("user")
            .order_by("code")
        )
    board = []
    for each in doctors:
        today = QueueEntry.objects.filter(doctor=each, queue_date=queue_date).select_related(
            "appointment__patient", "doctor"
        )
        waiting = waiting_queue(each, queue_date)
        board.append(
            {
                "doctor": each,
                "current": today.filter(
                    state__in=[QueueEntry.State.CALLED, QueueEntry.State.IN_CONSULTATION]
                ).first(),
                "waiting": waiting,
                "to_decide": list(
                    today.filter(state=QueueEntry.State.RECEPTION_TO_DECIDE).order_by(
                        "check_in_time"
                    )
                ),
                "alerts": [entry for entry in waiting if entry.is_emergency],
            }
        )
    return board
