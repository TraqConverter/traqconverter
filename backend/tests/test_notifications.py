"""In-app notifications: the hooks that create them, the bell's endpoints, dedupe and cleanup."""
from datetime import datetime, timedelta

import pytest

from app.models.delivery_link import DeliveryLink
from app.models.notification import Notification
from app.models.project import ProjectStatus
from app.services import notifications
from tests.test_language_guards import pipeline  # noqa: F401
from tests.test_review import fake, page_cache, review_project  # noqa: F401
from tests.test_protected_links import _pdf, stub_export  # noqa: F401
from tests.test_stripe_connect import (  # noqa: F401
    ACCOUNT,
    _event,
    _post,
    accounts_v1,
    calls,
    connect_secret,
    no_real_stripe,
)

CLIENT_EMAIL = "giulia.bianchi@cliente.it"
CLIENT_NAME = "Giulia Bianchi"


def _mine(db, user):
    db.expire_all()
    return (
        db.query(Notification)
        .filter(Notification.user_id == user["user"].id)
        .order_by(Notification.created_at)
        .all()
    )


@pytest.fixture()
def team(db, make_user):
    owner = make_user(email="owner@traqtest.io")
    owner["user"].full_name = "Maria Rossi"
    db.commit()
    member = make_user(email="member@traqtest.io", team=owner["team"])
    return {"owner": owner, "member": member}


# Assignment


def _assign(client, project, who, assignee):
    return client.patch(
        f"/projects/{project.id}/assign",
        json={"assignee_id": str(assignee["user"].id) if assignee else None},
        headers=who["headers"],
    )


def test_assignment_notifies_the_assignee(client, db, team, make_project, emails):
    project = make_project(team["owner"], pages=3)
    assert _assign(client, project, team["owner"], team["member"]).status_code == 200
    [n] = _mine(db, team["member"])
    assert n.kind == "assigned"
    assert n.title == "Maria Rossi assigned you source.pdf"
    assert n.body == "Italian → English, 3 pages"
    assert n.link == f"/editor/{project.id}"
    assert n.project_id == project.id and n.team_id == team["owner"]["team"].id
    assert _mine(db, team["owner"]) == []


def test_assigning_yourself_unassigning_and_no_op_notify_no_one(client, db, team, make_project, emails):
    project = make_project(team["owner"])
    assert _assign(client, project, team["member"], team["member"]).status_code == 200
    assert _mine(db, team["member"]) == []

    assert _assign(client, project, team["owner"], None).status_code == 200
    assert _assign(client, project, team["owner"], team["member"]).status_code == 200
    assert len(_mine(db, team["member"])) == 1
    assert _assign(client, project, team["owner"], team["member"]).status_code == 200
    assert _assign(client, project, team["owner"], None).status_code == 200
    assert len(_mine(db, team["member"])) == 1
    assert _mine(db, team["owner"]) == []


# Translation finished or failed


def test_finished_translation_notifies_uploader_and_assignee(db, team, pipeline):  # noqa: F811
    _, run = pipeline
    owner, member = team["owner"], team["member"]

    project = run(owner, "en-GB")
    assert project.status == ProjectStatus.COMPLETED
    [n] = _mine(db, owner)
    assert n.kind == "translation_done"
    assert n.title == "source.pdf is ready for review"
    assert n.link == f"/editor/{project.id}"
    assert _mine(db, member) == []

    # With an assignee who isn't the uploader, both hear about it.
    project.assignee_id = member["user"].id
    db.commit()
    db.query(Notification).delete()
    db.commit()
    notifications.translation_done(db, project)
    db.commit()
    assert [n.kind for n in _mine(db, owner)] == ["translation_done"]
    assert [n.kind for n in _mine(db, member)] == ["translation_done"]


def test_failed_translation_notifies_with_the_reason(db, team, pipeline):  # noqa: F811
    _, run = pipeline
    project = run(team["owner"], "it-IT")
    assert project.status == ProjectStatus.FAILED
    [n] = _mine(db, team["owner"])
    assert n.kind == "translation_failed"
    assert n.title == "source.pdf couldn't be translated"
    assert n.body.startswith("This document is already in Italian.")


def test_worker_retries_and_watchdog_do_not_duplicate_a_failure(db, team, make_project):
    from app.services.project_lifecycle import fail_project_by_id, mark_project_failed

    project = make_project(team["owner"], status=ProjectStatus.PROCESSING)
    project.assignee_id = team["owner"]["user"].id
    db.commit()
    fail_project_by_id(str(project.id), "Translation failed after retries; credits were refunded")
    db.expire_all()
    mark_project_failed(db, project, "Translation failed; credits were refunded")
    db.commit()
    [n] = _mine(db, team["owner"])
    assert n.body == "Translation failed after retries; credits were refunded"


# Dedupe and never raising


def test_dedupe_is_per_kind_project_user_within_two_minutes(db, team, make_project):
    owner, member = team["owner"]["user"], team["member"]["user"]
    p1, p2 = make_project(team["owner"]), make_project(team["owner"])
    for _ in range(3):
        notifications.notify(db, owner.id, "translation_done", "a", project_id=p1.id)
    notifications.notify(db, owner.id, "translation_failed", "b", project_id=p1.id)
    notifications.notify(db, owner.id, "translation_done", "c", project_id=p2.id)
    notifications.notify(db, member.id, "translation_done", "d", project_id=p1.id)
    db.commit()
    assert db.query(Notification).count() == 4

    db.query(Notification).filter(Notification.title == "a").update(
        {Notification.created_at: datetime.utcnow() - timedelta(minutes=3)}
    )
    db.commit()
    assert notifications.notify(db, owner.id, "translation_done", "e", project_id=p1.id) is not None
    db.commit()
    assert db.query(Notification).count() == 5


def test_notify_never_raises(db, team, caplog):
    import uuid

    # An unknown user breaks the foreign key; the caller's session carries on.
    assert notifications.notify(db, uuid.uuid4(), "assigned", "x") is None
    db.commit()
    assert notifications.notify(db, team["owner"]["user"].id, "not_a_kind", "x") is None
    assert db.query(Notification).count() == 0


# Endpoints


def test_list_unread_count_mark_read_and_mark_all(client, db, team, make_project):
    owner = team["owner"]
    projects = [make_project(owner) for _ in range(3)]
    for i, p in enumerate(projects):
        notifications.notify(db, owner["user"].id, "translation_done", f"n{i}", project_id=p.id, link=f"/editor/{p.id}")
        db.commit()
        db.query(Notification).filter(Notification.title == f"n{i}").update(
            {Notification.created_at: datetime.utcnow() - timedelta(minutes=10 - i)}
        )
        db.commit()

    body = client.get("/notifications", headers=owner["headers"]).json()
    assert body["unread_count"] == 3
    assert [n["title"] for n in body["items"]] == ["n2", "n1", "n0"]
    assert body["items"][0]["read_at"] is None and body["items"][0]["link"] == f"/editor/{projects[2].id}"
    assert [n["title"] for n in client.get("/notifications?limit=2", headers=owner["headers"]).json()["items"]] == ["n2", "n1"]

    first = body["items"][0]["id"]
    r = client.post(f"/notifications/{first}/read", headers=owner["headers"])
    assert r.status_code == 200 and r.json()["read_at"] is not None
    assert client.get("/notifications", headers=owner["headers"]).json()["unread_count"] == 2

    r = client.post("/notifications/read-all", headers=owner["headers"])
    assert r.status_code == 200 and r.json()["updated"] == 2
    body = client.get("/notifications", headers=owner["headers"]).json()
    assert body["unread_count"] == 0 and all(n["read_at"] for n in body["items"])


def test_another_user_cannot_see_or_mark_mine(client, db, team, make_user, make_project):
    owner = team["owner"]
    stranger = make_user(email="stranger@traqtest.io")
    n = notifications.notify(db, owner["user"].id, "translation_done", "mine", project_id=make_project(owner).id)
    db.commit()

    assert client.get("/notifications", headers=stranger["headers"]).json() == {"items": [], "unread_count": 0}
    assert client.post(f"/notifications/{n.id}/read", headers=stranger["headers"]).status_code == 404
    assert client.post(f"/notifications/{n.id}/read", headers=team["member"]["headers"]).status_code == 404
    assert client.post("/notifications/read-all", headers=stranger["headers"]).json()["updated"] == 0
    db.refresh(n)
    assert n.read_at is None
    assert client.get("/notifications").status_code == 401


# Client payment and download: creator only, no client details


def _no_client_data(rows):
    for n in rows:
        text = f"{n.title} {n.body} {n.link}"
        assert CLIENT_EMAIL not in text and CLIENT_NAME not in text and "@" not in text


@pytest.fixture()
def shared_link(client, db, storage, team, make_project, stub_export):  # noqa: F811
    owner = team["owner"]
    project = make_project(owner)
    storage["objects"][project.file_path] = _pdf(3, "Originale")
    project.file_name = "diploma.pdf"
    owner["team"].paypal_me = "EspressoTranslations"
    owner["team"].stripe_account_id = ACCOUNT
    owner["team"].stripe_account_status = "active"
    db.commit()

    def create(protected, by=None):
        who = by or team["member"]
        body = {"protected": True, "amount": "45.50", "client_name": CLIENT_NAME, "client_email": CLIENT_EMAIL} if protected else {}
        r = client.post(f"/projects/{project.id}/delivery-links", json=body, headers=who["headers"])
        assert r.status_code == 200, r.text
        return r.json(), r.json()["url"].rsplit("/d/", 1)[1]

    return project, create


def test_client_claim_notifies_the_link_creator_once(client, db, team, shared_link, emails):
    project, create = shared_link
    _, token = create(protected=True)
    assert client.post(f"/public/delivery/{token}/paid").status_code == 200
    assert client.post(f"/public/delivery/{token}/paid").status_code == 200

    [n] = _mine(db, team["member"])
    assert n.kind == "client_claimed_paid"
    assert n.title == "Your client says they've paid €45.50 for diploma - translation.pdf"
    assert n.link == f"/editor/{project.id}"
    assert _mine(db, team["owner"]) == []
    _no_client_data([n])


def test_stripe_payment_notifies_the_link_creator(client, db, monkeypatch, team, shared_link, calls, connect_secret, emails):  # noqa: F811
    _, create = shared_link
    body, _ = create(protected=True)
    event = _event(body["id"])
    event["data"]["object"]["customer_details"] = {"email": CLIENT_EMAIL, "name": CLIENT_NAME}
    assert _post(client, monkeypatch, event).json() == {"status": "unlocked"}
    assert _post(client, monkeypatch, _event(body["id"])).status_code == 200

    [n] = _mine(db, team["member"])
    assert n.kind == "client_paid"
    assert n.title == "Your client paid €45.50 for diploma - translation.pdf — unlocked"
    _no_client_data([n])


def test_first_download_notifies_the_creator_only_once(client, db, team, shared_link):
    _, create = shared_link
    _, token = create(protected=False)
    for _ in range(3):
        assert client.get(f"/public/delivery/{token}/file").status_code == 200
    db.expire_all()
    assert db.query(DeliveryLink).one().download_count == 3
    [n] = _mine(db, team["member"])
    assert n.kind == "client_downloaded"
    assert n.title == "Your client downloaded diploma - translation.pdf"
    _no_client_data([n])

    # Past the dedupe window, more downloads of the same link still say nothing.
    db.query(Notification).update({Notification.created_at: datetime.utcnow() - timedelta(hours=1)})
    db.commit()
    assert client.get(f"/public/delivery/{token}/file").status_code == 200
    assert len(_mine(db, team["member"])) == 1


def test_locked_download_attempt_is_not_a_download(client, db, team, shared_link):
    _, create = shared_link
    _, token = create(protected=True)
    assert client.get(f"/public/delivery/{token}/file").status_code == 403
    assert _mine(db, team["member"]) == []


def test_creator_who_left_falls_back_to_the_owner(client, db, team, shared_link):
    _, create = shared_link
    _, token = create(protected=False)
    db.query(DeliveryLink).update({DeliveryLink.created_by: None})
    db.commit()
    assert client.get(f"/public/delivery/{token}/file").status_code == 200
    assert [n.kind for n in _mine(db, team["owner"])] == ["client_downloaded"]


# Cleanup


def test_old_read_notifications_are_purged(db, team, make_project):
    uid = team["owner"]["user"].id
    now = datetime.utcnow()
    rows = {
        "old_read": (now - timedelta(days=91), now - timedelta(days=90)),
        "old_unread": (now - timedelta(days=200), None),
        "recent_read": (now - timedelta(days=10), now - timedelta(days=9)),
    }
    for title, (created, read) in rows.items():
        db.add(Notification(user_id=uid, kind="assigned", title=title, body="", created_at=created, read_at=read))
    db.commit()

    assert notifications.purge_old_read() == 1
    db.expire_all()
    assert sorted(n.title for n in db.query(Notification).all()) == ["old_unread", "recent_read"]
