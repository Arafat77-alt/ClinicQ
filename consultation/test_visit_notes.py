"""Tests for visit notes and who may read them (VIS-01, BR-15, PRIV-05)."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Patient, User
from booking.models import Appointment
from queueing.models import QueueEntry
from queueing.services import add_to_queue
from scheduling.models import Doctor

from .models import VisitRecord
from .services import can_read_visit_record, readable_history, save_visit_notes

DHAKA = ZoneInfo("Asia/Dhaka")
START = datetime(2026, 11, 16, 17, 0, tzinfo=DHAKA)
NOTES = {
    "complaint": "Cough for 3 days",
    "findings": "Mild fever",
    "diagnosis": "Viral infection",
    "advice": "Rest and fluids",
}


class VisitNotesTestCase(TestCase):
    """Shared set-up: two doctors, a receptionist, an admin and a patient in consultation."""

    def setUp(self):
        """Create the people; the patient is in consultation with doctor one."""
        self.now = START
        clock = patch("django.utils.timezone.now", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.doctor_user, self.doctor = self.make_doctor("d1", "D1")
        self.other_user, self.other_doctor = self.make_doctor("d2", "D2")
        self.receptionist = User.objects.create_user(
            username="shirin", password="x", role=User.Role.RECEPTIONIST
        )
        self.admin = User.objects.create_user(username="boss", password="x", role=User.Role.ADMIN)
        self.patient = Patient.objects.create(
            full_name="Karim Uddin", mobile_number="+8801711000001", approx_age=52
        )
        self.entry = self.queue(self.doctor)
        self.entry.state = QueueEntry.State.IN_CONSULTATION  # QUE-07 (Person B) does this
        self.entry.save()

    def make_doctor(self, username, code):
        """Create a doctor account and profile."""
        user = User.objects.create_user(username=username, password="x", role=User.Role.DOCTOR)
        return user, Doctor.objects.create(user=user, code=code, specialty="Medicine", room="1")

    def queue(self, doctor):
        """Put the patient in a doctor's queue today as a walk-in."""
        appointment = Appointment.objects.create(
            patient=self.patient,
            doctor=doctor,
            type=Appointment.Type.WALKIN,
            status=Appointment.Status.CHECKED_IN,
        )
        return add_to_queue(appointment, check_in_time=self.now)


class SaveNotesTests(VisitNotesTestCase):
    """VIS-01 and BR-15."""

    def test_notes_are_stored_with_the_visit_the_time_and_the_doctor(self):
        """VIS-01 confirmation step."""
        record = save_visit_notes(self.entry, self.doctor_user, NOTES)
        self.assertEqual(record.appointment, self.entry.appointment)
        self.assertEqual(record.patient, self.patient)
        self.assertEqual(record.doctor, self.doctor)
        self.assertEqual(record.created_at, START)
        self.assertEqual(record.diagnosis, "Viral infection")

    def test_saving_again_updates_the_same_record(self):
        """One visit, one record."""
        save_visit_notes(self.entry, self.doctor_user, NOTES)
        save_visit_notes(self.entry, self.doctor_user, {**NOTES, "advice": "Come back Monday"})
        self.assertEqual(VisitRecord.objects.count(), 1)
        self.assertEqual(VisitRecord.objects.get().advice, "Come back Monday")

    def test_empty_notes_are_refused(self):
        """Nothing to save means a plain message."""
        with self.assertRaisesMessage(ValidationError, "The notes are empty"):
            save_visit_notes(self.entry, self.doctor_user, {"complaint": "   "})

    def test_new_notes_need_the_patient_in_consultation(self):
        """A waiting patient has not been seen yet."""
        self.entry.state = QueueEntry.State.WAITING
        self.entry.save()
        with self.assertRaisesMessage(ValidationError, "only while the patient is in consultation"):
            save_visit_notes(self.entry, self.doctor_user, NOTES)

    def test_another_doctor_cannot_write_notes(self):
        """Notes only for your own queue."""
        with self.assertRaisesMessage(ValidationError, "your own queue"):
            save_visit_notes(self.entry, self.other_user, NOTES)

    def test_author_can_correct_notes_after_completion_within_24_hours(self):
        """BR-15: the 24-hour window."""
        save_visit_notes(self.entry, self.doctor_user, NOTES)
        self.entry.state = QueueEntry.State.COMPLETED
        self.entry.save()
        self.now = START + timedelta(hours=23)
        record = save_visit_notes(self.entry, self.doctor_user, {**NOTES, "diagnosis": "Flu"})
        self.assertEqual(record.diagnosis, "Flu")

    def test_notes_cannot_be_changed_after_24_hours(self):
        """BR-15: after 24 hours the original stays."""
        save_visit_notes(self.entry, self.doctor_user, NOTES)
        self.now = START + timedelta(hours=25)
        with self.assertRaisesMessage(ValidationError, "more than 24 hours ago"):
            save_visit_notes(self.entry, self.doctor_user, {**NOTES, "diagnosis": "Flu"})
        self.assertEqual(VisitRecord.objects.get().diagnosis, "Viral infection")


class PrivacyTests(VisitNotesTestCase):
    """PRIV-05: who may read clinical notes."""

    def setUp(self):
        """Save one record written by doctor one."""
        super().setUp()
        self.record = save_visit_notes(self.entry, self.doctor_user, NOTES)

    def test_author_can_read(self):
        """The doctor who wrote it."""
        self.assertTrue(can_read_visit_record(self.doctor_user, self.record))

    def test_other_doctor_without_the_patient_cannot_read(self):
        """A doctor who does not have the patient in their queue."""
        self.assertFalse(can_read_visit_record(self.other_user, self.record))
        self.assertEqual(list(readable_history(self.other_user, self.patient)), [])

    def test_other_doctor_with_the_patient_in_their_queue_can_read(self):
        """The patient is waiting for doctor two now."""
        self.entry.state = QueueEntry.State.COMPLETED
        self.entry.save()
        self.queue(self.other_doctor)
        self.assertTrue(can_read_visit_record(self.other_user, self.record))
        self.assertEqual(list(readable_history(self.other_user, self.patient)), [self.record])

    def test_access_ends_when_the_patient_leaves_the_other_doctors_queue(self):
        """Being in the queue yesterday is not enough."""
        self.entry.state = QueueEntry.State.COMPLETED
        self.entry.save()
        other_entry = self.queue(self.other_doctor)
        other_entry.state = QueueEntry.State.COMPLETED
        other_entry.save()
        self.assertFalse(can_read_visit_record(self.other_user, self.record))

    def test_receptionist_admin_and_patient_can_never_read(self):
        """PRIV-05: no clinical notes outside doctors."""
        patient_user = User.objects.create_user(username="p", password="x")
        for user in (self.receptionist, self.admin, patient_user):
            self.assertFalse(can_read_visit_record(user, self.record))
            self.assertEqual(list(readable_history(user, self.patient)), [])

    def test_record_page_refuses_receptionist_admin_and_other_doctor(self):
        """The same rule on the page, with a 403."""
        url = reverse("consultation:visit_record_detail", args=[self.record.pk])
        for user in (self.receptionist, self.admin, self.other_user):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.doctor_user)
        self.assertContains(self.client.get(url), "Viral infection")

    def test_visit_records_are_not_in_the_admin_site(self):
        """The administrator cannot read notes through the Django admin site either."""
        from django.contrib import admin

        self.assertNotIn(VisitRecord, admin.site._registry)


class VisitNotesPageTests(VisitNotesTestCase):
    """The notes page."""

    def url(self, entry=None):
        """Return the notes page address for an entry."""
        return reverse("consultation:visit_notes", args=[(entry or self.entry).pk])

    def test_doctor_saves_notes_from_the_page(self):
        """The form saves and says when."""
        self.client.force_login(self.doctor_user)
        response = self.client.post(self.url(), NOTES, follow=True)
        self.assertContains(response, "Notes saved at 17:00.")
        self.assertEqual(VisitRecord.objects.get().complaint, "Cough for 3 days")

    def test_empty_form_shows_a_plain_message(self):
        """Rule 10: plain words."""
        self.client.force_login(self.doctor_user)
        response = self.client.post(self.url(), {})
        self.assertContains(response, "The notes are empty.")

    def test_other_doctor_and_receptionist_cannot_open_the_page(self):
        """SEC-01."""
        for user in (self.other_user, self.receptionist, self.admin):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url()).status_code, 403)
