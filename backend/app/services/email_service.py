"""Transactional email — Resend integration.

Why direct HTTP instead of the `resend` SDK
-------------------------------------------
The `requests` library is already in our deps. Adding the `resend`
SDK would pull in `pydantic` v1 in some versions and increase the
attack surface for one POST request. A 30-line wrapper around
Resend's REST endpoint is simpler.

Falls back to a no-op (logging only) when RESEND_API_KEY is not
configured, so local dev keeps working without setting up Resend.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)


RESEND_URL = "https://api.resend.com/emails"


def is_configured() -> bool:
    return bool(getattr(settings, "RESEND_API_KEY", None))


def send_email(
    *,
    to: str | list[str],
    subject: str,
    html: str,
    text_fallback: Optional[str] = None,
    from_email: Optional[str] = None,
) -> bool:
    """Send a transactional email via Resend. Returns True on success.

    `to` accepts a single address or a list. `text_fallback` is shown
    in clients that don't render HTML; if you don't pass one we strip
    tags from the HTML as a best-effort fallback.

    On any failure (missing key, 4xx/5xx, network), we log and return
    False. Callers should NOT raise — invite flows shouldn't break
    just because email delivery hiccups.
    """
    if not is_configured():
        logger.info(
            "Resend not configured (no RESEND_API_KEY) — skipping email "
            "to %s (subject=%r)",
            to,
            subject,
        )
        return False

    sender = from_email or getattr(
        settings, "RESEND_FROM_EMAIL", None
    )
    if not sender:
        logger.warning(
            "RESEND_FROM_EMAIL not set — using a placeholder sender. "
            "Some recipients may reject the message."
        )
        sender = "no-reply@example.com"

    if isinstance(to, str):
        to_list = [to]
    else:
        to_list = list(to)

    payload = {
        "from": sender,
        "to": to_list,
        "subject": subject,
        "html": html,
    }
    if text_fallback:
        payload["text"] = text_fallback
    else:

        import re as _re
        no_tags = _re.sub(r"<[^>]+>", " ", html)
        payload["text"] = _re.sub(r"\s+", " ", no_tags).strip()

    try:
        resp = requests.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
    except Exception as e:
        logger.warning("Resend request failed: %s", e)
        return False

    if resp.status_code >= 400:
        logger.warning(
            "Resend returned %s: %s",
            resp.status_code,
            (resp.text or "")[:300],
        )
        return False

    logger.info(
        "Resend accepted email to %s (subject=%r)", to_list, subject
    )
    return True







def render_invite_email(
    *,
    inviter_name: str,
    inviter_email: str,
    team_name: str,
    role: str,
    register_url: str,
) -> tuple[str, str]:
    """Return (subject, html) for a team-invite email."""
    from html import escape

    # Names and team names are user-typed; unescaped they'd put markup in an email sent from our domain.
    subject = f"{inviter_name or inviter_email} invited you to {team_name or 'your team'} on OnlineDocTranslator"
    safe_role = escape((role or "Member").capitalize())
    safe_team = escape(team_name or "your team")
    safe_inviter = escape(inviter_name or inviter_email)
    register_url = escape(register_url, quote=True)

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#faf5ee;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1f2a2e;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#faf5ee;padding:32px 12px;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e7ddc5;border-radius:18px;padding:36px 32px;max-width:560px;">
        <tr><td>
          <div style="margin-bottom:24px;">
            <img src="https://www.onlinedoctranslator.ai/brand/logo-horizontal-1200x300.png" width="216" height="54" alt="OnlineDocTranslator" style="display:block;border:0;outline:none;text-decoration:none;width:216px;height:54px;">
          </div>
          <h1 style="font-size:24px;font-weight:700;letter-spacing:-0.02em;color:#1f2a2e;margin:0 0 14px;">
            You've been invited to join <span style="color:#0a7870;">{safe_team}</span>
          </h1>
          <p style="font-size:15px;line-height:1.55;color:#4a4638;margin:0 0 18px;">
            <strong>{safe_inviter}</strong> has invited you to join their team on OnlineDocTranslator as a <strong>{safe_role}</strong>. You'll get access to all team projects, translation memory, glossary, and certifications.
          </p>
          <div style="margin:28px 0;">
            <a href="{register_url}" style="display:inline-block;background:#0a7870;color:#ffffff;padding:13px 26px;border-radius:999px;font-weight:600;font-size:14px;text-decoration:none;">
              Accept invite &amp; create account
            </a>
          </div>
          <p style="font-size:13px;line-height:1.5;color:#8a8270;margin:0 0 8px;">
            If the button doesn't work, copy this link into your browser:
          </p>
          <p style="font-size:12px;line-height:1.5;color:#0a7870;word-break:break-all;margin:0 0 24px;">
            {register_url}
          </p>
          <hr style="border:none;border-top:1px solid #f1e8d1;margin:20px 0;">
          <p style="font-size:12px;color:#8a8270;line-height:1.5;margin:0;">
            Already have a OnlineDocTranslator account with this email? Just sign in — your invite will be accepted automatically and the team's projects will appear in your dashboard.
          </p>
        </td></tr>
      </table>
      <p style="font-size:11px;color:#9a9178;margin-top:18px;">
        Sent by OnlineDocTranslator · onlinedoctranslator.ai
      </p>
    </td></tr>
  </table>
</body>
</html>
"""
    return subject, html


def render_password_reset_email(*, name: str | None, link: str) -> tuple[str, str]:
    """Return (subject, html) for a password-reset email."""
    from html import escape

    subject = "Reset your OnlineDocTranslator password"
    greeting = f"Hi {escape(name)}," if name else "Hi,"
    safe_link = escape(link, quote=True)

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{subject}</title>
</head>
<body style="margin:0;padding:0;background:#faf5ee;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1f2a2e;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#faf5ee;padding:32px 12px;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e7ddc5;border-radius:18px;padding:36px 32px;max-width:560px;">
        <tr><td>
          <div style="margin-bottom:24px;">
            <img src="https://www.onlinedoctranslator.ai/brand/logo-horizontal-1200x300.png" width="216" height="54" alt="OnlineDocTranslator" style="display:block;border:0;outline:none;text-decoration:none;width:216px;height:54px;">
          </div>
          <h1 style="font-size:24px;font-weight:700;letter-spacing:-0.02em;color:#1f2a2e;margin:0 0 14px;">
            Reset your password
          </h1>
          <p style="font-size:15px;line-height:1.55;color:#4a4638;margin:0 0 18px;">
            {greeting} we got a request to reset the password for your OnlineDocTranslator account. Use the button below to choose a new one.
          </p>
          <div style="margin:28px 0;">
            <a href="{safe_link}" style="display:inline-block;background:#0a7870;color:#ffffff;padding:13px 26px;border-radius:999px;font-weight:600;font-size:14px;text-decoration:none;">
              Set a new password
            </a>
          </div>
          <p style="font-size:14px;line-height:1.5;color:#4a4638;margin:0 0 18px;">
            This link expires in 60 minutes and works once.
          </p>
          <p style="font-size:13px;line-height:1.5;color:#8a8270;margin:0 0 8px;">
            If the button doesn't work, copy this link into your browser:
          </p>
          <p style="font-size:12px;line-height:1.5;color:#0a7870;word-break:break-all;margin:0 0 24px;">
            {safe_link}
          </p>
          <hr style="border:none;border-top:1px solid #f1e8d1;margin:20px 0;">
          <p style="font-size:12px;color:#8a8270;line-height:1.5;margin:0;">
            If you didn't ask for this, you can ignore this email. Your password won't change.
          </p>
        </td></tr>
      </table>
      <p style="font-size:11px;color:#9a9178;margin-top:18px;">
        Sent by OnlineDocTranslator · onlinedoctranslator.ai
      </p>
    </td></tr>
  </table>
</body>
</html>
"""
    return subject, html


_STATUS_LABELS = {
    "PENDING": "Queued",
    "PROCESSING": "Translating",
    "FAILED": "Failed",
}


def project_status_label(status: str | None, review_status: str | None) -> str:
    """The status label the Projects page shows."""
    s = (getattr(status, "value", status) or "").upper()
    if s == "COMPLETED":
        r = (review_status or "").upper()
        if r == "CERTIFIED":
            return "Certified"
        if r == "IN_REVIEW":
            return "In review"
        return "Delivered"
    return _STATUS_LABELS.get(s, "Queued")


def render_assignment_email(
    *,
    assigner: str,
    file_name: str | None,
    source_language: str | None,
    target_language: str | None,
    page_count: int | None,
    status: str,
    link: str,
) -> tuple[str, str, str]:
    """Return (subject, html, text) for a project-assigned email."""
    from html import escape

    subject = f"{assigner} assigned you a translation"
    pair = f"{source_language or '?'} → {target_language or '?'}"
    pages = f"{page_count} page{'' if page_count == 1 else 's'}" if page_count is not None else "—"
    rows = [("File", file_name or "Untitled"), ("Languages", pair), ("Pages", pages), ("Status", status)]
    rows_html = "".join(
        f'<tr><td style="padding:6px 16px 6px 0;font-size:13px;color:#8a8270;white-space:nowrap;vertical-align:top;">{label}</td>'
        f'<td style="padding:6px 0;font-size:14px;color:#1f2a2e;font-weight:600;word-break:break-word;">{escape(value)}</td></tr>'
        for label, value in rows
    )
    safe_link = escape(link, quote=True)

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#faf5ee;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1f2a2e;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#faf5ee;padding:32px 12px;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e7ddc5;border-radius:18px;padding:36px 32px;max-width:560px;">
        <tr><td>
          <div style="margin-bottom:24px;">
            <img src="https://www.onlinedoctranslator.ai/brand/logo-horizontal-1200x300.png" width="216" height="54" alt="OnlineDocTranslator" style="display:block;border:0;outline:none;text-decoration:none;width:216px;height:54px;">
          </div>
          <h1 style="font-size:24px;font-weight:700;letter-spacing:-0.02em;color:#1f2a2e;margin:0 0 14px;">
            You have a new translation
          </h1>
          <p style="font-size:15px;line-height:1.55;color:#4a4638;margin:0 0 18px;">
            <strong>{escape(assigner)}</strong> assigned this project to you.
          </p>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#faf5ee;border:1px solid #f1e8d1;border-radius:12px;padding:10px 16px;">
            {rows_html}
          </table>
          <div style="margin:28px 0;">
            <a href="{safe_link}" style="display:inline-block;background:#0a7870;color:#ffffff;padding:13px 26px;border-radius:999px;font-weight:600;font-size:14px;text-decoration:none;">
              Open project
            </a>
          </div>
          <p style="font-size:13px;line-height:1.5;color:#8a8270;margin:0 0 8px;">
            If the button doesn't work, copy this link into your browser:
          </p>
          <p style="font-size:12px;line-height:1.5;color:#0a7870;word-break:break-all;margin:0 0 24px;">
            {safe_link}
          </p>
          <hr style="border:none;border-top:1px solid #f1e8d1;margin:20px 0;">
          <p style="font-size:12px;color:#8a8270;line-height:1.5;margin:0;">
            You're getting this because a teammate assigned you a project on OnlineDocTranslator.
          </p>
        </td></tr>
      </table>
      <p style="font-size:11px;color:#9a9178;margin-top:18px;">
        Sent by OnlineDocTranslator · onlinedoctranslator.ai
      </p>
    </td></tr>
  </table>
</body>
</html>
"""
    text = "\n".join(
        [f"{assigner} assigned you a translation on OnlineDocTranslator.", ""]
        + [f"{label}: {value}" for label, value in rows]
        + ["", f"Open project: {link}"]
    )
    return subject, html, text
