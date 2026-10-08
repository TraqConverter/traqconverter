import io
from datetime import date, datetime

import fitz
import pytest

from app.models.delivery_link import DeliveryLink
from app.services import paypal, protected_preview

CERT_STATEMENT = (
    "I, Daniela Esposito, a professional translator, certify that the attached document is a true, accurate "
    "and complete translation of the original, to the best of my knowledge and ability."
)


def _translation_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Invoice 4815162342 issued today", fontsize=14)
    page.insert_text((72, 140), "plain lowercase words only", fontsize=14)
    cert = doc.new_page()
    cert.insert_text((200, 80), "CERTIFIED TRANSLATION", fontsize=16)
    cert.insert_textbox(fitz.Rect(72, 140, 523, 400), CERT_STATEMENT, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def _pdf(pages: int, label: str) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"{label} page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture()
def stub_export(monkeypatch):
    import app.routers.export as export_router
    import app.services.export_service as export_service

    monkeypatch.setattr(export_router, "generate_docx", lambda *a, **kw: io.BytesIO(b"docx"))
    monkeypatch.setattr(export_service, "_convert_docx_to_pdf", lambda data: _translation_pdf())
    monkeypatch.setattr(export_router, "capture_template_in_background", lambda pid, uid: None)


@pytest.fixture()
def shared(client, db, storage, make_user, make_project, stub_export):
    owner = make_user(email="translator@traqtest.io")
    project = make_project(owner)
    storage["objects"][project.file_path] = _pdf(3, "Originale")
    project.file_name = "diploma.pdf"
    owner["team"].name = "Espresso Translations"
    owner["team"].paypal_me = "EspressoTranslations"
    db.commit()
    return owner, project


def _create(client, owner, project, **body):
    return client.post(f"/projects/{project.id}/delivery-links", json=body, headers=owner["headers"])


def _protected(client, owner, project, **extra):
    body = {"protected": True, "amount": 45, **extra}
    r = _create(client, owner, project, **body)
    assert r.status_code == 200, r.text
    return r.json(), r.json()["url"].rsplit("/d/", 1)[1]


# PayPal.me


@pytest.mark.parametrize(
    "raw, handle",
    [
        ("EspressoTranslations", "EspressoTranslations"),
        ("  @espresso.tr_1-a ", "espresso.tr_1-a"),
        ("https://paypal.me/EspressoTranslations", "EspressoTranslations"),
        ("paypal.me/EspressoTranslations/", "EspressoTranslations"),
        ("https://www.paypal.com/paypalme/EspressoTranslations", "EspressoTranslations"),
        ("https://www.paypal.com/paypalme/EspressoTranslations?locale.x=it_IT", "EspressoTranslations"),
        ("https://www.paypal.biz/danilocov", "danilocov"),
        ("https://www.paypal.com/biz/profile/danilocov", "danilocov"),
        ("", None),
        (None, None),
    ],
)
def test_paypal_me_is_normalised(raw, handle):
    assert paypal.normalise_handle(raw) == handle


@pytest.mark.parametrize(
    "raw",
    ["a" * 21, "has space", "evil/../x", "https://example.com/x", "https://paypal.com/EspressoTranslations",
     "name!", "paypal.me", "https://paypal.me/" + "a" * 21],
)
def test_paypal_me_rejects_anything_else(raw):
    with pytest.raises(ValueError):
        paypal.normalise_handle(raw)


def test_payment_url_format():
    assert paypal.payment_url("Espresso", 4500) == "https://paypal.me/Espresso/45EUR"
    assert paypal.payment_url("Espresso", 4550) == "https://paypal.me/Espresso/45.50EUR"
    assert paypal.payment_url("Espresso", 4505, "gbp") == "https://paypal.me/Espresso/45.05GBP"
    assert paypal.to_cents("45.5") == 4550
    assert paypal.display_amount(4550) == "€45.50"
    for bad in (0, -1, "100000.01", "abc"):
        with pytest.raises(ValueError):
            paypal.to_cents(bad)
    assert paypal.to_cents(100000) == 10_000_000


def test_payment_settings(client, db, make_user):
    owner = make_user()
    assert client.get("/settings/payments", headers=owner["headers"]).json()["paypal_me"] is None

    r = client.put("/settings/payments", json={"paypal_me": "https://paypal.me/Espresso"}, headers=owner["headers"])
    assert r.status_code == 200
    assert r.json() == {
        "paypal_me": "Espresso",
        "paypal_url": "https://paypal.me/Espresso",
        "can_edit": True,
        "stripe_status": None,
        "stripe_charges_enabled": False,
        "stripe_details_submitted": False,
        "stripe_requirements_due": 0,
    }
    db.refresh(owner["team"])
    assert owner["team"].paypal_me == "Espresso"

    bad = client.put("/settings/payments", json={"paypal_me": "not a handle"}, headers=owner["headers"])
    assert bad.status_code == 422

    member = make_user(team=owner["team"])
    assert client.get("/settings/payments", headers=member["headers"]).json()["can_edit"] is False
    assert client.put("/settings/payments", json={"paypal_me": "Mine"}, headers=member["headers"]).status_code == 403
    admin = make_user(team=owner["team"], role="ADMIN")
    assert client.put("/settings/payments", json={"paypal_me": ""}, headers=admin["headers"]).json()["paypal_me"] is None


# Creating protected links


def test_protected_link_needs_an_amount(client, db, shared):
    owner, project = shared
    assert _create(client, owner, project, protected=True).status_code == 422
    for amount in (0, -5, 100000.01):
        assert _create(client, owner, project, protected=True, amount=amount).status_code == 422

    owner["team"].paypal_me = None
    db.commit()
    assert db.query(DeliveryLink).count() == 0
    # Without Stripe or PayPal the link still works: the client pays by bank transfer and the team unlocks it.
    r = _create(client, owner, project, protected=True, amount=45)
    assert r.status_code in (200, 201)
    assert db.query(DeliveryLink).count() == 1


def test_client_name_in_the_body_is_ignored_and_not_stored(client, db, shared):
    owner, project = shared
    body, token = _protected(client, owner, project, client_name="Mario Rossi", client_email="mario@example.com")
    assert "client_name" not in body
    assert not hasattr(DeliveryLink, "client_name")
    assert "client_name" not in {c.name for c in DeliveryLink.__table__.columns}
    row = db.query(DeliveryLink).one()
    values = {c.name: getattr(row, c.name) for c in DeliveryLink.__table__.columns}
    assert not any("Mario" in str(v) or "mario@" in str(v) for v in values.values())
    listed = client.get(f"/projects/{project.id}/delivery-links", headers=owner["headers"]).json()[0]
    assert "client_name" not in listed
    assert "client_name" not in client.get(f"/public/delivery/{token}").json()


def test_protected_link_is_a_30_day_delivery_pdf(client, db, shared):
    owner, project = shared
    body, _ = _protected(client, owner, project, kind="docx", amount="45.50")
    assert body["kind"] == "delivery_pdf"
    assert body["protected"] is True and body["amount"] == 45.5 and body["currency"] == "EUR"
    assert "client_name" not in body
    assert body["payment_status"] == "awaiting"
    row = db.query(DeliveryLink).one()
    assert row.amount_cents == 4550
    assert (row.expires_at - datetime.utcnow()).days in (29, 30)
    assert (row.preview_pages, row.original_pages) == (2, 3)

    listed = client.get(f"/projects/{project.id}/delivery-links", headers=owner["headers"]).json()[0]
    assert listed["payment_status"] == "awaiting" and listed["unlocked_at"] is None


# Public side


def test_public_info_of_a_locked_link(client, shared):
    owner, project = shared
    _, token = _protected(client, owner, project, amount="45.50")
    info = client.get(f"/public/delivery/{token}").json()
    assert info["protected"] is True and info["locked"] is True
    assert info["amount"] == 45.5 and info["currency"] == "EUR"
    assert "client_name" not in info
    assert info["company"] == "Espresso Translations"
    assert info["preview_pages"] == 2 and info["original_pages"] == 3
    assert info["paypal_url"] == "https://paypal.me/EspressoTranslations/45.50EUR"
    assert info["paid_claimed"] is False


def test_locked_file_is_403_until_unlocked(client, db, storage, shared):
    owner, project = shared
    body, token = _protected(client, owner, project)
    r = client.get(f"/public/delivery/{token}/file")
    assert r.status_code == 403
    assert r.headers["cache-control"] == "no-store"
    assert db.query(DeliveryLink).one().download_count == 0

    # The preview is rendered on first view and served while locked.
    page = client.get(f"/public/delivery/{token}/preview/1")
    assert page.status_code == 200
    assert page.headers["content-type"] == "image/png"
    assert page.headers["cache-control"] == "no-store"
    assert page.content.startswith(b"\x89PNG")
    assert client.get(f"/public/delivery/{token}/preview/2").status_code == 200
    assert client.get(f"/public/delivery/{token}/preview/3").status_code == 404
    assert client.get(f"/public/delivery/{token}/preview/0").status_code == 404
    row = db.query(DeliveryLink).one()
    db.refresh(row)
    keys = list(row.preview_keys)
    assert len(keys) == 2 and all(k.startswith(f"delivery/preview/{row.id}/") for k in keys)

    r = client.post(f"/projects/{project.id}/delivery-links/{body['id']}/unlock", headers=owner["headers"])
    assert r.status_code == 200
    assert r.json()["payment_status"] == "unlocked"
    db.refresh(row)
    assert row.unlocked_at is not None and row.unlocked_by == owner["user"].id
    assert row.preview_keys is None
    assert set(keys) <= set(storage["deleted"])

    assert client.get(f"/public/delivery/{token}/preview/1").status_code == 404
    info = client.get(f"/public/delivery/{token}").json()
    assert info["locked"] is False and "paypal_url" not in info
    f = client.get(f"/public/delivery/{token}/file")
    assert f.status_code == 200 and f.headers["content-type"] == "application/pdf"


def test_unprotected_link_has_no_preview(client, shared):
    owner, project = shared
    token = _create(client, owner, project).json()["url"].rsplit("/d/", 1)[1]
    assert client.get(f"/public/delivery/{token}/preview/1").status_code == 404
    assert client.post(f"/public/delivery/{token}/paid").status_code == 404
    assert client.get(f"/public/delivery/{token}").json()["locked"] is False


def test_revoking_deletes_the_preview(client, db, storage, shared):
    owner, project = shared
    body, token = _protected(client, owner, project)
    assert client.get(f"/public/delivery/{token}/preview/1").status_code == 200
    row = db.query(DeliveryLink).one()
    db.refresh(row)
    keys = list(row.preview_keys)
    assert client.delete(f"/projects/{project.id}/delivery-links/{body['id']}", headers=owner["headers"]).status_code == 200
    assert set(keys) <= set(storage["deleted"])
    db.refresh(row)
    assert row.preview_keys is None
    assert client.get(f"/public/delivery/{token}/preview/1").status_code == 410


def test_deleting_the_project_or_account_deletes_the_preview(client, db, storage, shared, make_project):
    owner, project = shared
    _, token = _protected(client, owner, project)
    client.get(f"/public/delivery/{token}/preview/1")
    keys = list(db.query(DeliveryLink).one().preview_keys)
    assert client.delete(f"/projects/{project.id}", headers=owner["headers"]).status_code == 200
    assert set(keys) <= set(storage["deleted"])

    other = make_project(owner)
    storage["objects"][other.file_path] = _pdf(1, "Originale")
    other.file_name = "atto.pdf"
    db.commit()
    _, token = _protected(client, owner, other)
    client.get(f"/public/delivery/{token}/preview/1")
    keys = list(db.query(DeliveryLink).one().preview_keys)
    res = client.post("/auth/delete-account", headers=owner["headers"],
                      json={"password": "correct horse battery", "confirm": "DELETE"})
    assert res.status_code == 200
    assert set(keys) <= set(storage["deleted"])


def test_paid_claim_is_recorded_once_and_emails_once(client, db, shared, emails):
    owner, project = shared
    body, token = _protected(client, owner, project, amount="45.50")
    first = client.post(f"/public/delivery/{token}/paid")
    assert first.status_code == 200 and first.json() == {"paid_claimed": True, "locked": True}
    row = db.query(DeliveryLink).one()
    db.refresh(row)
    claimed_at = row.paid_claimed_at
    assert claimed_at is not None

    assert client.post(f"/public/delivery/{token}/paid").json()["paid_claimed"] is True
    db.refresh(row)
    assert row.paid_claimed_at == claimed_at
    assert len(emails) == 1
    mail = emails[0]
    assert mail["to"] == "translator@traqtest.io"
    assert mail["subject"] == "Your client says they've paid €45.50"
    assert (
        "Your client says they've paid €45.50 for diploma - translation.pdf. "
        "Check that the money has arrived, then unlock it in the editor (Share with client)."
    ) in mail["text_fallback"]
    assert client.get(f"/public/delivery/{token}").json()["paid_claimed"] is True
    listed = client.get(f"/projects/{project.id}/delivery-links", headers=owner["headers"]).json()[0]
    assert listed["payment_status"] == "claimed"


def test_paid_claim_is_rate_limited(client, shared, emails):
    owner, project = shared
    _, token = _protected(client, owner, project)
    codes = [client.post(f"/public/delivery/{token}/paid").status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429
    assert len(emails) == 1


def test_other_team_cannot_unlock(client, db, shared, make_user):
    owner, project = shared
    body, token = _protected(client, owner, project)
    stranger = make_user()
    r = client.post(f"/projects/{project.id}/delivery-links/{body['id']}/unlock", headers=stranger["headers"])
    assert r.status_code == 404
    assert db.query(DeliveryLink).one().unlocked_at is None
    assert client.get(f"/public/delivery/{token}/file").status_code == 403

    for role in ("REVIEWER", "MEMBER"):
        mate = make_user(team=owner["team"], role=role)
        r = client.post(f"/projects/{project.id}/delivery-links/{body['id']}/unlock", headers=mate["headers"])
        assert r.status_code == 403
    assert db.query(DeliveryLink).one().unlocked_at is None
    links = client.get(f"/projects/{project.id}/delivery-links", headers=mate["headers"]).json()
    assert links[0]["can_unlock"] is False

    pm = make_user(team=owner["team"], role="PM")
    assert client.get(f"/projects/{project.id}/delivery-links", headers=pm["headers"]).json()[0]["can_unlock"] is True
    r = client.post(f"/projects/{project.id}/delivery-links/{body['id']}/unlock", headers=pm["headers"])
    assert r.status_code == 200


# Rendering


def _clean(page):
    from PIL import Image

    pix = page.get_pixmap(dpi=protected_preview.DPI, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _diff(a, b, box) -> float:
    from PIL import ImageChops, ImageStat

    return sum(ImageStat.Stat(ImageChops.difference(a.crop(box), b.crop(box))).mean) / 3


def _box(rect) -> tuple[int, int, int, int]:
    s = protected_preview.DPI / 72
    return int(rect[0] * s), int(rect[1] * s), int(rect[2] * s) + 1, int(rect[3] * s) + 1


def test_words_with_digits_are_blurred_and_plain_words_are_not(monkeypatch):
    from PIL import Image

    monkeypatch.setattr(protected_preview, "_watermark", lambda img, text: img)
    with fitz.open(stream=_translation_pdf(), filetype="pdf") as doc:
        page = doc[0]
        clean = _clean(page)
        shown = Image.open(io.BytesIO(protected_preview.render_page(page, "x")))
        words = {w[4]: w[:4] for w in page.get_text("words")}
    assert _diff(clean, shown, _box(words["4815162342"])) > 20
    assert _diff(clean, shown, _box(words["lowercase"])) < 1


def test_certification_page_is_blurred_except_its_title(monkeypatch):
    from PIL import Image

    monkeypatch.setattr(protected_preview, "_watermark", lambda img, text: img)
    with fitz.open(stream=_translation_pdf(), filetype="pdf") as doc:
        page = doc[1]
        clean = _clean(page)
        shown = Image.open(io.BytesIO(protected_preview.render_page(page, "x")))
        title = _box(page.search_for("CERTIFIED TRANSLATION")[0])
        body = _box(page.search_for("professional translator")[0])

    def dark(img, box):
        return sum(1 for p in img.crop(box).convert("L").getdata() if p < 100)

    assert dark(shown, title) == dark(clean, title)
    assert dark(clean, body) > 50
    assert dark(shown, body) < dark(clean, body) * 0.05
    full = (0, title[3] + 4, clean.width, clean.height)
    assert dark(shown, full) < dark(clean, full) * 0.05


def test_watermark_covers_the_whole_page():
    from PIL import Image

    doc = fitz.open()
    page = doc.new_page()
    img = Image.open(io.BytesIO(protected_preview.render_page(page, protected_preview.watermark_text(date(2026, 10, 1)))))
    w, h = img.size
    for x0, y0 in ((0, 0), (w // 2, 0), (0, h // 2), (w // 2, h // 2)):
        quadrant = img.crop((x0, y0, x0 + w // 2, y0 + h // 2)).convert("L")
        assert sum(1 for p in quadrant.getdata() if p < 235) > 500
    doc.close()


def test_watermark_names_no_one():
    import inspect

    assert protected_preview.watermark_text(date(2026, 10, 1)) == "PREVIEW – NOT VALID – UNPAID · 01 Oct 2026"
    assert list(inspect.signature(protected_preview.watermark_text).parameters) == ["day"]
    assert list(inspect.signature(protected_preview.render_preview).parameters) == ["pdf", "day"]


def test_preview_leaves_out_the_original():
    doc = fitz.open(stream=_translation_pdf(), filetype="pdf")
    sep = doc.new_page()
    sep.insert_text((72, 400), "Copia del documento originale", fontsize=16)
    doc.new_page().insert_text((72, 72), "Originale 1")
    doc.new_page().insert_text((72, 72), "Originale 2")
    data = doc.tobytes()
    doc.close()
    assert protected_preview.split_pages(data) == (2, 2)
    assert len(protected_preview.render_preview(data, date(2026, 10, 1))) == 2
    assert protected_preview.split_pages(_pdf(3, "x")) == (3, 0)


def _words(*lines):
    """Word tuples like PyMuPDF's: one (block, line) per entry."""
    out = []
    for block, line, text in lines:
        for n, word in enumerate(text.split()):
            out.append((0, 0, 1, 1, word, block, line, n))
    return out


def _picked(*lines):
    words = _words(*lines)
    return [words[i][4] for i in sorted(protected_preview.sensitive_words(words))]


def test_word_selection():
    # Digits, wherever they are.
    assert _picked((0, 0, "issued on 14/03/1987 at no. 312/A for EUR 16.00")) == ["14/03/1987", "312/A", "16.00"]
    # Names: two or more capitalised words, ALL-CAPS surnames.
    assert _picked((0, 0, "Name: Mario Giuseppe"), (1, 0, "Surname: ROSSI")) == ["Mario", "Giuseppe", "ROSSI"]
    assert _picked((0, 0, "the mother, Anna Maria De Luca, declared")) == ["Anna", "Maria", "De", "Luca,"]
    # Common document words don't count, capitalised or not.
    assert _picked((0, 0, "BIRTH CERTIFICATE"), (1, 0, "Republic of Italy"), (2, 0, "CERTIFIED TRANSLATION")) == []
    assert _picked((0, 0, "Civil Status Office of Trani")) == []
    # A sentence's first word doesn't start a run in running text...
    assert _picked((0, 0, "Further Information is available from the registry office today.")) == []
    assert _picked((0, 0, "It was done. Further Information is available from the office.")) == []
    # ...but a short cell that is just a name does.
    assert _picked((3, 0, "Giovanna Bianchi")) == ["Giovanna", "Bianchi"]
    # Runs stop at line ends and sentence ends.
    assert _picked((0, 0, "signed by Rossi"), (0, 1, "Mario on the day")) == []
    assert _picked((0, 0, "it was Rossi. Mario then left")) == []
    # A lone capitalised word is left alone (places, sentence starts).
    assert _picked((0, 0, "born in Barletta yesterday")) == []
