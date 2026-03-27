from __future__ import annotations

import html

import httpx

from app.config import Settings
from app.models import User


POSTMARK_EMAIL_URL = "https://api.postmarkapp.com/email"


def send_email(settings: Settings, *, to_email: str, subject: str, text_body: str, html_body: str) -> None:
    if not settings.password_reset_email_enabled or not settings.postmark_server_token:
        raise ValueError("Transactional email is not configured")
    payload = {
        "From": settings.postmark_from_email,
        "To": to_email,
        "Subject": subject,
        "TextBody": text_body,
        "HtmlBody": html_body,
        "MessageStream": "outbound",
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Postmark-Server-Token": settings.postmark_server_token,
    }
    with httpx.Client(timeout=10) as client:
        response = client.post(POSTMARK_EMAIL_URL, headers=headers, json=payload)
        response.raise_for_status()


def send_password_reset_email(settings: Settings, user: User, *, reset_url: str) -> None:
    safe_name = user.full_name or user.username
    subject = "Reset your Market Reaction Forecaster password"
    text_body = (
        f"Hi {safe_name},\n\n"
        "We received a request to reset your password.\n"
        f"Use this link to choose a new password: {reset_url}\n\n"
        "If you didn't request this change, you can ignore this email."
    )
    html_body = (
        f"<p>Hi {html.escape(safe_name)},</p>"
        "<p>We received a request to reset your password.</p>"
        f"<p><a href=\"{html.escape(reset_url, quote=True)}\">Choose a new password</a></p>"
        "<p>If you didn't request this change, you can ignore this email.</p>"
    )
    send_email(settings, to_email=user.email, subject=subject, text_body=text_body, html_body=html_body)
