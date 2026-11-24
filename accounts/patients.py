"""Finding and creating patients at the reception desk (BKG-09)."""

import re

from .models import Patient


def normalize_mobile_number(text):
    """Turn a typed mobile number into the stored +8801XXXXXXXXX form.

    Receptionists type numbers the way callers say them, for example
    01712 345678 or 8801712345678.

    Args:
        text: The number as typed.

    Returns:
        The number in +8801XXXXXXXXX form when it can be recognised, otherwise the
        typed text without spaces, so that the validator can explain the problem.
    """
    digits = re.sub(r"[\s\-()]", "", text or "")
    if digits.startswith("+"):
        return digits
    if digits.startswith("8801") and len(digits) == 13:
        return "+" + digits
    if digits.startswith("01") and len(digits) == 11:
        return "+88" + digits
    return digits


def find_patients(text):
    """Find patients by mobile number, or by name when letters are typed (BKG-09).

    A guardian and the dependents who share the guardian's number are all
    returned, so the receptionist can choose who the appointment is for (AUTH-04).

    Args:
        text: A mobile number or part of a name.

    Returns:
        A list of Patient, people without a guardian first, then by name.
    """
    text = (text or "").strip()
    if not text:
        return []
    if any(character.isalpha() for character in text):
        found = Patient.objects.filter(full_name__icontains=text)[:20]
    else:
        found = Patient.objects.filter(mobile_number=normalize_mobile_number(text))
    return sorted(found, key=lambda patient: (patient.guardian_id is not None, patient.full_name))


def create_patient_for_reception(full_name, mobile_number, age):
    """Create a patient record with only a name, a number and an age (BKG-09).

    Args:
        full_name: The patient's full name.
        mobile_number: The mobile number as typed.
        age: The age in years.

    Returns:
        The new Patient.

    Raises:
        ValidationError: With a plain-language message when the number is not a
            Bangladeshi mobile number or already belongs to another patient (A-10).
    """
    patient = Patient(
        full_name=full_name.strip(),
        mobile_number=normalize_mobile_number(mobile_number),
        approx_age=age,
    )
    patient.full_clean()
    patient.save()
    return patient
