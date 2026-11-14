"""Admin site setup for the scheduling application."""

from django.contrib import admin

from .models import Doctor


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    """Let the administrator add and edit doctor profiles (SCH-01)."""

    list_display = ("code", "user", "specialty", "room", "default_slot_minutes", "is_active")
    list_filter = ("specialty", "is_active")
    search_fields = ("code", "user__username", "user__first_name", "user__last_name", "specialty")