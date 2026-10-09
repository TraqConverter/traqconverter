"""A client can leave an email on "I've paid"; we send one "document ready" email when the link is paid, then forget it."""
import json
from datetime import datetime, timedelta

import pytest

from app.models.delivery_link import DeliveryLink
from tests.test_protected_links import _protected, shared, stub_export  # noqa: F401

ADDRESS = "Mario.Rossi@Example.com"


def _claim(client, token, email=None):
    body = {"email": email} if email is not None else None
    return client.post(f"/public/delivery/{token}/paid", json=body)


def _unlock(client, owner, project, link_id):
    return client.post(f"/projects/{project.id}/delivery-links/{link_id}/unlock", headers=owner["headers"])


def _row(db) -> DeliveryLink:
    row = db.query(DeliveryLink).one()
    db.refresh(row)
    return row


def _client_mails(emails):
    return [m for m in emails if m["to"] != "translator@traqtest.io"]


@pytest.mark.parametrize("bad", ["not-an-email", "mario@", "@example.com", "a b@example.com", "x" * 400 + "@ex.com"])
def test_a_bad_email_is_rejected_and_nothing_is_recorded(client, db, shared, emails, bad):
    owner, project = shared
    _, token = _protected(client, owner, project)
    r = _claim(client, token, bad)
    assert r.status_code == 422
    assert bad not in r.text
    row = _row(db)
    assert row.client_email is None and row.paid_claimed_at is None
    assert emails == []


def test_the_email_is_stored_on_claim(client, db, shared, emails):
    owner, project = shared
    _, token = _protected(client, owner, project)
    r = _claim(client, token, f"  {ADDRESS} ")
    assert r.status_code == 200 and r.json() == {"paid_claimed": True, "locked": True}
    row = _row(db)
    assert row.client_email == "Mario.Rossi@example.com"
    assert row.paid_claimed_at is not None
    # An empty field is the same as no email.
    assert _claim(client, token, "").status_code == 200
    assert _row(db).client_email == "Mario.Rossi@example.com"


def test_the_email_is_never_in_api_responses(client, db, shared, emails, caplog):
    owner, project = shared
    body, token = _protected(client, owner, project)
    with caplog.at_level("DEBUG"):
        claim = _claim(client, token, ADDRESS)
        listed = client.get(f"/projects/{project.id}/delivery-links", headers=owner["headers"])
        projects = client.get("/projects/", headers=owner["headers"])
        info = client.get(f"/public/delivery/{token}")
    for r in (claim, listed, projects, info):
        assert r.status_code == 200
        assert "mario" not in r.text.lower()
    assert listed.json()[0]["client_will_be_emailed"] is True
    [row] = [p for p in projects.json() if p["id"] == str(project.id)]
    assert row["payment"]["client_will_be_emailed"] is True
    assert "mario" not in caplog.text.lower()
    assert all("mario" not in json.dumps(m).lower() for m in emails)


def test_unlock_emails_the_client_once_with_the_link_then_forgets_the_address(client, db, shared, emails, caplog):
    owner, project = shared
    body, token = _protected(client, owner, project)
    _claim(client, token, ADDRESS)
    with caplog.at_level("DEBUG"):
        r = _unlock(client, owner, project, body["id"])
    assert r.status_code == 200
    assert "mario" not in r.text.lower()
    listed = client.get(f"/projects/{project.id}/delivery-links", headers=owner["headers"]).json()[0]
    assert listed["client_will_be_emailed"] is False

    [mail] = _client_mails(emails)
    assert mail["to"] == "Mario.Rossi@example.com"
    assert mail["subject"] == "Your document is ready"
    url = f"/d/{token}"
    assert url in mail["html"] and url in mail["text_fallback"]
    assert "Espresso Translations" in mail["text_fallback"]
    assert "diploma - translation.pdf" in mail["text_fallback"]
    assert "Sent by OnlineDocTranslator" in mail["html"]
    assert _row(db).client_email is None
    assert "mario" not in caplog.text.lower()

    assert _unlock(client, owner, project, body["id"]).status_code == 200
    assert len(_client_mails(emails)) == 1


def test_no_email_means_no_client_mail(client, db, shared, emails):
    owner, project = shared
    body, token = _protected(client, owner, project)
    _claim(client, token)
    assert _unlock(client, owner, project, body["id"]).status_code == 200
    assert _client_mails(emails) == []
    assert client.get(f"/projects/{project.id}/delivery-links", headers=owner["headers"]).json()[0][
        "client_will_be_emailed"
    ] is False


def test_an_email_left_after_the_unlock_is_not_kept(client, db, shared, emails):
    owner, project = shared
    body, token = _protected(client, owner, project)
    _unlock(client, owner, project, body["id"])
    assert _claim(client, token, ADDRESS).status_code == 200
    assert _row(db).client_email is None


def test_a_later_claim_replaces_the_address_and_still_only_one_mail_goes(client, db, shared, emails):
    owner, project = shared
    body, token = _protected(client, owner, project)
    _claim(client, token, "first@example.com")
    _claim(client, token, "second@example.com")
    assert _row(db).client_email == "second@example.com"
    _unlock(client, owner, project, body["id"])
    assert [m["to"] for m in _client_mails(emails)] == ["second@example.com"]


def test_revoking_clears_the_email(client, db, shared, emails):
    owner, project = shared
    body, token = _protected(client, owner, project)
    _claim(client, token, ADDRESS)
    r = client.delete(f"/projects/{project.id}/delivery-links/{body['id']}", headers=owner["headers"])
    assert r.status_code == 200 and "mario" not in r.text.lower()
    assert _row(db).client_email is None


def test_cleanup_clears_the_email_of_an_expired_link(client, db, shared, emails):
    from app.services.delivery_links import purge_expired_files

    owner, project = shared
    _, token = _protected(client, owner, project)
    _claim(client, token, ADDRESS)
    row = _row(db)
    row.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    purge_expired_files()
    db.expire_all()
    assert _row(db).client_email is None


def test_cleanup_keeps_the_email_of_a_live_link(client, db, shared, emails):
    from app.services.delivery_links import purge_expired_files

    owner, project = shared
    _, token = _protected(client, owner, project)
    _claim(client, token, ADDRESS)
    purge_expired_files()
    db.expire_all()
    assert _row(db).client_email == "Mario.Rossi@example.com"


def test_deleting_the_project_deletes_the_email(client, db, shared, emails):
    owner, project = shared
    _, token = _protected(client, owner, project)
    _claim(client, token, ADDRESS)
    assert client.delete(f"/projects/{project.id}", headers=owner["headers"]).status_code == 200
    assert db.query(DeliveryLink).filter(DeliveryLink.client_email.isnot(None)).count() == 0


def test_a_failed_send_does_not_break_the_unlock(client, db, shared, monkeypatch, caplog):
    import app.services.email_service as email_service

    owner, project = shared
    body, token = _protected(client, owner, project)
    monkeypatch.setattr(email_service, "send_email", lambda **kw: True)
    _claim(client, token, ADDRESS)

    def boom(**kw):
        raise RuntimeError(f"Resend said no to {kw['to']}")

    monkeypatch.setattr(email_service, "send_email", boom)
    with caplog.at_level("DEBUG"):
        r = _unlock(client, owner, project, body["id"])
    assert r.status_code == 200 and r.json()["payment_status"] == "unlocked"
    row = _row(db)
    assert row.unlocked_at is not None and row.client_email is None
    assert "Couldn't send the client ready email" in caplog.text
    assert "mario" not in caplog.text.lower()
    assert client.get(f"/public/delivery/{token}/file").status_code == 200


def test_a_failed_send_logs_no_address(client, db, shared, monkeypatch, caplog):
    import app.services.email_service as email_service

    owner, project = shared
    body, token = _protected(client, owner, project)
    _claim(client, token, ADDRESS)
    monkeypatch.setattr(email_service, "send_email", lambda **kw: False)
    with caplog.at_level("DEBUG"):
        assert _unlock(client, owner, project, body["id"]).status_code == 200
    assert "Client ready email not sent" in caplog.text
    assert "mario" not in caplog.text.lower()


def test_no_mail_when_the_link_url_cant_be_recovered(client, db, shared, emails):
    owner, project = shared
    body, token = _protected(client, owner, project)
    _claim(client, token, ADDRESS)
    row = _row(db)
    row.token_sealed = None
    db.commit()
    assert _unlock(client, owner, project, body["id"]).status_code == 200
    assert _client_mails(emails) == []
    assert _row(db).client_email is None
