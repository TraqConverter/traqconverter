"""A project's stored files: deleting a project with everything attached, and dropping files a newer one replaced."""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.models.project import TranslationProject

logger = logging.getLogger(__name__)


def stored_keys(db: Session, project: TranslationProject) -> list[str]:
    from app.models.delivery_link import DeliveryLink
    from app.models.document_version import DocumentVersion

    keys = [project.file_path, project.output_file, project.authored_docx_s3_key]
    for file_key, preview_keys in db.query(DeliveryLink.file_key, DeliveryLink.preview_keys).filter(
        DeliveryLink.project_id == project.id
    ):
        keys += [file_key, *(preview_keys or [])]
    keys += [k for (k,) in db.query(DocumentVersion.s3_key).filter(DocumentVersion.project_id == project.id) if k]
    return [k for k in keys if k]


def delete_project(db: Session, project: TranslationProject, keep_memory: bool = False) -> None:
    """Delete the rows, then the stored files and cached page images; keep_memory detaches TM entries instead."""
    from app.models.delivery_link import DeliveryLink
    from app.models.segment_comment import SegmentComment
    from app.models.translation_segment import TranslationSegment
    from app.services import source_pages
    from app.services.s3_service import delete_objects_from_s3

    pid = str(project.id)
    keys = stored_keys(db, project)
    # Each table is removed explicitly so the delete works whether or not the schema cascades.
    try:
        segment_ids = [
            row[0] for row in db.query(TranslationSegment.id).filter(TranslationSegment.project_id == project.id)
        ]
        if segment_ids:
            db.query(SegmentComment).filter(SegmentComment.segment_id.in_(segment_ids)).delete(
                synchronize_session=False
            )
        db.query(TranslationSegment).filter(TranslationSegment.project_id == project.id).delete(
            synchronize_session=False
        )
        db.query(DeliveryLink).filter(DeliveryLink.project_id == project.id).delete(synchronize_session=False)
        memory_sql = (
            "UPDATE translation_memory SET project_id = NULL WHERE project_id = :pid"
            if keep_memory
            else "DELETE FROM translation_memory WHERE project_id = :pid"
        )
        for sql in (memory_sql, "DELETE FROM translation_jobs WHERE project_id = :pid"):
            sp = db.begin_nested()
            try:
                db.execute(text(sql), {"pid": pid})
                sp.commit()
            except Exception:
                sp.rollback()
        db.delete(project)
        db.commit()
    except Exception:
        db.rollback()
        raise
    delete_objects_from_s3(keys)
    source_pages.drop(project.id)


def _in_use(db: Session, key: str) -> bool:
    from app.models.delivery_link import DeliveryLink
    from app.models.document_version import DocumentVersion
    from app.models.learning import DocumentTemplate
    from app.models.review import ReviewState

    checks = (
        db.query(TranslationProject.id).filter(
            or_(
                TranslationProject.file_path == key,
                TranslationProject.output_file == key,
                TranslationProject.authored_docx_s3_key == key,
            )
        ),
        db.query(DocumentVersion.id).filter(DocumentVersion.s3_key == key),
        db.query(DeliveryLink.id).filter(DeliveryLink.file_key == key),
        db.query(DocumentTemplate.id).filter(DocumentTemplate.s3_key == key),
        db.query(ReviewState.project_id).filter(ReviewState.source_key == key),
    )
    return any(q.first() is not None for q in checks)


def delete_replaced(db: Session, keys: Iterable[Optional[str]]) -> None:
    """Delete files nothing points at any more, after the caller committed their replacement. Never raises."""
    from app.services.s3_service import delete_objects_from_s3

    try:
        orphans = [k for k in {k for k in keys if k} if not _in_use(db, k)]
        if orphans:
            delete_objects_from_s3(orphans)
    except Exception:
        logger.exception("Couldn't delete replaced files")
