"""Web addresses for the booking application."""

from django.urls import path

from . import views

app_name = "booking"

urlpatterns = [
    path("doctors/", views.doctor_search, name="doctor_search"),
    path("doctors/<int:doctor_id>/", views.doctor_detail, name="doctor_detail"),
]