"""Registration requires accepting the Terms of Service; the acceptance time is stored."""
from datetime import datetime, timedelta

import pytest

from app.models.team_member import TeamInvite, TeamMember
from app.models.user import User


def _body(email, **extra):
    return {"email": email, "password": "correct horse battery", "full_name": "New Person", **extra}


@pytest.mark.parametrize("extra", [{}, {"accept_terms": False}, {"accept_terms": None}])
def test_register_without_accepting_terms_is_422(client, db, extra):
    r = client.post("/auth/register", json=_body("noterms@traqtest.io", **extra))
    assert r.status_code == 422
    assert db.query(User).filter(User.email == "noterms@traqtest.io").first() is None


def test_register_with_terms_stores_the_acceptance_time(client, db):
    before = datetime.utcnow() - timedelta(seconds=5)
    r = client.post("/auth/register", json=_body("terms@traqtest.io", accept_terms=True))
    assert r.status_code == 200
    user = db.query(User).filter(User.email == "terms@traqtest.io").one()
    assert user.terms_accepted_at is not None
    assert before <= user.terms_accepted_at <= datetime.utcnow() + timedelta(seconds=5)


def test_invite_registration_needs_the_terms_too(client, db, make_user):
    owner = make_user()
    inv = TeamInvite(team_id=owner["team"].id, email="invitee@traqtest.io", role="MEMBER", invited_by=owner["user"].id)
    db.add(inv)
    db.commit()

    r = client.post("/auth/register", json=_body("invitee@traqtest.io", invite_token=inv.token))
    assert r.status_code == 422
    assert db.query(User).filter(User.email == "invitee@traqtest.io").first() is None

    r = client.post("/auth/register", json=_body("invitee@traqtest.io", invite_token=inv.token, accept_terms=True))
    assert r.status_code == 200
    user = db.query(User).filter(User.email == "invitee@traqtest.io").one()
    assert user.terms_accepted_at is not None
    member = db.query(TeamMember).filter(TeamMember.user_id == user.id, TeamMember.team_id == owner["team"].id)
    assert member.first() is not None


def test_existing_users_are_unaffected(client, make_user):
    existing = make_user(email="old@traqtest.io")
    assert client.get("/auth/me", headers=existing["headers"]).status_code == 200
