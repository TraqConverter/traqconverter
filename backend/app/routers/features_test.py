from fastapi import APIRouter, Depends
from app.dependencies.feature_guard import require_feature

router = APIRouter(prefix="/features", tags=["Feature Tests"])


@router.post("/team-invite")
def invite_team_member(
    allowed: bool = Depends(require_feature("team_collaboration"))
):
    return {"message": "Team collaboration feature accessed"}


@router.post("/terminology")
def add_term(
    allowed: bool = Depends(require_feature("terminology_memory"))
):
    return {"message": "Terminology memory feature accessed"}


@router.post("/glossary")
def create_glossary(
    allowed: bool = Depends(require_feature("glossaries"))
):
    return {"message": "Glossary feature accessed"}