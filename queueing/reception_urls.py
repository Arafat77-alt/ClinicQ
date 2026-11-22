"""Web addresses for the receptionist's queue pages (QUE-03, QUE-09, QUE-10).

Kept apart from queueing/urls.py, which belongs to Person B, so that the two
files never conflict.
"""

from django.urls import path

from . import reception_views

app_name = "reception_queue"

urlpatterns = [
    path("walk-in/", reception_views.walk_in, name="walk_in"),
    path("walk-in/<int:entry_id>/", reception_views.walk_in_done, name="walk_in_done"),
]
