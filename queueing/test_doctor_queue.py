"""Tests for the doctor's live queue page (QUE-06, PERF-03, SEC-01)."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Patient, User
from booking.models import Appointment
from scheduling.models import Doctor

from .doctor_queue import doctor_queue_snapshot
from .queue_actions import flag_emergency
from .services import add_to_queue, waiting_queue

DHAKA = ZoneInfo("Asia/Dhaka")
NOW = datetime(2026, 11, 16, 17, 5, tzinfo=DHAKA)


class DoctorQueueTestCase(TestCase):
    """Shared set-up: two doctors, a receptionist and three waiting patients."""

    def setUp(self):
        """Create the people and freeze the clock at Monday 17:05."""
        self.doctor_one = self.make_doctor("d1", "D1")
        self.doctor_two = self.make_doctor("d2", "D2")
        self.receptionist = User.objects.create_user(
            username="shirin", password="Strong-pass-123", role=User.Role.RECEPTIONIST
        )
        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

        self.on_time = self.make_entry(
            "Rahima Akter", "+8801711000001", 34, "17:00", NOW - timedelta(minutes=10), "Fever"
        )
        self.later = self.make_entry("Karim Uddin", "+8801711000002", 52, "17:10", NOW, "Cough")
        self.emergency = self.make_entry(
            "Sumaiya Islam", "+8801711000003", 28, "17:20", NOW, "Chest pain"
        )
        flag_emergency(self.emergency, self.doctor_one.user, "chest pain")
        self.other_doctor_entry = self.make_entry(
            "Other Doctor Patient",
            "+8801711000004",
            40,
            "17:00",
            NOW - timedelta(minutes=4),
            "Headache",
            doctor=self.doctor_two,
        )

    def make_doctor(self, username, code):
        """Create a doctor account with a profile."""
        user = User.objects.create_user(
            username=username, password="Strong-pass-123", role=User.Role.DOCTOR
        )
        return Doctor.objects.create(user=user, code=code, specialty="Medicine", room="101")

    def make_entry(self, name, number, age, start_text, check_in, reason, doctor=None):
        """Create a checked-in appointment and return its queue entry."""
        slot_start = datetime.fromisoformat(f"2026-11-16T{start_text}:00+06:00")
        patient = Patient.objects.create(full_name=name, mobile_number=number, approx_age=age)
        appointment = Appointment.objects.create(
            patient=patient,
            doctor=doctor or self.doctor_one,
            slot_start=slot_start,
            slot_end=slot_start + timedelta(minutes=15),
            type=Appointment.Type.ONLINE,
            status=Appointment.Status.BOOKED,
            reason=reason,
            created_by=self.receptionist,
        )
        return add_to_queue(appointment, check_in_time=check_in)

    def expected_tokens(self):
        """Return the calling order from the one existing queue ordering rule."""
        return [entry.token for entry in waiting_queue(self.doctor_one, timezone.localdate(NOW))]


class DoctorQueueSnapshotTests(DoctorQueueTestCase):
    """BR-08 and PERF-03 data built for the page and its JSON poll."""

    def test_snapshot_reuses_the_existing_calling_order(self):
        """The helper does not create a second queue order."""
        snapshot = doctor_queue_snapshot(self.doctor_one, now=NOW)
        self.assertEqual([row["token"] for row in snapshot["entries"]], self.expected_tokens())

    def test_snapshot_contains_name_age_reason_waiting_and_emergency(self):
        """QUE-06 shows all the details the doctor asked for."""
        snapshot = doctor_queue_snapshot(self.doctor_one, now=NOW)
        rows = {row["token"]: row for row in snapshot["entries"]}
        self.assertEqual(rows[self.on_time.token]["patient_name"], "Rahima Akter")
        self.assertEqual(rows[self.on_time.token]["age"], 34)
        self.assertEqual(rows[self.on_time.token]["reason"], "Fever")
        self.assertEqual(rows[self.on_time.token]["waiting_text"], "10 min")
        self.assertTrue(rows[self.emergency.token]["is_emergency"])
        self.assertEqual(rows[self.emergency.token]["emergency_reason"], "chest pain")


class DoctorQueuePageTests(DoctorQueueTestCase):
    """QUE-06 confirmation criteria through the real pages."""

    def setUp(self):
        """Log the doctor in before each page test."""
        super().setUp()
        self.page_url = reverse("queueing:doctor_live_queue")
        self.data_url = reverse("queueing:doctor_live_queue_data")
        self.client.force_login(self.doctor_one.user)

    def test_doctor_sees_order_details_emergency_and_refresh_time(self):
        """Criterion 1: the doctor sees the ordered, detailed queue."""
        response = self.client.get(self.page_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rahima Akter")
        self.assertContains(response, "Chest pain")
        self.assertContains(response, "Emergency: chest pain")
        self.assertContains(response, "10 min")
        self.assertContains(response, "Last updated")
        self.assertContains(response, "setInterval(refreshQueue, 3000)")

    def test_json_endpoint_returns_the_same_own_queue(self):
        """PERF-03: the poll returns the same ordered snapshot and refresh time."""
        response = self.client.get(self.data_url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([row["token"] for row in data["entries"]], self.expected_tokens())
        self.assertIn("updated_at", data)

    def test_doctor_cannot_see_another_doctors_patients(self):
        """SEC-01: a doctor only ever sees their own queue."""
        page = self.client.get(self.page_url)
        data = self.client.get(self.data_url).json()
        self.assertNotContains(page, "Other Doctor Patient")
        self.assertNotIn("Other Doctor Patient", [row["patient_name"] for row in data["entries"]])
        self.assertNotIn(self.other_doctor_entry.token, self.expected_tokens())

    def test_receptionist_is_refused_on_page_and_json(self):
        """SEC-01: patient names are not available to reception here."""
        self.client.force_login(self.receptionist)
        for url in (self.page_url, self.data_url):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_patient_is_refused_on_page_and_json(self):
        """SEC-01: a patient account cannot open either doctor endpoint."""
        patient_user = User.objects.create_user(
            username="patient", password="Strong-pass-123", role=User.Role.PATIENT
        )
        self.client.force_login(patient_user)
        for url in (self.page_url, self.data_url):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_anonymous_user_is_refused_on_page_and_json(self):
        """SEC-01: anonymous visitors are sent to the staff login page."""
        self.client.logout()
        for url in (self.page_url, self.data_url):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/login/", response.url)

    def test_doctor_without_a_profile_gets_a_plain_language_message(self):
        """USAB-06: explain what to do when the doctor profile is missing."""
        no_profile_user = User.objects.create_user(
            username="noprofile", password="Strong-pass-123", role=User.Role.DOCTOR
        )
        self.client.force_login(no_profile_user)
        page = self.client.get(self.page_url)
        self.assertEqual(page.status_code, 403)
        self.assertContains(page, "Ask the clinic administrator to create it", status_code=403)
        data = self.client.get(self.data_url)
        self.assertEqual(data.status_code, 403)
        self.assertIn("doctor profile", data.json()["error"])
