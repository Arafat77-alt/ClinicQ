"""Web addresses for the booking application."""

from django.urls import path

from . import views

app_name = "booking"

urlpatterns = [
    path("doctors/", views.doctor_search, name="doctor_search"),
    path("doctors/<int:doctor_id>/", views.doctor_detail, name="doctor_detail"),
    path("doctors/<int:doctor_id>/book/", views.book_slot, name="book_slot"),
    path(
        "appointments/<int:appointment_id>/confirmed/",
        views.booking_confirmation,
        name="booking_confirmation",
    ),
    path("appointments/mine/", views.my_appointments, name="my_appointments"),
    path(
        "appointments/<int:appointment_id>/cancel/",
        views.cancel_appointment,
        name="cancel_appointment",
    ),
    path("reception/book/", views.reception_start, name="reception_start"),
    path(
        "reception/book/<int:patient_id>/",
        views.reception_doctors,
        name="reception_doctors",
    ),
    path(
        "reception/book/<int:patient_id>/doctor/<int:doctor_id>/",
        views.reception_slots,
        name="reception_slots",
    ),
    path(
        "reception/appointment/<int:appointment_id>/",
        views.reception_confirmation,
        name="reception_confirmation",
    ),
]