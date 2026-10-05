import hashlib
import logging
import re
from datetime import datetime, timedelta

import pytest

from app.core.security import verify_password
from app.models.password_reset import PasswordResetToken

GENERIC = "If an account exists for that email, we've sent a reset link."
INVALID = "This reset link is invalid or has expired."
NEW_PASSWORD = "a brand new password"


@pytest.fixture()
def mail(monkeypatch):
    """Resend configured, sends captured instead of made."""
    import app.services.email_service as email_service

    sent: list[dict] = []
    monkeypatch.setattr(email_service, "is_configured", lambda: True)
    monkeypatch.setattr(email_service, "send_email", lambda **kw: sent.append(kw) or True)
    return sent


def _forgot(client, email, ip="198.51.100.1"):
    return client.post("/auth/forgot-password", json={"email": email}, headers={"X-Forwarded-For": ip})


def _token_from(sent_email) -> str:
    return re.search(r"/reset-password\?token=([A-Za-z0-9_\-]+)", sent_email["html"]).group(1)


def _request_token(client, mail, email) -> str:
    assert _forgot(client, email).status_code == 200
    return _token_from(mail[-1])


def _reset(client, token, password=NEW_PASSWORD):
    return client.post("/auth/reset-password", json={"token": token, "new_password": password})


def test_known_and_unknown_emails_get_the_same_answer(client, make_user, mail):
    make_user(email="known@traqtest.io")
    known = _forgot(client, "known@traqtest.io")
    unknown = _forgot(client, "nobody@traqtest.io")
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json() == {"message": GENERIC}
    assert len(mail) == 1
    assert mail[0]["to"] == "known@traqtest.io"
    assert mail[0]["subject"] == "Reset your TraqConverter password"
    assert "http://localhost:3000/reset-password?token=" in mail[0]["html"]
    assert "expires in 60 minutes" in mail[0]["html"]
    assert "If you didn't ask for this, you can ignore this email." in mail[0]["html"]


def test_email_lookup_ignores_case(client, make_user, mail):
    make_user(email="mixed@traqtest.io")
    assert _forgot(client, "MIXED@traqtest.io").status_code == 200
    assert len(mail) == 1


def test_token_is_stored_only_as_a_hash(client, db, make_user, mail):
    user = make_user(email="hash@traqtest.io")
    token = _request_token(client, mail, "hash@traqtest.io")
    row = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user["user"].id).one()
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in {row.token_hash, row.request_ip}
    assert row.expires_at - row.created_at == timedelta(minutes=60)


def test_new_request_invalidates_the_previous_link(client, make_user, mail):
    make_user(email="twice@traqtest.io")
    first = _request_token(client, mail, "twice@traqtest.io")
    second = _request_token(client, mail, "twice@traqtest.io")
    assert _reset(client, first).status_code == 400
    assert _reset(client, second).status_code == 200


def test_forgot_is_rate_limited_per_email(client, make_user, mail):
    make_user(email="spam@traqtest.io")
    statuses = [_forgot(client, "spam@traqtest.io", ip=f"203.0.113.{i}").status_code for i in range(7)]
    assert statuses[:5] == [200] * 5
    assert statuses[5:] == [429, 429]
    assert len(mail) == 5


def test_forgot_is_rate_limited_per_ip(client, mail):
    statuses = [_forgot(client, f"probe{i}@traqtest.io").status_code for i in range(7)]
    assert statuses[:5] == [200] * 5
    assert statuses[5:] == [429, 429]


def test_reset_works_once(client, db, make_user, mail):
    user = make_user(email="once@traqtest.io")
    token = _request_token(client, mail, "once@traqtest.io")

    r = _reset(client, token)
    assert r.status_code == 200
    db.refresh(user["user"])
    assert verify_password(NEW_PASSWORD, user["user"].password_hash)
    login = client.post("/auth/login", json={"email": "once@traqtest.io", "password": NEW_PASSWORD})
    assert login.status_code == 200

    again = _reset(client, token, "yet another password")
    assert again.status_code == 400
    assert again.json()["detail"] == INVALID


def test_unknown_token_is_rejected(client, db):
    r = _reset(client, "not-a-real-token")
    assert r.status_code == 400
    assert r.json()["detail"] == INVALID


def test_expired_token_is_rejected(client, db, make_user, mail):
    make_user(email="late@traqtest.io")
    token = _request_token(client, mail, "late@traqtest.io")
    row = db.query(PasswordResetToken).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    r = _reset(client, token)
    assert r.status_code == 400
    assert r.json()["detail"] == INVALID


@pytest.mark.parametrize("weak", ["short", "        ", "x" * 129])
def test_weak_password_is_rejected_like_registration(client, db, make_user, mail, weak):
    user = make_user(email="weak@traqtest.io")
    old_hash = user["user"].password_hash
    token = _request_token(client, mail, "weak@traqtest.io")
    assert _reset(client, token, weak).status_code == 422
    db.refresh(user["user"])
    assert user["user"].password_hash == old_hash
    assert _reset(client, token).status_code == 200


def test_reset_invalidates_other_unused_tokens(client, db, make_user, mail):
    user = make_user(email="others@traqtest.io")
    token = _request_token(client, mail, "others@traqtest.io")
    # A second live token, as if created before the invalidate-on-request rule.
    other = "another-live-token"
    db.add(PasswordResetToken(
        user_id=user["user"].id,
        token_hash=hashlib.sha256(other.encode()).hexdigest(),
        expires_at=datetime.utcnow() + timedelta(minutes=30),
    ))
    db.commit()

    assert _reset(client, token).status_code == 200
    assert _reset(client, other).status_code == 400
    assert db.query(PasswordResetToken).filter(PasswordResetToken.used_at.is_(None)).count() == 0


def test_reset_signs_out_existing_sessions(client, make_user, mail):
    user = make_user(email="session@traqtest.io")
    assert client.get("/auth/me", headers=user["headers"]).status_code == 200
    token = _request_token(client, mail, "session@traqtest.io")
    assert _reset(client, token).status_code == 200
    assert client.get("/auth/me", headers=user["headers"]).status_code == 401

    login = client.post("/auth/login", json={"email": "session@traqtest.io", "password": NEW_PASSWORD})
    fresh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/auth/me", headers=fresh).status_code == 200


def test_change_password_signs_out_existing_sessions(client, make_user):
    user = make_user()
    r = client.post(
        "/auth/change-password",
        headers=user["headers"],
        json={"current_password": "correct horse battery", "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 200
    assert client.get("/auth/me", headers=user["headers"]).status_code == 401
    fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/auth/me", headers=fresh).status_code == 200


def test_reset_is_rate_limited(client, db):
    statuses = [_reset(client, f"guess-{i}").status_code for i in range(12)]
    assert statuses[:10] == [400] * 10
    assert statuses[10:] == [429, 429]


def test_no_email_when_resend_is_not_configured(client, db, make_user, monkeypatch, caplog):
    import app.services.email_service as email_service

    monkeypatch.setattr(email_service, "RESEND_URL", "http://must-not-be-called.invalid")
    posts = []
    monkeypatch.setattr(email_service.requests, "post", lambda *a, **kw: posts.append(kw))
    monkeypatch.setattr(email_service.settings, "RESEND_API_KEY", None)
    make_user(email="nomail@traqtest.io")

    with caplog.at_level(logging.WARNING):
        r = _forgot(client, "nomail@traqtest.io")
    assert r.status_code == 200
    assert r.json() == {"message": GENERIC}
    assert posts == []
    assert any("not configured" in rec.getMessage() for rec in caplog.records)


def test_token_never_reaches_the_logs(client, db, make_user, mail, caplog):
    make_user(email="logs@traqtest.io")
    with caplog.at_level(logging.DEBUG):
        token = _request_token(client, mail, "logs@traqtest.io")
        _reset(client, token)
    assert all(token not in rec.getMessage() for rec in caplog.records)
