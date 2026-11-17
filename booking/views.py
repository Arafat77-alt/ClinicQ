"""Pages for the booking application."""

from django.shortcuts import get_object_or_404, render

from scheduling.models import Doctor

from .availability import free_slots, list_specialties, search_doctors


def doctor_search(request):
    """Let anyone search for doctors by name or specialty (BKG-01).

    The page is open to visitors who are not logged in, because it shows no
    personal data. Logging in is needed only to book (BKG-03).
    """
    query = request.GET.get("q", "").strip()
    doctors = search_doctors(query)
    specialties = list_specialties() if not doctors else []
    return render(
        request,
        "booking/doctor_search.html",
        {"query": query, "doctors": doctors, "specialties": specialties},
    )


def doctor_detail(request, doctor_id):
    """Show a doctor's free slots for the coming days (BKG-02)."""
    doctor = get_object_or_404(Doctor, pk=doctor_id, is_active=True)
    return render(
        request,
        "booking/doctor_detail.html",
        {"doctor": doctor, "days": free_slots(doctor)},
    )