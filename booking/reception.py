"""Booking by the receptionist (BKG-09)."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .availability import free_slots
from .models import Appointment


def book_for_patient(patient, doctor, slot_start, booked_by, reason=""):
    """Book a slot for a caller, as the receptionist (BKG-09, BR-01, BR-03).

    Reception may book until the slot ends. The database makes sure that two
    bookings cannot take the same slot (REL-02), even when two people press the
    button at the same moment.

    Args:
        patient: The Patient the appointment is for.
        doctor: The Doctor to book.
        slot_start: The start of the chosen slot, as a timezone-aware datetime.
        booked_by: The receptionist's account.
        reason: Optional reason for the visit.

    Returns:
        The new Appointment, with type Reception and status Booked.

    Raises:
        ValidationError: With a plain-language message when the time is not
            available or somebody else booked it first.
    """
    open_slots = {
        start: end
        for _day, day_slots in free_slots(doctor, now=timezone.now(), reception=True)
        for start, end in day_slots
    }
    if slot_start not in open_slots:
        raise ValidationError(
            "This time is no longer available. It may be taken, already over, or not "
            "part of the doctor's schedule. Choose another time."
        )
    try:
        with transaction.atomic():
            return Appointment.objects.create(
                patient=patient,
                doctor=doctor,
                slot_start=slot_start,
                slot_end=open_slots[slot_start],
                type=Appointment.Type.RECEPTION,
                status=Appointment.Status.BOOKED,
                reason=reason.strip(),
                created_by=booked_by,
            )
    except IntegrityError as error:
        raise ValidationError(
            "Someone else has just booked this time. Choose another time; "
            "the nearest free times are shown below."
        ) from error