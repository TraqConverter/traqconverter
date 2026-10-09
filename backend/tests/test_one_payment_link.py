import io
import uuid
from datetime import datetime, timedelta

import fitz
import pytest

from app.models.delivery_link import DeliveryLink


def _pdf(pages: int, label: str) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"{label} page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture()
def shared(client, db, storage, make_user, make_project, monkeypatch):
    import app.routers.delivery_links as delivery_router
    import app.routers.export as export_router
    import app.services.export_service as export_service

    monkeypatch.setattr(export_router, "generate_docx", lambda *a, **kw: io.BytesIO(b"docx"))
    monkeypatch.setattr(export_service, "_convert_docx_to_pdf", lambda data: _pdf(2, "Translation"))
    monkeypatch.setattr(export_router, "capture_template_in_background", lambda pid, uid: None)
    monkeypatch.setattr(delivery_router, "capture_template_in_background", lambda pid, uid: None)
    monkeypatch.setattr(delivery_router.protected_preview, "warm_in_background", lambda link_id: None)

    owner = make_user(email="translator@traqtest.io")
    project = make_project(owner)
    storage["objects"][project.file_path] = _pdf(1, "Originale")
    project.file_name = "diploma.pdf"
    db.commit()
    return owner, project


def _create(client, owner, project, **body):
    r = client.post(f"/projects/{project.id}/delivery-links", json=body, headers=owner["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _add(db, project, **fields):
    values = {
        "token_hash": uuid.uuid4().hex + uuid.uuid4().hex,
        "token_prefix": "abc123",
        "kind": "delivery_pdf",
        "file_name": "diploma.pdf",
        "file_key": f"delivery/{uuid.uuid4()}.pdf",
        "expires_at": datetime.utcnow() + timedelta(days=30),
        "protected": True,
        "amount_cents": 4500,
        "currency": "EUR",
        "created_at": datetime.utcnow() - timedelta(days=2),
        **fields,
    }
    link = DeliveryLink(project_id=project.id, **values)
    db.add(link)
    db.commit()
    return link


def test_a_new_protected_link_revokes_the_open_one(client, db, storage, shared):
    owner, project = shared
    old = _add(db, project, preview_keys=["preview/a.png"], client_email="client@example.com",
               paid_claimed_at=datetime.utcnow())
    old_key = old.file_key

    body = _create(client, owner, project, protected=True, amount=50)
    assert body["replaced"] == 1

    db.refresh(old)
    assert old.revoked_at is not None
    assert old.file_key is None and old.preview_keys is None and old.client_email is None
    assert {old_key, "preview/a.png"} <= set(storage["deleted"])

    new = db.query(DeliveryLink).filter(DeliveryLink.id == body["id"]).one()
    assert new.revoked_at is None and new.file_key


def test_paid_unlocked_unprotected_and_other_projects_are_left_alone(client, db, shared, make_project):
    owner, project = shared
    now = datetime.utcnow()
    card = _add(db, project, paid_at=now, unlocked_at=now, stripe_payment_intent="pi_1")
    marked = _add(db, project, unlocked_at=now, unlocked_by=owner["user"].id)
    plain = _add(db, project, protected=False, amount_cents=None)
    elsewhere = _add(db, make_project(owner))
    expired = _add(db, project, expires_at=now - timedelta(days=1))

    assert _create(client, owner, project, protected=True, amount=45)["replaced"] == 0
    for link in (card, marked, plain, elsewhere, expired):
        db.refresh(link)
        assert link.revoked_at is None and link.file_key


def test_an_unprotected_link_does_not_replace_the_payment_link(client, db, shared):
    owner, project = shared
    old = _add(db, project)
    body = _create(client, owner, project, kind="docx")
    assert body["replaced"] == 0
    db.refresh(old)
    assert old.revoked_at is None


def test_a_failed_create_keeps_the_open_link(client, db, shared, monkeypatch):
    owner, project = shared
    old = _add(db, project)
    from app.services import delivery_links

    def boom(*a, **kw):
        raise RuntimeError("render failed")

    monkeypatch.setattr(delivery_links, "render", boom)
    r = client.post(f"/projects/{project.id}/delivery-links", json={"protected": True, "amount": 45},
                    headers=owner["headers"])
    assert r.status_code == 500
    db.refresh(old)
    assert old.revoked_at is None


def test_projects_and_editor_show_the_single_open_link(client, db, shared):
    owner, project = shared
    _add(db, project)
    body = _create(client, owner, project, protected=True, amount=60)

    listed = {row["id"]: row for row in client.get("/projects/", headers=owner["headers"]).json()}
    assert listed[str(project.id)]["payment"]["link_id"] == body["id"]

    payment = client.get(f"/projects/{project.id}", headers=owner["headers"]).json()["payment"]
    assert payment["link_id"] == body["id"]
    assert payment["state"] == "awaiting" and payment["amount"] == 60
    assert payment["can_mark_paid"] is True
    assert payment["url"] == body["url"]


def test_editor_payment_for_each_state(client, db, make_user, make_project):
    owner = make_user()
    owner["user"].full_name = "Dan Rossi"
    db.commit()
    plain, claimed, marked = (make_project(owner) for _ in range(3))
    _add(db, claimed, paid_claimed_at=datetime.utcnow(), client_email="c@example.com")
    _add(db, marked, unlocked_at=datetime.utcnow(), unlocked_by=owner["user"].id)

    def payment(p):
        r = client.get(f"/projects/{p.id}", headers=owner["headers"])
        assert r.status_code == 200, r.text
        return r.json()["payment"]

    assert payment(plain) is None
    c = payment(claimed)
    assert c["state"] == "claimed" and c["client_will_be_emailed"] is True and c["can_mark_paid"] is True
    assert c["url"] is None  # no sealed token on a hand-made row
    assert "c@example.com" not in str(c)
    m = payment(marked)
    assert m["state"] == "marked_paid" and m["marked_by"] == "Dan Rossi" and m["can_mark_paid"] is False


def test_only_leads_can_mark_paid_from_the_editor(client, db, shared, make_user):
    owner, project = shared
    _add(db, project)
    member = make_user(team=owner["team"], role="MEMBER")

    r = client.get(f"/projects/{project.id}", headers=member["headers"])
    assert r.status_code == 200, r.text
    payment = r.json()["payment"]
    assert payment["state"] == "awaiting" and payment["can_mark_paid"] is False


def test_a_link_being_paid_on_stripe_is_not_replaced(client, db, shared):
    owner, project = shared
    paying = _add(db, project, checkout_started_at=datetime.utcnow() - timedelta(minutes=5))
    r = client.post(
        f"/projects/{project.id}/delivery-links", json={"protected": True, "amount": 45}, headers=owner["headers"]
    )
    assert r.status_code == 409
    assert "paying on the current link" in r.json()["detail"]
    db.refresh(paying)
    assert paying.revoked_at is None

    # Once that checkout can no longer be paid, the link can be replaced.
    paying.checkout_started_at = datetime.utcnow() - timedelta(minutes=40)
    db.commit()
    assert _create(client, owner, project, protected=True, amount=45)["replaced"] == 1
