"""Pages the receptionist uses to manage today's queues (QUE-01, QUE-03, QUE-09, QUE-10)."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.permissions import role_required
from booking.models import Appointment

from .checkin import check_in_booked_appointment, find_appointments_for_check_in
from .models import QueueEntry
from .queue_actions import flag_emergency, queue_board, remove_from_queue, return_to_queue
from .reception_forms import CheckInSearchForm, ReasonForm, WalkInForm
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


@role_required(User.Role.RECEPTIONIST)
def check_in(request):
    """Find a booked patient's appointment for check-in (QUE-01, USAB-03)."""
    form = CheckInSearchForm(request.POST if request.method == "POST" else None)
    appointments = []
    searched = False
    if request.method == "POST" and form.is_valid():
        appointments = find_appointments_for_check_in(form.cleaned_data["query"])
        searched = True
        if not appointments:
            form.add_error(
                None,
                "No appointment was found for today. Check the reference number or mobile "
                "number, or register the patient as a walk-in.",
            )
    return render(
        request,
        "queueing/reception/check_in.html",
        {"form": form, "appointments": appointments, "searched": searched},
    )


@role_required(User.Role.RECEPTIONIST)
@require_POST
def check_in_appointment(request, appointment_id):
    """Check in the selected appointment and give the patient a token (QUE-01)."""
    appointment = get_object_or_404(Appointment, pk=appointment_id)
    try:
        entry, was_late = check_in_booked_appointment(appointment)
    except ValidationError as error:
        for message in error.messages:
            messages.error(request, message)
        return redirect("reception_queue:check_in")
    if was_late:
        messages.info(
            request,
            "Late arrival: the patient keeps the appointment and joins the queue from "
            "the check-in time, not the original slot time.",
        )
    else:
        messages.success(request, "The patient is checked in and in the queue.")
    return redirect("reception_queue:check_in_done", entry_id=entry.pk)


@role_required(User.Role.RECEPTIONIST)
def check_in_done(request, entry_id):
    """Show the token issued at check-in so the receptionist can tell the patient (BR-14)."""
    entry = get_object_or_404(
        QueueEntry.objects.select_related("doctor__user", "appointment__patient"), pk=entry_id
    )
    return render(
        request,
        "queueing/reception/check_in_done.html",
        {"entry": entry, "ahead": patients_ahead(entry)},
    )


def _entry_or_forbidden(request, entry_id):
    """Return the queue entry, or None when a doctor asks for another doctor's patient.

    Receptionists may open any entry. A doctor may open only entries in their
    own queue (SEC-01).
    """
    entry = get_object_or_404(
        QueueEntry.objects.select_related("doctor__user", "appointment__patient"), pk=entry_id
    )
    if request.user.role == User.Role.DOCTOR and entry.doctor.user_id != request.user.pk:
        return None
    return entry


@role_required(User.Role.RECEPTIONIST, User.Role.DOCTOR)
def board(request):
    """Show today's queues: all doctors for reception, the own queue for a doctor.

    Supports QUE-09 (emergencies at the top, with an alert for the doctor) and
    QUE-10 (remove a patient, and decide about patients skipped twice).
    """
    doctor = None
    if request.user.role == User.Role.DOCTOR:
        doctor = getattr(request.user, "doctor", None)
        if doctor is None:
            return render(request, "queueing/reception/board.html", {"no_profile": True})
    return render(request, "queueing/reception/board.html", {"board": queue_board(doctor=doctor)})


@role_required(User.Role.RECEPTIONIST, User.Role.DOCTOR)
def emergency(request, entry_id):
    """Flag a waiting patient as an emergency, with a reason (QUE-09, BR-09)."""
    entry = _entry_or_forbidden(request, entry_id)
    if entry is None:
        return render(request, "accounts/forbidden.html", status=403)
    form = ReasonForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            flag_emergency(entry, request.user, form.cleaned_data["reason"])
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        else:
            messages.success(
                request, f"Token {entry.token} is now an emergency and is first in the queue."
            )
            return redirect("reception_queue:board")
    return render(
        request,
        "queueing/reception/reason_form.html",
        {
            "entry": entry,
            "form": form,
            "heading": "Flag as an emergency",
            "explanation": "The patient moves to the front of the doctor's queue and the "
            "doctor is alerted. Your name and the time are recorded.",
            "button": "Flag as emergency",
            "button_class": "btn-danger",
        },
    )


@role_required(User.Role.RECEPTIONIST)
def remove(request, entry_id):
    """Remove a patient from the queue, with a reason (QUE-10, BR-10)."""
    entry = get_object_or_404(
        QueueEntry.objects.select_related("doctor__user", "appointment__patient"), pk=entry_id
    )
    form = ReasonForm(
        request.POST if request.method == "POST" else None, initial={"reason": "Left the clinic"}
    )
    if request.method == "POST" and form.is_valid():
        try:
            remove_from_queue(entry, request.user, form.cleaned_data["reason"])
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        else:
            messages.success(
                request,
                f"Token {entry.token} was removed from the queue. The others moved up.",
            )
            return redirect("reception_queue:board")
    return render(
        request,
        "queueing/reception/reason_form.html",
        {
            "entry": entry,
            "form": form,
            "heading": "Remove from the queue",
            "explanation": "The patient leaves the queue and the appointment is cancelled. "
            "The patients behind move up.",
            "button": "Remove from the queue",
            "button_class": "btn-outline-danger",
        },
    )


@role_required(User.Role.RECEPTIONIST)
@require_POST
def return_entry(request, entry_id):
    """Return a patient who was skipped twice to the end of the queue (QUE-10, BR-10)."""
    entry = get_object_or_404(QueueEntry, pk=entry_id)
    try:
        return_to_queue(entry, request.user)
    except ValidationError as error:
        for message in error.messages:
            messages.error(request, message)
    else:
        messages.success(request, f"Token {entry.token} is back in the queue, at the end.")
    return redirect("reception_queue:board")
