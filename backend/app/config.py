from pydantic_settings import BaseSettings
from pydantic import ConfigDict, field_validator
from typing import List, Literal, Optional


class Settings(BaseSettings):


    app_name: str
    environment: str
    database_url: str
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int






    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> List[str]:
        return [
            o.strip()
            for o in self.CORS_ORIGINS.split(",")
            if o.strip()
        ]


    OPENAI_API_KEY: str






    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_VISION_MODEL: str = "claude-sonnet-4-6"
    # In-app Help chat.
    SUPPORT_CHAT_MODEL: str = "claude-sonnet-5"
    SUPPORT_CHAT_MAX_TOKENS: int = 1024


    stripe_secret_key: str
    stripe_publishable_key: str
    stripe_webhook_secret: str


    STRIPE_PRICE_PRO: str
    STRIPE_PRICE_BASIC: Optional[str] = None
    STRIPE_PRICE_STUDIO: Optional[str] = None
    STRIPE_PRICE_AGENCY: Optional[str] = None
    # Billing portal configuration (bpc_...) printed by scripts/stripe_setup.py; unset uses Stripe's default.
    STRIPE_PORTAL_CONFIGURATION: Optional[str] = None
    # Stripe Tax at checkout (automatic_tax + tax ID collection). Off: the seller is not VAT-registered.
    STRIPE_AUTOMATIC_TAX: bool = False

    # Connect: signing secret of the webhook endpoint that listens to events on connected accounts.
    STRIPE_CONNECT_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_CONNECT_DEFAULT_COUNTRY: str = "IT"
    # "v2": connected accounts via Accounts v2 (/v2/core/accounts), what the platform account is set up for. "v1": /v1/accounts.
    STRIPE_CONNECT_ACCOUNTS_API: Literal["v1", "v2"] = "v2"
    STRIPE_V2_API_VERSION: str = "2026-09-30.endive"
    # Our cut of each protected-link payment, in percent; 0 means no application fee at all.
    PLATFORM_FEE_PERCENT: float = 0


    STRIPE_SUCCESS_URL: str = "http://localhost:3000/success"
    STRIPE_CANCEL_URL: str = "http://localhost:3000/cancel"




    COMPANY_LOGO_PATH: Optional[str] = None





    RESEND_API_KEY: Optional[str] = None



    RESEND_FROM_EMAIL: Optional[str] = (
        "OnlineDocTranslator <notifications@onlinedoctranslator.ai>"
    )


    FRONTEND_URL: str = "http://localhost:3000"


    CREDIT_PRICE_CENTS: int = 100

    # Ask AI: edits included per page of a document, then 1 credit per this many more.
    AI_EDITS_PER_PAGE: int = 5
    AI_EDITS_PER_EXTRA_CREDIT: int = 5
    # Regenerate: the first N per document are free, later ones cost one credit per page, up to the cap.
    REGENERATE_FREE_PER_PROJECT: int = 1
    REGENERATE_LIMIT_PER_PROJECT: int = 3

    # A project's files and rows are deleted this many days after its translation last completed; 0 turns it off.
    DOCUMENT_RETENTION_DAYS: int = 90


    STRIPE_PRICE_CREDITS_10: Optional[str] = None
    STRIPE_PRICE_CREDITS_25: Optional[str] = None
    STRIPE_PRICE_CREDITS_50: Optional[str] = None


    SENTRY_DSN: Optional[str] = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1





    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"
    SQS_QUEUE_URL: Optional[str] = None



    S3_BUCKET_NAME: str





    SUPABASE_S3_ENDPOINT: Optional[str] = None
    SUPABASE_S3_ACCESS_KEY: Optional[str] = None
    SUPABASE_S3_SECRET_KEY: Optional[str] = None
    SUPABASE_S3_REGION: Optional[str] = None

    model_config = ConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()