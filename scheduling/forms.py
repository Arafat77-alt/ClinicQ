"""Forms for the scheduling application."""

from django import forms

from .models import ScheduleBreak, ScheduleRule


class TimeInput(forms.TimeInput):
    """A time field that shows the browser's time picker."""

    input_type = "time"

    def __init__(self, **kwargs):
        """Use the 24-hour format that the page and the database share."""
        super().__init__(format="%H:%M", **kwargs)


class ScheduleRuleForm(forms.ModelForm):
    """The doctor's form for one weekly session (SCH-02)."""

    class Meta:
        model = ScheduleRule
        fields = ["weekday", "start_time", "end_time", "slot_minutes"]
        labels = {"slot_minutes": "Slot length (minutes)"}
        widgets = {"start_time": TimeInput(), "end_time": TimeInput()}

    def __init__(self, *args, doctor, **kwargs):
        """Attach the doctor so the model can check for overlapping sessions."""
        super().__init__(*args, **kwargs)
        self.instance.doctor = doctor
        self.fields["slot_minutes"].initial = doctor.default_slot_minutes


class ScheduleBreakForm(forms.ModelForm):
    """The doctor's form for a break inside a session (SCH-02)."""

    class Meta:
        model = ScheduleBreak
        fields = ["start_time", "end_time"]
        widgets = {"start_time": TimeInput(), "end_time": TimeInput()}

    def __init__(self, *args, rule, **kwargs):
        """Attach the session so the model can check the break fits inside it."""
        super().__init__(*args, **kwargs)
        self.instance.rule = rule