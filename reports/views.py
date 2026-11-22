"""Pages for the reports application (SYS-04)."""

from django.shortcuts import render
from django.utils import timezone

from accounts.models import User
from accounts.permissions import role_required

from .services import schedule_for_day


@role_required(User.Role.RECEPTIONIST)
def print_schedule(request):
    """Show today's schedule, one printed page per doctor (SYS-04, R-09).

    Only receptionists may open it, because it lists patient names and numbers.
    """
    today = timezone.localdate()
    return render(
        request,
        "reports/print_schedule.html",
        {"today": today, "schedule": schedule_for_day(today), "printed_at": timezone.now()},
    )
