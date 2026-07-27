import re

from app.core.exceptions import bad_request

EMAIL_REGEX = r"^[\w\.-]+@[\w\.-]+\.\w+$"
PHONE_REGEX = r"^[0-9+\-\s]{8,20}$"


def validate_email(email: str | None):
    if not email:
        return

    if not re.fullmatch(EMAIL_REGEX, email):
        bad_request("Invalid email address")


def validate_phone(phone: str | None):
    if not phone:
        return

    if not re.fullmatch(PHONE_REGEX, phone):
        bad_request("Invalid phone number")


def validate_required(value, field_name: str):
    if value is None:
        bad_request(f"{field_name} is required")

    if isinstance(value, str) and not value.strip():
        bad_request(f"{field_name} is required")


def validate_length(
    value: str | None, field_name: str, min_length: int = 1, max_length: int = 255
):
    if value is None:
        return

    value = value.strip()

    if len(value) < min_length:
        bad_request(f"{field_name} must be at least {min_length} characters")

    if len(value) > max_length:
        bad_request(f"{field_name} cannot exceed {max_length} characters")


def validate_company_email(email: str, domain: str):
    validate_email(email)

    if not email.lower().endswith(f"@{domain.lower()}"):
        bad_request(f"Only @{domain} email addresses are allowed")
