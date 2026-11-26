"""Doctor-facing live queue pages (QUE-06, PERF-03, SEC-01)."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.permissions import role_required

from .call_next import call_next_patient
from .completion import complete_consultation, skip_patient
from .doctor_queue import doctor_queue_snapshot
from .models import ACTIVE_STATES, QueueEntry

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
        messages.error(request, str(error))
    else:
        messages.success(
            request,
            f"Token {entry.token} is now in consultation. Ask the patient to come in.",
        )
    return redirect(reverse("queueing:doctor_live_queue"))


def _active_entry_for(doctor):
    """Return the doctor's currently called or in-consultation entry today."""
    return (
        QueueEntry.objects.filter(
            doctor=doctor,
            queue_date=timezone.localdate(),
            state__in=ACTIVE_STATES,
        )
        .select_related("appointment")
        .first()
    )


@role_required(User.Role.DOCTOR)
@require_POST
def complete_current(request):
    """Mark the logged-in doctor's active consultation as completed."""
    doctor = _doctor_for(request)
    if doctor is None:
        messages.error(request, NO_PROFILE_MESSAGE)
        return redirect(reverse("queueing:doctor_live_queue"))
    entry = _active_entry_for(doctor)
    if entry is None:
        messages.error(request, "No patient is currently in consultation.")
        return redirect(reverse("queueing:doctor_live_queue"))
    try:
        complete_consultation(entry)
    except ValidationError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Consultation for token {entry.token} is now completed.")
    return redirect(reverse("queueing:doctor_live_queue"))


@role_required(User.Role.DOCTOR)
@require_POST
def skip_current(request):
    """Skip the logged-in doctor's currently called patient."""
    doctor = _doctor_for(request)
    if doctor is None:
        messages.error(request, NO_PROFILE_MESSAGE)
        return redirect(reverse("queueing:doctor_live_queue"))
    entry = _active_entry_for(doctor)
    if entry is None:
        messages.error(request, "No patient is currently called or in consultation.")
        return redirect(reverse("queueing:doctor_live_queue"))
    try:
        skip_patient(entry)
    except ValidationError as error:
        messages.error(request, str(error))
    else:
        messages.info(request, f"Token {entry.token} was skipped.")
    return redirect(reverse("queueing:doctor_live_queue"))
