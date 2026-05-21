from pydantic_settings import BaseSettings
from pydantic import ConfigDict, field_validator
from typing import List, Optional


class Settings(BaseSettings):

    # --- App ---
    app_name: str
    environment: str
    database_url: str
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int

    # --- CORS (audit medium fix) ---
    # Comma-separated list of allowed origins for the frontend. Defaults
    # to local dev. Set CORS_ORIGINS in production to your real frontend
    # domain(s). Star ("*") falls back to development behaviour and is
    # NOT permitted with credentials.
    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> List[str]:
        return [
            o.strip()
            for o in self.CORS_ORIGINS.split(",")
            if o.strip()
        ]

    # --- OpenAI ---
    OPENAI_API_KEY: str

    # --- Anthropic / Claude Vision (optional) ---
    # When set, image documents (passports, IDs, scans) are OCR'd with
    # Claude Vision instead of pytesseract — much better on stylised
    # fonts, low-contrast scans, holograms, and photographic backgrounds.
    # Leave empty to keep the tesseract pipeline.
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_VISION_MODEL: str = "claude-sonnet-4-6"

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

    # Optional company logo / header used on the certification page of
    # every exported translation. Should be an absolute path to a PNG
    # or JPG on the server's filesystem. Leave unset to skip the logo.
    COMPANY_LOGO_PATH: Optional[str] = None

    # NEW: CREDIT PRICING
    CREDIT_PRICE_CENTS: int = 100

    # NEW: CREDIT PACK PRICE IDs (one-time purchases from Stripe dashboard)
    STRIPE_PRICE_CREDITS_10: Optional[str] = None
    STRIPE_PRICE_CREDITS_25: Optional[str] = None
    STRIPE_PRICE_CREDITS_50: Optional[str] = None

    # --- Observability (optional; if set, Sentry init runs at startup) ---
    SENTRY_DSN: Optional[str] = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1

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