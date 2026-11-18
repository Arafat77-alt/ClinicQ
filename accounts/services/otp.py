"""One-time password (OTP) rules.

Story: AUTH-01, AUTH-02. Requirement: SEC-04.
These are plain functions with no database. The caller stores the code, the time it was
created and the number of attempts, and passes them in. The caller also passes the current
time (``now``), so the rules are easy to test. ``created_at`` and ``now`` must both be
timezone-aware, or both be naive.
"""

import secrets
from datetime import timedelta

OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 5
MAX_OTP_ATTEMPTS = 3
OTP_BLOCK_MINUTES = 15

RESULT_OK = "ok"
RESULT_WRONG_CODE = "wrong_code"
RESULT_EXPIRED = "expired"
RESULT_TOO_MANY_ATTEMPTS = "too_many_attempts"

_MESSAGES = {
    RESULT_OK: "Your code is correct.",
    RESULT_WRONG_CODE: "That code is not correct. Please check the SMS and try again.",
    RESULT_EXPIRED: "This code has expired. Please ask for a new code.",
    RESULT_TOO_MANY_ATTEMPTS: (
        "You entered a wrong code too many times. "
        "Please wait 15 minutes and then ask for a new code."
    ),
}


def generate_otp_code():
    """Create a random 6-digit one-time code.

    Story: AUTH-01, AUTH-02. Requirement: SEC-04.

    Returns:
        str: Six digits. It is a string so a leading zero is kept, for example "042917".
    """
    return "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))


def is_otp_expired(created_at, now):
    """Say whether a code is older than 5 minutes.

    Story: AUTH-01 (criterion 1). Requirement: SEC-04.

    Args:
        created_at (datetime): When the code was created.
        now (datetime): The current time.

    Returns:
        bool: True if more than 5 minutes have passed. A code is still valid at exactly
        5 minutes.
    """
    return now - created_at > timedelta(minutes=OTP_EXPIRY_MINUTES)


def is_attempt_limit_reached(attempts_used):
    """Say whether the person has used all 3 attempts.

    Story: AUTH-01 (criterion 2). Requirement: SEC-04.

    Args:
        attempts_used (int): How many wrong codes were entered so far.

    Returns:
        bool: True when 3 or more attempts were used.
    """
    return attempts_used >= MAX_OTP_ATTEMPTS


def attempts_left(attempts_used):
    """Count how many attempts remain.

    Story: AUTH-01. Requirement: SEC-04.

    Args:
        attempts_used (int): How many wrong codes were entered so far.

    Returns:
        int: Attempts remaining, never below 0.
    """
    return max(MAX_OTP_ATTEMPTS - attempts_used, 0)


def is_blocked(blocked_at, now):
    """Say whether a person is still blocked after 3 wrong codes.

    Story: AUTH-01 (criterion 2). Requirement: SEC-04.

    Args:
        blocked_at (datetime): When the block started (the 3rd wrong code).
        now (datetime): The current time.

    Returns:
        bool: True while less than 15 minutes have passed since the block started.
    """
    return now - blocked_at < timedelta(minutes=OTP_BLOCK_MINUTES)


def check_otp(entered_code, correct_code, created_at, attempts_used, now):
    """Check a code the person typed against the rules.

    The checks run in this order: attempt limit, expiry, then the code itself. A person
    who has used all attempts is refused even if the code is now correct.

    Story: AUTH-01, AUTH-02. Requirement: SEC-04.

    Args:
        entered_code (str): The code the person typed.
        correct_code (str): The code that was sent.
        created_at (datetime): When the correct code was created.
        attempts_used (int): How many wrong codes were entered before this one.
        now (datetime): The current time.

    Returns:
        str: One of RESULT_OK, RESULT_WRONG_CODE, RESULT_EXPIRED or
        RESULT_TOO_MANY_ATTEMPTS.
    """
    if is_attempt_limit_reached(attempts_used):
        return RESULT_TOO_MANY_ATTEMPTS
    if is_otp_expired(created_at, now):
        return RESULT_EXPIRED
    entered = (entered_code or "").strip()
    if entered and secrets.compare_digest(entered, correct_code):
        return RESULT_OK
    return RESULT_WRONG_CODE


def get_result_message(result):
    """Give a plain-language message for a check result.

    Story: AUTH-01, AUTH-02. Requirement: USAB-06 (say what went wrong and what to do).

    Args:
        result (str): The value returned by ``check_otp``.

    Returns:
        str: A message that can be shown to the person.

    Raises:
        ValueError: If the result is not one of the known results.
    """
    if result not in _MESSAGES:
        raise ValueError(
            "This result is not known. Please use a value returned by check_otp."
        )
    return _MESSAGES[result]
