"""Pages the receptionist uses to manage today's queues (QUE-03)."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import User
from accounts.permissions import role_required

from .models import QueueEntry
from .reception_forms import WalkInForm
from .services import patients_ahead
from .walkin import find_or_create_walk_in_patient, register_walk_in


@role_required(User.Role.RECEPTIONIST)
def walk_in(request):
    """Screen 1 of 2: type name, phone, age and choose a doctor (QUE-03, USAB-03)."""
    form = WalkInForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            patient, created = find_or_create_walk_in_patient(
                data["full_name"], data["mobile_number"], data["age"]
            )
            entry = register_walk_in(patient, data["doctor"], request.user, data["reason"])
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        else:
            if not created:
                messages.info(
                    request,
                    f"This number already belongs to {patient.full_name}, "
                    "so the existing patient record was used.",
                )
            return redirect("reception_queue:walk_in_done", entry_id=entry.pk)
    return render(request, "queueing/reception/walk_in.html", {"form": form})


@role_required(User.Role.RECEPTIONIST)
def walk_in_done(request, entry_id):
    """Screen 2 of 2: show the token to tell the patient (QUE-03, BR-14)."""
    entry = get_object_or_404(
        QueueEntry.objects.select_related("doctor__user", "appointment__patient"), pk=entry_id
    )
    return render(
        request,
        "queueing/reception/walk_in_done.html",
        {"entry": entry, "ahead": patients_ahead(entry)},
    )
