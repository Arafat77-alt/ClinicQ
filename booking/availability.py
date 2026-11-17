"""Finding doctors and their free slots (BKG-01, BKG-02)."""

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


def free_slots(doctor, now=None):
    """List the slots a patient can still book with a doctor (BKG-02, BR-03).

    A slot is offered when it starts at least 30 minutes from now and no more
    than 14 days ahead, and no active appointment already holds it. Cancelled
    appointments free their slot (BR-01).

    Args:
        doctor: The Doctor.
        now: The current time. Only tests pass this.

    Returns:
        A list of (date, slots) pairs in date order, where slots is a list of
        (start, end) timezone-aware datetimes. Days without free slots are left out.
    """
    now = now or timezone.now()
    earliest = now + timedelta(minutes=MIN_LEAD_MINUTES)
    latest = now + timedelta(days=BOOKING_WINDOW_DAYS)
    taken = set(
        Appointment.objects.filter(
            doctor=doctor,
            status__in=ACTIVE_STATUSES,
            slot_start__gte=earliest,
            slot_start__lte=latest,
        ).values_list("slot_start", flat=True)
    )
    result = []
    day = timezone.localdate(earliest)
    last_day = timezone.localdate(latest)
    while day <= last_day:
        slots = [
            (start, end)
            for start, end in generate_slots(doctor, day)
            if earliest <= start <= latest and start not in taken
        ]
        if slots:
            result.append((day, slots))
        day += timedelta(days=1)
    return result