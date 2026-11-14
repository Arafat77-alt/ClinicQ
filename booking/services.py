"""Business rules for the booking application."""

import secrets

REFERENCE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_reference_number(length=8):
    """Create a reference number that a patient can read out over the phone.

    Supports BKG-03 (a confirmed appointment shows a reference number). The
    alphabet leaves out the characters that are easy to confuse: the letters
    I and O, and the digits 0 and 1.

    Args:
        length: How many characters come after the CQ- prefix.

    Returns:
        A string such as CQ-7K4M9XPA.
    """
    code = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(length))
    return f"CQ-{code}"