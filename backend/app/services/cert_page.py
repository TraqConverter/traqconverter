"""What goes on a project's certification page: the template to use, the field values, the saved logo and stamp."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.certification import Certification
from app.services import cert_locale, docx_certification, docx_images, document_editor
from app.services.docx_blocks import DocxEditError

logger = logging.getLogger(__name__)

EXAMPLE_PROJECT = {
    "file_name": "birth-certificate.pdf",
    "document": "Birth certificate",
    "source_language": "Italian",
    "target_language": "English",
    "pages": 2,
    "client": "Example client",
}


STANDARD = "standard"


class TemplateNotFound(LookupError):
    pass


def is_docx(cert: Certification) -> bool:
    return (cert.file_name or "").lower().endswith(".docx")


def team_default(db: Session, team_id) -> Optional[Certification]:
    return (
        db.query(Certification)
        .filter(Certification.team_id == team_id, Certification.is_default.is_(True))
        .first()
    )


def templates(db: Session, team_id) -> list[Certification]:
    """The team's Word templates, default first."""
    rows = db.query(Certification).filter(Certification.team_id == team_id).all()
    return sorted((c for c in rows if is_docx(c)), key=lambda c: (not c.is_default, (c.file_name or "").lower()))


def template_for(db: Session, project, template_id: Optional[UUID | str] = None) -> Optional[Certification]:
    """The explicitly chosen template, else the project's, else the team default. STANDARD means the built-in page."""
    if template_id == STANDARD:
        return None
    if not template_id and getattr(project, "certification_standard", False):
        return None
    wanted = template_id or getattr(project, "certification_template_id", None)
    if wanted:
        cert = (
            db.query(Certification)
            .filter(Certification.id == wanted, Certification.team_id == project.team_id)
            .first()
        )
        if cert is None:
            raise TemplateNotFound(str(wanted))
        return cert
    cert = team_default(db, project.team_id)
    return cert if cert is not None and is_docx(cert) else None


def page_template_for(db: Session, project, template_id: Optional[UUID | str] = None) -> Optional[Certification]:
    """What an add uses. A saved pick that isn't a Word file (a PDF certificate) falls back to the team default."""
    cert = template_for(db, project, template_id)
    if cert is None or is_docx(cert) or template_id:
        return cert
    default = team_default(db, project.team_id)
    return default if default is not None and is_docx(default) else None


def choice_id(cert: Optional[Certification]) -> str:
    return str(cert.id) if cert is not None else STANDARD


def remember(project, cert: Optional[Certification]) -> None:
    """Save the pick on the project so later exports and re-adds use it."""
    project.certification_template_id = cert.id if cert is not None else None
    project.certification_standard = cert is None


def load_bytes(cert: Certification) -> bytes:
    return document_editor._download(cert.file_path)


def load_image(key: Optional[str], remove_background: bool) -> Optional[docx_images.PreparedImage]:
    if not key:
        return None
    try:
        return docx_images.prepare_image(document_editor._download(key), remove_background=remove_background)
    except (DocxEditError, OSError, KeyError):
        logger.warning("Skipping unreadable image %s for the certification page", key)
    except Exception:
        logger.exception("Couldn't load %s for the certification page", key)
    return None


def _translator(user) -> str:
    return (getattr(user, "full_name", "") or "").strip() or (getattr(user, "email", "") or "").split("@")[0]


def _batch_name(db: Session, project) -> str:
    batch_id = getattr(project, "batch_id", None)
    if not batch_id:
        return ""
    from app.models.batch import Batch

    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    return batch.name if batch else ""


def _values(user, team, lang: str, today: date, *, file_name: str, document: str, source: str, target: str,
            pages: int, client: str, certificate_number: str) -> dict[str, str]:
    return {
        "translator": _translator(user),
        "date": cert_locale.format_date(today, lang),
        "source_language": cert_locale.language_name(source, lang),
        "target_language": cert_locale.language_name(target, lang),
        "document": document,
        "pages": str(pages) if pages else "",
        "client": client,
        "translator_email": getattr(user, "email", "") or "",
        "company": (getattr(team, "name", "") or "") if team else "",
        "company_address": (getattr(team, "address", "") or "") if team else "",
        "certificate_number": certificate_number,
        "file_name": file_name,
    }


def page_language(target_language, template: Optional[bytes]) -> str:
    """A template is written in the translator's chosen language (often not the target); its values follow it."""
    if template:
        try:
            detected = cert_locale.detect_language(docx_certification.docx_text(template))
        except Exception:
            detected = None
        if detected:
            return detected
    return cert_locale.cert_language(target_language)


def content_for_project(db: Session, project, user, template: Optional[bytes]) -> docx_certification.CertContent:
    from app.models.team import Team
    from app.services.cert_template_service import build_substitution_values
    from app.services.glossary_service import project_source_language

    lang = page_language(project.target_language, template)
    today = date.today()
    team = db.query(Team).filter(Team.id == project.team_id).first()
    extra = build_substitution_values(user=user, project=project, team=team)
    values = _values(
        user, team, lang, today,
        file_name=project.file_name or "",
        document=Path(project.file_name or "").stem.replace("_", " ").strip(),
        # An "auto" upload names its language only in the detected profile.
        source=project_source_language(project) or project.source_language, target=project.target_language,
        pages=project.page_count or 0, client=_batch_name(db, project),
        certificate_number=extra.get("certificate_number", ""),
    )
    return docx_certification.CertContent(
        lang=lang,
        values=values,
        day=today,
        pages=project.page_count or 0,
        logo=load_image(getattr(user, "logo_s3_key", None), remove_background=False),
        stamp=load_image(team.stamp_s3_key if team else None, remove_background=True),
        template_docx=template,
        statement_override=project.certification_override_text,
        extra_tokens=extra,
    )


def example_content(db: Session, user, team, template: bytes) -> docx_certification.CertContent:
    """The current user's data on a sample project, for the template check."""
    from types import SimpleNamespace

    from app.services.cert_template_service import build_substitution_values

    ex = EXAMPLE_PROJECT
    lang = page_language(ex["target_language"], template)
    today = date.today()
    sample = SimpleNamespace(
        id=None, file_name=ex["file_name"], source_language=ex["source_language"],
        target_language=ex["target_language"], page_count=ex["pages"], total_segments=0,
    )
    extra = build_substitution_values(user=user, project=sample, team=team)
    extra["certificate_number"] = f"CERT-{today.year}-EXAMPLE"
    values = _values(
        user, team, lang, today,
        file_name=ex["file_name"], document=ex["document"], source=ex["source_language"],
        target=ex["target_language"], pages=ex["pages"], client=ex["client"],
        certificate_number=extra["certificate_number"],
    )
    return docx_certification.CertContent(
        lang=lang,
        values=values,
        day=today,
        pages=ex["pages"],
        logo=load_image(getattr(user, "logo_s3_key", None), remove_background=False),
        stamp=load_image(team.stamp_s3_key if team else None, remove_background=True),
        template_docx=template,
        extra_tokens=extra,
    )
