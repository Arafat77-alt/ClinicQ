"""Live queue status and waiting-time estimation helpers (QUE-04, BR-12)."""

from django.utils import timezone

from .estimate import MAX_RECENT_VISITS, estimate_waiting_range, format_waiting_estimate
from .models import ACTIVE_STATES, QueueEntry
from .services import patients_ahead


def recent_consultation_durations(doctor):
    """Return completed consultation lengths in minutes for a doctor (QUE-04, BR-12).

    Collects up to the last 20 completed visits that have both start and
    completion timestamps, ordered from oldest to newest.

    Args:
        doctor: The Doctor whose recent consultations are measured.

    Returns:
        A list of consultation durations in minutes (float).
    """
    entries = list(
        QueueEntry.objects.filter(
            doctor=doctor,
            state=QueueEntry.State.COMPLETED,
            started_at__isnull=False,
            completed_at__isnull=False,
        ).order_by("-completed_at")[:MAX_RECENT_VISITS]
    )
    entries.reverse()
    return [
        max(0.0, (entry.completed_at - entry.started_at).total_seconds() / 60.0)
        for entry in entries
    ]


def current_consultation_elapsed_minutes(doctor, queue_date, now=None):
    """Return minutes already spent with the doctor's active patient (BR-12).

    Args:
        doctor: The Doctor.
        queue_date: The clinic day.
        now: Optional timezone-aware current time. Defaults to current server time.

    Returns:
        Elapsed minutes as a non-negative float, or 0.0 when nobody is active.
    """
    active = (
        QueueEntry.objects.filter(
            doctor=doctor,
            queue_date=queue_date,
            state__in=ACTIVE_STATES,
        )
        .order_by("-started_at", "-called_at")
        .first()
    )
    if active is None:
        return 0.0
    start = active.started_at or active.called_at
    if start is None:
        return 0.0
    current_time = now or timezone.now()
    return max(0.0, (current_time - start).total_seconds() / 60.0)


def _estimate_text_for_state(
    entry,
    ahead,
    completed_durations,
    elapsed_minutes,
):
    """Return the plain-language wait or status message for a queue state."""
    if entry.state == QueueEntry.State.WAITING:
        return format_waiting_estimate(
            patients_ahead=ahead,
            completed_durations=completed_durations,
            minutes_with_current_patient=elapsed_minutes,
            default_slot_minutes=entry.doctor.default_slot_minutes,
        )
    if entry.state in ACTIVE_STATES:
        return "Your turn now"
    if entry.state == QueueEntry.State.COMPLETED:
        return "Consultation completed"
    return "Please speak to reception"


def build_live_queue_status(entry, now=None):
    """Build the live token, position and wait estimate data for a patient (QUE-04).

    Args:
        entry: The patient's QueueEntry.
        now: Optional timezone-aware current time for deterministic tests.

    Returns:
        A dictionary containing token, state, position, patients_ahead,
        estimate_low, estimate_high, estimate_text, doctor details and
        updated_at timestamp in Dhaka local time.
    """
    current_time = now or timezone.now()
    ahead = patients_ahead(entry) if entry.state == QueueEntry.State.WAITING else 0
    position = ahead + 1 if entry.state == QueueEntry.State.WAITING else 0

    completed_durations = recent_consultation_durations(entry.doctor)
    elapsed_minutes = current_consultation_elapsed_minutes(
        entry.doctor, entry.queue_date, now=current_time
    )

    if entry.state == QueueEntry.State.WAITING:
        low, high = estimate_waiting_range(
            patients_ahead=ahead,
            completed_durations=completed_durations,
            minutes_with_current_patient=elapsed_minutes,
            default_slot_minutes=entry.doctor.default_slot_minutes,
        )
    else:
        low, high = (0, 0)

    estimate_text = _estimate_text_for_state(
        entry=entry,
        ahead=ahead,
        completed_durations=completed_durations,
        elapsed_minutes=elapsed_minutes,
    )
    doctor_user = entry.doctor.user
    doctor_name = doctor_user.get_full_name() or doctor_user.username
    local_time = timezone.localtime(current_time)

    return {
        "token": entry.token,
        "state": entry.state,
        "state_display": entry.get_state_display(),
        "position": position,
        "patients_ahead": ahead,
        "estimate_low": low,
        "estimate_high": high,
        "estimate_text": estimate_text,
        "doctor_name": f"Dr. {doctor_name}",
        "doctor_specialty": entry.doctor.specialty,
        "room": entry.doctor.room,
        "updated_at": local_time.strftime("%H:%M:%S"),
    }
