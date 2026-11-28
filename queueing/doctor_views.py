"""Doctor-facing live queue pages (QUE-06, PERF-03, SEC-01)."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.permissions import role_required

from .call_next import call_next_patient
from .completion import complete_consultation
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


@role_required(User.Role.DOCTOR)
@require_POST
def call_next(request):
    """Call the first waiting patient in the logged-in doctor's own queue."""
    doctor = _doctor_for(request)
    if doctor is None:
        messages.error(request, NO_PROFILE_MESSAGE)
        return redirect(reverse("queueing:doctor_live_queue"))
    try:
        entry = call_next_patient(doctor)
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    else:
        messages.success(
            request,
            f"Token {entry.token} is now in consultation. Ask the patient to come in.",
        )
    return redirect(reverse("queueing:doctor_live_queue"))

@role_required(User.Role.DOCTOR)
@require_POST
def complete_current(request, entry_id):
    """Complete the current consultation for the logged-in doctor."""
    doctor = _doctor_for(request)
    if doctor is None:
        messages.error(request, NO_PROFILE_MESSAGE)
        return redirect(reverse("queueing:doctor_live_queue"))
    from .models import QueueEntry

    entry = QueueEntry.objects.select_related("doctor").filter(pk=entry_id, doctor=doctor).first()
    if entry is None:
        messages.error(request, "This patient is not in your queue.")
        return redirect(reverse("queueing:doctor_live_queue"))
    try:
        complete_consultation(entry)
    except ValidationError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Token {entry.token} has been marked as completed.")
    return redirect(reverse("queueing:doctor_live_queue"))
