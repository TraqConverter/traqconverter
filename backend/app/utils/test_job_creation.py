from app.database import SessionLocal
from app.services.job_service import create_translation_job
from app.models.team import Team
from app.models.user import User


def run():
    db = SessionLocal()

    team = db.query(Team).first()
    user = db.query(User).first()

    job = create_translation_job(
        db=db,
        team_id=team.id,
        user_id=user.id,
        source_language="en",
        target_language="fr",
        page_count=2
    )

    print("Job created:", job.id)
    print("Credits used:", job.credits_used)

    db.close()


if __name__ == "__main__":
    run()
