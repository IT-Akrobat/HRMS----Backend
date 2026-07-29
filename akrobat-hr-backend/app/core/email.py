import smtplib
from email.message import EmailMessage

from app.core.config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_PASSWORD,
    SMTP_FROM_EMAIL,
    SMTP_USE_TLS,
)
from app.core.logger import logger

# ---------------------------------------------------------------------------
# Backs the "Email notifications" toggle in Settings > Notifications
# ("Receive a copy of important updates by email"). Used from
# app/notifications/services.py::notify_employee() to send an email copy
# of every in-app notification to employees who've opted in.
#
# Deliberately not raise-on-failure: a broken/unconfigured mailbox should
# never block the in-app notification (or whatever action triggered it)
# from going through. If SMTP_HOST isn't set at all, this just logs once
# per call and returns -- no crash, no exception bubbling up.
# ---------------------------------------------------------------------------


def send_email(to_email: str | None, subject: str, body: str) -> bool:
    if not to_email:
        return False

    if not SMTP_HOST or not SMTP_USERNAME or not SMTP_PASSWORD:
        logger.info(
            "SMTP not configured (SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD) -- "
            f"skipping email to {to_email}: {subject!r}"
        )
        return False

    try:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = SMTP_FROM_EMAIL or SMTP_USERNAME
        message["To"] = to_email
        message.set_content(body)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USE_TLS:
                server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)

        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False
