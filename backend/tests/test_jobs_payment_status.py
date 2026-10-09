import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from app.models.delivery_link import DeliveryLink


@pytest.fixture()
def add_link(db):
    def _add(project, protected=True, days=30, **fields):
        link = DeliveryLink(
            project_id=project.id,
            token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            token_prefix="abc123",
            kind="delivery_pdf",
            file_name="diploma.pdf",
            file_key=f"delivery/{uuid.uuid4()}.pdf",
            expires_at=datetime.utcnow() + timedelta(days=days),
            protected=protected,
            amount_cents=4550 if protected else None,
            currency="EUR",
            **fields,
        )
        db.add(link)
        db.commit()
        return link

    return _add


def _rows(client, user, **params):
    r = client.get("/projects/", params=params, headers=user["headers"])
    assert r.status_code == 200, r.text
    return {row["id"]: row for row in r.json()}


def test_payment_status_for_each_case(client, db, make_user, make_project, add_link):
    owner = make_user()
    owner["user"].full_name = "Dan Rossi"
    db.commit()
    plain, unprotected, awaiting, claimed, card, marked, expired, revoked = (make_project(owner) for _ in range(8))
    add_link(unprotected, protected=False)
    add_link(awaiting)
    add_link(claimed, paid_claimed_at=datetime.utcnow())
    paid_at = datetime(2026, 10, 1, 9, 30)
    add_link(card, paid_at=paid_at, unlocked_at=paid_at, stripe_payment_intent="pi_123", paid_claimed_at=paid_at)
    add_link(marked, unlocked_at=datetime(2026, 10, 2), unlocked_by=owner["user"].id, paid_claimed_at=datetime(2026, 10, 1))
    add_link(expired, days=-1)
    add_link(revoked, revoked_at=datetime.utcnow())

    rows = _rows(client, owner)
    for p in (plain, unprotected, expired, revoked):
        assert rows[str(p.id)]["payment"] is None

    a = rows[str(awaiting.id)]["payment"]
    assert a["state"] == "awaiting" and a["amount"] == 45.5 and a["currency"] == "EUR"
    assert a["can_mark_paid"] is True and a["marked_by"] is None

    c = rows[str(claimed.id)]["payment"]
    assert c["state"] == "claimed" and c["claimed_at"] and c["can_mark_paid"] is True

    k = rows[str(card.id)]["payment"]
    assert k["state"] == "paid_card"
    assert k["paid_at"] == "2026-10-01T09:30:00Z"
    assert k["marked_by"] is None and k["can_mark_paid"] is False

    m = rows[str(marked.id)]["payment"]
    assert m["state"] == "marked_paid" and m["marked_by"] == "Dan Rossi"
    assert m["unlocked_at"] == "2026-10-02T00:00:00Z" and m["can_mark_paid"] is False

    flat = str(rows)
    assert "token_hash" not in flat and "file_key" not in flat


def test_an_unlocked_link_wins_else_the_newest_active_one(client, db, make_user, make_project, add_link):
    owner = make_user()
    project = make_project(owner)
    add_link(project, created_at=datetime.utcnow() - timedelta(days=3))
    newer = add_link(project, paid_claimed_at=datetime.utcnow(), created_at=datetime.utcnow() - timedelta(days=1))
    assert _rows(client, owner)[str(project.id)]["payment"]["link_id"] == str(newer.id)

    unlocked = add_link(
        project, days=-5, unlocked_at=datetime.utcnow() - timedelta(days=6), unlocked_by=owner["user"].id,
        created_at=datetime.utcnow() - timedelta(days=10),
    )
    payment = _rows(client, owner)[str(project.id)]["payment"]
    assert payment["link_id"] == str(unlocked.id) and payment["state"] == "marked_paid"


def test_payment_filter_and_counts(client, db, make_user, make_project, add_link):
    owner = make_user()
    none_, awaiting, claimed, card, marked = (make_project(owner) for _ in range(5))
    add_link(awaiting)
    add_link(claimed, paid_claimed_at=datetime.utcnow())
    add_link(card, paid_at=datetime.utcnow(), unlocked_at=datetime.utcnow())
    add_link(marked, unlocked_at=datetime.utcnow(), unlocked_by=owner["user"].id)

    assert set(_rows(client, owner, payment="claimed")) == {str(claimed.id)}
    assert set(_rows(client, owner, payment="awaiting")) == {str(awaiting.id)}
    assert set(_rows(client, owner, payment="paid")) == {str(card.id), str(marked.id)}
    assert len(_rows(client, owner)) == 5
    r = client.get("/projects/", params={"payment": "claimed"}, headers=owner["headers"])
    assert r.headers["x-total-count"] == "1"
    assert client.get("/projects/", params={"payment": "bogus"}, headers=owner["headers"]).status_code == 400

    summary = client.get("/projects/summary", headers=owner["headers"]).json()
    assert summary["payment"] == {"claimed": 1, "awaiting": 1, "paid": 2}


def test_list_has_no_per_project_queries(client, db, make_user, make_project, add_link):
    from app.database import engine

    owner = make_user()

    def count_queries(n_projects):
        for _ in range(n_projects):
            p = make_project(owner)
            add_link(p, unlocked_at=datetime.utcnow(), unlocked_by=owner["user"].id)
        statements = []
        listener = lambda *args: statements.append(args[2])  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            _rows(client, owner)
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len(statements)

    few = count_queries(2)
    many = count_queries(8)
    assert many == few


def test_only_leads_mark_as_paid_from_jobs(client, db, make_user, make_project, add_link):
    owner = make_user()
    project = make_project(owner)
    link = add_link(project, paid_claimed_at=datetime.utcnow())
    url = f"/projects/{project.id}/delivery-links/{link.id}/unlock"

    for role in ("MEMBER", "REVIEWER"):
        mate = make_user(team=owner["team"], role=role)
        payment = _rows(client, mate)[str(project.id)]["payment"]
        assert payment["state"] == "claimed" and payment["can_mark_paid"] is False
        r = client.post(url, headers=mate["headers"])
        assert r.status_code == 403
        assert "mark a client link as paid" in r.json()["detail"]
    db.refresh(link)
    assert link.unlocked_at is None

    pm = make_user(team=owner["team"], role="PM")
    pm["user"].full_name = "Paola Manager"
    db.commit()
    assert _rows(client, pm)[str(project.id)]["payment"]["can_mark_paid"] is True
    r = client.post(url, headers=pm["headers"])
    assert r.status_code == 200
    assert r.json()["payment_status"] == "unlocked" and r.json()["marked_paid_by"] == "Paola Manager"

    payment = _rows(client, owner)[str(project.id)]["payment"]
    assert payment["state"] == "marked_paid" and payment["marked_by"] == "Paola Manager"
    links = client.get(f"/projects/{project.id}/delivery-links", headers=owner["headers"]).json()
    assert links[0]["marked_paid_by"] == "Paola Manager"


def test_other_teams_cannot_see_or_mark(client, db, make_user, make_project, add_link):
    owner = make_user()
    project = make_project(owner)
    link = add_link(project, paid_claimed_at=datetime.utcnow())
    stranger = make_user()
    stranger_admin = make_user(team=stranger["team"], role="ADMIN")

    for user in (stranger, stranger_admin):
        assert str(project.id) not in _rows(client, user)
        assert _rows(client, user, payment="claimed") == {}
        assert client.get("/projects/summary", headers=user["headers"]).json()["payment"]["claimed"] == 0
        r = client.post(f"/projects/{project.id}/delivery-links/{link.id}/unlock", headers=user["headers"])
        assert r.status_code == 404
    db.refresh(link)
    assert link.unlocked_at is None and link.unlocked_by is None
