"""Forms for the booking application."""

from django import forms


class NewPatientForm(forms.Form):
    """The three details needed to register a caller who has no record (BKG-09)."""

    full_name = forms.CharField(max_length=150, label="Full name")
    mobile_number = forms.CharField(
        max_length=20,
        label="Mobile number",
        help_text="For example 01712345678.",
    )
    age = forms.IntegerField(min_value=0, max_value=120, label="Age (years)")


class ReceptionBookingForm(forms.Form):
    """The visit reason and the chosen time, sent by the time buttons (BKG-09)."""

    slot_start = forms.CharField()
    reason = forms.CharField(max_length=255, required=False, label="Reason for the visit")


class PatientBookingForm(forms.Form):
    """The chosen patient (self or dependent), time slot, and optional reason (BKG-03)."""

    patient_id = forms.IntegerField(widget=forms.HiddenInput())
    slot_start = forms.CharField(widget=forms.HiddenInput())
    reason = forms.CharField(
        max_length=255,
        required=False,
        label="Reason for the visit (optional)",
    )
