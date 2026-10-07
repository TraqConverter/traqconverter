"""Owner decisions and the remaining audit fixes: who manages billing and the stamp, refunds by bucket, project paging,
redirects behind the proxy, file names, login, upgrade messages, Regenerate, the payments refresh and staff roles."""
import io
import json
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.models.credit import CreditTransaction, CreditWallet
from app.models.project import ProjectStatus, TranslationProject
from app.services.credit_service import CreditService

BACKEND = Path(__file__).resolve().parent.parent
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _wallet(db, who):
    db.expire_all()
    return db.query(CreditWallet).filter(CreditWallet.team_id == who["team"].id).one()


# --- 1/2. Stamp: owner and admin only (now the media library, see test_media_library.py) ----

# --- 3. Refunds go back to the bucket they came from --------------------------


def _set(db, who, sub, bought, status="ACTIVE"):
    w = _wallet(db, who)
    w.subscription_credits, w.purchased_credits, w.subscription_status = sub, bought, status
    db.commit()


def test_mixed_charge_records_the_split_and_refunds_each_part(db, make_user):
    owner = make_user()
    _set(db, owner, sub=2, bought=10)
    CreditService.deduct_credits(db, str(owner["team"].id), 5, reference_id="job:1")
    db.commit()
    usage = db.query(CreditTransaction).filter(CreditTransaction.reference_id == "job:1").one()
    assert (usage.amount, usage.from_subscription, usage.from_purchased) == (-5, 2, 3)
    w = _wallet(db, owner)
    assert (w.subscription_credits, w.purchased_credits) == (0, 7)

    assert CreditService.refund_usage(db, "job:1") == 5
    db.commit()
    w = _wallet(db, owner)
    # The 3 pack credits come back as pack credits, which a renewal won't wipe.
    assert (w.subscription_credits, w.purchased_credits) == (2, 10)


def test_refund_is_idempotent(db, make_user):
    owner = make_user()
    _set(db, owner, sub=1, bought=4)
    CreditService.deduct_credits(db, str(owner["team"].id), 3, reference_id="job:2")
    db.commit()
    assert CreditService.refund_usage(db, "job:2") == 3
    db.commit()
    assert CreditService.refund_usage(db, "job:2") == 0
    db.commit()
    w = _wallet(db, owner)
    assert (w.subscription_credits, w.purchased_credits) == (1, 4)
    assert db.query(CreditTransaction).filter(CreditTransaction.reference_id == "refund:job:2").count() == 1


@pytest.mark.parametrize("status,expected", [("ACTIVE", (4, 0)), ("EXPIRED", (0, 4))])
def test_old_charge_without_a_split_refunds_by_subscription_status(db, make_user, status, expected):
    owner = make_user()
    _set(db, owner, sub=0, bought=0, status=status)
    wallet = _wallet(db, owner)
    db.add(CreditTransaction(wallet_id=wallet.id, type="USAGE", amount=-4, reference_id="job:old"))
    db.commit()
    assert CreditService.refund_usage(db, "job:old") == 4
    db.commit()
    w = _wallet(db, owner)
    assert (w.subscription_credits, w.purchased_credits) == expected


def test_pack_only_charge_survives_a_renewal_after_the_refund(db, make_user):
    owner = make_user()
    _set(db, owner, sub=0, bought=6)
    CreditService.deduct_credits(db, str(owner["team"].id), 6, reference_id="job:3")
    db.commit()
    CreditService.refund_usage(db, "job:3")
    db.commit()
    CreditService.grant_subscription_credits(db, str(owner["team"].id), 29)
    db.commit()
    w = _wallet(db, owner)
    assert (w.subscription_credits, w.purchased_credits) == (29, 6)


# --- 4. Paging on the projects list --------------------------------------------


def _many(db, owner, n, **fields):
    base = datetime.utcnow()
    out = []
    for i in range(n):
        p = TranslationProject(
            user_id=owner["user"].id, team_id=owner["team"].id, file_name=f"doc-{i:03d}.pdf",
            file_path=f"uploads/{uuid.uuid4()}", page_count=2, credits_used=2,
            status=fields.get("status", ProjectStatus.COMPLETED), review_status=fields.get("review_status", "DRAFT"),
            source_language="Italian", target_language="English", created_at=base - timedelta(minutes=i),
        )
        db.add(p)
        out.append(p)
    db.commit()
    return out


def test_list_pages_with_a_total(client, db, make_user):
    owner = make_user()
    _many(db, owner, 75)
    r = client.get("/projects/", headers=owner["headers"])
    assert r.status_code == 200
    assert isinstance(r.json(), list) and len(r.json()) == 50
    assert r.headers["X-Total-Count"] == "75"
    assert r.json()[0]["filename"] == "doc-000.pdf"

    r = client.get("/projects/", params={"limit": 50, "offset": 50}, headers=owner["headers"])
    assert [p["filename"] for p in r.json()] == [f"doc-{i:03d}.pdf" for i in range(50, 75)]
    assert client.get("/projects/", params={"limit": 201}, headers=owner["headers"]).status_code == 422
    assert len(client.get("/projects/", params={"limit": 200}, headers=owner["headers"]).json()) == 75


def test_filters_and_search_run_on_the_server(client, db, make_user):
    from app.models.batch import Batch

    owner = make_user()
    _many(db, owner, 60)
    review = _many(db, owner, 3, review_status="IN_REVIEW")
    _many(db, owner, 2, status=ProjectStatus.PROCESSING)
    _many(db, owner, 1, status=ProjectStatus.FAILED)
    batch = Batch(team_id=owner["team"].id, name="Rossi family")
    db.add(batch)
    db.flush()
    review[0].batch_id = batch.id
    review[1].file_name = "100%_certificate.pdf"
    db.commit()

    def get(**params):
        r = client.get("/projects/", params=params, headers=owner["headers"])
        assert r.status_code == 200, r.text
        return int(r.headers["X-Total-Count"]), r.json()

    assert get(status="review")[0] == 3
    assert get(status="active")[0] == 2
    assert get(status="failed")[0] == 1
    assert get(status="delivered")[0] == 60
    assert get(q="rossi")[1][0]["id"] == str(review[0].id)
    assert get(q="100%")[0] == 1
    assert get(q="doc-05")[0] == 10
    assert client.get("/projects/", params={"status": "nope"}, headers=owner["headers"]).status_code == 400

    s = client.get("/projects/summary", headers=owner["headers"]).json()
    assert s["total"] == 66
    assert s["counts"] == {"active": 2, "review": 3, "delivered": 60, "failed": 1}
    assert s["open"] == {"projects": 5, "pages": 10, "projects_with_pages": 5, "language_pairs": 1}
    assert s["credits_used"] == 132
    assert client.get("/projects/summary", params={"q": "rossi"}, headers=owner["headers"]).json()["total"] == 1


def test_assignee_filter_and_other_teams(client, db, make_user):
    owner = make_user()
    member = make_user(team=owner["team"])
    mine = _many(db, owner, 4)
    mine[0].assignee_id = member["user"].id
    db.commit()
    stranger = make_user()
    _many(db, stranger, 3)

    r = client.get("/projects/", params={"assignee": "me"}, headers=member["headers"])
    assert r.headers["X-Total-Count"] == "1"
    assert client.get("/projects/summary", params={"assignee": "unassigned"}, headers=owner["headers"]).json()["total"] == 3
    assert client.get("/projects/summary", headers=stranger["headers"]).json()["total"] == 3


def test_word_counts_come_from_sql(client, db, make_user, make_project):
    owner = make_user()
    make_project(owner, segments=("Hello   world", "  ", "Uno due\ttre\nquattro"))
    [row] = client.get("/projects/", headers=owner["headers"]).json()
    assert row["words"] == 6


# --- 5. Redirects keep https behind the proxy -----------------------------------


def test_slash_redirect_keeps_https_behind_a_proxy(db):
    from fastapi.testclient import TestClient
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    from app.main import app

    proxied = TestClient(ProxyHeadersMiddleware(app, trusted_hosts="*"), base_url="http://api.example.test")
    r = proxied.get("/projects", headers={"X-Forwarded-Proto": "https"}, follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "https://api.example.test/projects/"


def test_every_start_command_trusts_the_proxy_headers():
    railway = json.loads((BACKEND / "railway.json").read_text())["deploy"]["startCommand"]
    procfile = next(line for line in (BACKEND / "Procfile").read_text().splitlines() if line.startswith("web:"))
    dockerfile = next(line for line in (BACKEND / "Dockerfile").read_text().splitlines() if line.startswith("CMD"))
    for cmd in (railway, procfile, dockerfile):
        assert "--proxy-headers" in cmd and "--forwarded-allow-ips" in cmd, cmd


# --- 6. File names -----------------------------------------------------------


def test_media_names_cannot_leave_the_temp_dir(client, make_user):
    from tests.test_document_media import _png

    owner = make_user()
    name = f"escape_{uuid.uuid4().hex}.png"
    r = client.post("/media", headers=owner["headers"], files={"file": (f"../{name}", io.BytesIO(_png()), "image/png")})
    assert r.status_code == 200, r.text
    assert not (Path(tempfile.gettempdir()) / name).exists()


def test_project_names_are_cleaned_on_upload_and_rename(client, db, make_user, tmp_path):
    from tests.conftest import make_pdf

    owner = make_user()
    pdf = make_pdf(tmp_path / "doc.pdf")
    with open(pdf, "rb") as f:
        r = client.post("/projects/upload", headers=owner["headers"],
                        files={"file": ("..\\..\\evil.pdf", f, "application/pdf")},
                        data={"source_language": "Italian", "target_language": "English"})
    assert r.status_code == 200, r.text
    project = db.get(TranslationProject, uuid.UUID(r.json()["project_id"]))
    assert project.file_name == "evil.pdf"

    r = client.patch(f"/projects/{project.id}", headers=owner["headers"], json={"file_name": "a/b\\c\x00\n" + "x" * 400})
    assert r.status_code == 200
    name = r.json()["file_name"]
    assert "/" not in name and "\\" not in name and "\x00" not in name and "\n" not in name
    assert len(name) <= 200 and name.endswith(".pdf")
    assert client.patch(f"/projects/{project.id}", headers=owner["headers"], json={"file_name": "\x01\x02 "}).status_code == 400


# --- 7. CORS ---------------------------------------------------------------


def test_cors_exposes_the_download_name_and_total(client):
    from app.config import settings

    origin = settings.cors_origins[0]
    r = client.get("/health", headers={"Origin": origin})
    exposed = {h.strip().lower() for h in r.headers["access-control-expose-headers"].split(",")}
    assert {"content-disposition", "x-total-count"} <= exposed


# --- 8. Login ----------------------------------------------------------------


def test_inactive_user_cannot_log_in(client, db, make_user):
    owner = make_user(email="Someone@Traqtest.io")
    ok = client.post("/auth/login", json={"email": "someone@traqtest.io", "password": "correct horse battery"})
    assert ok.status_code == 200
    owner["user"].is_active = False
    db.commit()
    r = client.post("/auth/login", json={"email": "someone@traqtest.io", "password": "correct horse battery"})
    wrong = client.post("/auth/login", json={"email": "someone@traqtest.io", "password": "nope nope nope"})
    assert r.status_code == wrong.status_code == 400
    assert r.json() == wrong.json() == {"detail": "Invalid credentials"}


# --- 9. Upgrade message names the cheapest plan --------------------------------


@pytest.mark.parametrize("feature,plan", [
    ("templates", "Basic"), ("team_collaboration", "Basic"), ("download_translation", "Basic"),
    ("terminology_memory", "Pro"), ("glossaries", "Pro"), ("certifications", "Pro"),
])
def test_upgrade_message_names_the_cheapest_plan(feature, plan):
    from app.dependencies.feature_guard import upgrade_message

    assert upgrade_message(feature).endswith(f"Upgrade to {plan} to unlock it.")


def test_trial_download_names_basic(client, make_user, make_project):
    trial = make_user(plan="TRIAL")
    project = make_project(trial)
    r = client.get(f"/projects/{project.id}/export", headers=trial["headers"])
    assert r.status_code == 403
    assert "Upgrade to Basic" in r.json()["detail"]


# --- 10. Regenerate only for PDF and image sources -------------------------------


@pytest.mark.parametrize("kind,code", [("PDF", 200), ("IMAGE", 200), ("DOCX", 400)])
def test_regenerate_by_source_kind(client, make_user, make_project, monkeypatch, kind, code):
    from app.services import ai_actions

    monkeypatch.setattr(ai_actions, "run_rebuild", lambda *a: None)
    owner = make_user()
    project = make_project(owner, source_kind=kind)
    assert client.get(f"/projects/{project.id}", headers=owner["headers"]).json()["source_kind"] == kind
    assert client.post(f"/projects/{project.id}/rebuild-with-claude", headers=owner["headers"]).status_code == code


def test_image_regenerate_sends_a_pdf_to_the_model(db, make_user, make_project, storage, monkeypatch):
    import fitz
    from PIL import Image

    from app.services import ai_actions
    from app.services import claude_authored_rebuild as car

    owner = make_user()
    project = make_project(owner, source_kind="IMAGE")
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    storage["objects"][project.file_path] = buf.getvalue()
    project.file_name = "scan.png"
    db.commit()
    seen = {}

    def author(pdf_bytes, **kw):
        seen["pages"] = fitz.open(stream=pdf_bytes, filetype="pdf").page_count
        return b"PK docx"

    monkeypatch.setattr(car, "author_rebuild_docx", author)
    ai_actions.run_rebuild(str(project.id), None)
    assert seen["pages"] == 1


# --- 13. Staff roles ---------------------------------------------------------


@pytest.mark.parametrize("role", ["SUPERUSER", "SUPER_ADMIN", "ADMIN"])
def test_every_staff_role_passes_feature_checks(client, db, make_user, make_project, role):
    staff = make_user(plan="TRIAL")
    staff["user"].role = role
    db.commit()
    project = make_project(staff)
    assert client.get("/glossary", headers=staff["headers"]).status_code == 200
    assert client.get(f"/projects/{project.id}/export", headers=staff["headers"]).status_code != 403
