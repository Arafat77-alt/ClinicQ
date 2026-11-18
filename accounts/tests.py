"""Tests for the accounts application."""

import re
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Patient, User
from .services import (
    MAX_FAILED_LOGINS,
    create_staff_account,
    deactivate_staff_account,
    find_account,
    is_locked,
)

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

    def test_patient_cannot_be_their_own_guardian(self):
        """A patient must not be recorded as managing themselves."""
        patient = Patient.objects.create(
            full_name="Rahima Akter", mobile_number="+8801712345678"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Patient.objects.filter(pk=patient.pk).update(guardian=patient)

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



class StaffLoginTests(TestCase):
    """AUTH-06: log in with email and password, and the lock after 5 wrong passwords."""

    def setUp(self):
        """Create a receptionist who logs in with an email address."""
        self.user = User.objects.create_user(
            username="shirin",
            email="Shirin@Example.com",
            password="Strong-pass-123",
            role=User.Role.RECEPTIONIST,
        )

    def log_in(self, identifier, password):
        """Send the login form."""
        return self.client.post(
            reverse("accounts:login"), {"username": identifier, "password": password}
        )

    def test_staff_can_log_in_with_their_email_address(self):
        """AUTH-06: the email address works, whatever the capital letters."""
        response = self.log_in("shirin@example.com", "Strong-pass-123")
        self.assertRedirects(response, reverse("accounts:home"), fetch_redirect_response=False)

    def test_username_still_works_for_accounts_without_an_email(self):
        """Accounts made without an email can still log in with the username."""
        response = self.log_in("shirin", "Strong-pass-123")
        self.assertRedirects(response, reverse("accounts:home"), fetch_redirect_response=False)

    def test_find_account_returns_none_for_unknown_people(self):
        """Nobody matches an address that is not in the system."""
        self.assertIsNone(find_account("nobody@example.com"))
        self.assertIsNone(find_account(""))

    def test_wrong_password_gives_a_clear_message(self):
        """USAB-06: say what is wrong and what to do."""
        response = self.log_in("shirin@example.com", "wrong")
        self.assertContains(response, "email or password is not correct")

    def test_unknown_email_gets_the_same_message(self):
        """The page does not reveal whether an email address has an account."""
        response = self.log_in("nobody@example.com", "whatever")
        self.assertContains(response, "email or password is not correct")

    def test_account_is_locked_after_five_wrong_passwords(self):
        """AUTH-06 confirmation 1: 5 wrong passwords lock the account for 15 minutes."""
        for _ in range(MAX_FAILED_LOGINS):
            response = self.log_in("shirin@example.com", "wrong")
        self.assertContains(response, "locked for 15 minutes")
        self.user.refresh_from_db()
        self.assertTrue(is_locked(self.user))
        minutes = (self.user.locked_until - timezone.now()).total_seconds() / 60
        self.assertTrue(14 < minutes <= 15)

    def test_locked_account_refuses_even_the_correct_password(self):
        """While the lock lasts, the right password does not work either."""
        for _ in range(MAX_FAILED_LOGINS):
            self.log_in("shirin@example.com", "wrong")
        response = self.log_in("shirin@example.com", "Strong-pass-123")
        self.assertContains(response, "locked for 15 minutes")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_works_again_after_the_lock_runs_out(self):
        """The lock ends by itself after 15 minutes."""
        for _ in range(MAX_FAILED_LOGINS):
            self.log_in("shirin@example.com", "wrong")
        self.user.refresh_from_db()
        self.user.locked_until = timezone.now() - timedelta(minutes=1)
        self.user.save()
        response = self.log_in("shirin@example.com", "Strong-pass-123")
        self.assertRedirects(response, reverse("accounts:home"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_count, 0)
        self.assertIsNone(self.user.locked_until)

    def test_a_correct_login_resets_the_wrong_password_count(self):
        """Four wrong passwords and then a correct one do not add up to a lock."""
        for _ in range(MAX_FAILED_LOGINS - 1):
            self.log_in("shirin@example.com", "wrong")
        self.log_in("shirin@example.com", "Strong-pass-123")
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_count, 0)

    def test_deactivated_person_with_an_open_session_is_logged_out(self):
        """AUTH-05: deactivating an account ends access straight away."""
        self.client.login(username="shirin", password="Strong-pass-123")
        self.assertEqual(self.client.get(reverse("accounts:home")).status_code, 200)
        self.user.is_active = False
        self.user.save()
        response = self.client.get(reverse("accounts:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_staff_email_must_be_unique(self):
        """Two staff accounts cannot share an email address."""
        with self.assertRaises(ValidationError) as caught:
            create_staff_account("other", "SHIRIN@example.com", User.Role.DOCTOR, "Temp-pass-4821")
        self.assertIn("already used by another account", str(caught.exception))



class PasswordResetTests(TestCase):
    """AUTH-06: forgotten password reset by an emailed link."""

    def setUp(self):
        """Create a doctor who forgot their password."""
        self.user = User.objects.create_user(
            username="imran",
            email="imran@example.com",
            password="Strong-pass-123",
            role=User.Role.DOCTOR,
        )

    def request_link(self, email="imran@example.com"):
        """Ask for a reset link and return the link from the email."""
        self.client.post(reverse("accounts:password_reset"), {"email": email})
        if not mail.outbox:
            return None
        return re.search(r"http://testserver(\S+)", mail.outbox[-1].body).group(1)

    def choose_new_password(self, link, password="My-own-pass-9137"):
        """Open the emailed link and send the new password."""
        response = self.client.get(link)
        self.assertEqual(response.status_code, 302)
        return self.client.post(
            response.url, {"new_password1": password, "new_password2": password}
        )

    def test_reset_email_is_sent_with_a_link(self):
        """AUTH-06 confirmation 2: the person gets an emailed link."""
        link = self.request_link()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["imran@example.com"])
        self.assertIn("30 minutes", mail.outbox[0].body)
        self.assertIn("/password/reset/", link)

    def test_link_lets_the_person_choose_a_new_password(self):
        """The link works within 30 minutes and the new password logs in."""
        link = self.request_link()
        response = self.choose_new_password(link)
        self.assertRedirects(
            response, reverse("accounts:password_reset_complete"), fetch_redirect_response=False
        )
        self.assertTrue(self.client.login(username="imran@example.com", password="My-own-pass-9137"))

    def test_link_stops_working_after_it_is_used(self):
        """AUTH-06 confirmation 2: the link can be used only once."""
        link = self.request_link()
        self.choose_new_password(link)
        response = self.client.get(link, follow=True)
        self.assertContains(response, "This link cannot be used")

    def test_link_stops_working_after_30_minutes(self):
        """AUTH-06 confirmation 2: the link runs out after 30 minutes."""
        link = self.request_link()
        later = datetime.now() + timedelta(minutes=31)
        with patch.object(PasswordResetTokenGenerator, "_now", return_value=later):
            response = self.client.get(link, follow=True)
        self.assertContains(response, "This link cannot be used")

    def test_unknown_email_gets_the_same_page_and_no_email(self):
        """The page does not reveal whether an email address has an account."""
        response = self.client.post(
            reverse("accounts:password_reset"), {"email": "nobody@example.com"}, follow=True
        )
        self.assertContains(response, "Check your email")
        self.assertEqual(len(mail.outbox), 0)

    def test_deactivated_account_gets_no_reset_email(self):
        """A deactivated account cannot get back in through a reset."""
        self.user.is_active = False
        self.user.save()
        self.request_link()
        self.assertEqual(len(mail.outbox), 0)

    def test_choosing_a_new_password_removes_the_lock(self):
        """A reset proves control of the mailbox, so the lock is cleared."""
        self.user.locked_until = timezone.now() + timedelta(minutes=10)
        self.user.save()
        link = self.request_link()
        self.choose_new_password(link)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.locked_until)
        self.assertEqual(self.user.failed_login_count, 0)
