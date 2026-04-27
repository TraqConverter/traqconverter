from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional


class Settings(BaseSettings):

    # --- App ---
    app_name: str
    environment: str
    database_url: str
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int

    # --- OpenAI ---
    OPENAI_API_KEY: str

    # --- Stripe ---
    stripe_secret_key: str
    stripe_publishable_key: str
    stripe_webhook_secret: str

    # NEW: STRIPE PRICING (REQUIRED)
    STRIPE_PRICE_PRO: str
    STRIPE_PRICE_BASIC: Optional[str] = None

    # NEW: STRIPE URLS
    STRIPE_SUCCESS_URL: str = "http://localhost:3000/success"
    STRIPE_CANCEL_URL: str = "http://localhost:3000/cancel"

    # NEW: CREDIT PRICING
    CREDIT_PRICE_CENTS: int = 100

    # --- AWS (IAM compatible) ---
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"

    # --- Storage ---
    S3_BUCKET_NAME: str

    # --- Queue ---
    SQS_QUEUE_URL: str

    model_config = ConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()