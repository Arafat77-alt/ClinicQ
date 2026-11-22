"""Checking in patients who already have an appointment (QUE-01, BR-05, BR-06)."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.patients import normalize_mobile_number
from booking.models import Appointment

from .services import (
    CHECK_IN_OPENS_MINUTES,
    GRACE_MINUTES,
    NO_SHOW_AFTER_MINUTES,
    add_to_queue,
)


def find_appointments_for_check_in(query, day=None):
    """Find today's booked appointments for a check-in search (QUE-01).

    The receptionist can type a reference number, a mobile number or part of
    a patient name. Only appointments that can be checked in are returned.

    Args:
        query: What the receptionist typed.
        day: The clinic day to search. Defaults to today.

    Returns:
        A queryset of Appointment with patient and doctor loaded.
    """
    text = (query or "").strip()
    if not text:
        return Appointment.objects.none()
    day = day or timezone.localdate()
    appointments = Appointment.objects.filter(
        slot_start__date=day, status=Appointment.Status.BOOKED
    ).select_related("patient", "doctor__user")
    if text.upper().startswith("CQ-"):
        return appointments.filter(reference_number__iexact=text)
    if any(character.isalpha() for character in text):
        return appointments.filter(patient__full_name__icontains=text).order_by("slot_start")
    number = normalize_mobile_number(text)
    return appointments.filter(patient__mobile_number=number).order_by("slot_start")


def check_in_booked_appointment(appointment, now=None):
    """Check in a booked patient and return the entry and its arrival type (QUE-01).

    BR-05 sets the window: check-in opens 60 minutes before the slot, a patient
    who arrives by slot start + 15 minutes keeps appointment priority, and a
    later arrival keeps the appointment but joins the queue from the check-in
    time. After slot start + 60 minutes the appointment is past the no-show
    limit and reception is told to register a walk-in instead (BR-06).

    Args:
        appointment: The booked Appointment to check in.
        now: The arrival time. Defaults to the current time.

    Returns:
        A pair (entry, was_late): the new QueueEntry and whether the patient
        arrived after the grace period.

    Raises:
        ValidationError: With a plain-language message when the appointment
            cannot be checked in at this time.
    """
    now = now or timezone.now()
    if appointment.type == Appointment.Type.WALKIN or appointment.slot_start is None:
        raise ValidationError(
            "This appointment has no booked time. Register the patient as a walk-in instead."
        )
    if appointment.status != Appointment.Status.BOOKED:
        raise ValidationError(
            f"This appointment is already {appointment.get_status_display().lower()}. "
            "It cannot be checked in again."
        )
    slot_start = appointment.slot_start
    opens_at = slot_start - timedelta(minutes=CHECK_IN_OPENS_MINUTES)
    no_show_at = slot_start + timedelta(minutes=NO_SHOW_AFTER_MINUTES)
    if now < opens_at:
        raise ValidationError(
            f"Check-in opens {CHECK_IN_OPENS_MINUTES} minutes before the appointment time. "
            "Please try again closer to the time."
        )
    if now > no_show_at:
        raise ValidationError(
            "This appointment is past the no-show time. "
            "Register the patient as a walk-in instead."
        )
    was_late = now > slot_start + timedelta(minutes=GRACE_MINUTES)
    entry = add_to_queue(appointment, check_in_time=now)
    return entry, was_late
