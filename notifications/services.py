"""Console versions of text message and email sending.

Story: NOT-01 (confirmations). Requirement: REL-04 (real providers come later).
Every other application calls these two functions, so the names must not change.
"""


def send_sms(recipient, message):
    """Print a text message to the terminal instead of sending it.

    Story: NOT-01. Requirement: REL-04, USAB-06.

    Args:
        recipient (str): Mobile number, for example +8801712345678.
        message (str): The text of the message.

    Returns:
        bool: True when the message was handled.

    Raises:
        ValueError: If no mobile number was given.
    """
    if not recipient or not recipient.strip():
        raise ValueError(
            "No mobile number was given. Please enter a mobile number "
            "such as +8801712345678 and try again."
        )
    print(f"[SMS] To: {recipient} | Message: {message}")
    return True


def send_email(recipient, subject, message):
    """Print an email to the terminal instead of sending it.

    Story: NOT-01. Requirement: REL-04, USAB-06.

    Args:
        recipient (str): Email address of the receiver.
        subject (str): The subject line.
        message (str): The body of the email.

    Returns:
        bool: True when the email was handled.

    Raises:
        ValueError: If no email address was given.
    """
    if not recipient or not recipient.strip():
        raise ValueError(
            "No email address was given. Please enter an email address "
            "such as name@example.com and try again."
        )
    print(f"[EMAIL] To: {recipient} | Subject: {subject} | Message: {message}")
    return True