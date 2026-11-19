"""Pages for the booking application."""

from datetime import datetime

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Patient, User
from accounts.patients import create_patient_for_reception, find_patients
from accounts.permissions import patient_required, role_required
from scheduling.models import Doctor

from .availability import free_slots, list_specialties, search_doctors
from .forms import NewPatientForm, PatientBookingForm, ReceptionBookingForm
from .models import Appointment
from .patient_booking import (
    book_online_appointment,
    cancel_patient_appointment,
    family_patients,
    list_patient_appointments,
)
from .reception import book_for_patient


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
    """Show a doctor's free slots for the coming days (BKG-02, BKG-03)."""
    doctor = get_object_or_404(Doctor, pk=doctor_id, is_active=True)
    is_patient = (
        request.user.is_authenticated
        and request.user.role == User.Role.PATIENT
        and hasattr(request.user, "patient")
    )
    patients = family_patients(request.user.patient) if is_patient else []
    return render(
        request,
        "booking/doctor_detail.html",
        {
            "doctor": doctor,
            "days": free_slots(doctor),
            "is_patient": is_patient,
            "patients": patients,
        },
    )


@patient_required
def book_slot(request, doctor_id):
    """Confirm and create an online appointment for a patient or dependent (BKG-03)."""
    doctor = get_object_or_404(Doctor, pk=doctor_id, is_active=True)
    guardian_patient = request.user.patient
    patients = list(family_patients(guardian_patient))

    if request.method == "POST":
        form = PatientBookingForm(request.POST)
        if form.is_valid():
            try:
                slot_start = datetime.fromisoformat(form.cleaned_data["slot_start"])
                if timezone.is_naive(slot_start):
                    slot_start = timezone.make_aware(slot_start)
                appointment = book_online_appointment(
                    guardian_patient=guardian_patient,
                    target_patient_id=form.cleaned_data["patient_id"],
                    doctor=doctor,
                    slot_start=slot_start,
                    booked_by=request.user,
                    reason=form.cleaned_data["reason"],
                )
            except ValueError:
                form.add_error(
                    None, "The selected time was not understood. Please pick a slot again."
                )
            except ValidationError as error:
                for message in error.messages:
                    form.add_error(None, message)
            else:
                messages.success(
                    request,
                    f"Appointment booked! Reference number: {appointment.reference_number}.",
                )
                return redirect(
                    "booking:booking_confirmation", appointment_id=appointment.pk
                )
        slot_param = request.POST.get("slot_start", "")
    else:
        slot_param = request.GET.get("slot", "")
        form = PatientBookingForm(
            initial={"patient_id": guardian_patient.pk, "slot_start": slot_param}
        )

    selected_slot = None
    if slot_param:
        try:
            parsed = datetime.fromisoformat(slot_param)
            selected_slot = (
                timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
            )
        except ValueError:
            selected_slot = None

    return render(
        request,
        "booking/book_confirm.html",
        {
            "doctor": doctor,
            "form": form,
            "patients": patients,
            "selected_slot": selected_slot,
            "days": free_slots(doctor),
        },
    )


@patient_required
def booking_confirmation(request, appointment_id):
    """Display the confirmed appointment and reference number to the patient (BKG-03)."""
    appointment = get_object_or_404(
        Appointment.objects.select_related("patient", "doctor", "doctor__user"),
        pk=appointment_id,
        patient__in=family_patients(request.user.patient),
    )
    return render(
        request,
        "booking/booking_confirmation.html",
        {"appointment": appointment},
    )


@patient_required
def my_appointments(request):
    """Show upcoming and past appointments for the patient and dependents (BKG-04)."""
    upcoming, past = list_patient_appointments(request.user.patient)
    return render(
        request,
        "booking/my_appointments.html",
        {
            "upcoming": upcoming,
            "past": past,
            "guardian_patient": request.user.patient,
        },
    )


@patient_required
@require_POST
def cancel_appointment(request, appointment_id):
    """Cancel an eligible upcoming appointment for the patient or dependent (BKG-05)."""
    try:
        appointment = cancel_patient_appointment(request.user.patient, appointment_id)
    except ValidationError as error:
        for message in error.messages:
            messages.error(request, message)
    else:
        messages.success(
            request,
            f"Appointment {appointment.reference_number} has been cancelled and the time slot is now released.",
        )
    return redirect("booking:my_appointments")


@role_required(User.Role.RECEPTIONIST)
def reception_start(request):
    """Step 1: find the caller, or register them if they have no record (BKG-09)."""
    query = request.GET.get("q", "").strip()
    patients = find_patients(query)
    form = NewPatientForm(request.POST or None, initial={"mobile_number": query})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            patient = create_patient_for_reception(
                data["full_name"], data["mobile_number"], data["age"]
            )
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        else:
            messages.success(request, f"{patient.full_name} was registered.")
            return redirect("booking:reception_doctors", patient_id=patient.pk)
    return render(
        request,
        "booking/reception_start.html",
        {"query": query, "patients": patients, "form": form, "searched": bool(query)},
    )


@role_required(User.Role.RECEPTIONIST)
def reception_doctors(request, patient_id):
    """Step 2: choose the doctor (BKG-09)."""
    patient = get_object_or_404(Patient, pk=patient_id)
    doctors = Doctor.objects.filter(is_active=True).select_related("user")
    doctors = doctors.order_by("specialty", "user__first_name", "user__last_name")
    return render(
        request, "booking/reception_doctors.html", {"patient": patient, "doctors": doctors}
    )


@role_required(User.Role.RECEPTIONIST)
def reception_slots(request, patient_id, doctor_id):
    """Step 3: choose a free time and confirm the booking (BKG-09)."""
    patient = get_object_or_404(Patient, pk=patient_id)
    doctor = get_object_or_404(Doctor, pk=doctor_id, is_active=True)
    form = ReceptionBookingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            slot_start = datetime.fromisoformat(form.cleaned_data["slot_start"])
            if timezone.is_naive(slot_start):
                slot_start = timezone.make_aware(slot_start)
            appointment = book_for_patient(
                patient, doctor, slot_start, request.user, form.cleaned_data["reason"]
            )
        except ValueError:
            form.add_error(None, "The chosen time was not understood. Choose a time again.")
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        else:
            return redirect("booking:reception_confirmation", appointment_id=appointment.pk)
    days = free_slots(doctor, reception=True)
    return render(
        request,
        "booking/reception_slots.html",
        {"patient": patient, "doctor": doctor, "days": days, "form": form},
    )


@role_required(User.Role.RECEPTIONIST)
def reception_confirmation(request, appointment_id):
    """Show the booking, with the reference number to read to the caller (BKG-09)."""
    appointment = get_object_or_404(Appointment, pk=appointment_id)
    return render(request, "booking/reception_confirmation.html", {"appointment": appointment})