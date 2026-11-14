"""Admin site setup for the accounts application."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Patient, User


@admin.register(User)
class ClinicUserAdmin(UserAdmin):
    """Show the role fields in the Django admin site."""

    fieldsets = UserAdmin.fieldsets + (
        ("Clinic role", {"fields": ("role", "must_change_password")}),
    )
    list_display = ("username", "email", "role", "is_active")


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    """Let staff view and search patients in the Django admin site."""

    list_display = ("full_name", "mobile_number", "guardian", "created_at")
    search_fields = ("full_name", "mobile_number")