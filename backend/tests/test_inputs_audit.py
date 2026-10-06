"""Uploads that are refused leave nothing in storage, and malformed ids answer 4xx instead of 500."""
import pytest

from app.models.credit import CreditWallet
from app.models.project import TranslationProject
from tests.conftest import make_pdf


def _upload(client, owner, tmp_path, pages=3, **form):
    pdf = make_pdf(tmp_path / "doc.pdf", pages=pages)
    with open(pdf, "rb") as f:
        return client.post(
            "/projects/upload",
            headers=owner["headers"],
            files={"file": ("doc.pdf", f, "application/pdf")},
            data={"source_language": "Italian", "target_language": "English", **form},
        )


def _kept_uploads(storage):
    return [k for k in storage["objects"] if k not in storage["deleted"]]


def test_upload_refused_for_credits_is_deleted_from_storage(client, db, make_user, storage, tmp_path):
    owner = make_user(credits=1)
    assert _upload(client, owner, tmp_path, pages=3).status_code == 400
    assert _kept_uploads(storage) == []


def test_upload_over_the_page_cap_never_reaches_storage(client, make_user, storage, tmp_path, monkeypatch):
    from app.core import page_counter

    monkeypatch.setattr(page_counter, "MAX_PAGES", 2)
    owner = make_user(credits=50)
    assert _upload(client, owner, tmp_path, pages=3).status_code == 400
    assert storage["objects"] == {}


def test_accepted_upload_stays_in_storage(client, make_user, storage, tmp_path):
    owner = make_user(credits=10)
    assert _upload(client, owner, tmp_path, pages=1).status_code == 200
    assert len(_kept_uploads(storage)) == 1


def test_malformed_certification_template_id_is_400_and_free(client, db, make_user, storage, tmp_path):
    owner = make_user(credits=10)
    r = _upload(client, owner, tmp_path, pages=1, request_certification="true", certification_template_id="nope")
    assert r.status_code == 400
    assert db.query(TranslationProject).count() == 0
    db.expire_all()
    assert db.query(CreditWallet).one().subscription_credits == 10
    assert storage["objects"] == {}


def test_project_list_with_a_malformed_assignee_is_400(client, make_user):
    owner = make_user()
    assert client.get("/projects/", params={"assignee": "bob"}, headers=owner["headers"]).status_code == 400


def test_assigning_a_malformed_user_id_is_404(client, make_user, make_project):
    owner = make_user()
    project = make_project(owner)
    r = client.patch(f"/projects/{project.id}/assign", json={"assignee_id": "bob"}, headers=owner["headers"])
    assert r.status_code == 404


@pytest.mark.parametrize("method,path", [
    ("patch", "/glossary/not-a-uuid"),
    ("delete", "/glossary/not-a-uuid"),
    ("patch", "/members/not-a-uuid"),
    ("delete", "/members/not-a-uuid"),
    ("delete", "/members/invites/not-a-uuid"),
])
def test_malformed_ids_are_422(client, make_user, method, path):
    owner = make_user(plan="PRO")
    kwargs = {"json": {"role": "MEMBER"}} if method == "patch" else {}
    assert getattr(client, method)(path, headers=owner["headers"], **kwargs).status_code == 422


@pytest.mark.parametrize("method,path", [
    ("get", "/certifications/not-a-uuid/download"),
    ("get", "/certifications/not-a-uuid/scan"),
    ("delete", "/certifications/not-a-uuid"),
])
def test_malformed_certification_ids_are_404(client, make_user, method, path):
    owner = make_user(plan="PRO")
    assert getattr(client, method)(path, headers=owner["headers"]).status_code == 404
