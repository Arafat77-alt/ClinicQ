"""Registering walk-in patients at the front desk (QUE-03, BR-08, BR-14)."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import Patient
from accounts.patients import create_patient_for_reception, normalize_mobile_number
from booking.models import Appointment

from .models import QueueEntry
from .services import add_to_queue

# A patient in one of these states is still in a queue today.
OPEN_STATES = [
    QueueEntry.State.WAITING,
    QueueEntry.State.CALLED,
    QueueEntry.State.IN_CONSULTATION,
    QueueEntry.State.RECEPTION_TO_DECIDE,
]


def find_or_create_walk_in_patient(full_name, mobile_number, age):
    """Find the walk-in's patient record by phone number, or create one (QUE-03).

    A known number reuses the existing record, so one person never gets two
    records (A-10). When a guardian and dependents share the number, the person
    whose name matches is chosen; otherwise the number's owner is used.

    Args:
        full_name: The name the walk-in gave.
        mobile_number: The phone number as typed, for example 01712345678.
        age: The age in years.

    Returns:
        A pair (patient, created). created is True when a new record was made.

    Raises:
        ValidationError: With a plain-language message when the number is not
            a Bangladeshi mobile number.
    """
    number = normalize_mobile_number(mobile_number)
    # People without a guardian first, so the number's owner is known[0].
    known = sorted(
        Patient.objects.filter(mobile_number=number), key=lambda p: p.guardian_id is not None
    )
    if known:
        wanted = full_name.strip().casefold()
        for patient in known:
            if patient.full_name.casefold() == wanted:
                return patient, False
        return known[0], False
    return create_patient_for_reception(full_name, mobile_number, age), True


def register_walk_in(patient, doctor, registered_by, reason=""):
    """Add a walk-in patient to a doctor's queue today and give a token (QUE-03).

    The walk-in gets an Appointment of type Walk-in, with no time slot and the
    status Checked-In (SRS 3.3: walk-ins start at Checked-In). Then the queue
    entry is created by Person B's add_to_queue, which gives the next token for
    the doctor today (BR-14) and uses the arrival time as the effective time,
    so the walk-in waits behind patients who arrived earlier (BR-08). Everything
    happens in one transaction: if the token cannot be given, no half-made
    appointment is left behind.

    Args:
        patient: The Patient who walked in.
        doctor: The Doctor chosen by the receptionist.
        registered_by: The receptionist's account.
        reason: Optional reason for the visit.

    Returns:
        The new QueueEntry. Its token property gives, for example, D2-014.

    Raises:
        ValidationError: With a plain-language message when the doctor is not
            taking patients or the patient is already in this doctor's queue today
            (this stops a double click from giving two tokens).
    """
    if not doctor.is_active:
        raise ValidationError(
            "This doctor is not taking patients at the moment. Choose another doctor."
        )
    today = timezone.localdate()
    already = (
        QueueEntry.objects.filter(
            appointment__patient=patient, doctor=doctor, queue_date=today, state__in=OPEN_STATES
        )
        .select_related("doctor")
        .first()
    )
    if already:
        raise ValidationError(
            f"{patient.full_name} is already in this doctor's queue today with token "
            f"{already.token}. Use that token instead of registering the patient again."
        )
    with transaction.atomic():
        appointment = Appointment.objects.create(
            patient=patient,
            doctor=doctor,
            type=Appointment.Type.WALKIN,
            status=Appointment.Status.CHECKED_IN,
            reason=reason.strip(),
            created_by=registered_by,
        )
        return add_to_queue(appointment)
