"""Snapshot data for the doctor's live queue page (QUE-06, QUE-07, PERF-03)."""

from django.utils import timezone

from .queue_actions import queue_board


def _waiting_text(entry, now):
    """Describe how long a patient has waited in plain minutes."""
    minutes = max(0, int((now - entry.check_in_time).total_seconds() // 60))
    return f"{minutes} min"


def _current_row(entry):
    """Describe the doctor's active patient, if there is one."""
    if entry is None:
        return None
    patient = entry.appointment.patient
    start = entry.started_at or entry.called_at
    return {
        "entry_id": entry.pk,
        "token": entry.token,
        "patient_name": patient.full_name,
        "age": patient.age if patient.age is not None else "Not given",
        "reason": entry.appointment.reason or "Not given",
        "state": entry.state,
        "state_display": entry.get_state_display(),
        "started_text": timezone.localtime(start).strftime("%H:%M") if start else "",
    }


def doctor_queue_snapshot(doctor, now=None):
    """Build the doctor's own live queue for the page and its JSON poll.

    queue_board already uses waiting_queue for the calling order, so BR-08
    stays in one place. The active patient is included so a call is visible
    on the doctor's screen within the three-second refresh.

    Args:
        doctor: The logged-in doctor's profile.
        now: Optional current time for deterministic tests.

    Returns:
        A dictionary with the active patient, ordered entries and refresh time.
    """
    current_time = now or timezone.now()
    queue_date = timezone.localdate(current_time)
    board = queue_board(queue_date=queue_date, doctor=doctor)[0]
    entries = board["waiting"]
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
        "current": _current_row(board["current"]),
        "entries": rows,
        "updated_at": timezone.localtime(current_time).strftime("%H:%M:%S"),
    }
