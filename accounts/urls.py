"""Web addresses for the accounts application."""

from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.ClinicLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("password/change/", views.FirstPasswordChangeView.as_view(), name="password_change"),
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/new/", views.staff_create, name="staff_create"),
    path("staff/<int:user_id>/deactivate/", views.staff_deactivate, name="staff_deactivate"),
]