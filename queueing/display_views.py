"""Public waiting-room "Now serving" screen and its JSON poll (QUE-11, PERF-03)."""

from django.http import JsonResponse
from django.shortcuts import render

from .display import public_display_snapshot


def public_display(request):
    """Show the read-only token board; no login and no patient details (PRIV-03)."""
    return render(
        request,
        "queueing/display.html",
        {"display": public_display_snapshot()},
    )


def public_display_data(request):
    """Return a fresh privacy-safe snapshot for the three-second poll (PERF-03)."""
    return JsonResponse(public_display_snapshot())
