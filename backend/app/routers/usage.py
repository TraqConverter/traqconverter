"""AI edit allowance per document and the staff-only AI cost report."""
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.dependencies.tenant import get_user_project_or_404
from app.models.ai_usage import AiUsage
from app.models.credit import CreditTransaction, CreditWallet
from app.models.project import TranslationProject
from app.models.team import Team
from app.models.user import User
from app.services import ai_allowance
from app.services.ai_actions import is_staff

router = APIRouter(tags=["AI usage"])

TOP_PROJECTS = 20


@router.get("/projects/{project_id}/ai-allowance")
def get_ai_allowance(
    project_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = get_user_project_or_404(db, project_id, user)
    return ai_allowance.allowance(db, project)


def _usd(value) -> float:
    return float(round(Decimal(value or 0), 4))


def _revenue_usd(credits: int) -> float:
    return credits * settings.CREDIT_PRICE_CENTS / 100


def _credits_by_team(db: Session, since: datetime) -> dict:
    """Credits consumed per team in the period: usage minus refunds of it."""
    rows = (
        db.query(
            CreditWallet.team_id,
            CreditTransaction.type,
            func.coalesce(func.sum(CreditTransaction.amount), 0),
        )
        .join(CreditWallet, CreditWallet.id == CreditTransaction.wallet_id)
        .filter(CreditTransaction.created_at >= since, CreditTransaction.type.in_(("USAGE", "REFUND")))
        .group_by(CreditWallet.team_id, CreditTransaction.type)
        .all()
    )
    credits: dict = {}
    for team_id, _type, amount in rows:
        credits[team_id] = credits.get(team_id, 0) - int(amount)
    return credits


@router.get("/admin/ai-usage")
def ai_usage_report(
    days: int = Query(30, ge=1, le=366),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not is_staff(user):
        raise HTTPException(status_code=403, detail="Not available")
    since = datetime.utcnow() - timedelta(days=days)
    in_period = AiUsage.created_at >= since
    usd = func.coalesce(func.sum(AiUsage.usd), 0)
    calls = func.count(AiUsage.id)

    total_usd, total_calls, input_tokens, output_tokens, cache_read, cache_write = (
        db.query(
            usd,
            calls,
            func.coalesce(func.sum(AiUsage.input_tokens), 0),
            func.coalesce(func.sum(AiUsage.output_tokens), 0),
            func.coalesce(func.sum(AiUsage.cache_read_tokens), 0),
            func.coalesce(func.sum(AiUsage.cache_write_tokens), 0),
        )
        .filter(in_period)
        .one()
    )

    by_action = [
        {"action": action, "usd": _usd(cost), "calls": n}
        for action, cost, n in db.query(AiUsage.action, usd, calls)
        .filter(in_period)
        .group_by(AiUsage.action)
        .order_by(usd.desc())
        .all()
    ]

    team_cost = {
        team_id: (cost, n)
        for team_id, cost, n in db.query(AiUsage.team_id, usd, calls).filter(in_period).group_by(AiUsage.team_id).all()
    }
    team_credits = _credits_by_team(db, since)
    team_ids = [t for t in set(team_cost) | set(team_credits) if t is not None]
    names = dict(db.query(Team.id, Team.name).filter(Team.id.in_(team_ids)).all()) if team_ids else {}
    by_team = []
    for team_id in set(team_cost) | set(team_credits):
        cost, n = team_cost.get(team_id, (0, 0))
        credits = team_credits.get(team_id, 0)
        revenue = _revenue_usd(credits)
        by_team.append({
            "team_id": str(team_id) if team_id else None,
            "name": names.get(team_id) or ("Unattributed" if team_id is None else "Deleted team"),
            "usd": _usd(cost),
            "calls": n,
            "credits": credits,
            "revenue_usd": round(revenue, 2),
            "margin_usd": round(revenue - _usd(cost), 2),
        })
    by_team.sort(key=lambda t: t["usd"], reverse=True)

    top_projects = [
        {
            "project_id": str(project_id),
            "file_name": file_name,
            "team_name": team_name,
            "page_count": page_count,
            "usd": _usd(cost),
            "calls": n,
        }
        for project_id, file_name, team_name, page_count, cost, n in db.query(
            AiUsage.project_id,
            TranslationProject.file_name,
            Team.name,
            TranslationProject.page_count,
            usd,
            calls,
        )
        .join(TranslationProject, TranslationProject.id == AiUsage.project_id)
        .outerjoin(Team, Team.id == TranslationProject.team_id)
        .filter(in_period)
        .group_by(AiUsage.project_id, TranslationProject.file_name, Team.name, TranslationProject.page_count)
        .order_by(usd.desc())
        .limit(TOP_PROJECTS)
        .all()
    ]

    total_credits = sum(team_credits.values())
    revenue = _revenue_usd(total_credits)
    return {
        "days": days,
        "since": since.isoformat(),
        "credit_price_cents": settings.CREDIT_PRICE_CENTS,
        "totals": {
            "usd": _usd(total_usd),
            "calls": total_calls,
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "cache_read_tokens": int(cache_read),
            "cache_write_tokens": int(cache_write),
            "credits": total_credits,
            "revenue_usd": round(revenue, 2),
            "margin_usd": round(revenue - _usd(total_usd), 2),
        },
        "by_action": by_action,
        "by_team": by_team,
        "top_projects": top_projects,
    }
