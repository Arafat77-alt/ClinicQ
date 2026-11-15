"""Business rules for the scheduling application."""

from datetime import datetime, time

from django.utils import timezone


def to_minutes(clock):
    """Turn a time of day into minutes since midnight.

    Args:
        clock: A datetime.time.

    Returns:
        The number of minutes since midnight.
    """
    return clock.hour * 60 + clock.minute


def from_minutes(minutes):
    """Turn minutes since midnight back into a time of day.

    Args:
        minutes: Minutes since midnight, below 24 hours.

    Returns:
        A datetime.time.
    """
    return time(minutes // 60, minutes % 60)


def slot_windows(rule):
    """List the bookable slots of one weekly session (SCH-02).

    The session is cut into slots of the chosen length, and every slot that
    overlaps a break is left out. A session of Monday 17:00-21:00 with 15-minute
    slots gives 16 slots. A break from 19:00 to 19:30 removes 2 of them.

    Args:
        rule: A ScheduleRule with start_time, end_time, slot_minutes and breaks.

    Returns:
        A list of (start, end) pairs of datetime.time, in order.
    """
    start = to_minutes(rule.start_time)
    end = to_minutes(rule.end_time)
    step = rule.slot_minutes
    breaks = [(to_minutes(b.start_time), to_minutes(b.end_time)) for b in rule.breaks.all()]
    windows = []
    cursor = start
    while cursor + step <= end:
        slot_end = cursor + step
        inside_break = any(cursor < b_end and slot_end > b_start for b_start, b_end in breaks)
        if not inside_break:
            windows.append((from_minutes(cursor), from_minutes(slot_end)))
        cursor = slot_end
    return windows


def generate_slots(doctor, day):
    """List a doctor's bookable slots on one date (SCH-02, BKG-02).

    Slots come from the weekly sessions, so no slot is stored in the database
    until someone books it. Doctor leave (SCH-03) and clinic closed days
    (SCH-05) will be taken out here later.

    Args:
        doctor: The Doctor.
        day: A datetime.date.

    Returns:
        A list of (start, end) pairs of timezone-aware datetimes, in order.
        Empty when the doctor is not active or has no session that weekday.
    """
    if not doctor.is_active:
        return []
    slots = []
    rules = doctor.schedule_rules.filter(weekday=day.weekday()).prefetch_related("breaks")
    for rule in rules:
        for start, end in slot_windows(rule):
            slots.append(
                (
                    timezone.make_aware(datetime.combine(day, start)),
                    timezone.make_aware(datetime.combine(day, end)),
                )
            )
    return sorted(slots)