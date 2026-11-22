"""Business rules for the reports application (SYS-04)."""

from django.db.models import Q
from django.utils import timezone

from booking.models import Appointment
from scheduling.models import Doctor


def schedule_for_day(day=None):
    """Collect one day's appointments, grouped by doctor, for printing (SYS-04, R-09).

    Every active doctor is listed, even with no appointments, so the printed
    pile has one sheet per doctor. A doctor who was deactivated but still has
    appointments on this day is listed too. Every status is included
    (booked, checked in, cancelled, no-show and so on), because the paper copy
    must show the whole day. Walk-ins have no time slot, so they are found by
    the day of their queue entry and listed after the timed appointments.

    Args:
        day: The clinic day to print. Defaults to today in Dhaka time.

    Returns:
        A list of (doctor, appointments) pairs, ordered by doctor code.
        appointments is a list of Appointment, ordered by time.
    """
    day = day or timezone.localdate()
    appointments = (
        Appointment.objects.filter(
            Q(slot_start__date=day) | Q(slot_start__isnull=True, queue_entry__queue_date=day)
        )
        .select_related("patient", "doctor")
        .order_by("slot_start", "created_at")
    )
    by_doctor = {}
    for appointment in appointments:
        by_doctor.setdefault(appointment.doctor_id, []).append(appointment)

    doctors = Doctor.objects.filter(Q(is_active=True) | Q(pk__in=by_doctor.keys()))
    doctors = doctors.select_related("user").order_by("code")
    schedule = []
    for doctor in doctors:
        doctor_appointments = by_doctor.get(doctor.pk, [])
        # Timed appointments first (in time order), walk-ins last (in arrival order).
        doctor_appointments.sort(key=lambda item: item.slot_start is None)
        schedule.append((doctor, doctor_appointments))
    return schedule
