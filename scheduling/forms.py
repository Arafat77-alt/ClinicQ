"""Forms for the scheduling application."""

from django import forms

from .models import ScheduleBreak, ScheduleRule


class TimeInput(forms.TimeInput):
    """A time field that shows the browser's time picker."""

    input_type = "time"

    def __init__(self, **kwargs):
        """Use the 24-hour format that the page and the database share."""
        super().__init__(format="%H:%M", **kwargs)


class DateInput(forms.DateInput):
    """A date field that shows the browser's calendar."""

    input_type = "date"

    def __init__(self, **kwargs):
        """Use the year-month-day format that the calendar sends."""
        super().__init__(format="%Y-%m-%d", **kwargs)


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


class LeaveForm(forms.Form):
    """The doctor's form for days or hours of leave (SCH-03)."""

    start_date = forms.DateField(widget=DateInput(), label="First day")
    end_date = forms.DateField(widget=DateInput(), label="Last day")
    start_time = forms.TimeField(
        widget=TimeInput(),
        required=False,
        label="From (only for a few hours)",
        help_text="Leave both times empty to take whole days.",
    )
    end_time = forms.TimeField(widget=TimeInput(), required=False, label="Until")
    reason = forms.CharField(max_length=255, required=False, label="Reason (optional)")