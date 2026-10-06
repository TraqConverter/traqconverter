import logging
import os
from typing import Optional
from uuid import UUID
from pathlib import Path
from app.models.translation_segment import TranslationSegment

from fastapi import Form, BackgroundTasks
from fastapi import (
    APIRouter,
    Query,
    Response,
    UploadFile,
    File,
    Depends,
    HTTPException,
    Header,
)

from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.feature_guard import require_feature, user_has_feature
from app.dependencies.rate_limit import user_rate_limit
from app.dependencies.tenant import can_manage_project, get_user_project_or_404
from app.services import ai_actions, ai_usage, job_progress, project_instructions
from app.services.learning import capture_template_in_background
from app.services.project_lifecycle import enqueue_job, failure_code, job_charge_reference
from app.models.project import MODE_DTP, MODE_TRANSLATE, PROJECT_MODES, TranslationProject, ProjectStatus, is_dtp
from app.core.roles import is_staff
from app.models.user import User
from app.models.team import Team

from app.core.file_validation import clean_file_name, local_file_name, validate_file_extension, validate_file_size
from app.core.page_counter import get_page_count

from app.services.storage_service import save_file_locally
from app.services.s3_service import upload_file_to_s3, generate_presigned_download_url


from app.services.credit_service import (
    CreditService,
    WalletNotFoundError,
    InsufficientCreditsError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Projects"])

AUTHORED_ENGINE = "claude-authored"


def _validate_model_key(model: str | None) -> None:
    from app.services.ai_translation_service import MODEL_OPTIONS

    if model and model != AUTHORED_ENGINE and model not in MODEL_OPTIONS:
        raise HTTPException(status_code=400, detail="Unknown translation model")


def _sanitize_edited_html(raw: str) -> str:
    import nh3

    # Images are rebuilt from data: URIs only; remote src would make the server fetch arbitrary URLs.
    def _attr_filter(tag, attr, value):
        if tag == "img" and attr == "src" and not value.startswith("data:image/"):
            return None
        return value

    tags = set(nh3.ALLOWED_TAGS) | {
        "img", "span", "div", "font", "u", "s", "sub", "sup", "hr", "br",
        "style", "section", "article", "header", "footer", "main",
    }
    attributes = {
        "*": {"style", "class", "align", "colspan", "rowspan", "width", "height"},
        "img": {"src", "alt", "width", "height", "style"},
        "td": {"style", "colspan", "rowspan", "width", "align", "valign"},
        "th": {"style", "colspan", "rowspan", "width", "align", "valign"},
        "table": {"style", "width", "border", "cellpadding", "cellspacing"},
        "font": {"face", "size", "color"},
    }
    return nh3.clean(
        raw,
        tags=tags,
        attributes=attributes,
        attribute_filter=_attr_filter,
        url_schemes={"http", "https", "mailto", "data"},
        clean_content_tags={"script"},
        link_rel="noopener noreferrer",
    )


def _clean_instructions(text: str | None) -> str | None:
    try:
        return project_instructions.clean(text)
    except project_instructions.InstructionsTooLong as e:
        raise HTTPException(status_code=422, detail=str(e))


def _can_download(db: Session, user: User) -> bool:
    from app.core.plan_features import PLAN_FEATURES
    from app.dependencies.feature_guard import effective_plan

    return bool(PLAN_FEATURES.get(effective_plan(db, user), {}).get("download_translation"))


def _watermark_docx(docx_bytes: bytes) -> bytes:
    from io import BytesIO
    from docx import Document
    from docx.shared import Pt, RGBColor

    doc = Document(BytesIO(docx_bytes))
    for section in doc.sections:
        p = section.header.paragraphs[0] if section.header.paragraphs else section.header.add_paragraph()
        run = p.insert_paragraph_before().add_run("PREVIEW ONLY - upgrade your plan to download this translation")
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0xB9, 0x1C, 0x1C)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()










@router.get("/translation-models")
def list_translation_models():
    from app.services.ai_translation_service import MODEL_OPTIONS

    return {
        "models": [
            {
                "id": key,
                "label": cfg.get("label") or key,
                "provider": cfg.get("provider"),
            }
            for key, cfg in MODEL_OPTIONS.items()



            if key != "balanced"
        ]
    }






def _template_uuid(value: Optional[str]) -> Optional[UUID]:
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid certification_template_id")


def _discard_stored(key: Optional[str]) -> None:
    """Delete an upload no project ended up owning, so a refused document isn't kept."""
    if not key:
        return
    from app.services import s3_service

    try:
        s3_service.delete_objects_from_s3([key])
    except Exception:
        logger.exception("Couldn't delete orphaned upload %s", key)


@router.post("/upload")
async def upload_project(
    file: UploadFile = File(...),


    source_language: str = Form("English"),
    target_language: str = Form("Spanish"),
    model: str = Form("balanced"),



    use_tm: bool = Form(True),
    apply_glossary: bool = Form(True),
    request_certification: bool = Form(False),
    certification_template_id: Optional[str] = Form(None),
    batch_id: Optional[UUID] = Form(None),
    ai_instructions: Optional[str] = Form(None),
    mode: str = Form(MODE_TRANSLATE),

    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    validate_file_extension(file.filename)
    validate_file_size(file)
    mode = (mode or MODE_TRANSLATE).strip().lower()
    if mode not in PROJECT_MODES:
        raise HTTPException(status_code=400, detail="Unknown project mode")
    _validate_model_key(model)
    ai_instructions = _clean_instructions(ai_instructions)
    if mode == MODE_DTP:
        # Same language out as in; nothing to translate, learn from or certify.
        target_language = source_language
        model, ai_instructions = AUTHORED_ENGINE, None
        use_tm = apply_glossary = request_certification = False
        certification_template_id = None
    template_uuid = _template_uuid(certification_template_id)

    file_path = None
    stored_key = None
    project = None

    try:




        if idempotency_key:
            existing_project = (
                db.query(TranslationProject)
                .filter(
                    TranslationProject.idempotency_key == idempotency_key,
                    TranslationProject.user_id == current_user.id,
                )
                .first()
            )

            if existing_project:
                logger.info("Idempotent replay detected")
                return {
                    "message": "Project already created (idempotent replay)",
                    "project_id": str(existing_project.id),
                    "pages": existing_project.page_count,
                    "credits_used": existing_project.credits_used,
                }





        team = (
            db.query(Team)
            .filter(Team.owner_id == current_user.id)
            .first()
        )
        if not team:
            from app.models.team_member import TeamMember
            membership = (
                db.query(TeamMember)
                .filter(TeamMember.user_id == current_user.id)
                .first()
            )
            if membership:
                team = (
                    db.query(Team)
                    .filter(Team.id == membership.team_id)
                    .first()
                )

        if not team:
            raise HTTPException(status_code=400, detail="Team not found")

        if batch_id:
            from app.models.batch import Batch

            if not db.query(Batch.id).filter(Batch.id == batch_id, Batch.team_id == team.id).first():
                raise HTTPException(status_code=404, detail="Batch not found")




        file_path, _ = save_file_locally(file, str(team.id))

        # Rejected files never reach storage.
        page_count = get_page_count(file_path)
        credits_required = max(1, page_count)

        s3_key = stored_key = upload_file_to_s3(Path(file_path))
        logger.info(f"S3 upload successful: {s3_key}")




        if not user_has_feature(db, current_user, "certifications"):
            request_certification, template_uuid = False, None

        project = TranslationProject(
            user_id=current_user.id,
            team_id=team.id,
            file_name=clean_file_name(local_file_name(file.filename)) or "Untitled document",
            file_path=s3_key,
            page_count=page_count,
            credits_used=credits_required,
            idempotency_key=idempotency_key,

            source_language=source_language,
            target_language=target_language,
            model=model,
            ai_instructions=ai_instructions,
            mode=mode,


            use_tm=use_tm,
            apply_glossary=apply_glossary,
            add_certification=request_certification,
            certification_template_id=template_uuid,

            status=ProjectStatus.PENDING,
            progress_percent=0,
            batch_id=batch_id,
        )

        db.add(project)
        db.flush()





        if is_staff(current_user):
            new_balance = -1
        else:
            try:
                new_balance = CreditService.deduct_credits(
                    db=db,
                    team_id=str(team.id),
                    amount=credits_required,
                    reference_id=str(project.id),
                )
            except WalletNotFoundError:
                raise HTTPException(status_code=404, detail="Credit wallet not found")
            except InsufficientCreditsError:
                raise HTTPException(status_code=400, detail="Insufficient credits")

        enqueue_job(db, project.id, s3_key)
        db.commit()
        stored_key = None
        db.refresh(project)

        project_id = str(project.id)

        if file_path and os.path.exists(file_path):
            os.remove(file_path)

    except HTTPException:
        db.rollback()
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        _discard_stored(stored_key)
        raise

    except Exception as e:
        db.rollback()

        logger.exception("Upload failed")

        logger.error("Upload failed: %s", e)

        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        _discard_stored(stored_key)

        raise HTTPException(status_code=500, detail="Upload failed; nothing was charged")

    logger.info(f"Project {project_id} queued")

    return {
        "message": "Project created",
        "project_id": project_id,
        "pages": page_count,
        "credits_used": credits_required,
        "remaining_credits": new_balance,
        "batch_id": str(batch_id) if batch_id else None,
    }





PROJECT_STATUS_FILTERS = ("all", "active", "review", "delivered", "failed")
MAX_PROJECT_PAGE = 200


def _projects_scope(db: Session, user: User, assignee: str | None, q: str | None):
    """The caller's team projects, filtered by assignee and a search over file name, languages and batch name."""
    from sqlalchemy import or_

    from app.models.batch import Batch
    from app.models.team_member import TeamMember

    team = db.query(Team).filter(Team.owner_id == user.id).first()
    if not team:
        membership = db.query(TeamMember).filter(TeamMember.user_id == user.id).first()
        if membership:
            team = db.query(Team).filter(Team.id == membership.team_id).first()

    base = db.query(TranslationProject)
    if team:
        base = base.filter(TranslationProject.team_id == team.id)
    else:
        base = base.filter(TranslationProject.user_id == user.id)

    if assignee == "me":
        base = base.filter(TranslationProject.assignee_id == user.id)
    elif assignee == "unassigned":
        base = base.filter(TranslationProject.assignee_id.is_(None))
    elif assignee and assignee != "all":
        try:
            assignee_id = UUID(assignee)
        except ValueError:
            raise HTTPException(status_code=400, detail="assignee must be me, unassigned or a user id")
        base = base.filter(TranslationProject.assignee_id == assignee_id)

    term = (q or "").strip()[:200]
    if term:
        like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        batch_hit = (
            db.query(Batch.id)
            .filter(Batch.id == TranslationProject.batch_id, Batch.name.ilike(like, escape="\\"))
            .exists()
        )
        base = base.filter(or_(
            TranslationProject.file_name.ilike(like, escape="\\"),
            TranslationProject.source_language.ilike(like, escape="\\"),
            TranslationProject.target_language.ilike(like, escape="\\"),
            batch_hit,
        ))
    return base


def _status_condition(tab: str):
    """The Jobs page tabs as SQL. Delivered is a finished project not waiting on review."""
    from sqlalchemy import and_, func

    review = func.upper(func.coalesce(TranslationProject.review_status, "")) == "IN_REVIEW"
    if tab == "active":
        return TranslationProject.status.in_([ProjectStatus.PENDING, ProjectStatus.PROCESSING])
    if tab == "review":
        return and_(TranslationProject.status == ProjectStatus.COMPLETED, review)
    if tab == "delivered":
        return and_(TranslationProject.status == ProjectStatus.COMPLETED, ~review)
    if tab == "failed":
        return TranslationProject.status == ProjectStatus.FAILED
    return None


def _word_counts(db: Session, project_ids: list) -> dict[str, int]:
    """Source words per project, counted in the database instead of loading every segment."""
    from sqlalchemy import case, func

    if not project_ids:
        return {}
    text_ = func.btrim(TranslationSegment.source_text)
    words = case(
        (func.coalesce(text_, "") == "", 0),
        else_=func.coalesce(func.array_length(func.regexp_split_to_array(text_, r"\s+"), 1), 0),
    )
    rows = (
        db.query(TranslationSegment.project_id, func.coalesce(func.sum(words), 0))
        .filter(TranslationSegment.project_id.in_(project_ids))
        .group_by(TranslationSegment.project_id)
        .all()
    )
    return {str(pid): int(n) for pid, n in rows}


@router.get("/")
def list_projects(
    response: Response,
    assignee: str | None = None,
    status_filter: str = Query("all", alias="status"),
    q: str | None = None,
    limit: int = Query(50, ge=1, le=MAX_PROJECT_PAGE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One page of the team's projects, newest first; the X-Total-Count header has the number matching the filters.

    `assignee` is me, unassigned or a user id; `status` one of PROJECT_STATUS_FILTERS; `q` searches file name,
    languages and batch name.
    """
    tab = (status_filter or "all").lower()
    if tab not in PROJECT_STATUS_FILTERS:
        raise HTTPException(status_code=400, detail=f"status must be one of: {', '.join(PROJECT_STATUS_FILTERS)}")

    base = _projects_scope(db, current_user, assignee, q)
    condition = _status_condition(tab)
    if condition is not None:
        base = base.filter(condition)

    total = base.order_by(None).count()
    response.headers["X-Total-Count"] = str(total)
    projects = (
        base.order_by(TranslationProject.created_at.desc(), TranslationProject.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    related_ids = {p.assignee_id for p in projects if p.assignee_id}
    related_ids |= {p.user_id for p in projects if p.user_id}
    users_by_id = {}
    if related_ids:
        for u in db.query(User).filter(User.id.in_(related_ids)).all():
            users_by_id[str(u.id)] = u

    word_counts = _word_counts(db, [p.id for p in projects])

    from app.models.batch import Batch

    batch_ids = {p.batch_id for p in projects if p.batch_id}
    batch_names = dict(db.query(Batch.id, Batch.name).filter(Batch.id.in_(batch_ids)).all()) if batch_ids else {}

    result = []
    for p in projects:
        progress = job_progress.display_percent(p)

        a = users_by_id.get(str(p.assignee_id)) if p.assignee_id else None
        o = users_by_id.get(str(p.user_id)) if p.user_id else None

        result.append({
            "id": str(p.id),
            "filename": p.file_name,
            "status": p.status,
            "failure_reason": p.failure_reason,
            "failure_code": failure_code(p),



            "review_status": p.review_status or "DRAFT",
            "progress": progress,
            **job_progress.stage_fields(p),
            "source_lang": p.source_language,
            "target_lang": p.target_language,
            "mode": p.mode or MODE_TRANSLATE,
            "page_count": p.page_count,
            "words": word_counts.get(str(p.id), 0),
            "credits_used": p.credits_used,
            "created_at": p.created_at,
            "batch": {"id": str(p.batch_id), "name": batch_names.get(p.batch_id, "")} if p.batch_id else None,
            "assignee_id": str(p.assignee_id) if p.assignee_id else None,
            "assignee": (
                {
                    "id": str(a.id),
                    "email": a.email,
                    "full_name": a.full_name,
                }
                if a
                else None
            ),
            "owner": (
                {
                    "id": str(o.id),
                    "email": o.email,
                    "full_name": o.full_name,
                }
                if o
                else None
            ),
        })

    return result






@router.get("/summary")
def projects_summary(
    assignee: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """True totals for the Jobs tabs, the Dashboard KPIs and the sidebar count, whatever page the list is on."""
    from sqlalchemy import case, func, or_

    base = _projects_scope(db, current_user, assignee, q)

    def count(cond):
        return func.coalesce(func.sum(case((cond, 1), else_=0)), 0)

    active, review, delivered, failed = (_status_condition(t) for t in ("active", "review", "delivered", "failed"))
    # The Dashboard's "active" work: still translating or waiting on review.
    open_ = or_(active, review)
    row = base.with_entities(
        func.count(TranslationProject.id),
        count(active),
        count(review),
        count(delivered),
        count(failed),
        count(open_),
        func.coalesce(func.sum(case((open_, TranslationProject.page_count), else_=0)), 0),
        count(open_ & (TranslationProject.page_count > 0)),
        func.coalesce(func.sum(TranslationProject.credits_used), 0),
    ).order_by(None).one()
    pairs = (
        base.filter(open_)
        .with_entities(TranslationProject.source_language, TranslationProject.target_language)
        .filter(TranslationProject.source_language != "", TranslationProject.target_language != "")
        .distinct()
        .order_by(None)
        .count()
    )
    total, n_active, n_review, n_delivered, n_failed, n_open, open_pages, open_with_pages, credits = (int(x) for x in row)
    return {
        "total": total,
        "counts": {"active": n_active, "review": n_review, "delivered": n_delivered, "failed": n_failed},
        "open": {
            "projects": n_open,
            "pages": open_pages,
            "projects_with_pages": open_with_pages,
            "language_pairs": pairs,
        },
        "credits_used": credits,
    }


class _AssignPayload(BaseModel):
    assignee_id: str | None = None


def _send_assignment_email(to: str, **fields) -> None:
    from app.services import email_service

    try:
        subject, html, text = email_service.render_assignment_email(**fields)
        email_service.send_email(to=to, subject=subject, html=html, text_fallback=text)
    except Exception:
        logger.exception("Couldn't send the assignment email to %s", to)


def _queue_assignment_email(background_tasks: BackgroundTasks, project, assignee: User, assigner: User) -> None:
    from app.config import settings
    from app.services import email_service

    if not assignee.email:
        return
    if not email_service.is_configured():
        logger.warning("Project %s assigned but email is not configured (RESEND_API_KEY missing); no email sent", project.id)
        return
    background_tasks.add_task(
        _send_assignment_email,
        assignee.email,
        assigner=(assigner.full_name or "").strip() or assigner.email,
        file_name=project.file_name,
        source_language=project.source_language,
        target_language=project.target_language,
        page_count=project.page_count,
        status=email_service.project_status_label(project.status, project.review_status),
        link=f"{settings.FRONTEND_URL.rstrip('/')}/editor/{project.id}",
    )


def _notify_assignee(db: Session, project, assignee: User, assigner: User) -> None:
    from app.services import notifications

    who = (assigner.full_name or "").strip() or assigner.email
    pair = " → ".join(x for x in (project.source_language, project.target_language) if x)
    pages = f"{project.page_count} page{'s' if project.page_count != 1 else ''}" if project.page_count else ""
    notifications.notify(
        db, assignee.id, "assigned",
        f"{who} assigned you {project.file_name}",
        ", ".join(x for x in (pair, pages) if x),
        link=notifications.editor_link(project.id), project_id=project.id, team_id=project.team_id,
    )


@router.patch("/{project_id}/assign")
def assign_project(
    project_id: UUID,
    data: _AssignPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.team_member import TeamMember
    from app.models.team import Team

    project = (
        db.query(TranslationProject)
        .filter(TranslationProject.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")


    team = db.query(Team).filter(Team.id == project.team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    is_owner = team.owner_id == current_user.id
    is_member = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team.id, TeamMember.user_id == current_user.id)
        .first()
        is not None
    )
    if not (is_owner or is_member):
        raise HTTPException(status_code=403, detail="You can't assign this project")

    previous_assignee_id = project.assignee_id
    target = None
    if data.assignee_id is None:
        project.assignee_id = None
    else:

        try:
            target = db.query(User).filter(User.id == UUID(data.assignee_id)).first()
        except ValueError:
            target = None
        if not target:
            raise HTTPException(status_code=404, detail="Assignee not found")

        on_team = (
            target.id == team.owner_id
            or db.query(TeamMember)
            .filter(
                TeamMember.team_id == team.id, TeamMember.user_id == target.id
            )
            .first()
            is not None
        )
        if not on_team:
            raise HTTPException(
                status_code=400, detail="That user isn't on this team"
            )
        project.assignee_id = target.id

    newly_assigned = target is not None and target.id != previous_assignee_id and target.id != current_user.id
    if newly_assigned:
        _notify_assignee(db, project, target, current_user)

    db.commit()
    db.refresh(project)

    if newly_assigned:
        _queue_assignment_email(background_tasks, project, target, current_user)

    return {
        "project_id": str(project.id),
        "assignee_id": str(project.assignee_id) if project.assignee_id else None,
    }






@router.get("/{project_id}")
def get_project_status(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):


    project = get_user_project_or_404(db, project_id, current_user)

    progress = job_progress.display_percent(project)


    total = (
        db.query(TranslationSegment)
        .filter(TranslationSegment.project_id == project.id)
        .count()
    )
    translated = (
        db.query(TranslationSegment)
        .filter(
            TranslationSegment.project_id == project.id,
            TranslationSegment.translated_text.isnot(None),
            TranslationSegment.translated_text != "",
        )
        .count()
    )
    approved = (
        db.query(TranslationSegment)
        .filter(
            TranslationSegment.project_id == project.id,
            TranslationSegment.approved.is_(True),
        )
        .count()
    )


    tm_hits = (
        db.query(TranslationSegment.tm_pct)
        .filter(
            TranslationSegment.project_id == project.id,
            TranslationSegment.tm_pct.isnot(None),
        )
        .all()
    )
    tm_avg = (
        round(sum(int(r[0]) for r in tm_hits) / len(tm_hits)) if tm_hits else 0
    )


    assignee_payload = None
    if project.assignee_id:
        a = db.query(User).filter(User.id == project.assignee_id).first()
        if a:
            assignee_payload = {
                "id": str(a.id),
                "email": a.email,
                "full_name": a.full_name,
            }


    uploader_payload = None
    owner = db.query(User).filter(User.id == project.user_id).first()
    if owner:
        uploader_payload = {
            "id": str(owner.id),
            "email": owner.email,
            "full_name": owner.full_name,
        }

    return {
        "id": str(project.id),
        "status": project.status,
        "review_status": project.review_status or "DRAFT",
        "progress_percent": progress,
        **job_progress.stage_fields(project),
        "page_count": project.page_count,
        "retry_count": project.retry_count,
        "created_at": project.created_at,
        "file_name": project.file_name,
        "source_language": project.source_language,
        "target_language": project.target_language,
        "mode": project.mode or MODE_TRANSLATE,
        # PDF, IMAGE or DOCX once the worker has looked at the file; Regenerate only works for PDF and IMAGE.
        "source_kind": project.source_kind,
        "ai_instructions": project.ai_instructions,
        "stats": {
            "total_segments": total,
            "translated_segments": translated,
            "approved_segments": approved,
            "tm_average_pct": tm_avg,
        },
        "assignee": assignee_payload,
        "uploader": uploader_payload,
        "failure_reason": project.failure_reason,
        "failure_code": failure_code(project),
        "rebuild_status": project.rebuild_status,
        "rebuild_error": project.rebuild_error,
        "revision_count": project.revision_count or 0,
        "free_revisions_left": ai_actions.regenerations_left(project),
    }





REVIEW_STATUSES = {"DRAFT", "IN_REVIEW", "CERTIFIED"}
NOT_CERTIFIABLE = "An editable copy isn't a translation, so it can't be certified"


def refuse_dtp_certification(project) -> None:
    if is_dtp(project):
        raise HTTPException(status_code=409, detail=NOT_CERTIFIABLE)


class _ReviewStatusPayload(BaseModel):
    status: str


@router.patch("/{project_id}/review-status")
def update_review_status(
    project_id: UUID,
    data: _ReviewStatusPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    new_status = (data.status or "").strip().upper()
    if new_status not in REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid review status")



    project = get_user_project_or_404(db, project_id, current_user)
    if new_status == "CERTIFIED":
        refuse_dtp_certification(project)
        if project.status != ProjectStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="The translation must finish before it can be certified.")

    project.review_status = new_status
    db.commit()
    db.refresh(project)
    if new_status == "CERTIFIED":
        background_tasks.add_task(capture_template_in_background, project.id, current_user.id)
    return {"id": str(project.id), "review_status": project.review_status}






@router.post(
    "/{project_id}/certify",
    dependencies=[Depends(require_feature("certifications"))],
)
def certify_project(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):


    project = get_user_project_or_404(db, project_id, current_user)
    refuse_dtp_certification(project)

    if project.status != ProjectStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail="The translation must finish before it can be certified.",
        )

    project.review_status = "CERTIFIED"
    db.commit()
    db.refresh(project)
    background_tasks.add_task(capture_template_in_background, project.id, current_user.id)
    return {
        "id": str(project.id),
        "review_status": project.review_status,
        "certified_at": project.created_at.isoformat()
        if project.created_at
        else None,
    }















@router.get("/{project_id}/source-url")
def get_source_url(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, current_user)
    if not project.file_path:
        raise HTTPException(status_code=404, detail="Source file not available")


    url = generate_presigned_download_url(project.file_path, inline=True)


    fname = (project.file_name or "").lower()
    if fname.endswith(".pdf"):
        kind = "pdf"
    elif fname.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        kind = "image"
    else:
        kind = "other"
    return {"url": url, "kind": kind, "filename": project.file_name}








@router.get(
    "/{project_id}/rebuild-url",
    dependencies=[Depends(require_feature("download_translation"))],
)
def get_rebuild_url(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, current_user)
    if not project.output_file:



        return {"url": None, "kind": "none", "filename": None}


    url = generate_presigned_download_url(project.output_file, inline=True)
    name = (project.output_file or "").rsplit("/", 1)[-1].lower()
    if name.endswith(".pdf"):
        kind = "pdf"
    elif name.endswith((".png", ".jpg", ".jpeg", ".webp")):
        kind = "image"
    elif name.endswith(".docx"):
        kind = "docx"
    else:
        kind = "other"
    return {"url": url, "kind": kind, "filename": name}


@router.get(
    "/{project_id}/download",
    dependencies=[Depends(require_feature("download_translation"))],
)
def download_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):


    project = get_user_project_or_404(db, project_id, current_user)

    if project.status != ProjectStatus.COMPLETED:
        raise HTTPException(
            status_code=400, detail="Project processing not completed yet"
        )

    if not project.output_file:
        raise HTTPException(status_code=404, detail="Output file not available")

    download_url = generate_presigned_download_url(project.output_file)
    return {"download_url": download_url}












class _PatchProjectPayload(BaseModel):
    file_name: Optional[str] = None
    certification_template_id: Optional[str] = None
    ai_instructions: Optional[str] = None


@router.patch("/{project_id}")
def update_project(
    project_id: UUID,
    data: _PatchProjectPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partial update: rename, cert template, instructions for the AI. Only the fields the caller sends are touched."""
    project = get_user_project_or_404(db, project_id, current_user)

    if data.file_name is not None:
        new_name = clean_file_name(data.file_name)
        if not new_name:
            raise HTTPException(
                status_code=400, detail="file_name can't be empty"
            )

        original_ext = ""
        if project.file_name and "." in project.file_name:
            original_ext = "." + project.file_name.rsplit(".", 1)[-1]
        if original_ext and not new_name.lower().endswith(original_ext.lower()):
            new_name = new_name + original_ext
        project.file_name = clean_file_name(new_name)

    if data.certification_template_id is not None:
        refuse_dtp_certification(project)
        project.certification_standard = data.certification_template_id == "standard"
        if data.certification_template_id in ("", "standard"):
            project.certification_template_id = None
        else:
            try:
                project.certification_template_id = UUID(
                    data.certification_template_id
                )
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid certification_template_id",
                )

    if "ai_instructions" in data.model_fields_set:
        project.ai_instructions = _clean_instructions(data.ai_instructions)

    db.commit()
    db.refresh(project)
    return {
        "id": str(project.id),
        "file_name": project.file_name,
        "ai_instructions": project.ai_instructions,
        "certification_template_id": (
            str(project.certification_template_id)
            if project.certification_template_id
            else "standard" if project.certification_standard else None
        ),
    }













from fastapi.responses import Response as _FastResponse  # noqa: E402


def _project_preview_team_check(db, project_id, user):
    """Return the project if the user can view it, else 404."""
    return get_user_project_or_404(db, project_id, user)














def _resolve_rebuild_docx_bytes(
    project, segments, *, preview_only: bool = True
) -> bytes:
    from io import BytesIO


    edited_html = getattr(project, "edited_html", None)
    if edited_html and edited_html.strip():
        try:
            from htmldocx import HtmlToDocx  # type: ignore
            from docx import Document

            parser = HtmlToDocx()
            doc = Document()
            parser.add_html_to_document(_sanitize_edited_html(edited_html), doc)
            buf = BytesIO()
            doc.save(buf)
            return buf.getvalue()
        except Exception:
            logger.exception(
                "HTML→DOCX conversion failed — falling back to "
                "authored DOCX or segment renderer"
            )


    authored_key = getattr(project, "authored_docx_s3_key", None)
    if authored_key:
        try:
            import tempfile
            from app.services.s3_service import download_file_from_s3

            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
            tmp.close()
            from pathlib import Path as _P

            download_file_from_s3(authored_key, _P(tmp.name))
            with open(tmp.name, "rb") as f:
                data = f.read()
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
            return data
        except Exception:
            logger.exception(
                "Authored DOCX download failed — falling back to "
                "segment renderer"
            )


    from app.services.export_service import _build_layout_docx_live

    docx_buf = _build_layout_docx_live(
        segments, project, preview_only=preview_only
    )
    if docx_buf is None and (project.source_kind or "").upper() == "DOCX" and project.output_file:
        # A Word upload is translated in place; the worker's rebuilt copy is the document.
        from app.services.document_editor import _download

        try:
            return _download(project.output_file)
        except Exception:
            logger.exception("Rebuilt DOCX download failed (project=%s)", project.id)
    if docx_buf is None:
        raise HTTPException(
            status_code=500, detail="Couldn't build rebuild DOCX"
        )
    try:
        return docx_buf.getvalue()
    except AttributeError:
        return docx_buf


@router.get("/{project_id}/preview/source")
def preview_source(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stream the source file inline. For PDFs the browser's native
    viewer renders within ~1s. For images the browser displays them
    immediately. Anything else (DOCX, etc.) gets converted to PDF
    via LibreOffice first so the iframe always renders something.
    """
    import requests as _req
    import tempfile
    from app.services.s3_service import generate_presigned_download_url
    from app.services.export_service import _convert_docx_to_pdf

    project = _project_preview_team_check(db, project_id, user)
    if not project.file_path:
        raise HTTPException(status_code=404, detail="Source not available")

    url = generate_presigned_download_url(project.file_path)
    r = _req.get(url, timeout=20)
    if not r.ok:
        raise HTTPException(
            status_code=502, detail="Couldn't fetch source from storage"
        )
    bytes_ = r.content
    fname = (project.file_name or project.file_path).lower()

    if fname.endswith(".pdf"):
        media = "application/pdf"
    elif fname.endswith((".png", ".jpg", ".jpeg", ".webp")):




        try:
            from io import BytesIO as _BIO
            from PIL import Image
            img = Image.open(_BIO(bytes_))
            buf = _BIO()
            img.convert("RGB").save(buf, format="PDF", resolution=150)
            bytes_ = buf.getvalue()
            media = "application/pdf"
        except Exception as e:
            logger.warning(
                "Source image → PDF conversion failed: %s", e
            )
            if fname.endswith(".png"):
                media = "image/png"
            elif fname.endswith(".webp"):
                media = "image/webp"
            else:
                media = "image/jpeg"
    elif fname.endswith(".docx"):




        with tempfile.TemporaryDirectory():
            converted = _convert_docx_to_pdf(bytes_)
        if converted:
            bytes_ = converted
            media = "application/pdf"
        else:
            media = (
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            )
    else:
        media = "application/octet-stream"

    return _FastResponse(
        content=bytes_,
        media_type=media,
        headers={
            "Content-Disposition": "inline",



            "Cache-Control": "private, max-age=300",
        },
    )


class _EditedHtmlPayload(BaseModel):
    html: str


@router.patch("/{project_id}/edited-html")
def save_edited_html(
    project_id: UUID,
    data: _EditedHtmlPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, current_user)

    raw = data.html or ""
    if len(raw) > 2_000_000:
        raise HTTPException(
            status_code=413,
            detail="Edited HTML too large (>2MB)",
        )
    project.edited_html = _sanitize_edited_html(raw).strip() or None
    db.commit()
    return {"ok": True, "size": len(project.edited_html or "")}


@router.delete("/{project_id}/edited-html")
def clear_edited_html(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Drop the WYSIWYG override and fall back to the authored DOCX /
    segment-driven rebuild on the next preview/export."""
    project = get_user_project_or_404(db, project_id, current_user)
    project.edited_html = None
    db.commit()
    return {"ok": True}



def _project_for_regenerate(db: Session, project_id: UUID, user: User) -> TranslationProject:
    """The project row-locked, so two clicks can't both pass the regenerate limit or the running-rebuild check."""
    get_user_project_or_404(db, project_id, user)
    project = (
        db.query(TranslationProject)
        .filter(TranslationProject.id == project_id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    if project.status != ProjectStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="The translation must finish before it can be regenerated")
    return project


@router.post(
    "/{project_id}/rebuild-with-claude",
    dependencies=[Depends(user_rate_limit("rebuild", max_requests=10, per_seconds=3600))],
)
def rebuild_with_claude(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Queue a fresh Claude-authored layout rebuild; poll GET /projects/{id} for rebuild_status."""
    project = _project_for_regenerate(db, project_id, current_user)
    if (project.source_kind or "").upper() not in ai_actions.REGENERABLE_KINDS:
        raise HTTPException(status_code=400, detail="Regenerating only works for PDF and image source projects")

    ai_actions.use_regeneration(project)
    ai_actions.claim_rebuild(project)
    db.commit()
    background_tasks.add_task(
        ai_usage.bind(ai_actions.run_rebuild, action="regenerate", project_id=project.id, team_id=project.team_id, user_id=current_user.id),
        str(project.id),
        None,
    )
    return {
        "ok": True,
        "rebuild_status": "rebuild_in_progress",
        "revision_count": project.revision_count,
        "regenerations_left": ai_actions.regenerations_left(project),
        "charged": False,
    }


class _RerunProjectPayload(BaseModel):
    model: Optional[str] = None


@router.post("/{project_id}/rerun")
def rerun_project(
    project_id: UUID,
    data: _RerunProjectPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-process the whole project through the queue; charged like a new upload."""
    from app.models.credit import CreditTransaction

    project = get_user_project_or_404(db, project_id, current_user)
    if project.status in (ProjectStatus.PENDING, ProjectStatus.PROCESSING):
        raise HTTPException(status_code=409, detail="This project is already being processed")

    new_model = (data.model or "").strip()
    if new_model:
        _validate_model_key(new_model)
        project.model = new_model

    attempt = (
        db.query(CreditTransaction)
        .filter(CreditTransaction.reference_id.like(f"{project.id}:rerun:%"))
        .count()
        + 1
    )
    ai_actions.charge(db, project, current_user, job_charge_reference(project.id, attempt))
    project.status = ProjectStatus.PENDING
    project.progress_percent = 0
    project.progress_stage = None
    project.progress_detail = None
    project.stage_started_at = None
    project.failure_reason = None
    enqueue_job(db, project.id, project.file_path)
    db.commit()
    return {"status": project.status, "model_used": project.model}


@router.delete("/{project_id}")
def delete_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete a project and everything attached to it.

    We explicitly remove dependent rows in the right order so the
    delete works regardless of whether each FK has ON DELETE CASCADE
    set in the schema. Previously the SQLAlchemy `db.delete(project)`
    failed silently when any reference (segment comments, TM entries,
    job rows on older schemas, etc) blocked the cascade.
    """
    from sqlalchemy import text
    from app.models.translation_segment import TranslationSegment
    from app.models.segment_comment import SegmentComment


    project = get_user_project_or_404(db, project_id, current_user)
    if not can_manage_project(db, project, current_user):
        raise HTTPException(status_code=403, detail="Only the uploader or a team admin can delete this project")
    pid = str(project.id)
    from app.models.delivery_link import DeliveryLink

    stored_keys = [project.file_path, project.output_file, project.authored_docx_s3_key]
    for file_key, preview_keys in db.query(DeliveryLink.file_key, DeliveryLink.preview_keys).filter(
        DeliveryLink.project_id == project.id
    ):
        stored_keys += [file_key, *(preview_keys or [])]
    # Every saved edit is its own file; they go with the project too.
    from app.models.document_version import DocumentVersion

    stored_keys += [
        k for (k,) in db.query(DocumentVersion.s3_key).filter(DocumentVersion.project_id == project.id).all() if k
    ]

    try:

        segment_ids = [
            row[0]
            for row in db.query(TranslationSegment.id)
            .filter(TranslationSegment.project_id == project.id)
            .all()
        ]
        if segment_ids:
            db.query(SegmentComment).filter(
                SegmentComment.segment_id.in_(segment_ids)
            ).delete(synchronize_session=False)


        db.query(TranslationSegment).filter(
            TranslationSegment.project_id == project.id
        ).delete(synchronize_session=False)









        sp = db.begin_nested()
        try:
            db.execute(
                text(
                    "DELETE FROM translation_memory WHERE project_id = :pid"
                ),
                {"pid": pid},
            )
            sp.commit()
        except Exception:
            sp.rollback()




        sp = db.begin_nested()
        try:
            db.execute(
                text(
                    "DELETE FROM translation_jobs WHERE project_id = :pid"
                ),
                {"pid": pid},
            )
            sp.commit()
        except Exception:
            sp.rollback()


        db.delete(project)
        db.commit()
    except Exception as e:
        logger.exception("Project delete failed: %s", e)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Couldn't delete project",
        )

    from app.services.s3_service import delete_objects_from_s3

    delete_objects_from_s3(stored_keys)
    return {"message": "Project deleted successfully"}
