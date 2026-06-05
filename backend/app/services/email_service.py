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
        # Cheap text fallback: strip tags + collapse whitespace.
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


# ============================================================
# Templates
# ============================================================


def render_invite_email(
    *,
    inviter_name: str,
    inviter_email: str,
    team_name: str,
    role: str,
    register_url: str,
) -> tuple[str, str]:
    """Return (subject, html) for a team-invite email."""
    safe_role = (role or "Member").capitalize()
    safe_team = team_name or "your team"
    safe_inviter = inviter_name or inviter_email
    subject = f"{safe_inviter} invited you to {safe_team} on TraqConverter"

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
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:24px;">
            <div style="width:36px;height:36px;border-radius:10px;background:#0a7870;color:#fff;font-weight:700;font-size:16px;display:inline-block;text-align:center;line-height:36px;">T</div>
            <span style="font-weight:600;font-size:16px;color:#1f2a2e;margin-left:10px;">TraqConverter</span>
          </div>
          <h1 style="font-size:24px;font-weight:700;letter-spacing:-0.02em;color:#1f2a2e;margin:0 0 14px;">
            You've been invited to join <span style="color:#0a7870;">{safe_team}</span>
          </h1>
          <p style="font-size:15px;line-height:1.55;color:#4a4638;margin:0 0 18px;">
            <strong>{safe_inviter}</strong> has invited you to join their team on TraqConverter as a <strong>{safe_role}</strong>. You'll get access to all team projects, translation memory, glossary, and certifications.
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
            Already have a TraqConverter account with this email? Just sign in — your invite will be accepted automatically and the team's projects will appear in your dashboard.
          </p>
        </td></tr>
      </table>
      <p style="font-size:11px;color:#9a9178;margin-top:18px;">
        Sent by TraqConverter · onlinedoctranslator.ai
      </p>
    </td></tr>
  </table>
</body>
</html>
"""
    return subject, html
