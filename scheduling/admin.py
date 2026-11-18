"""Admin site setup for the scheduling application."""

from django.contrib import admin

from .models import Doctor, ScheduleBreak, ScheduleRule


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    """Let the administrator add and edit doctor profiles (SCH-01)."""

    list_display = ("code", "user", "specialty", "room", "default_slot_minutes", "is_active")
    list_filter = ("specialty", "is_active")
    search_fields = ("code", "user__username", "user__first_name", "user__last_name", "specialty")


class ScheduleBreakInline(admin.TabularInline):
    """Show the breaks of a session on the same page."""

    model = ScheduleBreak
    extra = 0


@admin.register(ScheduleRule)
class ScheduleRuleAdmin(admin.ModelAdmin):
    """Let staff view weekly sessions (doctors edit their own on the site)."""

    list_display = ("doctor", "weekday", "start_time", "end_time", "slot_minutes")
    list_filter = ("doctor", "weekday")
    inlines = [ScheduleBreakInline]