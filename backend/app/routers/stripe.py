from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
import stripe

from app.database import get_db
from app.models.user import User
from app.config import settings

router = APIRouter(prefix="/stripe", tags=["Stripe"])

stripe.api_key = settings.stripe_secret_key
print("Stripe key being used:", stripe.api_key)


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.stripe_webhook_secret
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    event_type = event["type"]
    print("Received event:", event_type)

    # ---------------------------------------
    # 1️⃣ Store customer on checkout
    # ---------------------------------------
    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata", {})
        user_id = metadata.get("user_id")

        if not user_id:
            print("No user_id in metadata")
            return {"status": "ignored"}

        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            print("User not found")
            return {"status": "ignored"}

        user.stripe_customer_id = session.get("customer")
        db.commit()

        print(f"Stored Stripe customer ID for {user.email}")

    # ---------------------------------------
    # 2️⃣ Activate / Renew on Invoice Paid
    # ---------------------------------------
    if event_type in ["invoice.paid", "invoice.payment_succeeded"]:
        invoice = event["data"]["object"]
        customer_id = invoice.get("customer")
        subscription_id = invoice.get("subscription")

        print("Invoice event triggered")
        print("Customer ID:", customer_id)

        if not customer_id:
            return {"status": "ignored"}

        # Fetch Stripe customer to get email
        stripe_customer = stripe.Customer.retrieve(customer_id)
        customer_email = stripe_customer.get("email")

        print("Stripe customer email:", customer_email)

        if not customer_email:
            return {"status": "ignored"}

        user = db.query(User).filter(
            User.email == customer_email
        ).first()

        if not user:
            print("No user found for email")
            return {"status": "ignored"}

        print("Before update:", user.subscription_plan)

        user.subscription_status = "ACTIVE"
        user.subscription_plan = "PRO"
        user.stripe_customer_id = customer_id
        user.stripe_subscription_id = subscription_id
        user.monthly_credits = 39

        db.commit()
        db.refresh(user)

        print("After update:", user.subscription_plan)
        print(f"User {user.email} upgraded to PRO.")

    # ---------------------------------------
    # 3️⃣ Handle Subscription Cancellation
    # ---------------------------------------
    if event_type == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")

        user = db.query(User).filter(
            User.stripe_customer_id == customer_id
        ).first()

        if user:
            user.subscription_status = "INACTIVE"
            user.subscription_plan = "BASIC"
            user.stripe_subscription_id = None

            db.commit()
            print(f"User {user.email} downgraded to BASIC.")

    return {"status": "success"}