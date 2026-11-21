"""Forms for the clinic administrator to add and edit doctor profiles (SCH-01)."""

from django import forms
from django.db.models import Q

from accounts.models import User

from .models import Doctor


class DoctorProfileForm(forms.ModelForm):
    """Form for adding or editing a doctor profile (SCH-01).

    The photo field is left out as instructed in the feature guide so that no
    media storage configuration is needed yet.
    """

    class Meta:
        model = Doctor
        fields = ["user", "code", "specialty", "room", "default_slot_minutes", "is_active"]
        labels = {
            "user": "Doctor account",
            "code": "Doctor code (for example D1 or D2)",
            "specialty": "Specialty",
            "room": "Consulting room",
            "default_slot_minutes": "Default slot length (minutes)",
            "is_active": "Active (takes new appointments)",
        }
        help_texts = {
            "code": "Used in queue tokens such as D2-014 (BR-14).",
            "default_slot_minutes": "Default length of one appointment slot (15 minutes).",
        }

    def __init__(self, *args, **kwargs):
        """Limit the user choices to accounts with the doctor role (SEC-01)."""
        super().__init__(*args, **kwargs)
        current_user_id = self.instance.user_id if self.instance and self.instance.pk else None
        available_doctors = User.objects.filter(role=User.Role.DOCTOR).filter(
            Q(doctor__isnull=True) | Q(pk=current_user_id)
        )
        self.fields["user"].queryset = available_doctors.order_by("username")
        self.fields["user"].error_messages["invalid_choice"] = (
            "Choose a staff account that has the Doctor role and does not "
            "already have a doctor profile."
        )
