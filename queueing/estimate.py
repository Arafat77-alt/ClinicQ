"""Estimated waiting time calculation for the live queue (QUE-04, QUE-13, BR-12)."""

# BR-12 defaults from SRS Section 3.3.
MIN_COMPLETED_VISITS_FOR_AVERAGE = 5
MAX_RECENT_VISITS = 20
DEFAULT_SLOT_MINUTES = 15
RANGE_LOW_FACTOR = 0.8
RANGE_HIGH_FACTOR = 1.2
ROUNDING_STEP_MINUTES = 5


def round_to_nearest_five(minutes):
    """Round a number of minutes to the nearest 5 minutes (BR-12).

    Values halfway or higher round up, so 28.8 becomes 30 and 43.2 becomes 45.

    Args:
        minutes: A non-negative number of minutes.

    Returns:
        An integer multiple of 5, never below 0.
    """
    if minutes <= 0:
        return 0
    return int((minutes + (ROUNDING_STEP_MINUTES / 2)) // ROUNDING_STEP_MINUTES) * ROUNDING_STEP_MINUTES


def average_consultation_minutes(
    completed_durations=(),
    default_slot_minutes=DEFAULT_SLOT_MINUTES,
):
    """Work out the doctor's average consultation time in minutes (QUE-04, QUE-13, BR-12).

    Uses the doctor's last 20 completed consultations. When fewer than 5
    completed consultations exist, returns the doctor's default slot length.

    Args:
        completed_durations: Sequence of completed consultation lengths in minutes,
            ordered from oldest to newest.
        default_slot_minutes: The doctor's slot length (default 15 minutes).

    Returns:
        The average consultation length in minutes as a float.
    """
    recent = [d for d in list(completed_durations)[-MAX_RECENT_VISITS:] if d and d > 0]
    if len(recent) < MIN_COMPLETED_VISITS_FOR_AVERAGE:
        return float(default_slot_minutes)
    return sum(recent) / len(recent)


def estimate_waiting_range(
    patients_ahead,
    completed_durations=(),
    minutes_with_current_patient=0,
    default_slot_minutes=DEFAULT_SLOT_MINUTES,
):
    """Calculate the estimated waiting time range in minutes (QUE-04, BR-12).

    Formula from BR-12:
        EWT = (patients_ahead * doctor's average consultation time)
              - time already spent with the current patient (never below 0).
    The result is returned as a (low, high) range of -20% to +20%, rounded to
    the nearest 5 minutes.

    Args:
        patients_ahead: Number of patients ahead in the queue (0 or more).
        completed_durations: Sequence of completed consultation durations in minutes.
        minutes_with_current_patient: Minutes already spent with the current patient.
        default_slot_minutes: Fallback slot length when fewer than 5 visits exist.

    Returns:
        A (low_minutes, high_minutes) tuple of integers rounded to the nearest 5.
    """
    if patients_ahead <= 0:
        return (0, 0)
    average = average_consultation_minutes(
        completed_durations=completed_durations,
        default_slot_minutes=default_slot_minutes,
    )
    spent = max(0.0, float(minutes_with_current_patient))
    raw_minutes = max(0.0, (patients_ahead * average) - spent)
    low = round_to_nearest_five(raw_minutes * RANGE_LOW_FACTOR)
    high = round_to_nearest_five(raw_minutes * RANGE_HIGH_FACTOR)
    return (low, high)


def format_waiting_estimate(
    patients_ahead,
    completed_durations=(),
    minutes_with_current_patient=0,
    default_slot_minutes=DEFAULT_SLOT_MINUTES,
):
    """Return a plain-language waiting time range for the patient screen (QUE-04, BR-12).

    Examples:
        "about 30–45 min" or "about 0–5 min".

    Args:
        patients_ahead: Number of patients ahead in the queue.
        completed_durations: Sequence of completed consultation durations in minutes.
        minutes_with_current_patient: Minutes already spent with the current patient.
        default_slot_minutes: Fallback slot length when fewer than 5 visits exist.

    Returns:
        A human-readable string showing the estimated range.
    """
    low, high = estimate_waiting_range(
        patients_ahead=patients_ahead,
        completed_durations=completed_durations,
        minutes_with_current_patient=minutes_with_current_patient,
        default_slot_minutes=default_slot_minutes,
    )
    if low == high:
        return f"about {low} min"
    return f"about {low}–{high} min"
