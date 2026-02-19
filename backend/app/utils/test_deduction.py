from app.database import SessionLocal
from app.services.credit_service import deduct_credits
from app.models.team import Team


def run():
    db = SessionLocal()

    team = db.query(Team).first()

    new_balance = deduct_credits(db, team.id, 3)

    print("New balance:", new_balance)

    db.close()


if __name__ == "__main__":
    run()
