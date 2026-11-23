"""Snapshot data for the doctor's live queue page (QUE-06, PERF-03)."""

from django.utils import timezone

from .services import waiting_queue


def _waiting_text(entry, now):
    """Describe how long a patient has waited in plain minutes."""
    minutes = max(0, int((now - entry.check_in_time).total_seconds() // 60))
    return f"{minutes} min"


def doctor_queue_snapshot(doctor, now=None):
    """Build the doctor's own waiting queue for the page and its JSON poll.

    The calling order comes only from waiting_queue, so BR-08 stays in one
    place. Emergency first, then earliest effective time, then earliest
    check-in time are already applied there.

    Args:
        doctor: The logged-in doctor's profile.
        now: Optional current time for deterministic tests.

    Returns:
        A dictionary with the ordered entries and the refresh time.
    """
    current_time = now or timezone.now()
    queue_date = timezone.localdate(current_time)
    entries = waiting_queue(doctor, queue_date)
    rows = []
    for position, entry in enumerate(entries, start=1):
        patient = entry.appointment.patient
        rows.append(
            {
                "position": position,
                "entry_id": entry.pk,
                "token": entry.token,
                "patient_name": patient.full_name,
                "age": patient.age if patient.age is not None else "Not given",
                "reason": entry.appointment.reason or "Not given",
                "waiting_text": _waiting_text(entry, current_time),
                "is_emergency": entry.is_emergency,
                "emergency_reason": entry.emergency_reason if entry.is_emergency else "",
            }
        )
    return {
        "entries": rows,
        "updated_at": timezone.localtime(current_time).strftime("%H:%M:%S"),
    }
