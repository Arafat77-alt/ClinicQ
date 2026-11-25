"""Privacy-safe snapshot data for the public waiting-room display (QUE-11, PRIV-03)."""

from django.utils import timezone

from .queue_actions import queue_board

NEXT_TOKEN_COUNT = 3


def _current_row(entry):
    """Describe the active patient's token without any personal details."""
    if entry is None:
        return None
    return {"token": entry.token, "state_display": entry.get_state_display()}


def public_display_snapshot(now=None):
    """Build the Now serving board for the public page and its JSON poll.

    The board is derived from queue_board so BR-08 calling order and BR-11
    (one active patient per doctor) stay in one place. Only doctor codes,
    rooms, token numbers and counts leave this function, so PRIV-03 holds
    for both the page and the three-second poll (PERF-03).

    Args:
        now: Optional current time for deterministic tests.

    Returns:
        A dictionary with the clinic date, one row per doctor and refresh time.
    """
    current_time = now or timezone.now()
    queue_date = timezone.localdate(current_time)
    doctors = []
    for group in queue_board(queue_date=queue_date):
        doctor = group["doctor"]
        waiting = group["waiting"]
        doctors.append(
            {
                "code": doctor.code,
                "room": doctor.room,
                "current": _current_row(group["current"]),
                "waiting_count": len(waiting) + len(group["to_decide"]),
                "next_tokens": [entry.token for entry in waiting[:NEXT_TOKEN_COUNT]],
            }
        )
    return {
        "date": queue_date.strftime("%A, %d %B %Y"),
        "doctors": doctors,
        "updated_at": timezone.localtime(current_time).strftime("%H:%M:%S"),
    }
