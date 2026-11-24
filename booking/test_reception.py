"""Tests for booking by the receptionist (BKG-09)."""

from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import Patient, User
from scheduling.models import Doctor, ScheduleRule

from .availability import free_slots
from .models import Appointment
from .reception import book_for_patient

DHAKA = ZoneInfo("Asia/Dhaka")
SUNDAY_MORNING = datetime(2026, 11, 15, 10, 0, tzinfo=DHAKA)
MONDAY_5PM = datetime(2026, 11, 16, 17, 0, tzinfo=DHAKA)


class ReceptionTestCase(TestCase):
    """Shared set-up: a doctor with a Monday session, a receptionist, a patient."""

    def setUp(self):
        """Create the people and the doctor's weekly session."""
        doctor_user = User.objects.create_user(
            username="d1",
            password="Strong-pass-123",
            role=User.Role.DOCTOR,
            first_name="Imran",
            last_name="Hossain",
        )
        self.doctor = Doctor.objects.create(
            user=doctor_user, code="D1", specialty="Cardiology", room="101"
        )
        ScheduleRule.objects.create(
            doctor=self.doctor,
            weekday=ScheduleRule.Weekday.MONDAY,
            start_time=time(17, 0),
            end_time=time(21, 0),
            slot_minutes=15,
        )
        self.receptionist = User.objects.create_user(
            username="shirin", password="Strong-pass-123", role=User.Role.RECEPTIONIST
        )
        self.patient = Patient.objects.create(
            full_name="Rahima Akter", mobile_number="+8801712345678", approx_age=34
        )

    def clock(self, moment):
        """Pretend that the current time is the given moment."""
        return patch("django.utils.timezone.now", return_value=moment)


class ReceptionSlotRuleTests(ReceptionTestCase):
    """BR-03: reception may book until the slot ends."""

    def starts(self, now, reception):
        """List the start times of every free slot at the given moment."""
        days = free_slots(self.doctor, now=now, reception=reception)
        return [start for _day, slots in days for start, _end in slots]

    def test_reception_sees_a_slot_that_has_started_but_not_ended(self):
        """At 17:50 the 17:45-18:00 slot can still be booked by reception."""
        now = datetime(2026, 11, 16, 17, 50, tzinfo=DHAKA)
        self.assertIn(
            datetime(2026, 11, 16, 17, 45, tzinfo=DHAKA), self.starts(now, reception=True)
        )

    def test_reception_does_not_see_a_slot_that_has_ended(self):
        """At 18:00 the 17:45-18:00 slot is over."""
        now = datetime(2026, 11, 16, 18, 0, tzinfo=DHAKA)
        starts = self.starts(now, reception=True)
        self.assertNotIn(datetime(2026, 11, 16, 17, 45, tzinfo=DHAKA), starts)
        self.assertIn(datetime(2026, 11, 16, 18, 0, tzinfo=DHAKA), starts)

    def test_patients_still_need_30_minutes_notice(self):
        """The patient rule is unchanged."""
        now = datetime(2026, 11, 16, 17, 50, tzinfo=DHAKA)
        starts = self.starts(now, reception=False)
        self.assertNotIn(datetime(2026, 11, 16, 17, 45, tzinfo=DHAKA), starts)
        self.assertNotIn(datetime(2026, 11, 16, 18, 0, tzinfo=DHAKA), starts)


class BookForPatientTests(ReceptionTestCase):
    """BKG-09 confirmation 2: an appointment of type Reception is created."""

    def test_booking_creates_a_reception_appointment(self):
        """The appointment has the right type, status, times and creator."""
        with self.clock(SUNDAY_MORNING):
            appointment = book_for_patient(
                self.patient, self.doctor, MONDAY_5PM, self.receptionist, "Chest pain follow-up"
            )
        self.assertEqual(appointment.type, Appointment.Type.RECEPTION)
        self.assertEqual(appointment.status, Appointment.Status.BOOKED)
        self.assertEqual(appointment.slot_end, MONDAY_5PM + timedelta(minutes=15))
        self.assertEqual(appointment.created_by, self.receptionist)
        self.assertTrue(appointment.reference_number.startswith("CQ-"))
        self.assertEqual(appointment.reason, "Chest pain follow-up")

    def test_a_taken_slot_cannot_be_booked_again(self):
        """The second caller is told the time is no longer available."""
        with self.clock(SUNDAY_MORNING):
            book_for_patient(self.patient, self.doctor, MONDAY_5PM, self.receptionist)
            with self.assertRaises(ValidationError) as caught:
                book_for_patient(self.patient, self.doctor, MONDAY_5PM, self.receptionist)
        self.assertIn("no longer available", str(caught.exception))

    def test_a_time_outside_the_schedule_is_refused(self):
        """Only slots from the doctor's weekly schedule can be booked."""
        tuesday = datetime(2026, 11, 17, 17, 0, tzinfo=DHAKA)
        with self.clock(SUNDAY_MORNING):
            with self.assertRaises(ValidationError):
                book_for_patient(self.patient, self.doctor, tuesday, self.receptionist)

    def test_two_people_booking_at_the_same_moment_get_exactly_one_appointment(self):
        """REL-02: the database refuses the second booking, with a clear message."""
        slots = [(MONDAY_5PM, MONDAY_5PM + timedelta(minutes=15))]
        with self.clock(SUNDAY_MORNING):
            book_for_patient(self.patient, self.doctor, MONDAY_5PM, self.receptionist)
            with patch("booking.reception.free_slots", return_value=[(MONDAY_5PM.date(), slots)]):
                with self.assertRaises(ValidationError) as caught:
                    book_for_patient(self.patient, self.doctor, MONDAY_5PM, self.receptionist)
        self.assertIn("Someone else has just booked this time", str(caught.exception))
        count = Appointment.objects.filter(doctor=self.doctor, slot_start=MONDAY_5PM).count()
        self.assertEqual(count, 1)


class ReceptionPageTests(ReceptionTestCase):
    """BKG-09 and SEC-01: the booking pages."""

    def log_in(self):
        """Log in as the receptionist."""
        self.client.login(username="shirin", password="Strong-pass-123")

    def test_anonymous_visitor_is_sent_to_login(self):
        """People who are not logged in cannot book for callers."""
        response = self.client.get(reverse("booking:reception_start"))
        self.assertEqual(response.status_code, 302)

    def test_doctor_cannot_use_the_reception_pages(self):
        """SEC-01: only receptionists book by phone."""
        self.client.login(username="d1", password="Strong-pass-123")
        response = self.client.get(reverse("booking:reception_start"))
        self.assertEqual(response.status_code, 403)

    def test_search_by_number_shows_the_patient(self):
        """BKG-09 confirmation 1: the existing patient is found."""
        self.log_in()
        response = self.client.get(reverse("booking:reception_start"), {"q": "01712345678"})
        self.assertContains(response, "Rahima Akter")
        self.assertContains(response, "age 34")
        self.assertContains(response, "Book for this person")

    def test_unknown_number_offers_to_register_the_caller(self):
        """BKG-09 confirmation 1: no record, so register with a name, number and age."""
        self.log_in()
        response = self.client.get(reverse("booking:reception_start"), {"q": "01999999999"})
        self.assertContains(response, "No patient was found")
        self.assertContains(response, "Register and continue")

    def test_registering_a_caller_continues_to_the_doctor_list(self):
        """Only a name, a number and an age are needed."""
        self.log_in()
        response = self.client.post(
            reverse("booking:reception_start"),
            {"full_name": "Karim Uddin", "mobile_number": "01812345678", "age": 62},
        )
        patient = Patient.objects.get(mobile_number="+8801812345678")
        self.assertRedirects(response, reverse("booking:reception_doctors", args=[patient.pk]))

    def test_registering_an_existing_number_shows_the_reason(self):
        """USAB-06: the page explains why the record was refused."""
        self.log_in()
        response = self.client.post(
            reverse("booking:reception_start"),
            {"full_name": "Someone Else", "mobile_number": "01712345678", "age": 40},
        )
        self.assertContains(response, "already belongs to another patient")

    def test_doctor_list_and_slot_page_show_times(self):
        """The receptionist can reach the free times of a doctor."""
        self.log_in()
        page = self.client.get(reverse("booking:reception_doctors", args=[self.patient.pk]))
        self.assertContains(page, "Dr. Imran Hossain")
        with self.clock(SUNDAY_MORNING):
            slots = self.client.get(
                reverse("booking:reception_slots", args=[self.patient.pk, self.doctor.pk])
            )
        self.assertContains(slots, "Monday, 16 November")
        self.assertContains(slots, "17:00")

    def test_choosing_a_time_books_it_and_shows_the_reference_number(self):
        """BKG-09 confirmation 2: the appointment is created and confirmed."""
        self.log_in()
        url = reverse("booking:reception_slots", args=[self.patient.pk, self.doctor.pk])
        with self.clock(SUNDAY_MORNING):
            response = self.client.post(
                url, {"slot_start": MONDAY_5PM.isoformat(), "reason": "Check-up"}
            )
        appointment = Appointment.objects.get()
        self.assertRedirects(
            response, reverse("booking:reception_confirmation", args=[appointment.pk])
        )
        self.assertEqual(appointment.type, "reception")
        page = self.client.get(reverse("booking:reception_confirmation", args=[appointment.pk]))
        self.assertContains(page, appointment.reference_number)
        self.assertContains(page, "17:00 to 17:15")

    def test_a_booked_time_disappears_from_the_patient_pages(self):
        """The slot is no longer offered to patients on the doctor page."""
        self.log_in()
        url = reverse("booking:reception_slots", args=[self.patient.pk, self.doctor.pk])
        with self.clock(SUNDAY_MORNING):
            self.client.post(url, {"slot_start": MONDAY_5PM.isoformat()})
            public = self.client.get(reverse("booking:doctor_detail", args=[self.doctor.pk]))
        # Monday 16 November 17:00 is taken. Monday 23 November 17:00 is still free.
        self.assertContains(public, ">17:00<", count=1)
        self.assertContains(public, ">17:15<", count=2)

    def test_booking_a_taken_time_shows_a_clear_message(self):
        """USAB-06: the page says the time is no longer available."""
        self.log_in()
        url = reverse("booking:reception_slots", args=[self.patient.pk, self.doctor.pk])
        with self.clock(SUNDAY_MORNING):
            self.client.post(url, {"slot_start": MONDAY_5PM.isoformat()})
            response = self.client.post(url, {"slot_start": MONDAY_5PM.isoformat()})
        self.assertContains(response, "no longer available")
        self.assertEqual(Appointment.objects.count(), 1)

    def test_a_garbled_time_shows_a_clear_message(self):
        """A broken time value does not crash the page."""
        self.log_in()
        url = reverse("booking:reception_slots", args=[self.patient.pk, self.doctor.pk])
        with self.clock(SUNDAY_MORNING):
            response = self.client.post(url, {"slot_start": "not a time"})
        self.assertContains(response, "was not understood")
