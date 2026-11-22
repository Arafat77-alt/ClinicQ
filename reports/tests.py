"""Tests for the printed daily schedule (SYS-04, R-09)."""

from datetime import date, datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse

from accounts.models import Patient, User
from booking.models import Appointment
from scheduling.models import Doctor

from .services import schedule_for_day

DHAKA = ZoneInfo("Asia/Dhaka")
TODAY = date(2026, 11, 16)
NOW = datetime(2026, 11, 16, 9, 0, tzinfo=DHAKA)


def at(day, hour, minute=0):
    """Return a Dhaka-time moment on the given day."""
    return datetime.combine(day, time(hour, minute), tzinfo=DHAKA)


class PrintScheduleTestCase(TestCase):
    """Shared set-up: two doctors, a receptionist and a patient (all made up)."""

    def setUp(self):
        """Create the people used by every test."""
        self.doctor_one = self.make_doctor("d1", "D1", "Imran", "Hossain")
        self.doctor_two = self.make_doctor("d2", "D2", "Nusrat", "Jahan")
        self.receptionist = User.objects.create_user(
            username="shirin", password="Strong-pass-123", role=User.Role.RECEPTIONIST
        )
        self.patient = Patient.objects.create(
            full_name="Rahima Akter", mobile_number="+8801712345678", approx_age=34
        )
        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def make_doctor(self, username, code, first_name, last_name):
        """Create a doctor account with a profile."""
        user = User.objects.create_user(
            username=username,
            password="Strong-pass-123",
            role=User.Role.DOCTOR,
            first_name=first_name,
            last_name=last_name,
        )
        return Doctor.objects.create(user=user, code=code, specialty="Medicine", room="101")

    def book(self, doctor, start, status=Appointment.Status.BOOKED):
        """Create a 15-minute appointment for the patient."""
        return Appointment.objects.create(
            patient=self.patient,
            doctor=doctor,
            slot_start=start,
            slot_end=start.replace(minute=start.minute + 15),
            type=Appointment.Type.RECEPTION,
            status=status,
        )


class ScheduleServiceTests(PrintScheduleTestCase):
    """SYS-04: what goes on the printed schedule."""

    def test_appointments_are_grouped_by_doctor_in_time_order(self):
        """Each doctor gets their own list, earliest time first."""
        late = self.book(self.doctor_one, at(TODAY, 18))
        early = self.book(self.doctor_one, at(TODAY, 17))
        other = self.book(self.doctor_two, at(TODAY, 17))
        schedule = dict(schedule_for_day(TODAY))
        self.assertEqual(schedule[self.doctor_one], [early, late])
        self.assertEqual(schedule[self.doctor_two], [other])

    def test_every_status_is_shown(self):
        """Cancelled and no-show appointments are still printed (SYS-04)."""
        self.book(self.doctor_one, at(TODAY, 17), Appointment.Status.CANCELLED)
        self.book(self.doctor_one, at(TODAY, 17, 30), Appointment.Status.NO_SHOW)
        statuses = [item.status for item in dict(schedule_for_day(TODAY))[self.doctor_one]]
        self.assertEqual(statuses, ["cancelled", "no_show"])

    def test_another_days_appointments_are_not_shown(self):
        """Yesterday and tomorrow are left out."""
        self.book(self.doctor_one, at(date(2026, 11, 15), 17))
        self.book(self.doctor_one, at(date(2026, 11, 17), 17))
        self.assertEqual(dict(schedule_for_day(TODAY))[self.doctor_one], [])

    def test_doctor_with_no_appointments_is_still_listed(self):
        """Every active doctor gets a sheet, even an empty one."""
        self.book(self.doctor_one, at(TODAY, 17))
        schedule = dict(schedule_for_day(TODAY))
        self.assertIn(self.doctor_two, schedule)
        self.assertEqual(schedule[self.doctor_two], [])

    def test_inactive_doctor_is_listed_only_with_appointments(self):
        """A deactivated doctor without appointments today does not waste paper."""
        self.doctor_two.is_active = False
        self.doctor_two.save()
        self.assertNotIn(self.doctor_two, dict(schedule_for_day(TODAY)))
        self.book(self.doctor_two, at(TODAY, 17))
        self.assertIn(self.doctor_two, dict(schedule_for_day(TODAY)))


class PrintSchedulePageTests(PrintScheduleTestCase):
    """SYS-04: who can open the page and what it shows."""

    url = reverse("reports:print_schedule")

    def test_receptionist_can_open_the_page(self):
        """The receptionist sees each doctor and the patient's details."""
        self.book(self.doctor_one, at(TODAY, 17))
        self.client.force_login(self.receptionist)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rahima Akter")
        self.assertContains(response, "+8801712345678")
        self.assertContains(response, "17:00")
        self.assertContains(response, "Booked")
        self.assertContains(response, "No appointments for this doctor today.")

    def test_page_breaks_after_each_doctor(self):
        """The print rules put every doctor on a new sheet."""
        self.client.force_login(self.receptionist)
        response = self.client.get(self.url)
        self.assertContains(response, "page-break-after: always")
        self.assertContains(response, 'class="cq-sheet"', count=2)

    def test_other_roles_are_refused(self):
        """Doctors, patients and the administrator cannot open it (SEC-01)."""
        for role in (User.Role.DOCTOR, User.Role.PATIENT, User.Role.ADMIN):
            user = User.objects.create_user(username=f"x-{role}", password="x", role=role)
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_visitor_who_is_not_logged_in_is_sent_to_login(self):
        """Anonymous visitors must log in first."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])
