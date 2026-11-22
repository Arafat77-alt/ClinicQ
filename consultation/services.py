"""Business rules for visit notes (VIS-01, BR-15, PRIV-05)."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import User
from queueing.models import QueueEntry

from .models import VisitRecord

# BR-15: only the author may change a note, and only within 24 hours.
EDIT_WINDOW = timedelta(hours=24)

# A patient in one of these states is "in the doctor's queue right now".
IN_QUEUE_STATES = [
    QueueEntry.State.WAITING,
    QueueEntry.State.CALLED,
    QueueEntry.State.IN_CONSULTATION,
    QueueEntry.State.RECEPTION_TO_DECIDE,
]

NOTE_FIELDS = ("complaint", "findings", "diagnosis", "advice")


def doctor_profile(user):
    """Return the Doctor profile of a logged-in doctor, or None for anyone else."""
    if not user.is_authenticated or user.role != User.Role.DOCTOR:
        return None
    return getattr(user, "doctor", None)


def save_visit_notes(entry, user, notes):
    """Save the doctor's notes for the patient being seen (VIS-01, BR-15).

    New notes can be written only while the patient is In consultation with
    this doctor. The author may correct their own notes for 24 hours after
    first saving them, even after the consultation ends (BR-15). The time and
    the doctor's name are stored automatically.

    Args:
        entry: The QueueEntry of the patient.
        user: The logged-in account.
        notes: A dictionary with complaint, findings, diagnosis and advice.

    Returns:
        The saved VisitRecord.

    Raises:
        ValidationError: With a plain-language message when the person is not
            the patient's doctor, the patient is not in consultation, nothing
            was written, or the 24 hours for changes are over.
    """
    doctor = doctor_profile(user)
    if doctor is None or entry.doctor_id != doctor.pk:
        raise ValidationError("You can write notes only for patients in your own queue.")
    cleaned = {field: (notes.get(field) or "").strip() for field in NOTE_FIELDS}
    if not any(cleaned.values()):
        raise ValidationError(
            "The notes are empty. Write at least one of: complaint, findings, diagnosis or advice."
        )
    record = VisitRecord.objects.filter(appointment=entry.appointment).first()
    if record is None:
        if entry.state != QueueEntry.State.IN_CONSULTATION:
            raise ValidationError(
                "You can write notes only while the patient is in consultation. "
                "Call the patient in first."
            )
        return VisitRecord.objects.create(
            appointment=entry.appointment,
            patient=entry.appointment.patient,
            doctor=doctor,
            **cleaned,
        )
    if record.doctor_id != doctor.pk:
        raise ValidationError("Only the doctor who wrote these notes can change them.")
    if timezone.now() - record.created_at > EDIT_WINDOW:
        raise ValidationError(
            "These notes were saved more than 24 hours ago, so they can no longer be changed."
        )
    for field, value in cleaned.items():
        setattr(record, field, value)
    record.save()
    return record


def has_patient_in_queue(doctor, patient):
    """Tell whether the patient is in this doctor's queue right now (PRIV-05)."""
    return QueueEntry.objects.filter(
        doctor=doctor,
        queue_date=timezone.localdate(),
        appointment__patient=patient,
        state__in=IN_QUEUE_STATES,
    ).exists()


def can_read_visit_record(user, record):
    """Decide whether someone may read a visit record (VIS-01, PRIV-05, SEC-01).

    Only the doctor who wrote it, and a doctor who has the patient in their
    queue right now, may read it. Receptionists, the administrator and
    patients may not (patients get their own summary in VIS-05).

    Args:
        user: The logged-in account.
        record: The VisitRecord.

    Returns:
        True when the person may read the notes.
    """
    doctor = doctor_profile(user)
    if doctor is None:
        return False
    return record.doctor_id == doctor.pk or has_patient_in_queue(doctor, record.patient)


def readable_history(user, patient):
    """List the patient's visit records this person may read, newest first (PRIV-05).

    Args:
        user: The logged-in account.
        patient: The Patient.

    Returns:
        A queryset of VisitRecord. It is empty for anyone who is not a doctor.
    """
    doctor = doctor_profile(user)
    records = VisitRecord.objects.filter(patient=patient).select_related("doctor__user")
    if doctor is None:
        return records.none()
    if has_patient_in_queue(doctor, patient):
        return records
    return records.filter(doctor=doctor)
