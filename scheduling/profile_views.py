"""Pages for the clinic administrator to manage doctor profiles (SCH-01)."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.permissions import role_required
from booking.models import ACTIVE_STATUSES, Appointment

from .models import Doctor
from .profile_forms import DoctorProfileForm


@role_required(User.Role.ADMIN)
def doctor_list(request):
    """List all doctor profiles for the clinic administrator (SCH-01)."""
    doctors = Doctor.objects.select_related("user").order_by("code")
    return render(request, "scheduling/doctor_list.html", {"doctors": doctors})


@role_required(User.Role.ADMIN)
def doctor_create(request):
    """Let the clinic administrator add a new doctor profile (SCH-01)."""
    form = DoctorProfileForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        doctor = form.save()
        messages.success(
            request,
            f"{doctor} was added and now appears in patient search.",
        )
        return redirect("scheduling:doctor_list")
    return render(
        request,
        "scheduling/doctor_form.html",
        {"form": form, "editing": False},
    )


@role_required(User.Role.ADMIN)
def doctor_edit(request, doctor_id):
    """Let the clinic administrator edit an existing doctor profile (SCH-01)."""
    doctor = get_object_or_404(Doctor, pk=doctor_id)
    form = DoctorProfileForm(request.POST or None, instance=doctor)
    if request.method == "POST" and form.is_valid():
        doctor = form.save()
        messages.success(request, f"The profile for {doctor} was updated.")
        return redirect("scheduling:doctor_list")
    return render(
        request,
        "scheduling/doctor_form.html",
        {"form": form, "doctor": doctor, "editing": True},
    )


@role_required(User.Role.ADMIN)
def doctor_delete(request, doctor_id):
    """Offer to deactivate a doctor instead of deleting them (SCH-01 Confirmation 2).

    A doctor is never deleted so that past and future appointments keep their
    history. When the administrator tries to delete a doctor, this page
    explains why deletion is blocked and offers a one-click Deactivate action.
    """
    doctor = get_object_or_404(Doctor, pk=doctor_id)
    future_count = Appointment.objects.filter(
        doctor=doctor,
        status__in=ACTIVE_STATUSES,
        slot_start__gte=timezone.now(),
    ).count()
    if request.method == "POST":
        doctor.is_active = False
        doctor.save(update_fields=["is_active"])
        messages.warning(
            request,
            f"{doctor} cannot be deleted because clinic records must be preserved. "
            "The doctor has been deactivated instead and no longer appears in search.",
        )
        return redirect("scheduling:doctor_list")
    return render(
        request,
        "scheduling/doctor_delete_confirm.html",
        {"doctor": doctor, "future_count": future_count},
    )


@role_required(User.Role.ADMIN)
@require_POST
def doctor_deactivate(request, doctor_id):
    """Deactivate a doctor profile so they disappear from search and booking (SCH-01)."""
    doctor = get_object_or_404(Doctor, pk=doctor_id)
    doctor.is_active = False
    doctor.save(update_fields=["is_active"])
    messages.success(
        request,
        f"{doctor} was deactivated and removed from patient search and booking.",
    )
    return redirect("scheduling:doctor_list")
