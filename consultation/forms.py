"""Forms for the consultation application (VIS-01)."""

from django import forms

from .models import VisitRecord


class VisitNotesForm(forms.ModelForm):
    """The four parts of the doctor's notes (VIS-01)."""

    class Meta:
        model = VisitRecord
        fields = ["complaint", "findings", "diagnosis", "advice"]
        widgets = {field: forms.Textarea(attrs={"rows": 3}) for field in fields}
