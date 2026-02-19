from app.database import SessionLocal
from app.models.team import Team
from app.services.subscription_service import grant_monthly_credits


def run():
    db = SessionLocal()

    team = db.query(Team).first()

    new_balance = grant_monthly_credits(db, team.id)

    print("New balance after subscription:", new_balance)

    db.close()


if __name__ == "__main__":
    run()
