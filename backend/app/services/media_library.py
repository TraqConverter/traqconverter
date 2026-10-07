"""The team's media library: which stamp and logo a project uses, and loading them ready for a document."""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.media_asset import AUTO_KINDS, MediaAsset
from app.services import cert_locale, docx_images, document_editor
from app.services.docx_blocks import DocxEditError

logger = logging.getLogger(__name__)

_BASE_CODE = re.compile(r"^[a-z]{2,3}$")
MIME_BY_EXT = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


class AssetUnavailable(Exception):
    """The asset exists but its file couldn't be read from storage."""


def language_base(value: Optional[str]) -> Optional[str]:
    """'en-GB', 'EN', 'English (UK)' -> 'en'; None when empty or unknown."""
    raw = (value or "").strip()
    if not raw or raw.lower() == "auto":
        return None
    code = cert_locale.language_code(raw)
    if code:
        return code
    base = raw.replace("_", "-").split("-")[0].lower()
    return base if _BASE_CODE.match(base) else None


def project_language(project) -> Optional[str]:
    return language_base(getattr(project, "target_language", None))


def auto_asset(db: Session, team_id, kind: str, language: Optional[str]) -> Optional[MediaAsset]:
    """The auto-use asset for the language, else the language-free one."""
    if team_id is None or kind not in AUTO_KINDS:
        return None
    rows = (
        db.query(MediaAsset)
        .filter(MediaAsset.team_id == team_id, MediaAsset.kind == kind, MediaAsset.auto_use.is_(True))
        .all()
    )
    by_lang = {r.language: r for r in rows}
    if language and language in by_lang:
        return by_lang[language]
    return by_lang.get(None)


def team_assets(db: Session, team_id, kind: Optional[str] = None, language: Optional[str] = None) -> list[MediaAsset]:
    q = db.query(MediaAsset).filter(MediaAsset.team_id == team_id)
    if kind:
        q = q.filter(MediaAsset.kind == kind)
    if language:
        q = q.filter(MediaAsset.language == language)
    return q.order_by(MediaAsset.created_at.desc(), MediaAsset.name).all()


def ranked_for(assets: list[MediaAsset], language: Optional[str]) -> list[MediaAsset]:
    """The project's language first, then language-free, then the rest; auto-use ahead within each."""
    def rank(a: MediaAsset):
        group = 0 if language and a.language == language else 1 if a.language is None else 2
        return (group, not a.auto_use, (a.name or "").lower())

    return sorted(assets, key=rank)


def set_auto_use(db: Session, asset: MediaAsset) -> None:
    """Make `asset` the automatic pick for its kind and language, unsetting the previous one first."""
    q = db.query(MediaAsset).filter(
        MediaAsset.team_id == asset.team_id,
        MediaAsset.kind == asset.kind,
        MediaAsset.auto_use.is_(True),
        MediaAsset.id != asset.id,
    )
    q = q.filter(MediaAsset.language.is_(None)) if asset.language is None else q.filter(MediaAsset.language == asset.language)
    for other in q.all():
        other.auto_use = False
    db.flush()
    asset.auto_use = True


def prepare(asset: MediaAsset) -> docx_images.PreparedImage:
    """The asset's picture ready for a document; a stamp scanned on white paper gets a clear background."""
    try:
        raw = document_editor._download(asset.s3_key)
    except Exception as e:
        logger.warning("Couldn't load media asset %s: %s", asset.id, e)
        raise AssetUnavailable() from e
    try:
        return docx_images.prepare_image(raw, remove_background=asset.kind == "stamp")
    except DocxEditError as e:
        logger.warning("Media asset %s isn't a readable image: %s", asset.id, e)
        raise AssetUnavailable() from e


def auto_image(db: Session, project, kind: str) -> tuple[Optional[docx_images.PreparedImage], Optional[MediaAsset]]:
    """The project's automatic stamp or logo, loaded. Raises AssetUnavailable when the file can't be read."""
    asset = auto_asset(db, project.team_id, kind, project_language(project))
    if asset is None:
        return None, None
    return prepare(asset), asset


def auto_image_or_none(db: Session, project, kind: str) -> Optional[docx_images.PreparedImage]:
    try:
        return auto_image(db, project, kind)[0]
    except AssetUnavailable:
        return None


def has_kind(db: Session, team_id, kind: str) -> bool:
    return (
        db.query(MediaAsset.id).filter(MediaAsset.team_id == team_id, MediaAsset.kind == kind).first() is not None
    )


def export_stamp_key(db: Session, project) -> Optional[str]:
    """For documents from before the editable stamp: the language-matched stamp, else the old team stamp."""
    asset = auto_asset(db, project.team_id, "stamp", project_language(project))
    if asset is not None:
        return asset.s3_key
    if has_kind(db, project.team_id, "stamp"):
        return None
    from app.models.team import Team

    team = db.query(Team).filter(Team.id == project.team_id).first()
    return team.stamp_s3_key if team else None


def logo_key(db: Session, project) -> Optional[str]:
    asset = auto_asset(db, getattr(project, "team_id", None), "logo", project_language(project))
    return asset.s3_key if asset else None


def logo_key_for_export(project) -> Optional[str]:
    """logo_key with its own session, for export code that runs without one."""
    if getattr(project, "team_id", None) is None:
        return None
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return logo_key(db, project)
    except Exception:
        logger.exception("Couldn't look up the logo for project %s", getattr(project, "id", None))
        return None
    finally:
        db.close()


def forget_legacy_key(db: Session, team_id, key: str) -> None:
    """A deleted asset mustn't come back through the old Settings columns it was copied from."""
    db.execute(text("UPDATE teams SET stamp_s3_key = NULL WHERE id = :tid AND stamp_s3_key = :key"), {"tid": team_id, "key": key})
    db.execute(
        text(
            "UPDATE users SET logo_s3_key = NULL WHERE logo_s3_key = :key AND id IN ("
            " SELECT owner_id FROM teams WHERE id = :tid UNION SELECT user_id FROM team_members WHERE team_id = :tid)"
        ),
        {"tid": team_id, "key": key},
    )


# --- moving the Settings logo and stamp into the library ------------------------------


def _mime(key: str) -> Optional[str]:
    return MIME_BY_EXT.get(key.rsplit(".", 1)[-1].lower()) if "." in key else None


def _insert(conn, team_id, user_id, name: str, kind: str, key: str, auto_use: bool) -> None:
    conn.execute(
        text(
            "INSERT INTO media_assets (id, team_id, uploaded_by, name, kind, language, s3_key, mime_type, auto_use, created_at)"
            " VALUES (:id, :team_id, :user_id, :name, :kind, NULL, :key, :mime, :auto_use, :now)"
        ),
        {
            "id": str(uuid.uuid4()), "team_id": str(team_id), "user_id": str(user_id) if user_id else None,
            "name": name[:80], "kind": kind, "key": key, "mime": _mime(key), "auto_use": auto_use,
            "now": datetime.utcnow(),
        },
    )


def backfill_from_settings(conn) -> int:
    """Copy each team's Settings stamp and its people's logos into the library. Safe to run twice."""
    added = 0
    teams = conn.execute(text("SELECT id, owner_id, stamp_s3_key FROM teams")).fetchall()
    for team_id, owner_id, stamp_key in teams:
        rows = conn.execute(
            text("SELECT s3_key, kind, auto_use, language FROM media_assets WHERE team_id = :tid"), {"tid": str(team_id)}
        ).fetchall()
        known = {r[0] for r in rows}
        auto = {r[1] for r in rows if r[2] and r[3] is None}
        if stamp_key and stamp_key not in known:
            _insert(conn, team_id, owner_id, "Company stamp", "stamp", stamp_key, "stamp" not in auto)
            known.add(stamp_key)
            added += 1
        people = conn.execute(
            text(
                "SELECT u.id, u.logo_s3_key, u.full_name, u.email, u.id = :owner AS is_owner FROM users u"
                " WHERE u.logo_s3_key IS NOT NULL AND (u.id = :owner OR u.id IN"
                " (SELECT user_id FROM team_members WHERE team_id = :tid))"
                " ORDER BY (u.id = :owner) DESC, u.email"
            ),
            {"owner": str(owner_id), "tid": str(team_id)},
        ).fetchall()
        for user_id, key, full_name, email, is_owner in people:
            if key in known:
                continue
            who = (full_name or "").strip() or (email or "").split("@")[0]
            name = "Company logo" if is_owner else f"Logo ({who})"
            _insert(conn, team_id, user_id, name, "logo", key, bool(is_owner) and "logo" not in auto)
            known.add(key)
            added += 1
    return added
