"""Tests for finding doctors and free slots (BKG-01, BKG-02)."""

from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse

from accounts.models import Patient, User
from scheduling.models import Doctor, ScheduleRule

from .availability import free_slots, list_specialties, search_doctors
from .models import Appointment

DHAKA = ZoneInfo("Asia/Dhaka")
# A Sunday morning. The next Monday is 16 November 2026.
SUNDAY_MORNING = datetime(2026, 11, 15, 10, 0, tzinfo=DHAKA)


def make_doctor(username, first_name, last_name, code, specialty, **extra):
    """Create a doctor account and its profile for the tests."""
    user = User.objects.create_user(
        username=username,
        password="Strong-pass-123",
        role=User.Role.DOCTOR,
        first_name=first_name,
        last_name=last_name,
    )
    return Doctor.objects.create(user=user, code=code, specialty=specialty, room="101", **extra)


class SearchTests(TestCase):
    """BKG-01: search for doctors by name or specialty."""

    def setUp(self):
        """Create three doctors with different specialties."""
        self.cardio = make_doctor("d1", "Imran", "Hossain", "D1", "Cardiology")
        self.skin = make_doctor("d2", "Nadia", "Rahman", "D2", "Dermatology")
        self.general = make_doctor("d3", "Karim", "Uddin", "D3", "General Medicine")

    def test_specialty_search_lists_matching_doctors(self):
        """BKG-01 confirmation 1: typing 'cardio' lists the cardiologist."""
        found = list(search_doctors("cardio"))
        self.assertEqual(found, [self.cardio])

    def test_name_search_works_for_first_and_last_names(self):
        """Doctors are found by first name or last name, in any capital letters."""
        self.assertEqual(list(search_doctors("NADIA")), [self.skin])
        self.assertEqual(list(search_doctors("uddin")), [self.general])

    def test_title_dr_is_ignored(self):
        """Typing 'Dr. Imran' finds Imran."""
        self.assertEqual(list(search_doctors("Dr. Imran")), [self.cardio])
        self.assertEqual(list(search_doctors("dr imran hossain")), [self.cardio])

    def test_empty_search_lists_all_active_doctors(self):
        """Nothing typed shows every active doctor."""
        self.assertEqual(len(search_doctors("")), 3)

    def test_inactive_doctor_is_not_listed(self):
        """A deactivated doctor does not appear in search."""
        self.skin.is_active = False
        self.skin.save()
        self.assertEqual(list(search_doctors("derma")), [])
        self.assertNotIn("Dermatology", list_specialties())

    def test_search_page_is_open_to_visitors_without_login(self):
        """The search page shows no personal data, so no login is needed."""
        response = self.client.get(reverse("booking:doctor_search"), {"q": "cardio"})
        self.assertContains(response, "Imran Hossain")
        self.assertNotContains(response, "Nadia Rahman")

    def test_no_match_shows_a_friendly_message_and_all_specialties(self):
        """BKG-01 confirmation 2: a message and the list of specialties."""
        response = self.client.get(reverse("booking:doctor_search"), {"q": "zzzz"})
        self.assertContains(response, "We could not find a doctor")
        self.assertContains(response, "Cardiology")
        self.assertContains(response, "Dermatology")
        self.assertContains(response, "General Medicine")

    def test_emergency_notice_is_shown(self):
        """SAFE-01: booking pages tell people what to do in an emergency."""
        response = self.client.get(reverse("booking:doctor_search"))
        self.assertContains(response, "call 999 or go to the nearest hospital")


class FreeSlotTests(TestCase):
    """BKG-02: free slots within the booking window."""

    def setUp(self):
        """Create a doctor with a Monday 17:00-21:00 session and a patient."""
        self.doctor = make_doctor("d1", "Imran", "Hossain", "D1", "Cardiology")
        ScheduleRule.objects.create(
            doctor=self.doctor,
            weekday=ScheduleRule.Weekday.MONDAY,
            start_time=time(17, 0),
            end_time=time(21, 0),
            slot_minutes=15,
        )
        self.patient = Patient.objects.create(
            full_name="Rahima Akter", mobile_number="+8801712345678"
        )
        self.monday = datetime(2026, 11, 16, 17, 0, tzinfo=DHAKA)

    def book(self, start, status=Appointment.Status.BOOKED):
        """Create an appointment that starts at the given time."""
        return Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            slot_start=start,
            slot_end=start + timedelta(minutes=15),
            status=status,
        )

    def test_free_slots_are_listed_for_each_monday_in_the_window(self):
        """BR-03: only the next 14 days are offered."""
        days = free_slots(self.doctor, now=SUNDAY_MORNING)
        self.assertEqual([str(day) for day, _ in days], ["2026-11-16", "2026-11-23"])
        self.assertEqual(len(days[0][1]), 16)

    def test_a_taken_slot_is_not_offered(self):
        """BKG-02: slots that are taken cannot be selected."""
        self.book(self.monday)
        days = free_slots(self.doctor, now=SUNDAY_MORNING)
        starts = [start for start, _ in days[0][1]]
        self.assertEqual(len(starts), 15)
        self.assertNotIn(self.monday, starts)

    def test_a_cancelled_appointment_frees_its_slot(self):
        """BR-01: a cancelled appointment no longer holds the slot."""
        self.book(self.monday, status=Appointment.Status.CANCELLED)
        days = free_slots(self.doctor, now=SUNDAY_MORNING)
        self.assertEqual(len(days[0][1]), 16)

    def test_past_slots_and_slots_within_30_minutes_are_not_offered(self):
        """BR-03: a slot must start at least 30 minutes from now."""
        now = datetime(2026, 11, 16, 18, 0, tzinfo=DHAKA)
        days = free_slots(self.doctor, now=now)
        first_day_starts = [start for start, _ in days[0][1]]
        self.assertEqual(first_day_starts[0], datetime(2026, 11, 16, 18, 30, tzinfo=DHAKA))
        self.assertEqual(len(first_day_starts), 10)

    def test_slots_beyond_14_days_are_not_offered(self):
        """BR-03: the Monday 30 November is more than 14 days away."""
        days = free_slots(self.doctor, now=SUNDAY_MORNING)
        self.assertNotIn("2026-11-30", [str(day) for day, _ in days])

    def test_inactive_doctor_has_no_free_slots(self):
        """A deactivated doctor takes no new bookings."""
        self.doctor.is_active = False
        self.doctor.save()
        self.assertEqual(free_slots(self.doctor, now=SUNDAY_MORNING), [])


class DoctorPageTests(TestCase):
    """BKG-02: the doctor page shows free times."""

    def setUp(self):
        """Create a doctor with a Monday session."""
        self.doctor = make_doctor("d1", "Imran", "Hossain", "D1", "Cardiology")
        ScheduleRule.objects.create(
            doctor=self.doctor,
            weekday=ScheduleRule.Weekday.MONDAY,
            start_time=time(17, 0),
            end_time=time(18, 0),
            slot_minutes=15,
        )

    def test_page_lists_free_times_in_dhaka_time(self):
        """BKG-02 confirmation: the page shows the day and the free times."""
        with patch("booking.availability.timezone.now", return_value=SUNDAY_MORNING):
            response = self.client.get(reverse("booking:doctor_detail", args=[self.doctor.pk]))
        self.assertContains(response, "Monday, 16 November")
        self.assertContains(response, "17:00")
        self.assertContains(response, "17:45")
        self.assertContains(response, "call 999 or go to the nearest hospital")

    def test_page_explains_when_there_are_no_free_times(self):
        """USAB-06: say what is going on and what to do."""
        ScheduleRule.objects.all().delete()
        response = self.client.get(reverse("booking:doctor_detail", args=[self.doctor.pk]))
        self.assertContains(response, "no free times in the next 14 days")

    def test_inactive_doctor_page_is_not_found(self):
        """A deactivated doctor cannot be opened."""
        self.doctor.is_active = False
        self.doctor.save()
        response = self.client.get(reverse("booking:doctor_detail", args=[self.doctor.pk]))
        self.assertEqual(response.status_code, 404)