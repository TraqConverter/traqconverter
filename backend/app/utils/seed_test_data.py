import uuid
from app.database import SessionLocal
from app.models.user import User
from app.models.team import Team
from app.models.credit import CreditWallet


def run():
    db = SessionLocal()

    # Create test user
    user = User(
        email="admin@test.com",
        password_hash="hashedpassword",
        full_name="Admin User"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id

    # Create team
    team = Team(
        name="Test Team",
        owner_id=user_id
    )
    db.add(team)
    db.commit()
    db.refresh(team)
    team_id = team.id

    # Create wallet with 10 credits
    wallet = CreditWallet(
        team_id=team_id,
        balance=10,
        subscription_credits=30
    )
    db.add(wallet)
    db.commit()

    print("Seeded successfully")
    print("User ID:", user_id)
    print("Team ID:", team_id)

    db.close()


if __name__ == "__main__":
    run()
