"""Tests for the accounts application."""

from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Patient


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