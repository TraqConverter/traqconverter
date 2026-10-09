import hashlib
import io
import secrets
import zipfile
from datetime import date, datetime, timedelta

import fitz
import pytest

from app.models.delivery_link import DeliveryLink
from app.models.project import ProjectStatus

TRANSLATION_PAGES = 2
ORIGINAL_DOCX = b"original-docx-bytes"


def _pdf(pages: int, label: str) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"{label} page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def _texts(data: bytes) -> list[str]:
    with fitz.open(stream=data, filetype="pdf") as doc:
        return [page.get_text().strip() for page in doc]


@pytest.fixture()
def stub_export(monkeypatch):
    """No LibreOffice here: the DOCX export is a marker and 'converting' it gives a known PDF."""
    import app.routers.export as export_router
    import app.services.export_service as export_service

    state = {"version": 1, "captured": []}

    def fake_docx(segs, email, project=None, user=None):
        from app.services.export_wrapper import SKIP_SOURCE_PAGES

        state["skip_source_pages"] = SKIP_SOURCE_PAGES.get()
        return io.BytesIO(f"docx v{state['version']}".encode())

    def fake_convert(data: bytes):
        if data == ORIGINAL_DOCX:
            return _pdf(1, "Original docx")
        return _pdf(TRANSLATION_PAGES, f"Translation v{state['version']}")

    monkeypatch.setattr(export_router, "generate_docx", fake_docx)
    monkeypatch.setattr(export_service, "_convert_docx_to_pdf", fake_convert)
    monkeypatch.setattr(export_router, "capture_template_in_background", lambda pid, uid: state["captured"].append(pid))
    return state


def _original(storage, project, data: bytes, file_name: str):
    storage["objects"][project.file_path] = data
    project.file_name = file_name


def _jpeg(width: int, height: int) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, "JPEG")
    return buf.getvalue()


def test_delivery_pdf_is_translation_then_separator_then_original(client, db, storage, make_user, make_project, stub_export):
    owner = make_user()
    project = make_project(owner)
    _original(storage, project, _pdf(3, "Originale"), "diploma.pdf")
    db.commit()

    r = client.get(f"/projects/{project.id}/export/delivery.pdf", headers=owner["headers"])
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert "diploma - translation.pdf" in r.headers["content-disposition"]
    texts = _texts(r.content)
    assert len(texts) == TRANSLATION_PAGES + 1 + 3
    assert texts[0].startswith("Translation")
    assert texts[TRANSLATION_PAGES] == "Copy of the original document"
    assert texts[-1] == "Originale page 3"
    with fitz.open(stream=r.content, filetype="pdf") as doc:
        assert doc.metadata["title"] == "diploma - translation.pdf"
    assert stub_export["captured"] == [project.id]


def test_delivery_pdf_asks_the_export_without_the_embedded_original(client, db, storage, make_user, make_project, stub_export):
    from app.services.export_wrapper import SKIP_SOURCE_PAGES

    owner = make_user()
    project = make_project(owner)
    _original(storage, project, _pdf(1, "Original"), "source.pdf")
    db.commit()
    assert client.get(f"/projects/{project.id}/export/delivery.pdf", headers=owner["headers"]).status_code == 200
    # The original goes after the separator, so the export must not also open with it.
    assert stub_export["skip_source_pages"] is True
    assert SKIP_SOURCE_PAGES.get() is False


def test_original_first_and_without_original(client, db, storage, make_user, make_project, stub_export):
    owner = make_user()
    project = make_project(owner)
    _original(storage, project, _pdf(1, "Originale"), "atto.pdf")
    db.commit()

    first = _texts(client.get(
        f"/projects/{project.id}/export/delivery.pdf?order=original_first", headers=owner["headers"]
    ).content)
    assert first[0] == "Copy of the original document"
    assert first[1] == "Originale page 1"
    assert first[2].startswith("Translation")

    alone = _texts(client.get(
        f"/projects/{project.id}/export/delivery.pdf?include_original=false", headers=owner["headers"]
    ).content)
    assert len(alone) == TRANSLATION_PAGES
    assert all(t.startswith("Translation") for t in alone)

    bad = client.get(f"/projects/{project.id}/export/delivery.pdf?order=sideways", headers=owner["headers"])
    assert bad.status_code == 422


def test_image_original_becomes_an_a4_page(client, db, storage, make_user, make_project, stub_export):
    owner = make_user()
    portrait = make_project(owner)
    _original(storage, portrait, _jpeg(600, 900), "scan.jpg")
    landscape = make_project(owner)
    _original(storage, landscape, _jpeg(1200, 500), "scan.png")
    db.commit()

    for project, (w, h) in ((portrait, (595, 842)), (landscape, (842, 595))):
        data = client.get(f"/projects/{project.id}/export/delivery.pdf", headers=owner["headers"]).content
        with fitz.open(stream=data, filetype="pdf") as doc:
            assert len(doc) == TRANSLATION_PAGES + 2
            page = doc[-1]
            assert (round(page.rect.width), round(page.rect.height)) == (w, h)
            images = page.get_image_info()
            assert len(images) == 1
            box = fitz.Rect(images[0]["bbox"])
            assert page.rect.contains(box)
            # Aspect ratio kept.
            src_ratio = 600 / 900 if project is portrait else 1200 / 500
            assert box.width / box.height == pytest.approx(src_ratio, rel=0.01)


def test_docx_original_is_converted_and_separator_follows_the_certification_language(
    client, db, storage, make_user, make_project, stub_export
):
    owner = make_user()
    project = make_project(owner)
    _original(storage, project, ORIGINAL_DOCX, "contratto.docx")
    project.target_language = "Italian"
    db.commit()

    texts = _texts(client.get(f"/projects/{project.id}/export/delivery.pdf", headers=owner["headers"]).content)
    assert texts[TRANSLATION_PAGES] == "Copia del documento originale"
    assert texts[-1] == "Original docx page 1"


def test_separator_language_is_read_from_the_certification_page():
    from app.services import docx_certification
    from app.services.delivery_pdf import separator_language

    content = docx_certification.CertContent(lang="de", values={"translator": "Anna Muster"}, day=date.today())
    page = docx_certification.standalone(content, page_break=False)
    assert separator_language(page, "English") == "de"
    assert separator_language(b"not a docx", "Japanese") == "en"
    assert separator_language(b"not a docx", "French") == "fr"


def test_unusable_original_is_reported(client, db, storage, make_user, make_project, stub_export):
    owner = make_user()
    project = make_project(owner)
    _original(storage, project, b"not a pdf", "broken.pdf")
    db.commit()
    r = client.get(f"/projects/{project.id}/export/delivery.pdf", headers=owner["headers"])
    assert r.status_code == 422
    assert "original" in r.json()["detail"]


def test_delivery_pdf_needs_download_feature_and_team_access(client, db, storage, make_user, make_project, stub_export):
    trial = make_user(plan="TRIAL")
    project = make_project(trial)
    assert client.get(f"/projects/{project.id}/export/delivery.pdf", headers=trial["headers"]).status_code == 403

    owner = make_user()
    stranger = make_user()
    theirs = make_project(owner)
    assert client.get(f"/projects/{theirs.id}/export/delivery.pdf", headers=stranger["headers"]).status_code == 404


def test_batch_zip_of_delivery_pdfs(client, db, storage, make_user, make_project, stub_export):
    owner = make_user()
    bid = client.post("/batches", json={"name": "Rossi"}, headers=owner["headers"]).json()["id"]
    a, b = make_project(owner), make_project(owner)
    _original(storage, a, _pdf(1, "A"), "a.pdf")
    _original(storage, b, _pdf(2, "B"), "b.pdf")
    a.batch_id = b.batch_id = bid
    db.commit()

    r = client.get(f"/batches/{bid}/export.zip?format=delivery", headers=owner["headers"])
    assert r.status_code == 200, r.text
    assert "Delivery PDF" in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(zf.namelist()) == ["a.pdf", "b.pdf"]
    assert len(_texts(zf.read("b.pdf"))) == TRANSLATION_PAGES + 1 + 2


# Client links


def _create(client, owner, project, **body):
    return client.post(f"/projects/{project.id}/delivery-links", json=body, headers=owner["headers"])


def _token(url: str) -> str:
    return url.rsplit("/d/", 1)[1]


@pytest.fixture()
def shared(client, db, storage, make_user, make_project, stub_export):
    owner = make_user()
    project = make_project(owner)
    _original(storage, project, _pdf(1, "Originale"), "diploma.pdf")
    owner["team"].name = "Espresso Translations"
    db.commit()
    return owner, project


def test_create_link_returns_url_once_and_stores_only_a_hash(client, db, shared):
    from app.config import settings

    owner, project = shared
    r = _create(client, owner, project)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"].startswith(settings.FRONTEND_URL.rstrip("/") + "/d/")
    token = _token(body["url"])
    assert len(token) >= 43
    assert body["kind"] == "delivery_pdf" and body["status"] == "active"
    assert body["token_prefix"] == token[:6]

    row = db.query(DeliveryLink).one()
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    stored = " ".join(str(getattr(row, c.name)) for c in DeliveryLink.__table__.columns)
    assert token not in stored
    assert (row.expires_at - datetime.utcnow()).days in (6, 7)

    listed = client.get(f"/projects/{project.id}/delivery-links", headers=owner["headers"]).json()
    assert len(listed) == 1 and "url" not in listed[0]
    assert token not in str(listed)


def test_public_metadata_and_download(client, db, storage, shared):
    owner, project = shared
    body = _create(client, owner, project, expires_in_days=30).json()
    token = _token(body["url"])

    meta = client.get(f"/public/delivery/{token}")
    assert meta.status_code == 200
    info = meta.json()
    assert info["valid"] is True
    assert info["file_name"] == "diploma - translation.pdf"
    assert info["company"] == "Espresso Translations"
    assert info["expires_at"].endswith("Z")
    assert meta.headers["cache-control"] == "no-store"

    f = client.get(f"/public/delivery/{token}/file")
    assert f.status_code == 200
    assert f.headers["content-type"] == "application/pdf"
    assert "attachment" in f.headers["content-disposition"]
    assert len(_texts(f.content)) == TRANSLATION_PAGES + 2

    row = db.query(DeliveryLink).one()
    db.refresh(row)
    assert row.download_count == 1 and row.last_downloaded_at is not None


def test_link_is_a_snapshot(client, db, shared, stub_export):
    owner, project = shared
    token = _token(_create(client, owner, project, kind="docx").json()["url"])
    stub_export["version"] = 2
    assert client.get(f"/public/delivery/{token}/file").content == b"docx v1"
    assert client.get(f"/projects/{project.id}/export", headers=owner["headers"]).content == b"docx v2"


def test_expired_and_revoked_links_are_gone(client, db, storage, shared):
    owner, project = shared
    expired = _token(_create(client, owner, project, expires_in_days=1).json()["url"])
    row = db.query(DeliveryLink).one()
    row.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    assert client.get(f"/public/delivery/{expired}").status_code == 410
    assert client.get(f"/public/delivery/{expired}").json()["valid"] is False
    assert client.get(f"/public/delivery/{expired}/file").status_code == 410

    revoked_body = _create(client, owner, project).json()
    revoked = _token(revoked_body["url"])
    assert client.get(f"/public/delivery/{revoked}").status_code == 200
    key = db.query(DeliveryLink).filter(DeliveryLink.id == revoked_body["id"]).one().file_key
    r = client.delete(f"/projects/{project.id}/delivery-links/{revoked_body['id']}", headers=owner["headers"])
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    assert client.get(f"/public/delivery/{revoked}").status_code == 410
    assert client.get(f"/public/delivery/{revoked}/file").status_code == 410
    assert key in storage["deleted"]


def test_wrong_token_is_404(client, shared):
    owner, project = shared
    _create(client, owner, project)
    assert client.get(f"/public/delivery/{secrets.token_urlsafe(32)}").status_code == 404
    assert client.get(f"/public/delivery/{secrets.token_urlsafe(32)}/file").status_code == 404
    assert client.get("/public/delivery/short").status_code == 404


def test_other_team_cannot_create_list_or_revoke(client, db, shared, make_user):
    owner, project = shared
    link_id = _create(client, owner, project).json()["id"]
    stranger = make_user()
    assert _create(client, stranger, project).status_code == 404
    assert client.get(f"/projects/{project.id}/delivery-links", headers=stranger["headers"]).status_code == 404
    assert client.delete(f"/projects/{project.id}/delivery-links/{link_id}", headers=stranger["headers"]).status_code == 404
    assert db.query(DeliveryLink).one().revoked_at is None


def test_teammate_can_revoke(client, db, shared, make_user):
    owner, project = shared
    link_id = _create(client, owner, project).json()["id"]
    mate = make_user(team=owner["team"])
    assert client.delete(f"/projects/{project.id}/delivery-links/{link_id}", headers=mate["headers"]).status_code == 200


def test_create_needs_download_feature_and_valid_options(client, db, storage, make_user, make_project, shared, stub_export):
    owner, project = shared
    assert _create(client, owner, project, expires_in_days=3).status_code == 422
    assert _create(client, owner, project, kind="zip").status_code == 422

    trial = make_user(plan="TRIAL")
    theirs = make_project(trial)
    assert _create(client, trial, theirs).status_code == 403

    pending = make_project(owner, status=ProjectStatus.PROCESSING)
    assert _create(client, owner, pending).status_code == 400


def test_public_endpoints_are_rate_limited(client, shared):
    owner, project = shared
    token = _token(_create(client, owner, project).json()["url"])
    codes = [client.get(f"/public/delivery/{token}/file").status_code for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429
    codes = [client.get(f"/public/delivery/{secrets.token_urlsafe(32)}").status_code for _ in range(61)]
    assert codes[-1] == 429


def test_expired_link_files_are_purged_after_a_week(client, db, storage, shared):
    from app.services.delivery_links import purge_expired_files

    owner, project = shared
    old_id = _create(client, owner, project).json()["id"]
    recent_id = _create(client, owner, project).json()["id"]
    now = datetime.utcnow()
    old = db.query(DeliveryLink).filter(DeliveryLink.id == old_id).one()
    recent = db.query(DeliveryLink).filter(DeliveryLink.id == recent_id).one()
    old.expires_at = now - timedelta(days=8)
    recent.expires_at = now - timedelta(days=2)
    old_key, recent_key = old.file_key, recent.file_key
    db.commit()

    assert purge_expired_files() == 1
    db.expire_all()
    assert old.file_key is None and old_key in storage["deleted"]
    assert recent.file_key == recent_key and recent_key not in storage["deleted"]


def test_deleting_the_project_deletes_link_files(client, db, storage, shared):
    owner, project = shared
    _create(client, owner, project)
    key = db.query(DeliveryLink).one().file_key
    assert client.delete(f"/projects/{project.id}", headers=owner["headers"]).status_code == 200
    assert key in storage["deleted"]
    assert db.query(DeliveryLink).count() == 0


def test_oversized_original_pdf_pages_are_fitted_to_a4():
    import fitz

    from app.services.delivery_pdf import _fit_to_a4

    src = fitz.open()
    for w, h in ((2480, 3508), (595.28, 841.89), (3508, 2480)):  # first: a 300 dpi scan saved at pixel size
        src.new_page(width=w, height=h).insert_text((50, 100), "Original", fontsize=40)
    out = _fit_to_a4(src)
    sizes = [(round(p.rect.width), round(p.rect.height)) for p in out]
    assert sizes == [(595, 842), (595, 842), (842, 595)]
    assert all("Original" in p.get_text() for p in out)
