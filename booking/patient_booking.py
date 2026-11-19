"""Patient self-service booking, listing, and cancellation (BKG-03, BKG-04, BKG-05)."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Patient

from .availability import free_slots
from .models import Appointment

# BR-04: patients may cancel online up to 2 hours before the appointment starts.
CANCELLATION_LEAD_HOURS = 2
CANCELLABLE_STATUSES = {
    Appointment.Status.BOOKED,
    Appointment.Status.NEEDS_RESCHEDULING,
}


def family_patients(guardian_patient):
    """Return a queryset of the logged-in patient and their dependents (AUTH-04)."""
    return Patient.objects.filter(
        Q(pk=guardian_patient.pk) | Q(guardian=guardian_patient)
    ).order_by("guardian_id", "full_name")


def book_online_appointment(
    guardian_patient,
    target_patient_id,
    doctor,
    slot_start,
    booked_by,
    reason="",
    now=None,
):
    """Book an online appointment for a patient or their dependent (BKG-03).

    Enforces BR-01 (one active booking per slot), BR-03 (14-day window and
    30-minute lead time), REL-02 (atomic database uniqueness), and SEC-01
    (patient may only book for themselves or their own dependents).

    Args:
        guardian_patient: The logged-in Patient profile.
        target_patient_id: Primary key of the Patient receiving care.
        doctor: The active Doctor being booked.
        slot_start: Timezone-aware start datetime of the chosen slot.
        booked_by: The logged-in patient User account.
        reason: Optional visit reason.
        now: Optional current datetime for deterministic tests.

    Returns:
        Appointment: The newly created online Appointment.

    Raises:
        ValidationError: If the target patient does not belong to this family,
            the slot is no longer free, or someone else booked it first.
    """
    current_time = now or timezone.now()
    target_patient = family_patients(guardian_patient).filter(pk=target_patient_id).first()
    if target_patient is None:
        raise ValidationError(
            "You can only book appointments for yourself or your registered dependents."
        )

    open_slots = {
        start: end
        for _day, day_slots in free_slots(doctor, now=current_time, reception=False)
        for start, end in day_slots
    }
    if slot_start not in open_slots:
        raise ValidationError(
            "Slot just taken — this time is no longer available. "
            "Choose one of the nearby free times below."
        )

    try:
        with transaction.atomic():
            return Appointment.objects.create(
                patient=target_patient,
                doctor=doctor,
                slot_start=slot_start,
                slot_end=open_slots[slot_start],
                type=Appointment.Type.ONLINE,
                status=Appointment.Status.BOOKED,
                reason=(reason or "").strip(),
                created_by=booked_by,
            )
    except IntegrityError as error:
        raise ValidationError(
            "Slot just taken — another patient booked this time a moment ago. "
            "Choose one of the nearby free times below."
        ) from error


def list_patient_appointments(guardian_patient, now=None):
    """Split a patient's family appointments into upcoming and past lists (BKG-04).

    Args:
        guardian_patient: The logged-in Patient profile.
        now: Optional current datetime for deterministic tests.

    Returns:
        tuple[list[Appointment], list[Appointment]]: ``(upcoming, past)``.
    """
    current_time = now or timezone.now()
    appointments = (
        Appointment.objects.filter(patient__in=family_patients(guardian_patient))
        .select_related("patient", "doctor", "doctor__user")
        .order_by("slot_start", "created_at")
    )

    upcoming = []
    past = []
    for appt in appointments:
        appt.can_patient_cancel = can_cancel_appointment(appt, now=current_time)
        is_upcoming_status = appt.status in {
            Appointment.Status.BOOKED,
            Appointment.Status.NEEDS_RESCHEDULING,
            Appointment.Status.CHECKED_IN,
            Appointment.Status.IN_CONSULTATION,
        }
        if is_upcoming_status and (appt.slot_start is None or appt.slot_start >= current_time):
            upcoming.append(appt)
        else:
            past.append(appt)

    past.reverse()
    return upcoming, past


def can_cancel_appointment(appointment, now=None):
    """Return True if a patient is allowed to cancel ``appointment`` online (BKG-05, BR-04).

    Appointments in ``needs_rescheduling`` (triggered when a doctor takes leave)
    may be cancelled at any time before start, even within 2 hours.
    """
    current_time = now or timezone.now()
    if appointment.status not in CANCELLABLE_STATUSES:
        return False
    if appointment.slot_start is None:
        return False
    if appointment.status == Appointment.Status.NEEDS_RESCHEDULING:
        return current_time <= appointment.slot_start
    cutoff = appointment.slot_start - timedelta(hours=CANCELLATION_LEAD_HOURS)
    return current_time <= cutoff


def cancel_patient_appointment(guardian_patient, appointment_id, now=None):
    """Cancel an appointment for the logged-in patient or their dependent (BKG-05).

    Enforces SEC-01 (family ownership), status eligibility, and BR-04 (must be
    cancelled at least 2 hours before ``slot_start``). Setting status to
    ``cancelled`` immediately releases the slot for other patients.

    Args:
        guardian_patient: The logged-in Patient profile.
        appointment_id: Primary key of the Appointment to cancel.
        now: Optional current datetime for deterministic tests.

    Returns:
        Appointment: The updated cancelled Appointment.

    Raises:
        ValidationError: If the appointment is not found in this family, has
            already passed/completed/cancelled, or is within 2 hours of start.
    """
    current_time = now or timezone.now()
    appointment = (
        Appointment.objects.select_related("patient", "doctor", "doctor__user")
        .filter(pk=appointment_id, patient__in=family_patients(guardian_patient))
        .first()
    )
    if appointment is None:
        raise ValidationError("That appointment was not found in your account.")

    if appointment.status == Appointment.Status.CANCELLED:
        raise ValidationError("This appointment has already been cancelled.")

    if appointment.status not in CANCELLABLE_STATUSES:
        raise ValidationError(
            "This appointment can no longer be cancelled online because it is already "
            "in progress or completed."
        )

    if appointment.slot_start is not None and current_time > appointment.slot_start:
        raise ValidationError(
            "This appointment time has already passed and cannot be cancelled."
        )

    if not can_cancel_appointment(appointment, now=current_time):
        raise ValidationError(
            f"Appointments cannot be cancelled online less than {CANCELLATION_LEAD_HOURS} "
            "hours before the scheduled time. Please call clinic reception for help."
        )

    appointment.status = Appointment.Status.CANCELLED
    appointment.save(update_fields=["status", "updated_at"])
    return appointment