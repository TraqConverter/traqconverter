"""Sign-in, account deletion and invite emails, from the accounts audit. Stripe and email are mocked."""
import pytest

from app.models.project import TranslationProject
from app.models.segment_comment import SegmentComment
from app.models.translation_segment import TranslationSegment
from app.models.user import User

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def stripe_cancels(monkeypatch):
    import stripe

    cancelled = []
    monkeypatch.setattr(stripe.Subscription, "cancel", lambda sub_id, **kw: cancelled.append(sub_id))
    return cancelled


def _register(client, email):
    body = {"email": email, "password": PASSWORD, "full_name": "New Person", "accept_terms": True}
    return client.post("/auth/register", json=body)


def _delete(client, who):
    return client.post("/auth/delete-account", headers=who["headers"], json={"password": PASSWORD, "confirm": "DELETE"})


def test_sign_in_ignores_the_case_of_the_email(client):
    assert _register(client, "Maria.Rossi@Example.com").status_code == 200
    r = client.post("/auth/login", json={"email": "maria.rossi@example.com", "password": PASSWORD})
    assert r.status_code == 200
    assert _register(client, "maria.rossi@example.com").json()["detail"] == "Email already registered"


def test_sign_in_still_works_for_an_older_mixed_case_account(client, db, make_user):
    make_user(email="Old.Account@traqtest.io")
    r = client.post("/auth/login", json={"email": "old.account@traqtest.io", "password": PASSWORD})
    assert r.status_code == 200


def test_inviting_an_existing_user_ignores_email_case(client, db, make_user):
    owner = make_user(plan="PRO")
    make_user(email="Colleague@traqtest.io")
    r = client.post("/members/invite", headers=owner["headers"], json={"email": "colleague@traqtest.io"})
    assert r.json().get("added") is True


def test_member_who_uploaded_and_commented_can_delete_their_account(client, db, make_user, make_project):
    owner = make_user()
    member = make_user(team=owner["team"])
    project = make_project(member)
    segment = db.query(TranslationSegment).filter(TranslationSegment.project_id == project.id).first()
    db.add(SegmentComment(segment_id=segment.id, user_id=member["user"].id, text="check this"))
    db.commit()
    member_id, owner_id, project_id = member["user"].id, owner["user"].id, project.id

    r = _delete(client, member)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.query(User).filter(User.id == member_id).first() is None
    kept = db.query(TranslationProject).filter(TranslationProject.id == project_id).one()
    assert kept.user_id == owner_id
    assert db.query(SegmentComment).one().user_id is None


def test_deleting_an_owner_account_cancels_the_subscription(client, db, make_user, stripe_cancels):
    owner = make_user(plan="PRO")
    owner["user"].stripe_subscription_id = "sub_live"
    db.commit()

    assert _delete(client, owner).status_code == 200
    assert stripe_cancels == ["sub_live"]


def test_owner_account_stays_when_stripe_cannot_cancel(client, db, make_user, monkeypatch):
    import stripe

    def down(sub_id, **kw):
        raise stripe.error.APIConnectionError("network down")

    monkeypatch.setattr(stripe.Subscription, "cancel", down)
    owner = make_user(plan="PRO")
    owner["user"].stripe_subscription_id = "sub_live"
    db.commit()

    assert _delete(client, owner).status_code == 502
    db.expire_all()
    assert db.query(User).filter(User.id == owner["user"].id).first() is not None


def test_an_already_cancelled_subscription_does_not_block_deletion(client, db, make_user, monkeypatch):
    import stripe

    def gone(sub_id, **kw):
        raise stripe.error.InvalidRequestError("No such subscription", "id")

    monkeypatch.setattr(stripe.Subscription, "cancel", gone)
    owner = make_user(plan="PRO")
    owner["user"].stripe_subscription_id = "sub_old"
    db.commit()

    assert _delete(client, owner).status_code == 200


def test_member_who_started_the_subscription_leaves_it_with_the_owner(client, db, make_user, stripe_cancels):
    owner = make_user(plan="PRO")
    member = make_user(team=owner["team"])
    member["user"].stripe_subscription_id = "sub_live"
    member["user"].stripe_customer_id = "cus_1"
    db.commit()

    assert _delete(client, member).status_code == 200
    assert stripe_cancels == []
    db.expire_all()
    kept = db.query(User).filter(User.id == owner["user"].id).one()
    assert (kept.stripe_subscription_id, kept.stripe_customer_id) == ("sub_live", "cus_1")


def test_invite_email_escapes_names_typed_by_users():
    from app.services.email_service import render_invite_email

    subject, html = render_invite_email(
        inviter_name='<a href="https://evil.test">Log in here</a>',
        inviter_email="x@traqtest.io",
        team_name="<img src=x onerror=alert(1)>",
        role="MEMBER",
        register_url="https://app.test/register?invite=abc&team=x",
    )
    assert "<a href=\"https://evil.test\">" not in html
    assert "<img src=x" not in html
    assert "&lt;a href=" in html
    assert "invite=abc&amp;team=x" in html
