"""Doctor leave and the appointments it affects (SCH-03, BR-13)."""

from collections import namedtuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from booking.models import Appointment
from notifications.services import send_sms

from .models import DoctorLeave

LeaveResult = namedtuple("LeaveResult", ["leave", "rescheduled", "failed_notices"])


def add_leave(doctor, start_date, end_date, start_time=None, end_time=None, reason=""):
    """Save a doctor's leave and look after the patients it affects (SCH-03).

    When the leave is saved, no new slots are offered for that period, every
    booked appointment inside it becomes "Needs rescheduling", and each affected
    patient gets a text message (BR-13, NOT-03). A message that cannot be sent
    never stops the leave from being saved (REL-04); the patient is listed in
    the result so that reception can call them.

    Args:
        doctor: The Doctor who will be away.
        start_date: The first day of the leave.
        end_date: The last day of the leave.
        start_time: Optional start, for leave of a few hours on one day.
        end_time: Optional end, for leave of a few hours on one day.
        reason: Optional note.

    Returns:
        A LeaveResult with the saved leave, the appointments that need new
        times, and those whose patient could not be messaged.

    Raises:
        ValidationError: With a plain-language message when the dates or times
            do not make sense, the leave is already over, or it overlaps
            another leave.
    """
    if (start_time is None) != (end_time is None):
        raise ValidationError(
            "Enter both a start time and an end time, or leave both empty to take whole days."
        )
    if start_time is not None and start_date != end_date:
        raise ValidationError(
            "Leave for a few hours can only be on one day. Use the same date for "
            "the first and last day, or leave the times empty to take whole days."
        )
    if end_date < start_date:
        raise ValidationError(
            "The last day of the leave cannot be before the first day. "
            "Check both dates and try again."
        )
    if start_time is not None and end_time <= start_time:
        raise ValidationError(
            "The end time must be after the start time. Check both times and try again."
        )
    leave = DoctorLeave(
        doctor=doctor,
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        reason=reason.strip(),
    )
    if leave.ends_at <= timezone.now():
        raise ValidationError(
            "This leave is already over, so there is nothing to save. "
            "Choose dates that have not passed yet."
        )
    for other in doctor.leaves.all():
        if leave.starts_at < other.ends_at and leave.ends_at > other.starts_at:
            raise ValidationError(
                f"This leave overlaps your leave on {other}. "
                "Remove that leave first, or choose different dates."
            )
    with transaction.atomic():
        leave.save()
        affected = list(
            Appointment.objects.filter(
                doctor=doctor,
                status=Appointment.Status.BOOKED,
                slot_start__lt=leave.ends_at,
                slot_end__gt=leave.starts_at,
            ).select_related("patient", "doctor__user")
        )
        for appointment in affected:
            appointment.status = Appointment.Status.NEEDS_RESCHEDULING
            appointment.save()
    failed = [a for a in affected if not _send_leave_notice(a, leave)]
    return LeaveResult(leave, affected, failed)


def _send_leave_notice(appointment, leave):
    """Tell one patient that their appointment needs a new time (NOT-03).

    Args:
        appointment: The affected appointment.
        leave: The leave that caused it.

    Returns:
        True when the message was handed over, False when it could not be sent.
    """
    doctor = appointment.doctor
    name = doctor.user.get_full_name() or doctor.user.username
    when = timezone.localtime(appointment.slot_start)
    message = (
        f"ClinicQ: Dr. {name} will be away on {leave}. Your appointment "
        f"{appointment.reference_number} on {when:%d %b %Y} at {when:%H:%M} needs a new "
        "time. Please call the clinic or visit ClinicQ to choose another time."
    )
    try:
        return bool(send_sms(appointment.patient.mobile_number, message))
    except Exception:  # REL-04: a failed message must never stop the leave
        return False