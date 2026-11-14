"""Tests for the accounts application."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import Patient, User
from .services import create_staff_account, deactivate_staff_account


class PatientMobileNumberTests(TestCase):
    """A-10: a mobile number identifies one patient; dependents share it."""

    def test_two_independent_patients_cannot_share_a_number(self):
        """Two patients without a guardian must not use the same number."""
        Patient.objects.create(full_name="Rahima Akter", mobile_number="+8801712345678")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Patient.objects.create(full_name="Another Person", mobile_number="+8801712345678")

    def test_dependent_can_share_the_guardian_number(self):
        """A dependent may use the guardian's number."""
        guardian = Patient.objects.create(full_name="Rahima Akter", mobile_number="+8801712345678")
        dependent = Patient.objects.create(
            full_name="Her Mother", mobile_number="+8801712345678", guardian=guardian
        )
        self.assertEqual(dependent.guardian, guardian)

    def test_duplicate_number_shows_a_clear_message(self):
        """USAB-06: the error must explain the reason and how to fix it."""
        Patient.objects.create(full_name="Rahima Akter", mobile_number="+8801712345678")
        duplicate = Patient(full_name="Another Person", mobile_number="+8801712345678")
        with self.assertRaises(ValidationError) as caught:
            duplicate.full_clean()
        self.assertIn("already belongs to another patient", str(caught.exception))


class StaffAccountServiceTests(TestCase):
    """AUTH-05: creating and deactivating staff accounts."""

    def make_admin(self):
        """Create a clinic administrator for the tests."""
        return User.objects.create_user(
            username="manager", password="Strong-pass-123", role=User.Role.ADMIN
        )

    def test_new_staff_account_must_change_password(self):
        """AUTH-05 confirmation 1: a new receptionist must set a new password."""
        user = create_staff_account(
            "shirin", "shirin@example.com", User.Role.RECEPTIONIST, "Temp-pass-4821"
        )
        self.assertTrue(user.must_change_password)
        self.assertEqual(user.role, User.Role.RECEPTIONIST)
        self.assertTrue(user.check_password("Temp-pass-4821"))

    def test_patient_role_is_refused_with_a_clear_message(self):
        """Staff accounts cannot be given the patient role."""
        with self.assertRaises(ValidationError) as caught:
            create_staff_account("x", "x@example.com", User.Role.PATIENT, "Temp-pass-4821")
        self.assertIn("Choose one of these roles", str(caught.exception))

    def test_duplicate_username_is_refused_with_a_clear_message(self):
        """A username can belong to only one account."""
        create_staff_account("shirin", "a@example.com", User.Role.RECEPTIONIST, "Temp-pass-4821")
        with self.assertRaises(ValidationError) as caught:
            create_staff_account("Shirin", "b@example.com", User.Role.DOCTOR, "Temp-pass-4821")
        self.assertIn("already used by another account", str(caught.exception))

    def test_weak_password_is_refused(self):
        """SEC-02: passwords need at least 8 characters."""
        with self.assertRaises(ValidationError):
            create_staff_account("shirin", "a@example.com", User.Role.RECEPTIONIST, "abc")

    def test_deactivated_account_is_kept_but_cannot_log_in(self):
        """AUTH-05 confirmation 2: access is denied, records remain."""
        admin = self.make_admin()
        user = create_staff_account("imran", "i@example.com", User.Role.DOCTOR, "Temp-pass-4821")
        deactivate_staff_account(user, acting_user=admin)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertTrue(User.objects.filter(username="imran").exists())

    def test_administrator_cannot_deactivate_themselves(self):
        """An administrator must not lock themselves out."""
        admin = self.make_admin()
        with self.assertRaises(ValidationError) as caught:
            deactivate_staff_account(admin, acting_user=admin)
        self.assertIn("cannot deactivate your own account", str(caught.exception))

    def test_superuser_gets_the_administrator_role(self):
        """A superuser created from the command line is a clinic administrator."""
        superuser = User.objects.create_superuser("root", "r@example.com", "Strong-pass-123")
        self.assertEqual(superuser.role, User.Role.ADMIN)


class StaffAccountPageTests(TestCase):
    """AUTH-05 and SEC-01: the pages and the role checks."""

    def setUp(self):
        """Create an administrator and a receptionist."""
        self.admin = User.objects.create_user(
            username="manager", password="Strong-pass-123", role=User.Role.ADMIN
        )
        self.receptionist = User.objects.create_user(
            username="shirin", password="Strong-pass-123", role=User.Role.RECEPTIONIST
        )

    def test_anonymous_visitor_is_sent_to_login(self):
        """People who are not logged in cannot see staff pages."""
        response = self.client.get(reverse("accounts:staff_list"))
        self.assertRedirects(
            response, f"{reverse('accounts:login')}?next={reverse('accounts:staff_list')}"
        )

    def test_receptionist_cannot_open_staff_pages(self):
        """SEC-01: a non-administrator gets a 403 page."""
        self.client.login(username="shirin", password="Strong-pass-123")
        response = self.client.get(reverse("accounts:staff_list"))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "do not have permission", status_code=403)

    def test_administrator_can_create_a_staff_account(self):
        """AUTH-05: the administrator creates a receptionist."""
        self.client.login(username="manager", password="Strong-pass-123")
        response = self.client.post(
            reverse("accounts:staff_create"),
            {
                "username": "nadia",
                "first_name": "Nadia",
                "last_name": "Rahman",
                "email": "nadia@example.com",
                "role": "receptionist",
                "temporary_password": "Temp-pass-4821",
            },
        )
        self.assertRedirects(response, reverse("accounts:staff_list"))
        self.assertTrue(User.objects.filter(username="nadia", must_change_password=True).exists())

    def test_form_shows_the_reason_when_the_username_is_taken(self):
        """USAB-06: the page explains what went wrong."""
        self.client.login(username="manager", password="Strong-pass-123")
        response = self.client.post(
            reverse("accounts:staff_create"),
            {
                "username": "shirin",
                "email": "x@example.com",
                "role": "doctor",
                "temporary_password": "Temp-pass-4821",
            },
        )
        self.assertContains(response, "already used by another account")

    def test_new_staff_member_must_change_password_at_first_login(self):
        """AUTH-05 confirmation 1, through the real pages."""
        create_staff_account("nadia", "n@example.com", User.Role.DOCTOR, "Temp-pass-4821")
        self.client.post(
            reverse("accounts:login"), {"username": "nadia", "password": "Temp-pass-4821"}
        )
        response = self.client.get(reverse("accounts:home"))
        self.assertRedirects(response, reverse("accounts:password_change"))
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "Temp-pass-4821",
                "new_password1": "My-own-pass-9137",
                "new_password2": "My-own-pass-9137",
            },
        )
        self.assertRedirects(response, reverse("accounts:home"), fetch_redirect_response=False)
        self.assertFalse(User.objects.get(username="nadia").must_change_password)
        self.assertEqual(self.client.get(reverse("accounts:home")).status_code, 200)

    def test_deactivated_staff_member_sees_a_clear_message(self):
        """AUTH-05 confirmation 2, through the real pages."""
        user = create_staff_account("imran", "i@example.com", User.Role.DOCTOR, "Temp-pass-4821")
        deactivate_staff_account(user, acting_user=self.admin)
        response = self.client.post(
            reverse("accounts:login"), {"username": "imran", "password": "Temp-pass-4821"}
        )
        self.assertContains(response, "has been deactivated")

    def test_administrator_can_deactivate_from_the_list(self):
        """AUTH-05: the Deactivate button works and keeps the record."""
        self.client.login(username="manager", password="Strong-pass-123")
        response = self.client.post(
            reverse("accounts:staff_deactivate", args=[self.receptionist.pk])
        )
        self.assertRedirects(response, reverse("accounts:staff_list"))
        self.receptionist.refresh_from_db()
        self.assertFalse(self.receptionist.is_active)