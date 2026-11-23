"""Doctor-facing live queue pages (QUE-06, PERF-03, SEC-01)."""

from django.http import JsonResponse
from django.shortcuts import render

from accounts.models import User
from accounts.permissions import role_required

from .doctor_queue import doctor_queue_snapshot

TEMPLATE_NAME = "queueing/doctor/live_queue.html"
NO_PROFILE_MESSAGE = (
    "Your doctor profile has not been created yet. "
    "Ask the clinic administrator to create it, then reload this page."
)


def _doctor_for(request):
    """Return the logged-in doctor's own profile, or None when it is missing."""
    return getattr(request.user, "doctor", None)


@role_required(User.Role.DOCTOR)
def live_queue(request):
    """Show only the logged-in doctor's waiting patients in calling order."""
    doctor = _doctor_for(request)
    if doctor is None:
        return render(
            request,
            TEMPLATE_NAME,
            {"no_profile": True, "message": NO_PROFILE_MESSAGE},
            status=403,
        )
    return render(request, TEMPLATE_NAME, {"snapshot": doctor_queue_snapshot(doctor)})


@role_required(User.Role.DOCTOR)
def live_queue_data(request):
    """Return the same own-queue snapshot for polling by the doctor's page."""
    doctor = _doctor_for(request)
    if doctor is None:
        return JsonResponse({"error": NO_PROFILE_MESSAGE}, status=403)
    return JsonResponse(doctor_queue_snapshot(doctor))
