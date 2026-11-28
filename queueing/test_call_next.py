"""Tests for the doctor calling the next patient (QUE-07, BR-08, BR-11, SEC-01)."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Patient, User
from booking.models import Appointment
from scheduling.models import Doctor

from .call_next import call_next_patient
from .completion import complete_consultation, skip_patient
from .live import build_live_queue_status
from .models import QueueEntry
from .queue_actions import flag_emergency
from .services import add_to_queue, waiting_queue

DHAKA = ZoneInfo("Asia/Dhaka")
NOW = datetime(2026, 11, 16, 17, 5, tzinfo=DHAKA)


class CallNextTestCase(TestCase):
    """Shared set-up: two doctors and a queue with an emergency at the front."""

    def setUp(self):
        """Create the people, queue entries and a fixed clock."""
        self.doctor_one = self.make_doctor("d1", "D1")
        self.doctor_two = self.make_doctor("d2", "D2")
        self.receptionist = User.objects.create_user(
            username="shirin", password="Strong-pass-123", role=User.Role.RECEPTIONIST
        )
        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

        self.normal = self.make_entry(
            "Rahima Akter", "+8801711000001", 34, "17:00", NOW - timedelta(minutes=10)
        )
        self.emergency = self.make_entry("Sumaiya Islam", "+8801711000003", 28, "17:20", NOW)
        flag_emergency(self.emergency, self.doctor_one.user, "chest pain")
        self.later = self.make_entry("Karim Uddin", "+8801711000002", 52, "17:10", NOW)
        self.other_doctor_entry = self.make_entry(
            "Other Doctor Patient",
            "+8801711000004",
            40,
            "17:00",
            NOW - timedelta(minutes=4),
            doctor=self.doctor_two,
        )

    def make_doctor(self, username, code):
        """Create a doctor account with a profile."""
        user = User.objects.create_user(
            username=username, password="Strong-pass-123", role=User.Role.DOCTOR
        )
        return Doctor.objects.create(user=user, code=code, specialty="Medicine", room="101")

    def make_entry(self, name, number, age, start_text, check_in, doctor=None):
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
            reason="Fever",
            created_by=self.receptionist,
        )
        return add_to_queue(appointment, check_in_time=check_in)


class CallNextServiceTests(CallNextTestCase):
    """QUE-07 and BR-11 rules at the service layer."""

    def test_call_next_uses_existing_order_and_enters_consultation(self):
        """One call takes the BR-08 first patient straight into consultation."""
        first = waiting_queue(self.doctor_one, timezone.localdate(NOW))[0]
        entry = call_next_patient(self.doctor_one, now=NOW)
        self.assertEqual(entry.pk, first.pk)
        entry.refresh_from_db()
        self.assertEqual(entry.state, QueueEntry.State.IN_CONSULTATION)
        self.assertEqual(entry.called_at, NOW)
        self.assertEqual(entry.started_at, NOW)
        self.assertEqual(entry.appointment.status, Appointment.Status.IN_CONSULTATION)

    def test_patient_live_status_shows_the_active_state(self):
        """QUE-04 reflects the call without a new live-status implementation."""
        entry = call_next_patient(self.doctor_one, now=NOW)
        status = build_live_queue_status(entry, now=NOW)
        self.assertEqual(status["state_display"], "In consultation")
        self.assertEqual(status["estimate_text"], "Your turn now")

    def test_second_call_is_refused_with_a_plain_message(self):
        """BR-11: only one patient may be active for a doctor."""
        first = call_next_patient(self.doctor_one, now=NOW)
        with self.assertRaises(ValidationError) as caught:
            call_next_patient(self.doctor_one, now=NOW + timedelta(minutes=1))
        self.assertIn("Complete or skip that patient", str(caught.exception))
        first.refresh_from_db()
        self.assertEqual(first.state, QueueEntry.State.IN_CONSULTATION)
        self.assertEqual(
            QueueEntry.objects.filter(
                doctor=self.doctor_one,
                queue_date=timezone.localdate(NOW),
                state__in=[QueueEntry.State.CALLED, QueueEntry.State.IN_CONSULTATION],
            ).count(),
            1,
        )

    def test_calling_an_empty_queue_is_refused(self):
        """USAB-06: say there is nobody waiting and what will happen next."""
        for entry in (self.normal, self.emergency, self.later):
            entry.delete()
        with self.assertRaises(ValidationError) as caught:
            call_next_patient(self.doctor_one, now=NOW)
        self.assertIn("Nobody is waiting right now", str(caught.exception))

    def test_call_next_only_touches_the_doctors_own_queue(self):
        """SEC-01: another doctor's patient is never chosen."""
        call_next_patient(self.doctor_one, now=NOW)
        self.other_doctor_entry.refresh_from_db()
        self.assertEqual(self.other_doctor_entry.state, QueueEntry.State.WAITING)

    def test_existing_completion_service_still_works(self):
        """QUE-08: completion accepts the new In consultation entry."""
        entry = call_next_patient(self.doctor_one, now=NOW)
        complete_consultation(entry, now=NOW + timedelta(minutes=8))
        entry.refresh_from_db()
        self.assertEqual(entry.state, QueueEntry.State.COMPLETED)
        self.assertEqual(entry.appointment.status, Appointment.Status.COMPLETED)

    def test_existing_skip_service_still_works(self):
        """BR-10: a called patient can still be skipped back into the queue."""
        entry = call_next_patient(self.doctor_one, now=NOW)
        skip_patient(entry, now=NOW + timedelta(minutes=1))
        entry.refresh_from_db()
        self.assertEqual(entry.state, QueueEntry.State.WAITING)
        self.assertEqual(entry.skip_count, 1)
        self.assertEqual(entry.appointment.status, Appointment.Status.CHECKED_IN)


class CallNextPageTests(CallNextTestCase):
    """QUE-07 confirmation criteria through the real doctor page."""

    def setUp(self):
        """Log the doctor in before each page test."""
        super().setUp()
        self.page_url = reverse("queueing:doctor_live_queue")
        self.data_url = reverse("queueing:doctor_live_queue_data")
        self.call_url = reverse("queueing:doctor_call_next")
        self.client.force_login(self.doctor_one.user)

    def test_doctor_calls_next_and_sees_it_on_both_views(self):
        """Criterion 1: one click shows the active patient on doctor views."""
        response = self.client.post(self.call_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.page_url)
        page = self.client.get(self.page_url)
        self.assertContains(page, "Now with doctor")
        self.assertContains(page, "Token D1-002 is now in consultation")
        data = self.client.get(self.data_url).json()
        self.assertEqual(data["current"]["patient_name"], "Sumaiya Islam")
        self.assertContains(page, "setInterval(refreshQueue, 3000)")

    def test_current_patient_message_asks_to_finish_first(self):
        """Criterion 2: a second call asks the doctor to complete current first."""
        self.client.post(self.call_url)
        response = self.client.post(self.call_url)
        page = self.client.get(response.url)
        self.assertContains(page, "Complete or skip that patient before calling the next one")
        self.assertEqual(
            QueueEntry.objects.filter(
                doctor=self.doctor_one,
                state__in=[QueueEntry.State.CALLED, QueueEntry.State.IN_CONSULTATION],
            ).count(),
            1,
        )

    def test_call_next_refusal_message_has_no_list_brackets(self):
        """QUE-07: the refusal is plain text, not a stringified list."""
        self.client.post(self.call_url)
        self.client.get(self.page_url)
        response = self.client.post(self.call_url)
        refusal = " ".join(str(message) for message in get_messages(response.wsgi_request))
        self.assertIn("A patient is already in consultation", refusal)
        self.assertNotIn("[", refusal)
        self.assertNotIn("]", refusal)

    def test_receptionist_is_refused_on_the_call_endpoint(self):
        """SEC-01: only doctors may change the queue."""
        self.client.force_login(self.receptionist)
        self.assertEqual(self.client.post(self.call_url).status_code, 403)

    def test_patient_is_refused_on_the_call_endpoint(self):
        """SEC-01: patient accounts cannot call patients."""
        patient_user = User.objects.create_user(
            username="patient", password="Strong-pass-123", role=User.Role.PATIENT
        )
        self.client.force_login(patient_user)
        self.assertEqual(self.client.post(self.call_url).status_code, 403)

    def test_anonymous_user_is_refused_on_the_call_endpoint(self):
        """SEC-01: anonymous visitors are sent to the staff login page."""
        self.client.logout()
        response = self.client.post(self.call_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_get_is_not_allowed_to_call_a_patient(self):
        """A refreshed page must never call the next patient by accident."""
        self.assertEqual(self.client.get(self.call_url).status_code, 405)
