"""Web addresses for the receptionist's queue pages (QUE-03, QUE-09, QUE-10).

Kept apart from queueing/urls.py, which belongs to Person B, so that the two
files never conflict.
"""

from django.urls import path

from . import reception_views

app_name = "reception_queue"

urlpatterns = [
    path("check-in/", reception_views.check_in, name="check_in"),
    path(
        "check-in/<int:appointment_id>/",
        reception_views.check_in_appointment,
        name="check_in_appointment",
    ),
    path("check-in/<int:entry_id>/done/", reception_views.check_in_done, name="check_in_done"),
    path("walk-in/", reception_views.walk_in, name="walk_in"),
    path("walk-in/<int:entry_id>/", reception_views.walk_in_done, name="walk_in_done"),
    path("today/", reception_views.board, name="board"),
    path("entry/<int:entry_id>/emergency/", reception_views.emergency, name="emergency"),
    path("entry/<int:entry_id>/remove/", reception_views.remove, name="remove"),
    path("entry/<int:entry_id>/return/", reception_views.return_entry, name="return"),
]
