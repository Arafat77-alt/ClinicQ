"""Models for the consultation application (VIS-01)."""

from django.db import models


class VisitRecord(models.Model):
    """The doctor's notes for one visit (VIS-01, BR-15, PRIV-05).

    One record belongs to one appointment (walk-ins have an appointment too),
    so the notes are stored "against that visit". The author and the time are
    stored automatically. Who may read a record is decided in services.py:
    only the author, and any doctor who has the patient in their queue right
    now. Receptionists and the administrator never see clinical notes, which
    is also why this model is not registered in the Django admin site.

    Attributes:
        appointment: The visit these notes belong to.
        patient: The patient (copied from the appointment, to find history fast).
        doctor: The doctor who wrote the notes.
        complaint: What the patient says is wrong.
        findings: What the doctor found on examination.
        diagnosis: The doctor's conclusion.
        advice: Advice and next steps for the patient.
        created_at: When the notes were first saved.
        updated_at: When the notes were last changed.
    """

    appointment = models.OneToOneField(
        "booking.Appointment", on_delete=models.PROTECT, related_name="visit_record"
    )
    patient = models.ForeignKey(
        "accounts.Patient", on_delete=models.PROTECT, related_name="visit_records"
    )
    doctor = models.ForeignKey(
        "scheduling.Doctor", on_delete=models.PROTECT, related_name="visit_records"
    )
    complaint = models.TextField("Complaint", blank=True)
    findings = models.TextField("Findings", blank=True)
    diagnosis = models.TextField("Diagnosis", blank=True)
    advice = models.TextField("Advice", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        """Return the date and the doctor code, never clinical text."""
        return f"Visit of {self.created_at:%d %b %Y} with {self.doctor.code}"
