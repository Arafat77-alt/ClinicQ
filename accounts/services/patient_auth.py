"""Business rules for patient registration and login with a one-time password.

Stories: AUTH-01 (patient registration), AUTH-02 (patient OTP login).
Requirements: SEC-04 (5-minute expiry, 3 attempts, 15-minute block),
USAB-06 (plain-language error messages), A-10 (one mobile number per account).
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import OtpChallenge, Patient, User, mobile_number_validator
from accounts.patients import normalize_mobile_number
from notifications.services import send_sms

from .otp import (
    RESULT_OK,
    RESULT_TOO_MANY_ATTEMPTS,
    RESULT_WRONG_CODE,
    check_otp,
    generate_otp_code,
    get_result_message,
    is_attempt_limit_reached,
    is_blocked,
)

PATIENT_SESSION_TIMEOUT_SECONDS = 30 * 60
STAFF_SESSION_TIMEOUT_SECONDS = 15 * 60


def _validate_and_normalize_mobile(raw_number):
    """Return +8801XXXXXXXXX or raise a plain-language ValidationError.

    Story: AUTH-01, AUTH-02. Requirement: USAB-05, USAB-06.
    """
    normalized = normalize_mobile_number(raw_number)
    try:
        mobile_number_validator(normalized)
    except ValidationError as exc:
        raise ValidationError(
            "Enter a valid Bangladeshi mobile number such as +8801712345678."
        ) from exc
    return normalized


def _ensure_not_blocked(challenge, now):
    """Stop the request if the mobile number is currently in a 15-minute block.

    Story: AUTH-01 (criterion 2), AUTH-02. Requirement: SEC-04, USAB-06.
    """
    if challenge is None or challenge.blocked_at is None:
        return
    if is_blocked(challenge.blocked_at, now):
        raise ValidationError(get_result_message(RESULT_TOO_MANY_ATTEMPTS))
    challenge.blocked_at = None
    challenge.attempts_used = 0
    challenge.save(update_fields=["blocked_at", "attempts_used"])


def request_registration_otp(mobile_number, now=None):
    """Send a 6-digit OTP to register a new patient account (AUTH-01).

    If reception already created a Patient record without a login account,
    registration is allowed and will link the new login to that record. If an
    online account already exists for this number, the patient is told to log
    in instead.

    Story: AUTH-01 (criteria 1 & 2). Requirement: SEC-04, A-10, USAB-06.

    Args:
        mobile_number (str): Mobile number typed by the patient.
        now (datetime, optional): Current time for deterministic tests.

    Returns:
        OtpChallenge: The saved challenge record.

    Raises:
        ValidationError: If the number is invalid, already registered online,
            or currently blocked after 3 wrong attempts.
    """
    current_time = now or timezone.now()
    normalized = _validate_and_normalize_mobile(mobile_number)

    existing_primary = Patient.objects.filter(
        mobile_number=normalized, guardian__isnull=True
    ).first()
    if existing_primary and existing_primary.user_id is not None:
        raise ValidationError(
            "This mobile number is already registered. "
            "Please go to the patient login page to sign in with a code."
        )

    challenge = OtpChallenge.objects.filter(mobile_number=normalized).first()
    _ensure_not_blocked(challenge, current_time)

    code = generate_otp_code()
    challenge, _ = OtpChallenge.objects.update_or_create(
        mobile_number=normalized,
        defaults={
            "purpose": OtpChallenge.Purpose.REGISTER,
            "code": code,
            "created_at": current_time,
            "attempts_used": 0,
            "blocked_at": None,
        },
    )
    send_sms(
        normalized,
        f"Your ClinicQ registration code is {code}. It expires in 5 minutes.",
    )
    return challenge



def complete_registration_with_otp(
    full_name, mobile_number, entered_code, date_of_birth=None, now=None
):
    """Verify the registration OTP and create the patient login account (AUTH-01).

    Story: AUTH-01 (criteria 1 & 2). Requirement: SEC-04, A-10, USAB-06.

    Args:
        full_name (str): Patient's full name.
        mobile_number (str): Mobile number in +8801XXXXXXXXX form.
        entered_code (str): Six-digit code entered by the patient.
        date_of_birth (date, optional): Patient's date of birth.
        now (datetime, optional): Current time for deterministic tests.

    Returns:
        User: The newly created User with role ``patient``.

    Raises:
        ValidationError: If the name is missing, no active OTP exists, or the
            code is wrong, expired, or blocked.
    """
    current_time = now or timezone.now()
    cleaned_name = (full_name or "").strip()
    if not cleaned_name:
        raise ValidationError("Please enter your full name before continuing.")

    normalized = _validate_and_normalize_mobile(mobile_number)
    challenge = OtpChallenge.objects.filter(
        mobile_number=normalized,
        purpose=OtpChallenge.Purpose.REGISTER,
    ).first()
    if challenge is None:
        raise ValidationError(
            "No registration code was found for this number. "
            "Please ask for a new code first."
        )

    _verify_challenge_code(challenge, entered_code, current_time)

    with transaction.atomic():
        existing_primary = Patient.objects.filter(
            mobile_number=normalized, guardian__isnull=True
        ).first()
        if existing_primary and existing_primary.user_id is not None:
            challenge.delete()
            raise ValidationError(
                "This mobile number is already registered. "
                "Please log in with a one-time code instead."
            )

        username = f"patient_{normalized.lstrip('+')}"
        user = User.objects.create_user(
            username=username,
            role=User.Role.PATIENT,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])

        if existing_primary:
            existing_primary.user = user
            existing_primary.full_name = cleaned_name
            if date_of_birth:
                existing_primary.date_of_birth = date_of_birth
            existing_primary.save(update_fields=["user", "full_name", "date_of_birth"])
        else:
            patient = Patient(
                user=user,
                full_name=cleaned_name,
                mobile_number=normalized,
                date_of_birth=date_of_birth,
            )
            patient.full_clean()
            patient.save()

        challenge.delete()
    return user

def request_login_otp(mobile_number, now=None):
    """Send a 6-digit OTP to a registered patient so they can log in (AUTH-02).

    Story: AUTH-02 (criterion 1). Requirement: SEC-04, USAB-06.

    Args:
        mobile_number (str): Registered patient's mobile number.
        now (datetime, optional): Current time for deterministic tests.

    Returns:
        OtpChallenge: The saved challenge record.

    Raises:
        ValidationError: If the number is invalid, has no online patient
            account, or is currently blocked.
    """
    current_time = now or timezone.now()
    normalized = _validate_and_normalize_mobile(mobile_number)

    patient = (
        Patient.objects.select_related("user")
        .filter(mobile_number=normalized, guardian__isnull=True, user__isnull=False)
        .first()
    )
    if patient is None or not patient.user.is_active:
        raise ValidationError(
            "No registered patient account was found for this mobile number. "
            "Please register first or ask reception for help."
        )

    challenge = OtpChallenge.objects.filter(mobile_number=normalized).first()
    _ensure_not_blocked(challenge, current_time)

    code = generate_otp_code()
    challenge, _ = OtpChallenge.objects.update_or_create(
        mobile_number=normalized,
        defaults={
            "purpose": OtpChallenge.Purpose.LOGIN,
            "code": code,
            "created_at": current_time,
            "attempts_used": 0,
            "blocked_at": None,
        },
    )
    send_sms(
        normalized,
        f"Your ClinicQ login code is {code}. It expires in 5 minutes.",
    )
    return challenge


def verify_login_otp(mobile_number, entered_code, now=None):
    """Verify a patient's login OTP and return their User account (AUTH-02).

    Story: AUTH-02 (criterion 1). Requirement: SEC-04, USAB-06.

    Args:
        mobile_number (str): Registered patient's mobile number.
        entered_code (str): Six-digit code entered by the patient.
        now (datetime, optional): Current time for deterministic tests.

    Returns:
        User: The authenticated patient User.

    Raises:
        ValidationError: If no active login code exists or the code is wrong,
            expired, or blocked.
    """
    current_time = now or timezone.now()
    normalized = _validate_and_normalize_mobile(mobile_number)

    challenge = OtpChallenge.objects.filter(
        mobile_number=normalized,
        purpose=OtpChallenge.Purpose.LOGIN,
    ).first()
    if challenge is None:
        raise ValidationError(
            "No login code was found for this number. Please ask for a new code."
        )

    _verify_challenge_code(challenge, entered_code, current_time)

    patient = (
        Patient.objects.select_related("user")
        .filter(mobile_number=normalized, guardian__isnull=True, user__isnull=False)
        .first()
    )
    if patient is None or not patient.user.is_active:
        challenge.delete()
        raise ValidationError(
            "This patient account is not active. Please contact clinic reception."
        )

    challenge.delete()
    return patient.user


def _verify_challenge_code(challenge, entered_code, now):
    """Validate ``entered_code`` against ``challenge`` and update attempt counters.

    Story: AUTH-01, AUTH-02. Requirement: SEC-04, USAB-06.
    """
    _ensure_not_blocked(challenge, now)

    result = check_otp(
        entered_code=entered_code,
        correct_code=challenge.code,
        created_at=challenge.created_at,
        attempts_used=challenge.attempts_used,
        now=now,
    )
    if result == RESULT_OK:
        return

    if result == RESULT_WRONG_CODE:
        challenge.attempts_used += 1
        if is_attempt_limit_reached(challenge.attempts_used):
            challenge.blocked_at = now
            challenge.save(update_fields=["attempts_used", "blocked_at"])
            raise ValidationError(get_result_message(RESULT_TOO_MANY_ATTEMPTS))
        challenge.save(update_fields=["attempts_used"])

    raise ValidationError(get_result_message(result))