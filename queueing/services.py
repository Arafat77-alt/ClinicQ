"""Business rules for the queueing application (BR-05, BR-08, BR-14)."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from booking.models import Appointment

from .models import QueueEntry

# BR-05: a patient who checks in by slot start + 15 minutes keeps appointment
# priority. These become clinic settings that the administrator can change (SCH-04).
CHECK_IN_OPENS_MINUTES = 60
GRACE_MINUTES = 15
NO_SHOW_AFTER_MINUTES = 60

TOKEN_RETRIES = 5


def next_token_number(doctor, queue_date):
    """Return the next token number for a doctor on a day (BR-14).

    Tokens run 1, 2, 3 ... per doctor per day and start again every day.

    Args:
        doctor: The Doctor.
        queue_date: The clinic day.

    Returns:
        The next free token number.
    """
    highest = QueueEntry.objects.filter(doctor=doctor, queue_date=queue_date).aggregate(
        highest=Max("token_number")
    )["highest"]
    return (highest or 0) + 1


def effective_time_for(appointment, check_in_time):
    """Work out the time used to order the queue for one patient (BR-08).

    The effective time is the slot start for a patient with an appointment who
    checks in on time, and the check-in time for walk-ins and late arrivals.

    Args:
        appointment: The patient's Appointment.
        check_in_time: When the patient arrived.

    Returns:
        A timezone-aware datetime.
    """
    if appointment.type == Appointment.Type.WALKIN or appointment.slot_start is None:
        return check_in_time
    if check_in_time > appointment.slot_start + timedelta(minutes=GRACE_MINUTES):
        return check_in_time
    return appointment.slot_start


def add_to_queue(appointment, check_in_time=None):
    """Put a patient in their doctor's queue and give them a token (QUE-01, QUE-03).

    The check-in window rules (BR-05) and the no-show limit (BR-06) are checked
    by the check-in story, before this function is called. Here the entry is
    created with the next token (BR-14) and the effective time (BR-08), and the
    appointment becomes Checked-In. If two patients check in at the same moment,
    the database refuses the repeated token and a new one is chosen.

    Args:
        appointment: The Appointment that is checking in, or a walk-in's appointment.
        check_in_time: When the patient arrived. Defaults to now.

    Returns:
        The new QueueEntry.

    Raises:
        ValidationError: With a plain-language message when the patient is
            already in the queue or the appointment cannot join a queue.
    """
    check_in_time = check_in_time or timezone.now()
    allowed = (Appointment.Status.BOOKED, Appointment.Status.CHECKED_IN)
    if appointment.status not in allowed:
        raise ValidationError(
            f"This appointment is {appointment.get_status_display().lower()}, so the patient "
            "cannot join the queue. Only booked appointments and walk-ins can check in."
        )
    if QueueEntry.objects.filter(appointment=appointment).exists():
        raise ValidationError(
            "This patient is already in the queue. Check the queue for their token."
        )
    queue_date = timezone.localdate(check_in_time)
    for _attempt in range(TOKEN_RETRIES):
        try:
            with transaction.atomic():
                entry = QueueEntry.objects.create(
                    appointment=appointment,
                    doctor=appointment.doctor,
                    queue_date=queue_date,
                    token_number=next_token_number(appointment.doctor, queue_date),
                    check_in_time=check_in_time,
                    effective_time=effective_time_for(appointment, check_in_time),
                )
                if appointment.status != Appointment.Status.CHECKED_IN:
                    appointment.status = Appointment.Status.CHECKED_IN
                    appointment.save()
                return entry
        except IntegrityError:
            continue  # another patient took this token a moment ago, so try the next one
    raise ValidationError(
        "The queue is very busy right now and the token could not be given. "
        "Please try again in a moment."
    )


def waiting_queue(doctor, queue_date):
    """List the waiting patients in the order they will be called (BR-08).

    The order is: emergencies first (earliest flagged first), then the earliest
    effective time, then the earliest check-in time.

    Args:
        doctor: The Doctor.
        queue_date: The clinic day.

    Returns:
        A list of QueueEntry in calling order.
    """
    entries = QueueEntry.objects.filter(
        doctor=doctor, queue_date=queue_date, state=QueueEntry.State.WAITING
    ).select_related("appointment__patient", "doctor")
    return list(
        entries.order_by("-is_emergency", "emergency_flagged_at", "effective_time", "check_in_time")
    )


def patients_ahead(entry):
    """Count how many waiting patients will be called before this one (QUE-04).

    Args:
        entry: A QueueEntry.

    Returns:
        The number of waiting patients ahead, or 0 when the patient is not
        waiting.
    """
    queue = waiting_queue(entry.doctor, entry.queue_date)
    for position, waiting in enumerate(queue):
        if waiting.pk == entry.pk:
            return position
    return 0
