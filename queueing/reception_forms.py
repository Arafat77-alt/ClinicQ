"""Forms used by the receptionist on the queue pages (QUE-03, QUE-09, QUE-10)."""

from django import forms

from scheduling.models import Doctor


class DoctorChoiceField(forms.ModelChoiceField):
    """A doctor drop-down that shows the code, the name and the room."""

    def label_from_instance(self, doctor):
        """Return for example: D1 - Dr. Imran Hossain (Cardiology, room 101)."""
        name = doctor.user.get_full_name() or doctor.user.username
        return f"{doctor.code} - Dr. {name} ({doctor.specialty}, room {doctor.room})"


class WalkInForm(forms.Form):
    """Everything needed to put a walk-in in a queue, on one screen (QUE-03, USAB-03)."""

    full_name = forms.CharField(max_length=150, label="Full name")
    mobile_number = forms.CharField(
        max_length=20,
        label="Mobile number",
        help_text="For example 01712345678. A known number finds the existing patient.",
    )
    age = forms.IntegerField(min_value=0, max_value=120, label="Age (years)")
    doctor = DoctorChoiceField(
        queryset=Doctor.objects.none(),
        label="Doctor",
        empty_label="Choose a doctor",
        error_messages={"required": "Choose the doctor the patient wants to see."},
    )
    reason = forms.CharField(max_length=255, required=False, label="Reason for the visit")

    def __init__(self, *args, **kwargs):
        """Offer only active doctors, ordered by code."""
        super().__init__(*args, **kwargs)
        self.fields["doctor"].queryset = (
            Doctor.objects.filter(is_active=True).select_related("user").order_by("code")
        )


class ReasonForm(forms.Form):
    """A required reason, for an emergency or a removal (QUE-09, QUE-10)."""

    reason = forms.CharField(
        max_length=255,
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3}),
        error_messages={"required": "A reason is required. Write it in a few words."},
    )
