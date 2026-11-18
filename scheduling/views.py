"""Pages for the scheduling application."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.permissions import role_required

from .forms import LeaveForm, ScheduleBreakForm, ScheduleRuleForm
from .leave import add_leave
from .models import Doctor, DoctorLeave, ScheduleBreak, ScheduleRule


def _own_doctor(user):
    """Return the doctor profile of the logged-in doctor, or None if there is none."""
    return Doctor.objects.filter(user=user).first()


def _saturday_first(rule):
    """Sort sessions by weekday starting from Saturday, then by start time."""
    return ((rule.weekday - 5) % 7, rule.start_time)


@role_required(User.Role.DOCTOR)
def availability(request):
    """Show the doctor's own weekly sessions and breaks (SCH-02)."""
    doctor = _own_doctor(request.user)
    rules = []
    if doctor is not None:
        rules = sorted(
            doctor.schedule_rules.prefetch_related("breaks"), key=_saturday_first
        )
    return render(request, "scheduling/availability.html", {"doctor": doctor, "rules": rules})


@role_required(User.Role.DOCTOR)
def rule_add(request):
    """Let the doctor add a weekly session (SCH-02)."""
    doctor = _own_doctor(request.user)
    if doctor is None:
        return redirect("scheduling:availability")
    form = ScheduleRuleForm(request.POST or None, doctor=doctor)
    if request.method == "POST" and form.is_valid():
        rule = form.save()
        messages.success(
            request,
            f"Saved. Patients can now book {rule.slot_count} slots "
            f"every {rule.get_weekday_display()}.",
        )
        return redirect("scheduling:availability")
    return render(request, "scheduling/rule_form.html", {"form": form})


@role_required(User.Role.DOCTOR)
@require_POST
def rule_delete(request, rule_id):
    """Let the doctor remove one of their own weekly sessions (SCH-02)."""
    rule = get_object_or_404(ScheduleRule, pk=rule_id, doctor__user=request.user)
    rule.delete()
    messages.success(
        request,
        "The session was removed. Appointments that are already booked are not changed.",
    )
    return redirect("scheduling:availability")


@role_required(User.Role.DOCTOR)
def break_add(request, rule_id):
    """Let the doctor add a break to one of their own sessions (SCH-02)."""
    rule = get_object_or_404(ScheduleRule, pk=rule_id, doctor__user=request.user)
    form = ScheduleBreakForm(request.POST or None, rule=rule)
    if request.method == "POST" and form.is_valid():
        form.save()
        rule = ScheduleRule.objects.get(pk=rule.pk)
        messages.success(
            request,
            f"The break was saved. {rule.slot_count} slots are now offered "
            f"every {rule.get_weekday_display()}.",
        )
        return redirect("scheduling:availability")
    return render(request, "scheduling/break_form.html", {"form": form, "rule": rule})


@role_required(User.Role.DOCTOR)
@require_POST
def break_delete(request, break_id):
    """Let the doctor remove a break from one of their own sessions (SCH-02)."""
    session_break = get_object_or_404(ScheduleBreak, pk=break_id, rule__doctor__user=request.user)
    session_break.delete()
    messages.success(request, "The break was removed.")
    return redirect("scheduling:availability")


@role_required(User.Role.DOCTOR)
def leave_list(request):
    """Show the doctor's leave and let them add more (SCH-03)."""
    doctor = _own_doctor(request.user)
    if doctor is None:
        return render(request, "scheduling/leave.html", {"doctor": None})
    form = LeaveForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            result = add_leave(
                doctor,
                data["start_date"],
                data["end_date"],
                data["start_time"],
                data["end_time"],
                data["reason"],
            )
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        else:
            _report_leave(request, result)
            return redirect("scheduling:leave_list")
    leaves = doctor.leaves.filter(end_date__gte=timezone.localdate())
    return render(
        request, "scheduling/leave.html", {"doctor": doctor, "form": form, "leaves": leaves}
    )


def _report_leave(request, result):
    """Tell the doctor what the leave changed (SCH-03, NOT-03)."""
    count = len(result.rescheduled)
    messages.success(
        request,
        f"Leave saved for {result.leave}. No new bookings will be made for that time. "
        f"{count} appointment{'s' if count != 1 else ''} need{'' if count != 1 else 's'} a "
        f"new time, and the patients have been told.",
    )
    if result.failed_notices:
        names = ", ".join(a.patient.full_name for a in result.failed_notices)
        messages.warning(
            request,
            f"A text message could not be sent to: {names}. "
            "Please ask reception to call them.",
        )


@role_required(User.Role.DOCTOR)
@require_POST
def leave_delete(request, leave_id):
    """Let the doctor remove one of their own leaves (SCH-03)."""
    leave = get_object_or_404(DoctorLeave, pk=leave_id, doctor__user=request.user)
    leave.delete()
    messages.success(
        request,
        "The leave was removed and the times are open for booking again. Appointments "
        "that were already moved to 'Needs rescheduling' are not changed; reception "
        "can help rebook them.",
    )
    return redirect("scheduling:leave_list")