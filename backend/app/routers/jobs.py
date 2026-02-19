from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.dependencies import get_current_user
from app.models.user import User
from app.models.team import Team
from app.models.credit import CreditWallet
from app.schemas.job import JobCreate, JobResponse
from app.services.job_service import create_translation_job


# ✅ DEFINE ROUTER FIRST
router = APIRouter(prefix="/jobs", tags=["jobs"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/", response_model=JobResponse)
def create_job(
    job_data: JobCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    team = db.query(Team).filter(Team.owner_id == current_user.id).first()

    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    wallet = db.query(CreditWallet).filter(CreditWallet.team_id == team.id).first()

    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    now = datetime.utcnow()

    # 🔒 Auto-expire subscription if needed
    if wallet.subscription_expires_at and wallet.subscription_expires_at < now:
        wallet.subscription_status = "EXPIRED"
        db.commit()

    # 🔒 Block only if expired AND no credits
    if wallet.subscription_status != "ACTIVE" and wallet.balance <= 0:
        raise HTTPException(
            status_code=403,
            detail="Subscription expired and no credits available"
        )

    job = create_translation_job(
        db=db,
        team_id=team.id,
        user_id=current_user.id,
        source_language=job_data.source_language,
        target_language=job_data.target_language,
        page_count=job_data.page_count,
    )

    return JobResponse(
        id=str(job.id),
        source_language=job.source_language,
        target_language=job.target_language,
        page_count=job.page_count,
        credits_used=job.credits_used,
        status=job.status,
    )
