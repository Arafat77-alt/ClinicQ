"""Tests for receptionist check-in of booked appointments (QUE-01, BR-05, BR-14)."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Patient, User
from booking.models import Appointment
from scheduling.models import Doctor

from .checkin import check_in_booked_appointment, find_appointments_for_check_in
from .models import QueueEntry

DHAKA = ZoneInfo("Asia/Dhaka")
SLOT_START = datetime(2026, 11, 16, 17, 0, tzinfo=DHAKA)


class CheckInTestCase(TestCase):
    """Shared set-up: one doctor, one receptionist and one booked patient."""

    def setUp(self):
        """Create the people and freeze the clock 10 minutes before the slot."""
        doctor_user = User.objects.create_user(
            username="imran", password="Strong-pass-123", role=User.Role.DOCTOR
        )
        self.doctor = Doctor.objects.create(
            user=doctor_user, code="D1", specialty="Medicine", room="101"
        )
        self.receptionist = User.objects.create_user(
            username="shirin", password="Strong-pass-123", role=User.Role.RECEPTIONIST
        )
        self.patient = Patient.objects.create(
            full_name="Rahima Akter", mobile_number="+8801712345678", approx_age=34
        )
        clock_patch = patch(
            "django.utils.timezone.now", return_value=SLOT_START - timedelta(minutes=10)
        )
        clock_patch.start()
        self.addCleanup(clock_patch.stop)

    def make_appointment(self, status=Appointment.Status.BOOKED, slot_start=None, kind=None):
        """Create a booked appointment for the test patient."""
        start = slot_start or SLOT_START
        return Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            slot_start=start,
            slot_end=start + timedelta(minutes=15),
            type=kind or Appointment.Type.ONLINE,
            status=status,
            created_by=self.receptionist,
        )


class CheckInServiceTests(CheckInTestCase):
    """QUE-01 business rules for time windows and queue order."""

    def test_on_time_check_in_keeps_the_slot_time(self):
        """BR-05 and BR-08: an on-time patient keeps appointment priority."""
        appointment = self.make_appointment()
        entry, was_late = check_in_booked_appointment(appointment)
        self.assertFalse(was_late)
        self.assertEqual(entry.token, "D1-001")
        self.assertEqual(entry.effective_time, SLOT_START)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.CHECKED_IN)

    def test_late_arrival_joins_from_the_check_in_time(self):
        """BR-05: a late arrival keeps the appointment but loses slot priority."""
        appointment = self.make_appointment()
        arrived_at = SLOT_START + timedelta(minutes=20)
        entry, was_late = check_in_booked_appointment(appointment, now=arrived_at)
        self.assertTrue(was_late)
        self.assertEqual(entry.effective_time, arrived_at)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.CHECKED_IN)

    def test_arrival_after_the_no_show_limit_is_refused(self):
        """BR-06: reception is told to register a walk-in after the no-show limit."""
        appointment = self.make_appointment()
        with self.assertRaises(ValidationError) as caught:
            check_in_booked_appointment(appointment, now=SLOT_START + timedelta(minutes=61))
        self.assertIn("walk-in", str(caught.exception))
        self.assertFalse(QueueEntry.objects.exists())
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.BOOKED)

    def test_check_in_before_the_window_opens_is_refused(self):
        """BR-05: check-in does not open until 60 minutes before the slot."""
        appointment = self.make_appointment()
        with self.assertRaises(ValidationError) as caught:
            check_in_booked_appointment(appointment, now=SLOT_START - timedelta(minutes=61))
        self.assertIn("opens 60 minutes before", str(caught.exception))

    def test_a_patient_cannot_be_checked_in_twice(self):
        """A second check-in does not issue a second token."""
        appointment = self.make_appointment()
        check_in_booked_appointment(appointment)
        with self.assertRaises(ValidationError) as caught:
            check_in_booked_appointment(appointment)
        self.assertIn("already checked in", str(caught.exception))
        self.assertEqual(QueueEntry.objects.count(), 1)

    def test_a_walk_in_appointment_is_checked_in_by_its_own_page(self):
        """Walk-ins use QUE-03, not the booked-appointment check-in."""
        appointment = self.make_appointment(kind=Appointment.Type.WALKIN, slot_start=None)
        with self.assertRaises(ValidationError) as caught:
            check_in_booked_appointment(appointment)
        self.assertIn("walk-in", str(caught.exception))

    def test_search_finds_todays_appointment_by_reference_or_number(self):
        """The receptionist can search by reference or mobile number (QUE-01)."""
        appointment = self.make_appointment()
        by_reference = find_appointments_for_check_in(appointment.reference_number)
        by_mobile = find_appointments_for_check_in("01712 345678")
        self.assertEqual(list(by_reference), [appointment])
        self.assertEqual(list(by_mobile), [appointment])


class CheckInPageTests(CheckInTestCase):
    """QUE-01 confirmation criteria through the real reception pages."""

    def setUp(self):
        """Log the receptionist in before each page test."""
        super().setUp()
        self.client.force_login(self.receptionist)
        self.appointment = self.make_appointment()

    def test_receptionist_finds_and_checks_in_the_patient(self):
        """A search followed by one click checks the patient in and shows the token."""
        search_url = reverse("reception_queue:check_in")
        response = self.client.post(search_url, {"query": self.appointment.reference_number})
        self.assertContains(response, self.patient.full_name)
        check_in_url = reverse("reception_queue:check_in_appointment", args=[self.appointment.pk])
        response = self.client.post(check_in_url)
        entry = QueueEntry.objects.get()
        self.assertRedirects(response, reverse("reception_queue:check_in_done", args=[entry.pk]))
        self.assertContains(self.client.get(response.url), entry.token)

    def test_no_show_page_offers_walk_in_registration(self):
        """Criterion 3: after the no-show limit, reception can offer a walk-in."""
        with patch("django.utils.timezone.now", return_value=SLOT_START + timedelta(minutes=61)):
            response = self.client.post(
                reverse("reception_queue:check_in_appointment", args=[self.appointment.pk])
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("reception_queue:check_in"))
        page = self.client.get(response.url)
        self.assertContains(page, "past the no-show time")
        self.assertContains(page, reverse("reception_queue:walk_in"))

    def test_late_arrival_message_explains_the_queue_position(self):
        """Criterion 2: reception is told why a late arrival is placed differently."""
        with patch("django.utils.timezone.now", return_value=SLOT_START + timedelta(minutes=20)):
            response = self.client.post(
                reverse("reception_queue:check_in_appointment", args=[self.appointment.pk])
            )
        page = self.client.get(response.url)
        self.assertContains(page, "Late arrival")

    def test_doctor_cannot_open_the_check_in_page(self):
        """SEC-01: only receptionists may check patients in."""
        self.client.force_login(self.doctor.user)
        response = self.client.get(reverse("reception_queue:check_in"))
        self.assertEqual(response.status_code, 403)
