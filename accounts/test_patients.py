"""Tests for finding and creating patients at the reception desk (BKG-09)."""

from datetime import date
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Patient
from .patients import create_patient_for_reception, find_patients, normalize_mobile_number


class NormalizeMobileNumberTests(TestCase):
    """Numbers are typed the way callers say them."""

    def test_common_ways_of_writing_a_number_give_the_same_result(self):
        """01712..., 8801712... and +8801712... all become +8801712345678."""
        for typed in [
            "01712345678",
            "01712 345678",
            "01712-345678",
            "8801712345678",
            "+8801712345678",
        ]:
            self.assertEqual(normalize_mobile_number(typed), "+8801712345678")

    def test_unknown_forms_are_kept_so_the_validator_can_explain(self):
        """A short number is returned as typed, without spaces."""
        self.assertEqual(normalize_mobile_number("0171 234"), "0171234")


class FindPatientsTests(TestCase):
    """BKG-09 confirmation 1: the existing patient is found by mobile number."""

    def setUp(self):
        """Create a guardian with a dependent, and an unrelated patient."""
        self.guardian = Patient.objects.create(
            full_name="Rahima Akter", mobile_number="+8801712345678", approx_age=34
        )
        self.dependent = Patient.objects.create(
            full_name="Her Mother",
            mobile_number="+8801712345678",
            guardian=self.guardian,
            approx_age=62,
        )
        self.other = Patient.objects.create(
            full_name="Karim Uddin", mobile_number="+8801812345678", approx_age=62
        )

    def test_search_by_number_finds_the_guardian_and_their_dependents(self):
        """The guardian comes first, then the dependent who shares the number."""
        self.assertEqual(find_patients("01712345678"), [self.guardian, self.dependent])

    def test_search_by_name_works_when_letters_are_typed(self):
        """A caller who does not know the number can be found by name."""
        self.assertEqual(find_patients("karim"), [self.other])

    def test_unknown_number_finds_nobody(self):
        """No record for the number."""
        self.assertEqual(find_patients("01999999999"), [])

    def test_empty_search_finds_nobody(self):
        """Nothing typed lists nothing."""
        self.assertEqual(find_patients("  "), [])


class CreatePatientTests(TestCase):
    """BKG-09 confirmation 1: a record needs only a name, a number and an age."""

    def test_record_is_created_from_name_number_and_age(self):
        """The number is stored in +8801XXXXXXXXX form."""
        patient = create_patient_for_reception("  Shirin Sultana ", "01712 345678", 28)
        self.assertEqual(patient.full_name, "Shirin Sultana")
        self.assertEqual(patient.mobile_number, "+8801712345678")
        self.assertEqual(patient.age, 28)

    def test_number_that_already_belongs_to_a_patient_is_refused_clearly(self):
        """A-10: one number, one patient, with a message that says what to do."""
        create_patient_for_reception("Rahima Akter", "01712345678", 34)
        with self.assertRaises(ValidationError) as caught:
            create_patient_for_reception("Another Person", "01712345678", 40)
        self.assertIn("already belongs to another patient", str(caught.exception))

    def test_bad_number_is_refused_with_a_clear_message(self):
        """USAB-06: say what the number should look like."""
        with self.assertRaises(ValidationError) as caught:
            create_patient_for_reception("Someone", "12345", 30)
        self.assertIn("+8801XXXXXXXXX", str(caught.exception))


class PatientAgeTests(TestCase):
    """The age comes from the date of birth, or from the approximate age."""

    def test_age_from_date_of_birth(self):
        """A birthday that has not happened yet this year is not counted."""
        patient = Patient(
            full_name="A", mobile_number="+8801712345678", date_of_birth=date(1990, 12, 31)
        )
        with patch("django.utils.timezone.localdate", return_value=date(2026, 11, 17)):
            self.assertEqual(patient.age, 35)

    def test_age_falls_back_to_the_approximate_age(self):
        """Walk-ins and callers only give an age."""
        patient = Patient(full_name="A", mobile_number="+8801712345678", approx_age=50)
        self.assertEqual(patient.age, 50)

    def test_age_is_none_when_nothing_is_known(self):
        """No date of birth and no age."""
        self.assertIsNone(Patient(full_name="A", mobile_number="+8801712345678").age)