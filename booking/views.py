"""Pages for the booking application."""

from datetime import datetime

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import Patient, User
from accounts.patients import create_patient_for_reception, find_patients
from accounts.permissions import role_required
from scheduling.models import Doctor

from .availability import free_slots, list_specialties, search_doctors
from .forms import NewPatientForm, ReceptionBookingForm
from .models import Appointment
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
    """Show a doctor's free slots for the coming days (BKG-02)."""
    doctor = get_object_or_404(Doctor, pk=doctor_id, is_active=True)
    return render(
        request,
        "booking/doctor_detail.html",
        {"doctor": doctor, "days": free_slots(doctor)},
    )


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