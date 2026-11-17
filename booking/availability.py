"""Finding doctors and their free slots (BKG-01, BKG-02, BKG-09)."""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from scheduling.models import Doctor
from scheduling.services import generate_slots

from .models import ACTIVE_STATUSES, Appointment

# BR-03: patients book from 14 days ahead up to 30 minutes before the slot.
# These become clinic settings that the administrator can change (SCH-04) later.
BOOKING_WINDOW_DAYS = 14
MIN_LEAD_MINUTES = 30


def search_doctors(query):
    """Find active doctors by name or specialty (BKG-01).

    Every word typed must match the first name, the last name or the specialty,
    in any capital letters. The titles "Dr" and "Dr." are ignored. Nothing typed
    lists all active doctors.

    Args:
        query: The text the patient typed.

    Returns:
        A queryset of Doctor, ordered by specialty and name.
    """
    doctors = Doctor.objects.filter(is_active=True).select_related("user")
    words = [word for word in query.replace(".", " ").split() if word.lower() != "dr"]
    for word in words:
        doctors = doctors.filter(
            Q(specialty__icontains=word)
            | Q(user__first_name__icontains=word)
            | Q(user__last_name__icontains=word)
        )
    return doctors.order_by("specialty", "user__first_name", "user__last_name")


def list_specialties():
    """List every specialty that an active doctor offers (BKG-01).

    Returns:
        A sorted list of specialty names, without repeats.
    """
    names = Doctor.objects.filter(is_active=True).values_list("specialty", flat=True)
    return sorted(set(names), key=str.lower)


def free_slots(doctor, now=None, reception=False):
    """List the slots that can still be booked with a doctor (BKG-02, BKG-09, BR-03).

    For patients, a slot is offered when it starts at least 30 minutes from now
    and no more than 14 days ahead. Reception may book until the slot ends, so
    for reception a slot is offered while it has not finished. In both cases a
    slot held by an active appointment is hidden, and a cancelled appointment
    frees its slot (BR-01).

    Args:
        doctor: The Doctor.
        now: The current time. Only tests pass this.
        reception: True when a receptionist is booking.

    Returns:
        A list of (date, slots) pairs in date order, where slots is a list of
        (start, end) timezone-aware datetimes. Days without free slots are left out.
    """
    now = now or timezone.now()
    earliest = now + timedelta(minutes=MIN_LEAD_MINUTES)
    latest = now + timedelta(days=BOOKING_WINDOW_DAYS)
    first_moment = now - timedelta(days=1) if reception else earliest
    taken = set(
        Appointment.objects.filter(
            doctor=doctor,
            status__in=ACTIVE_STATUSES,
            slot_start__gte=first_moment,
            slot_start__lte=latest,
        ).values_list("slot_start", flat=True)
    )

    def can_book(start, end):
        """Apply the booking rule of the person who is booking."""
        if reception:
            return end > now and start <= latest
        return earliest <= start <= latest

    result = []
    day = timezone.localdate(now if reception else earliest)
    last_day = timezone.localdate(latest)
    while day <= last_day:
        slots = [
            (start, end)
            for start, end in generate_slots(doctor, day)
            if can_book(start, end) and start not in taken
        ]
        if slots:
            result.append((day, slots))
        day += timedelta(days=1)
    return result