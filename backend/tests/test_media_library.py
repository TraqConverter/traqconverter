"""The media library: the API, moving the Settings logo and stamp into it, and where its pictures are used."""
import hashlib
import io
import uuid
import zipfile
from types import SimpleNamespace

import pytest
from docx import Document
from docx.shared import Cm
from lxml import etree

from app.models.media_asset import MediaAsset
from app.services import docx_blocks, docx_images, docx_page_stamp, media_library
from tests.test_document_media import (  # noqa: F401  (project_with_doc is a fixture)
    WP,
    _body_xml,
    _get,
    _png,
    project_with_doc,
)

RED, BLUE, GREEN = (200, 30, 30), (20, 40, 200), (20, 160, 60)


def add_media(db, storage, owner, kind="stamp", language=None, auto_use=True, color=RED, name=None):
    """A library picture stored straight in the database, as an upload would leave it."""
    key = f"media/{uuid.uuid4()}_{kind}.png"
    storage["objects"][key] = _png((200, 200), color=color, paper=kind == "stamp")
    asset = MediaAsset(
        team_id=owner["team"].id, uploaded_by=owner["user"].id, name=name or f"{kind} {language or 'any'}",
        kind=kind, language=language, s3_key=key, mime_type="image/png", width_px=200, height_px=200,
        size_bytes=len(storage["objects"][key]), auto_use=False,
    )
    db.add(asset)
    db.flush()
    if auto_use:
        media_library.set_auto_use(db, asset)
    db.commit()
    return asset


def _post(client, who, content=None, filename="stamp.png", **form):
    return client.post(
        "/media",
        headers=who["headers"],
        data={k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in form.items()},
        files={"file": (filename, content if content is not None else _png(), "image/png")},
    )


def _media_hashes(data: bytes) -> set[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith("word/media/")}


def _prepared_hash(storage, asset) -> str:
    image = docx_images.prepare_image(storage["objects"][asset.s3_key], remove_background=asset.kind == "stamp")
    return hashlib.sha256(image.data).hexdigest()


# --- API ----------------------------------------------------------------------------


def test_upload_list_edit_delete(client, db, storage, make_user):
    owner = make_user()
    r = _post(client, owner, kind="stamp", language="en-GB", auto_use=True, name="ISO EN")
    assert r.status_code == 200, r.text
    asset = r.json()
    assert (asset["name"], asset["kind"], asset["language"], asset["auto_use"]) == ("ISO EN", "stamp", "en", True)
    assert (asset["width_px"], asset["height_px"], asset["mime_type"]) == (120, 60, "image/png")
    assert asset["url"].startswith("https://storage.test/media/")
    stored = db.get(MediaAsset, uuid.UUID(asset["id"]))
    assert stored.s3_key in storage["objects"] and stored.size_bytes == len(storage["objects"][stored.s3_key])

    listed = client.get("/media", headers=owner["headers"]).json()
    assert [a["id"] for a in listed["assets"]] == [asset["id"]] and listed["can_edit"] is True
    assert client.get("/media?kind=logo", headers=owner["headers"]).json()["assets"] == []
    assert len(client.get("/media?language=en", headers=owner["headers"]).json()["assets"]) == 1
    assert client.get("/media?language=it", headers=owner["headers"]).json()["assets"] == []

    r = client.patch(f"/media/{asset['id']}", headers=owner["headers"], json={"name": "  ISO   stamp ", "language": "pt"})
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["language"], r.json()["auto_use"]) == ("ISO stamp", "pt", True)
    r = client.patch(f"/media/{asset['id']}", headers=owner["headers"], json={"language": None})
    assert r.json()["language"] is None
    r = client.patch(f"/media/{asset['id']}", headers=owner["headers"], json={"kind": "signature"})
    assert (r.json()["kind"], r.json()["auto_use"]) == ("signature", False), "only stamps and logos are automatic"

    key = stored.s3_key
    assert client.delete(f"/media/{asset['id']}", headers=owner["headers"]).status_code == 200
    assert key in storage["deleted"]
    assert client.get("/media", headers=owner["headers"]).json()["assets"] == []
    assert client.delete(f"/media/{asset['id']}", headers=owner["headers"]).status_code == 404


def test_teams_only_see_and_change_their_own_media(client, db, storage, make_user):
    owner = make_user()
    stranger = make_user()
    asset = add_media(db, storage, owner)
    assert client.get("/media", headers=stranger["headers"]).json()["assets"] == []
    assert client.patch(f"/media/{asset.id}", headers=stranger["headers"], json={"name": "x"}).status_code == 404
    assert client.delete(f"/media/{asset.id}", headers=stranger["headers"]).status_code == 404
    assert asset.s3_key not in storage["deleted"]


@pytest.mark.parametrize("role,allowed", [("ADMIN", True), ("MEMBER", False), ("PM", False), ("REVIEWER", False)])
def test_only_the_owner_and_admins_change_the_library(client, db, storage, make_user, role, allowed):
    owner = make_user()
    other = make_user(team=owner["team"], role=role)
    asset = add_media(db, storage, owner)
    listed = client.get("/media", headers=other["headers"]).json()
    assert len(listed["assets"]) == 1 and listed["can_edit"] is allowed
    expected = 200 if allowed else 403
    assert _post(client, other).status_code == expected
    assert client.patch(f"/media/{asset.id}", headers=other["headers"], json={"name": "Renamed"}).status_code == expected
    assert client.delete(f"/media/{asset.id}", headers=other["headers"]).status_code == expected


def test_upload_validation(client, make_user):
    owner = make_user()
    assert _post(client, owner, content=b"not an image").status_code == 400
    assert _post(client, owner, filename="stamp.svg").status_code == 400
    assert _post(client, owner, content=b"\x89PNG" + b"0" * (docx_images.MAX_UPLOAD_BYTES + 1)).status_code == 400
    assert _post(client, owner, language="not a language!").status_code == 422
    assert _post(client, owner, name="x" * 81).status_code == 422
    assert _post(client, owner, kind="signature", auto_use=True).status_code == 422
    assert _post(client, owner, kind="banner").status_code == 422
    r = _post(client, owner, filename="../../etc/Company_stamp.png")
    assert r.status_code == 200 and r.json()["name"] == "Company stamp"
    assert ".." not in client.get("/media", headers=owner["headers"]).json()["assets"][0]["url"]


def test_the_library_is_for_paid_plans(client, make_user):
    trial = make_user(plan="TRIAL")
    assert client.get("/media", headers=trial["headers"]).status_code == 403
    assert _post(client, trial).status_code == 403
    basic = make_user(plan="BASIC")
    assert client.get("/media", headers=basic["headers"]).status_code == 200


def test_one_automatic_picture_per_kind_and_language(client, db, storage, make_user):
    owner = make_user()
    first = _post(client, owner, kind="stamp", language="en", auto_use=True).json()
    any_lang = _post(client, owner, kind="stamp", auto_use=True).json()
    logo = _post(client, owner, kind="logo", language="en", auto_use=True).json()
    second = _post(client, owner, kind="stamp", language="en", auto_use=True).json()
    auto = {a["id"]: a["auto_use"] for a in client.get("/media", headers=owner["headers"]).json()["assets"]}
    assert auto == {first["id"]: False, any_lang["id"]: True, logo["id"]: True, second["id"]: True}

    # Moving the language-free stamp onto English takes English's slot.
    r = client.patch(f"/media/{any_lang['id']}", headers=owner["headers"], json={"language": "en"})
    assert r.status_code == 200 and r.json()["auto_use"] is True
    auto = {a["id"]: a["auto_use"] for a in client.get("/media", headers=owner["headers"]).json()["assets"]}
    assert auto[second["id"]] is False and auto[logo["id"]] is True
    assert client.patch(f"/media/{first['id']}", headers=owner["headers"], json={"auto_use": True}).json()["auto_use"]
    auto = {a["id"]: a["auto_use"] for a in client.get("/media", headers=owner["headers"]).json()["assets"]}
    assert auto[any_lang["id"]] is False
    count = db.query(MediaAsset).filter(MediaAsset.team_id == owner["team"].id, MediaAsset.auto_use.is_(True)).count()
    assert count == 2

    other = make_user()
    assert _post(client, other, kind="stamp", language="en", auto_use=True).json()["auto_use"], "per team"


def test_resolving_by_target_language():
    assert media_library.language_base("en-GB") == "en"
    assert media_library.language_base("English (UK)") == "en"
    assert media_library.language_base("pt-BR") == "pt"
    assert media_library.language_base("th-TH") == "th"
    assert media_library.language_base("auto") is None
    assert media_library.language_base("") is None


# --- moving the Settings logo and stamp into the library ------------------------------------


def test_settings_stamp_and_logos_become_library_pictures(db, make_user):
    owner = make_user()
    member = make_user(team=owner["team"], role="MEMBER")
    twin = make_user(team=owner["team"], role="MEMBER")
    owner["team"].stamp_s3_key = "uploads/stamp.png"
    owner["user"].logo_s3_key = "uploads/owner_logo.png"
    member["user"].logo_s3_key = "uploads/member_logo.jpg"
    twin["user"].logo_s3_key = "uploads/owner_logo.png"
    empty = make_user()
    db.commit()

    assert media_library.backfill_from_settings(db.connection()) == 3
    db.commit()
    rows = db.query(MediaAsset).filter(MediaAsset.team_id == owner["team"].id).all()
    got = {(r.kind, r.s3_key, r.auto_use, r.language) for r in rows}
    assert got == {
        ("stamp", "uploads/stamp.png", True, None),
        ("logo", "uploads/owner_logo.png", True, None),
        ("logo", "uploads/member_logo.jpg", False, None),
    }
    assert {r.mime_type for r in rows} == {"image/png", "image/jpeg"}
    assert next(r for r in rows if r.kind == "stamp").name == "Company stamp"
    assert db.query(MediaAsset).filter(MediaAsset.team_id == empty["team"].id).count() == 0
    assert media_library.backfill_from_settings(db.connection()) == 0, "running it again adds nothing"


def test_deleting_a_copied_stamp_doesnt_bring_back_the_settings_one(client, db, storage, make_user):
    owner = make_user()
    storage["objects"]["uploads/stamp.png"] = _png((200, 200), paper=True)
    owner["team"].stamp_s3_key = "uploads/stamp.png"
    db.commit()
    media_library.backfill_from_settings(db.connection())
    db.commit()
    asset = db.query(MediaAsset).filter(MediaAsset.team_id == owner["team"].id).one()
    assert client.delete(f"/media/{asset.id}", headers=owner["headers"]).status_code == 200
    db.refresh(owner["team"])
    assert owner["team"].stamp_s3_key is None


# --- the page stamp of a new editor document ----------------------------------------------


def _footer_media_hashes(data: bytes) -> set[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        rels = [n for n in z.namelist() if n.startswith("word/_rels/footer")]
        targets = set()
        for name in rels:
            for rel in etree.fromstring(z.read(name)):
                if rel.get("Target", "").startswith("media/"):
                    targets.add("word/" + rel.get("Target"))
        return {hashlib.sha256(z.read(t)).hexdigest() for t in targets}


def test_new_document_gets_the_stamp_for_its_target_language(client, db, storage, project_with_doc):
    owner, project = project_with_doc()
    english = add_media(db, storage, owner, "stamp", "en", color=BLUE)
    fallback = add_media(db, storage, owner, "stamp", None, color=GREEN)
    add_media(db, storage, owner, "stamp", "it", color=RED)
    data, _ = _get(client, owner, project)
    assert _footer_media_hashes(data) == {_prepared_hash(storage, english)}
    state = client.get(f"/projects/{project.id}/document/page-stamp", headers=owner["headers"]).json()
    assert state["asset_id"] == str(english.id) and state["enabled"] and state["available"]
    assert [s["id"] for s in state["stamps"]][:2] == [str(english.id), str(fallback.id)], "matching language first"

    owner2, italian_project = project_with_doc()
    italian_project.target_language = "pt-BR"
    db.commit()
    fallback2 = add_media(db, storage, owner2, "stamp", None, color=GREEN)
    add_media(db, storage, owner2, "stamp", "en", color=BLUE)
    data, _ = _get(client, owner2, italian_project)
    assert _footer_media_hashes(data) == {_prepared_hash(storage, fallback2)}

    owner3, bare = project_with_doc()
    add_media(db, storage, owner3, "stamp", "it", color=RED)
    data, _ = _get(client, owner3, bare)
    assert docx_page_stamp.is_marked(data) and _footer_media_hashes(data) == set()
    state = client.get(f"/projects/{bare.id}/document/page-stamp", headers=owner3["headers"]).json()
    assert state["enabled"] is False and state["available"] is True

    owner4, nothing = project_with_doc()
    _get(client, owner4, nothing)
    state = client.get(f"/projects/{nothing.id}/document/page-stamp", headers=owner4["headers"]).json()
    assert state["available"] is False and state["stamps"] == []


def test_page_stamp_picture_can_be_switched(client, db, storage, project_with_doc, make_user):
    owner, project = project_with_doc()
    english = add_media(db, storage, owner, "stamp", "en", color=BLUE)
    other = add_media(db, storage, owner, "stamp", "nl", auto_use=False, color=GREEN)
    logo = add_media(db, storage, owner, "logo", None, color=RED)
    _, v = _get(client, owner, project)
    url = f"/projects/{project.id}/document/page-stamp"
    r = client.put(url, headers=owner["headers"], json={"version": v, "align": "left", "width_cm": 4})
    v = r.json()["version"]

    r = client.put(url, headers=owner["headers"], json={"version": v, "asset_id": str(other.id)})
    assert r.status_code == 200, r.text
    state = r.json()
    assert (state["asset_id"], state["align"], state["width_cm"], state["version"]) == (str(other.id), "left", 4.0, v + 1)
    data, _ = _get(client, owner, project)
    assert _footer_media_hashes(data) == {_prepared_hash(storage, other)}

    assert client.put(url, headers=owner["headers"], json={"version": v + 1, "asset_id": str(logo.id)}).status_code == 404
    stranger = make_user()
    theirs = add_media(db, storage, stranger, "stamp", None)
    assert client.put(url, headers=owner["headers"], json={"version": v + 1, "asset_id": str(theirs.id)}).status_code == 404

    off = client.put(url, headers=owner["headers"], json={"version": v + 1, "enabled": False}).json()
    assert off["enabled"] is False and off["asset_id"] is None
    on = client.put(url, headers=owner["headers"], json={"version": v + 2, "enabled": True, "asset_id": str(english.id)}).json()
    assert on["enabled"] and on["asset_id"] == str(english.id)
    assert client.post(f"/projects/{project.id}/document/undo", headers=owner["headers"], json={}).status_code == 200
    assert client.get(url, headers=owner["headers"]).json()["enabled"] is False


# --- certification page -------------------------------------------------------------------


def test_certification_page_uses_the_language_matched_logo_and_stamp(client, db, storage, project_with_doc):
    owner, project = project_with_doc()
    en_logo = add_media(db, storage, owner, "logo", "en", color=BLUE)
    any_logo = add_media(db, storage, owner, "logo", None, color=GREEN)
    en_stamp = add_media(db, storage, owner, "stamp", "en", color=BLUE)
    it_stamp = add_media(db, storage, owner, "stamp", "it", color=RED)
    _, v = _get(client, owner, project)
    r = client.post(f"/projects/{project.id}/document/certification", headers=owner["headers"], json={"version": v})
    assert r.status_code == 200, r.text
    data, _ = _get(client, owner, project)
    assert _prepared_hash(storage, en_logo) in _media_hashes(data)
    assert _prepared_hash(storage, en_stamp) in _media_hashes(data)
    assert _prepared_hash(storage, any_logo) not in _media_hashes(data)
    assert _prepared_hash(storage, it_stamp) not in _media_hashes(data)

    # Another target language falls back to the language-free logo.
    owner2, french = project_with_doc()
    french.target_language = "fr-FR"
    db.commit()
    fr_any = add_media(db, storage, owner2, "logo", None, color=GREEN)
    add_media(db, storage, owner2, "logo", "en", color=BLUE)
    _, v = _get(client, owner2, french)
    assert client.post(f"/projects/{french.id}/document/certification", headers=owner2["headers"], json={"version": v}).status_code == 200
    data, _ = _get(client, owner2, french)
    assert _prepared_hash(storage, fr_any) in _media_hashes(data)


# --- placing a library picture --------------------------------------------------------------


def _a4(*paras) -> bytes:
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.left_margin = section.right_margin = Cm(2)
    section.top_margin, section.bottom_margin = Cm(2.5), Cm(3)
    for text in paras:
        doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return docx_blocks.tag_blocks(buf.getvalue())


def test_bottom_right_offsets_come_from_the_page_size_and_margins():
    data = _a4("Page one", "Page two")
    ids = docx_blocks.block_ids(data)
    image = docx_images.prepare_image(_png((200, 100)))
    out, made = docx_images.place_on_pages(data, image, ids, "bottom", "right", 5)
    info = {i["id"]: i for i in docx_images.list_images(out)}
    cx, cy = 5 * 360_000, 2.5 * 360_000
    tw, th = (21 - 4) * 360_000, (29.7 - 5.5) * 360_000
    for image_id in made:
        assert info[image_id]["floating"]
        assert abs(info[image_id]["x_emu"] - (tw - cx)) < 1000
        assert abs(info[image_id]["y_emu"] - (th - cy)) < 1000
    top, made = docx_images.place_on_pages(data, image, ids[:1], "top", "center", 5)
    entry = next(i for i in docx_images.list_images(top) if i["id"] == made[0])
    assert entry["y_emu"] == 0 and abs(entry["x_emu"] - (tw - cx) / 2) < 1000
    assert docx_images.page_offsets(docx_images.section_geometry(docx_blocks._Doc.load(data), docx_blocks._Doc.load(data).find_block(ids[0])), 100, 50, "top", "left") == (0, 0)


def test_place_on_every_page_skips_the_certification_page_and_is_one_undo(client, db, storage, project_with_doc):
    owner, project = project_with_doc()
    stamp = add_media(db, storage, owner, "stamp", "en")
    _, v = _get(client, owner, project)
    v = client.post(f"/projects/{project.id}/document/certification", headers=owner["headers"], json={"version": v}).json()["version"]
    data, _ = _get(client, owner, project)
    texts = docx_blocks.paragraph_texts(data, docx_blocks.block_ids(data))
    cert_block = next(b for b, t in texts.items() if t == "CERTIFIED TRANSLATION")
    pages = [b for b, t in texts.items() if t in ("CERTIFICATE OF RESIDENCE", "Signature: ________")]
    before = docx_images.list_images(data)
    media_before = _media_hashes(data)

    url = f"/projects/{project.id}/document/media/{stamp.id}/place"
    r = client.post(url, headers=owner["headers"], json={
        "version": v, "scope": "all", "block_ids": pages + [cert_block], "vertical": "bottom", "align": "right", "width_cm": 2.5,
    })
    assert r.status_code == 200, r.text
    assert r.json()["version"] == v + 1 and len(r.json()["image_ids"]) == 2
    data, _ = _get(client, owner, project)
    info = {i["id"]: i for i in docx_images.list_images(data)}
    placed = [info[i] for i in r.json()["image_ids"]]
    assert {p["block_id"] for p in placed} == set(pages)
    assert all(p["floating"] and p["width_cm"] == 2.5 and p["y_emu"] > 0 and p["x_emu"] > 0 for p in placed)
    assert _media_hashes(data) == media_before, "the certification stamp is the same file: no new media part"
    embeds = {b.get(f"{{{docx_blocks.R_NS}}}embed") for b in _body_xml(data).iter(f"{{{docx_blocks.A_NS}}}blip")}
    assert len(embeds) == 1

    assert client.post(f"/projects/{project.id}/document/undo", headers=owner["headers"], json={}).status_code == 200
    data, _ = _get(client, owner, project)
    assert docx_images.list_images(data) == before


def test_editor_picker_lists_the_project_language_first(client, db, storage, project_with_doc, make_user):
    owner, project = project_with_doc()
    italian = add_media(db, storage, owner, "stamp", "it", name="A italian")
    anyone = add_media(db, storage, owner, "logo", None, name="B any")
    english = add_media(db, storage, owner, "stamp", "en", name="C english")
    r = client.get(f"/projects/{project.id}/document/media", headers=owner["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["language"] == "en"
    assert [a["id"] for a in r.json()["assets"]] == [str(english.id), str(anyone.id), str(italian.id)]
    assert client.get(f"/projects/{project.id}/document/media", headers=make_user()["headers"]).status_code == 404
    trial, trial_project = project_with_doc(plan="TRIAL")
    assert client.get(f"/projects/{trial_project.id}/document/media", headers=trial["headers"]).status_code == 403


def test_place_on_this_page_top_or_at_the_cursor(client, db, storage, project_with_doc, make_user):
    owner, project = project_with_doc()
    logo = add_media(db, storage, owner, "logo", None, color=BLUE)
    data, v = _get(client, owner, project)
    ids = docx_blocks.block_ids(data)
    url = f"/projects/{project.id}/document/media/{logo.id}/place"

    r = client.post(url, headers=owner["headers"], json={"version": v, "scope": "page", "block_id": ids[0], "vertical": "top", "align": "center", "width_cm": 3.5})
    assert r.status_code == 200, r.text
    v = r.json()["version"]
    data, _ = _get(client, owner, project)
    entry = docx_images.list_images(data)[0]
    assert entry["floating"] and entry["y_emu"] == 0 and entry["block_id"] == ids[0] and entry["width_cm"] == 3.5
    assert len(_media_hashes(data)) == 1

    r = client.post(url, headers=owner["headers"], json={"version": v, "block_id": ids[1], "vertical": "cursor", "align": "left", "width_cm": 5})
    assert r.status_code == 200, r.text
    data, v = _get(client, owner, project)
    cursor = next(i for i in docx_images.list_images(data) if i["id"] == r.json()["image_ids"][0])
    assert not cursor["floating"] and cursor["width_cm"] == 5.0
    assert len(_media_hashes(data)) == 1, "the same picture shares its media part"
    assert len(list(_body_xml(data).iter(f"{{{WP}}}docPr"))) == 2

    bad = [
        {"version": v, "scope": "all", "block_ids": ids, "vertical": "cursor"},
        {"version": v, "scope": "page", "vertical": "top"},
        {"version": v, "scope": "all", "vertical": "top"},
        {"version": v, "scope": "page", "block_id": ids[0], "width_cm": 30},
    ]
    for body in bad:
        assert client.post(url, headers=owner["headers"], json=body).status_code == 422, body
    assert client.post(url, headers=owner["headers"], json={"version": v - 1, "block_id": ids[0]}).status_code == 409

    stranger = make_user()
    theirs = add_media(db, storage, stranger, "logo", None)
    other_url = f"/projects/{project.id}/document/media/{theirs.id}/place"
    assert client.post(other_url, headers=owner["headers"], json={"version": v, "block_id": ids[0]}).status_code == 404
    assert client.post(url, headers=stranger["headers"], json={"version": v, "block_id": ids[0]}).status_code == 404

    member = make_user(team=owner["team"], role="MEMBER")
    assert client.post(url, headers=member["headers"], json={"version": v, "block_id": ids[0]}).status_code == 200


# --- export of documents from before the editable stamp --------------------------------------


def test_old_document_export_uses_the_language_matched_stamp_then_the_settings_one(db, storage, make_user, tmp_path):
    from app.services.export_service import _resolve_team_stamp

    owner = make_user()
    storage["objects"]["uploads/settings_stamp.png"] = b"settings stamp"
    owner["team"].stamp_s3_key = "uploads/settings_stamp.png"
    owner["team"].stamp_alignment = "left"
    db.commit()
    project = SimpleNamespace(team_id=owner["team"].id, target_language="English", id=None)

    path, align = _resolve_team_stamp(project, tmp_path)
    assert open(path, "rb").read() == b"settings stamp" and align == "left", "no library stamp yet: the old one"

    italian = add_media(db, storage, owner, "stamp", "it", color=RED)
    assert _resolve_team_stamp(project, tmp_path) == (None, "right"), "the team has library stamps, none for English"
    english = add_media(db, storage, owner, "stamp", "en", color=BLUE)
    path, _ = _resolve_team_stamp(project, tmp_path)
    assert open(path, "rb").read() == storage["objects"][english.s3_key]
    project.target_language = "it-IT"
    path, _ = _resolve_team_stamp(project, tmp_path)
    assert open(path, "rb").read() == storage["objects"][italian.s3_key]
