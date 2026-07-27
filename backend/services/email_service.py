import logging
import os
from base64 import b64encode
from datetime import datetime
from html import escape
from urllib.parse import urlencode

import httpx
from sqlalchemy import select

from models.orm import User

logger = logging.getLogger("email_service")

_API_URL = "https://api.brevo.com/v3/smtp/email"
_API_KEY = os.environ.get("BREVO_API_KEY", "")
_FROM_EMAIL = os.environ.get("BREVO_FROM_EMAIL", "")
_FROM_NAME = os.environ.get("BREVO_FROM_NAME", "Bird Stream")
_APP_URL = os.environ.get("APP_URL", "http://localhost:5173").rstrip("/")


def _app_link(**params: str) -> str:
    return f"{_APP_URL}?{urlencode(params)}"


def render_email_template(
    *,
    preheader: str,
    eyebrow: str,
    title: str,
    greeting: str,
    message: str,
    action_label: str,
    action_url: str,
    note: str,
    snapshot_data_url: str | None = None,
    snapshot_alt: str = "Bird detected on the main camera",
) -> str:
    """Render the shared, email-client-safe Bird Stream layout.

    All arguments are treated as plain text. Keeping this helper generic makes
    it the default presentation layer for future transactional emails.
    """
    values = {
        key: escape(value, quote=True)
        for key, value in {
            "preheader": preheader,
            "eyebrow": eyebrow,
            "title": title,
            "greeting": greeting,
            "message": message,
            "action_label": action_label,
            "action_url": action_url,
            "note": note,
        }.items()
    }
    logo_url = escape(f"{_APP_URL}/birb.png", quote=True)
    snapshot_html = ""
    if snapshot_data_url:
        if not snapshot_data_url.startswith("data:image/jpeg;base64,"):
            raise ValueError("Snapshot must be a base64-encoded JPEG data URL")
        snapshot_html = f"""
              <div style="margin:2px 0 26px;padding:8px;background:#edf3e8;border:1px solid #d8e4d2;border-radius:16px;">
                <img src="{escape(snapshot_data_url, quote=True)}" width="500"
                     alt="{escape(snapshot_alt, quote=True)}"
                     style="display:block;width:100%;max-width:500px;height:auto;border-radius:10px;">
                <p style="margin:8px 4px 2px;font-size:12px;line-height:18px;color:#718071;">
                  Snapshot from the main camera
                </p>
              </div>"""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{values["title"]}</title>
</head>
<body style="margin:0;padding:0;background:#f4f1e8;color:#30483a;font-family:Arial,'Helvetica Neue',sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
    {values["preheader"]}
  </div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f4f1e8;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
               style="max-width:600px;background:#fffdf8;border:1px solid #dfe6d8;border-radius:24px;overflow:hidden;box-shadow:0 12px 36px rgba(55,78,61,.10);">
          <tr>
            <td style="height:10px;background:#9fbd88;font-size:0;line-height:0;">&nbsp;</td>
          </tr>
          <tr>
            <td align="center" style="padding:28px 36px 6px;">
              <div style="font-size:23px;line-height:1;color:#77966a;letter-spacing:10px;margin-bottom:-14px;">&#127807;&nbsp;&nbsp;&#127811;</div>
              <img src="{logo_url}" width="112" alt="Bird Stream birb"
                   style="display:block;width:112px;max-width:100%;height:auto;margin:0 auto;">
              <div style="font-size:12px;line-height:18px;font-weight:bold;letter-spacing:2px;text-transform:uppercase;color:#78916e;">
                {values["eyebrow"]}
              </div>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding:8px 42px 34px;">
              <h1 style="margin:0 0 18px;font-family:Georgia,'Times New Roman',serif;font-size:34px;line-height:42px;font-weight:normal;color:#2f513e;">
                {values["title"]}
              </h1>
              <p style="margin:0 0 12px;font-size:17px;line-height:27px;color:#405848;">{values["greeting"]}</p>
              <p style="margin:0 0 26px;font-size:15px;line-height:25px;color:#617064;">{values["message"]}</p>
              {snapshot_html}
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td align="center" bgcolor="#52785f" style="border-radius:999px;">
                    <a href="{values["action_url"]}"
                       style="display:inline-block;padding:14px 28px;border:1px solid #52785f;border-radius:999px;color:#ffffff;text-decoration:none;font-size:15px;line-height:20px;font-weight:bold;">
                      {values["action_label"]} &nbsp;&#8594;
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:24px 0 0;font-size:13px;line-height:21px;color:#879087;">{values["note"]}</p>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding:20px 34px;background:#edf3e8;border-top:1px solid #dfe8d8;">
              <div style="font-size:18px;line-height:22px;color:#7fa06f;">&#10087;&nbsp; &#127811; &nbsp;&#10087;</div>
              <p style="margin:7px 0 0;font-size:12px;line-height:18px;color:#718071;">
                Sent with a little birbsong from Birb Stream
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


async def _send(
    to_email: str,
    to_name: str,
    subject: str,
    html: str,
    text: str,
    attachments: list[dict[str, str]] | None = None,
) -> bool:
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
                **({"attachment": attachments} if attachments else {}),
            },
        )
    if resp.status_code == 201:
        logger.info("Email '%s' sent to %s", subject, to_email)
        return True
    logger.error("Brevo %s: %s", resp.status_code, resp.text)
    return False


async def send_verification_email(to_email: str, username: str, token: str) -> bool:
    url = _app_link(**{"verify-token": token})
    return await _send(
        to_email=to_email,
        to_name=username,
        subject="Welcome to Birb Stream — verify your email",
        html=render_email_template(
            preheader="One small step before you can settle in.",
            eyebrow="Welcome to the flock",
            title="Let’s make it official",
            greeting=f"Hi {username},",
            message="Thanks for joining Birb Stream. Confirm your email address and you’ll be ready to watch, chat, and enjoy the view.",
            action_label="Verify my email",
            action_url=url,
            note="This link is available for 24 hours. If you didn’t create this account, you can safely ignore this email.",
        ),
        text=(
            f"Welcome to Birb Stream, {username}!\n\n"
            f"Verify your email (link expires in 24 hours):\n{url}\n\n"
            "If you didn't create this account, you can safely ignore this email."
        ),
    )


async def send_password_reset_email(to_email: str, username: str, token: str) -> bool:
    url = _app_link(**{"reset-token": token})
    return await _send(
        to_email=to_email,
        to_name=username,
        subject="Reset your Birb Stream password",
        html=render_email_template(
            preheader="Your secure password reset link is inside.",
            eyebrow="A fresh start",
            title="Forgot your password?",
            greeting=f"Hi {username},",
            message="No worries — it happens to the best of us. Use the button below to choose a new password and get back to the stream.",
            action_label="Choose a new password",
            action_url=url,
            note="This link is available for 1 hour. If you didn’t request a password reset, there’s nothing you need to do.",
        ),
        text=(
            f"Hi {username},\n\n"
            f"Reset your password (link expires in 1 hour):\n{url}\n\n"
            f"If you didn't request this, ignore this email."
        ),
    )


async def send_bird_alert_email(
    to_email: str,
    username: str,
    snapshot_jpeg: bytes,
    detected_at: str,
) -> bool:
    """Send a bird alert containing the exact JPEG frame that triggered it."""
    encoded_snapshot = b64encode(snapshot_jpeg).decode("ascii")
    snapshot_data_url = f"data:image/jpeg;base64,{encoded_snapshot}"
    watch_url = _APP_URL
    return await _send(
        to_email=to_email,
        to_name=username,
        subject="Birb Visiting",
        html=render_email_template(
            preheader="A birb has appeared.",
            eyebrow="Look who flew in",
            title="Birb is here!",
            greeting=f"Hi {username},",
            message=f"Spotted a birb on the main camera at {detected_at}. Take a peek before birb flies away.",
            action_label="Watch the live stream",
            action_url=watch_url,
            note="You’re receiving this because birb alerts are enabled in your account options. You can switch them off at any time.",
            snapshot_data_url=snapshot_data_url,
        ),
        text=(
            f"Hi {username},\n\n"
            f"Spotted a birb at {detected_at}.\n"
            f"Watch live: {watch_url}\n\n"
            "You can turn off birb alerts in your account options."
        ),
        attachments=[{"content": encoded_snapshot, "name": "bird-sighting.jpg"}],
    )


async def send_bird_alerts(
    db_factory,
    snapshot_jpeg: bytes,
    detected_at: str | None = None,
) -> int:
    """Notify every opted-in user. This is the detector integration boundary."""
    detected_at = detected_at or datetime.now().astimezone().strftime("%d %B %Y at %H:%M")
    with db_factory() as session:
        recipients = list(
            session.execute(
                select(User.email, User.username).where(
                    User.bird_notification_email.is_(True),
                    User.is_verified.is_(True),
                    User.is_blocked.is_(False),
                )
            ).all()
        )

    sent = 0
    for email, username in recipients:
        if await send_bird_alert_email(email, username, snapshot_jpeg, detected_at):
            sent += 1
    return sent
