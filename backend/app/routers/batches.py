"""Client batches: several documents uploaded together and kept consistent with each other."""
import logging
import re
import tempfile
import zipfile
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import _resolve_team_id, require_feature
from app.dependencies.tenant import team_ids_for
from app.models.batch import Batch, BatchTerm
from app.models.project import ProjectStatus, TranslationProject, is_dtp
from app.models.user import User
from app.services.learning import capture_template_in_background
from app.services.project_lifecycle import failure_code

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/batches", tags=["Batches"])


class _CreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class _ReviewPayload(BaseModel):
    status: str


def _batch_or_404(db: Session, batch_id: UUID, user: User) -> Batch:
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch or batch.team_id not in team_ids_for(db, user):
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


def _projects(db: Session, batch: Batch) -> list[TranslationProject]:
    return (
        db.query(TranslationProject)
        .filter(TranslationProject.batch_id == batch.id)
        .order_by(TranslationProject.created_at)
        .all()
    )


def _summary(batch: Batch, counts: dict) -> dict:
    return {
        "id": str(batch.id),
        "name": batch.name,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "documents": counts.get("documents", 0),
        "pages": counts.get("pages", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "in_progress": counts.get("documents", 0) - counts.get("completed", 0) - counts.get("failed", 0),
        "terms": counts.get("terms", 0),
    }


def _counts(db: Session, batch_ids: list) -> dict:
    if not batch_ids:
        return {}
    P = TranslationProject
    rows = (
        db.query(
            P.batch_id,
            func.count(P.id),
            func.coalesce(func.sum(P.page_count), 0),
            func.sum(case((P.status == ProjectStatus.COMPLETED, 1), else_=0)),
            func.sum(case((P.status == ProjectStatus.FAILED, 1), else_=0)),
        )
        .filter(P.batch_id.in_(batch_ids))
        .group_by(P.batch_id)
        .all()
    )
    out = {
        bid: {"documents": n, "pages": int(pages or 0), "completed": int(done or 0), "failed": int(failed or 0)}
        for bid, n, pages, done, failed in rows
    }
    for bid, n in db.query(BatchTerm.batch_id, func.count(BatchTerm.id)).filter(BatchTerm.batch_id.in_(batch_ids)).group_by(BatchTerm.batch_id):
        out.setdefault(bid, {})["terms"] = n
    return out


@router.post("")
def create_batch(data: _CreatePayload, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    team_id = _resolve_team_id(db, current_user)
    if not team_id:
        raise HTTPException(status_code=400, detail="Team not found")
    name = " ".join(data.name.split())
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    batch = Batch(team_id=team_id, name=name, created_by=current_user.id)
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return _summary(batch, {})


@router.get("")
def list_batches(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    teams = team_ids_for(db, current_user)
    if not teams:
        return []
    batches = db.query(Batch).filter(Batch.team_id.in_(teams)).order_by(Batch.created_at.desc()).limit(200).all()
    counts = _counts(db, [b.id for b in batches])
    return [_summary(b, counts.get(b.id, {})) for b in batches]


@router.get("/{batch_id}")
def get_batch(batch_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    batch = _batch_or_404(db, batch_id, current_user)
    projects = _projects(db, batch)
    terms = (
        db.query(BatchTerm).filter(BatchTerm.batch_id == batch.id).order_by(BatchTerm.created_at, BatchTerm.source_term).all()
    )
    names = {p.id: p.file_name for p in projects}
    body = _summary(batch, _counts(db, [batch.id]).get(batch.id, {}))
    body["projects"] = [
        {
            "id": str(p.id),
            "filename": p.file_name,
            "status": p.status,
            "review_status": p.review_status or "DRAFT",
            "progress": 100 if p.status == ProjectStatus.COMPLETED else (p.progress_percent or 0),
            "page_count": p.page_count,
            "source_lang": p.source_language,
            "target_lang": p.target_language,
            "mode": p.mode or "translate",
            "failure_reason": p.failure_reason,
            "failure_code": failure_code(p),
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in projects
    ]
    body["batch_terms"] = [
        {
            "source_term": t.source_term,
            "target_term": t.target_term,
            "kind": t.kind,
            "target_language": t.target_language,
            "first_project_id": str(t.first_project_id) if t.first_project_id else None,
            "first_project_name": names.get(t.first_project_id),
        }
        for t in terms
    ]
    return body


def _zip_name(file_name: str, ext: str, used: set) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", file_name or "document")
    stem = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", stem).strip() or "document"
    name, n = f"{stem}.{ext}", 2
    while name.lower() in used:
        name, n = f"{stem} ({n}).{ext}", n + 1
    used.add(name.lower())
    return name


@router.get("/{batch_id}/export.zip", dependencies=[Depends(require_feature("download_translation"))])
def export_batch(
    batch_id: UUID,
    background_tasks: BackgroundTasks,
    format: str = Query("docx", pattern="^(docx|pdf|delivery)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.routers.export import render_export
    from app.services.delivery_pdf import DeliveryError, build_delivery_pdf

    batch = _batch_or_404(db, batch_id, current_user)
    done = [p for p in _projects(db, batch) if p.status == ProjectStatus.COMPLETED]
    if not done:
        raise HTTPException(status_code=400, detail="No finished documents in this batch yet")

    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    used: set = set()
    failed = []
    with zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in done:
            try:
                if format == "delivery":
                    data = build_delivery_pdf(db, p, current_user)
                else:
                    data = render_export(db, p, current_user, format).getvalue()
            except DeliveryError as e:
                failed.append(f"{p.file_name}: {e}")
                continue
            except Exception:
                logger.exception("Batch export failed for project %s", p.id)
                failed.append(p.file_name)
                continue
            zf.writestr(_zip_name(p.file_name, "pdf" if format == "delivery" else format, used), data)
            background_tasks.add_task(capture_template_in_background, p.id, current_user.id)
        if failed:
            zf.writestr("NOT_EXPORTED.txt", "These documents could not be exported:\n" + "\n".join(failed) + "\n")
    spool.seek(0)
    safe = re.sub(r"[^A-Za-z0-9 _.-]+", "_", batch.name).strip() or "batch"
    label = "Delivery PDF" if format == "delivery" else format.upper()
    return StreamingResponse(
        spool,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe} ({label}).zip"'},
    )


@router.post("/{batch_id}/review-status")
def bulk_review_status(
    batch_id: UUID,
    data: _ReviewPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.routers.project import REVIEW_STATUSES

    new_status = (data.status or "").strip().upper()
    if new_status not in REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid review status")
    batch = _batch_or_404(db, batch_id, current_user)
    updated, skipped = [], 0
    for p in _projects(db, batch):
        # Unfinished documents keep their status; they can't be reviewed or certified yet. Editable copies are never certified.
        if p.status != ProjectStatus.COMPLETED or (new_status == "CERTIFIED" and is_dtp(p)):
            skipped += 1
            continue
        if (p.review_status or "DRAFT") != new_status:
            p.review_status = new_status
            updated.append(p.id)
    db.commit()
    if new_status == "CERTIFIED":
        for pid in updated:
            background_tasks.add_task(capture_template_in_background, pid, current_user.id)
    return {"updated": len(updated), "skipped": skipped, "review_status": new_status}
