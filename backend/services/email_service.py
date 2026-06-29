import logging
import os

import httpx

logger = logging.getLogger("email_service")

_API_URL = "https://api.brevo.com/v3/smtp/email"
_API_KEY = os.environ.get("BREVO_API_KEY", "")
_FROM_EMAIL = os.environ.get("BREVO_FROM_EMAIL", "")
_FROM_NAME = os.environ.get("BREVO_FROM_NAME", "Bird Stream")
_APP_URL = os.environ.get("APP_URL", "http://localhost:5173")


async def _send(to_email: str, to_name: str, subject: str, html: str, text: str) -> bool:
    if not _API_KEY or not _FROM_EMAIL:
        logger.warning("Brevo not configured (BREVO_API_KEY / BREVO_FROM_EMAIL missing)")
        return False
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            _API_URL,
            headers={"api-key": _API_KEY, "Content-Type": "application/json"},
            json={
                "sender": {"email": _FROM_EMAIL, "name": _FROM_NAME},
                "to": [{"email": to_email, "name": to_name}],
                "subject": subject,
                "htmlContent": html,
                "textContent": text,
            },
        )
    if resp.status_code == 201:
        logger.info(f"Email '{subject}' sent to {to_email}")
        return True
    logger.error(f"Brevo {resp.status_code}: {resp.text}")
    return False


async def send_verification_email(to_email: str, username: str, token: str) -> bool:
    url = f"{_APP_URL}?verify-token={token}"
    return await _send(
        to_email=to_email,
        to_name=username,
        subject="Verify your Bird Stream account",
        html=(
            f"<h2>Welcome to Bird Stream, {username}!</h2>"
            f"<p>Click the link below to verify your email address. It expires in 24 hours.</p>"
            f'<p><a href="{url}">{url}</a></p>'
        ),
        text=(
            f"Welcome to Bird Stream, {username}!\n\n"
            f"Verify your email (link expires in 24 hours):\n{url}"
        ),
    )


async def send_password_reset_email(to_email: str, username: str, token: str) -> bool:
    url = f"{_APP_URL}?reset-token={token}"
    return await _send(
        to_email=to_email,
        to_name=username,
        subject="Reset your Bird Stream password",
        html=(
            f"<h2>Password reset</h2>"
            f"<p>Hi {username}, click below to set a new password. The link expires in 1 hour.</p>"
            f'<p><a href="{url}">{url}</a></p>'
            f"<p>If you didn't request this, you can safely ignore this email.</p>"
        ),
        text=(
            f"Hi {username},\n\n"
            f"Reset your password (link expires in 1 hour):\n{url}\n\n"
            f"If you didn't request this, ignore this email."
        ),
    )
