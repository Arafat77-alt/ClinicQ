"""Patient live queue status pages and JSON polling endpoint (QUE-04, PERF-03)."""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from accounts.permissions import patient_required
from booking.patient_booking import family_patients

from .live import build_live_queue_status
from .models import QueueEntry


def _authorized_queue_entry(request, appointment_id):
    """Fetch the QueueEntry for an appointment and check patient family ownership."""
    entry = get_object_or_404(
        QueueEntry.objects.select_related("appointment__patient", "doctor__user"),
        appointment_id=appointment_id,
    )
    allowed_ids = family_patients(request.user.patient).values_list("pk", flat=True)
    if entry.appointment.patient_id not in allowed_ids:
        return None
    return entry


@patient_required
def live_status(request, appointment_id):
    """Show the patient's token, queue position and live waiting estimate (QUE-04)."""
    entry = _authorized_queue_entry(request, appointment_id)
    if entry is None:
        return render(request, "accounts/forbidden.html", status=403)
    status = build_live_queue_status(entry)
    return render(
        request,
        "queueing/reception/live_status.html",
        {"entry": entry, "status": status},
    )


@patient_required
def live_status_json(request, appointment_id):
    """Return fresh live queue data for polling within 5 seconds (QUE-04, PERF-03)."""
    entry = _authorized_queue_entry(request, appointment_id)
    if entry is None:
        return JsonResponse({"error": "Access denied."}, status=403)
    return JsonResponse(build_live_queue_status(entry))
