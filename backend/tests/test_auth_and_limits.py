from types import SimpleNamespace

import pytest

from app.models.team_member import TeamInvite, TeamMember
from app.models.user import User


def _register(client, email, token=None):
    body = {"email": email, "password": "correct horse battery", "full_name": "New Person"}
    if token:
        body["invite_token"] = token
    return client.post("/auth/register", json=body)


@pytest.fixture()
def invite(db, make_user):
    owner = make_user()
    inv = TeamInvite(team_id=owner["team"].id, email="invitee@traqtest.io", role="MEMBER", invited_by=owner["user"].id)
    db.add(inv)
    db.commit()
    return owner, inv


def _member_of(db, email, team_id):
    user = db.query(User).filter(User.email == email).one()
    return db.query(TeamMember).filter(TeamMember.user_id == user.id, TeamMember.team_id == team_id).first()


def test_register_with_invited_email_but_no_token_does_not_join(client, db, invite):
    owner, _ = invite
    assert _register(client, "invitee@traqtest.io").status_code == 200
    assert _member_of(db, "invitee@traqtest.io", owner["team"].id) is None


def test_register_with_invite_token_joins_team(client, db, invite):
    owner, inv = invite
    assert _register(client, "invitee@traqtest.io", inv.token).status_code == 200
    assert _member_of(db, "invitee@traqtest.io", owner["team"].id) is not None


def test_token_for_another_email_is_useless(client, db, invite):
    owner, inv = invite
    assert _register(client, "attacker@traqtest.io", inv.token).status_code == 200
    assert _member_of(db, "attacker@traqtest.io", owner["team"].id) is None


def test_signed_in_user_accepts_with_token(client, db, invite, make_user):
    owner, inv = invite
    existing = make_user(email="invitee@traqtest.io")
    assert client.post("/members/invites/accept", headers=existing["headers"], json={"token": "wrong"}).status_code == 404
    assert client.post("/members/invites/accept", headers=existing["headers"], json={"token": inv.token}).status_code == 200


def test_trial_cannot_invite(client, make_user):
    trial = make_user(plan="TRIAL", credits=1)
    r = client.post("/members/invite", headers=trial["headers"], json={"email": "x@traqtest.io"})
    assert r.status_code == 403


def test_spoofed_forwarded_for_does_not_change_client_ip():
    from app.dependencies.rate_limit import client_ip

    req = SimpleNamespace(
        headers={"x-forwarded-for": "1.2.3.4, 203.0.113.9"},
        client=SimpleNamespace(host="10.0.0.1"),
    )
    assert client_ip(req) == "203.0.113.9"


def test_login_rate_limit_ignores_spoofed_header(client, db, make_user):
    user = make_user(email="victim@traqtest.io")
    statuses = []
    for i in range(12):
        r = client.post(
            "/auth/login",
            json={"email": "victim@traqtest.io", "password": "wrong"},
            headers={"X-Forwarded-For": f"10.9.{i}.1, 198.51.100.7"},
        )
        statuses.append(r.status_code)
    assert 429 in statuses
    assert user


def test_page_counts(tmp_path):
    from docx import Document

    from app.core.page_counter import get_page_count
    from tests.conftest import make_pdf

    assert get_page_count(str(make_pdf(tmp_path / "a.pdf", pages=4))) == 4

    doc = Document()
    table = doc.add_table(rows=60, cols=2)
    for row in table.rows:
        for cell in row.cells:
            cell.text = " ".join(["parola"] * 10)
    path = tmp_path / "tables.docx"
    doc.save(path)
    assert get_page_count(str(path)) == 3


def test_page_cap(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from app.core import page_counter
    from tests.conftest import make_pdf

    monkeypatch.setattr(page_counter, "MAX_PAGES", 3)
    with pytest.raises(HTTPException):
        page_counter.get_page_count(str(make_pdf(tmp_path / "big.pdf", pages=4)))
