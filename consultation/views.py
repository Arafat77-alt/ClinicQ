"""Pages for the consultation application (VIS-01)."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import User
from accounts.permissions import role_required
from queueing.models import QueueEntry

from .forms import VisitNotesForm
from .models import VisitRecord
from .services import can_read_visit_record, readable_history, save_visit_notes


@role_required(User.Role.DOCTOR)
def visit_notes(request, entry_id):
    """Write or correct the notes for a patient in my queue (VIS-01, BR-15)."""
    entry = get_object_or_404(
        QueueEntry.objects.select_related("doctor", "appointment__patient"), pk=entry_id
    )
    if entry.doctor.user_id != request.user.pk:
        return render(request, "accounts/forbidden.html", status=403)
    record = VisitRecord.objects.filter(appointment=entry.appointment).first()
    form = VisitNotesForm(request.POST if request.method == "POST" else None, instance=record)
    if request.method == "POST" and form.is_valid():
        try:
            record = save_visit_notes(entry, request.user, form.cleaned_data)
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        else:
            saved_at = timezone.localtime(record.updated_at)
            messages.success(request, f"Notes saved at {saved_at:%H:%M}.")
            return redirect("consultation:visit_notes", entry_id=entry.pk)
    patient = entry.appointment.patient
    history = readable_history(request.user, patient).exclude(appointment=entry.appointment)
    return render(
        request,
        "consultation/visit_notes.html",
        {"entry": entry, "patient": patient, "form": form, "record": record, "history": history},
    )


@role_required(User.Role.DOCTOR)
def visit_record_detail(request, record_id):
    """Read one earlier visit record, if PRIV-05 allows it (VIS-01)."""
    record = get_object_or_404(
        VisitRecord.objects.select_related("doctor__user", "patient"), pk=record_id
    )
    if not can_read_visit_record(request.user, record):
        return render(request, "accounts/forbidden.html", status=403)
    return render(request, "consultation/visit_record_detail.html", {"record": record})
