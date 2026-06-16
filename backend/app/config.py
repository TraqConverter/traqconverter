from pydantic_settings import BaseSettings
from pydantic import ConfigDict, field_validator
from typing import List, Optional


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


    stripe_secret_key: str
    stripe_publishable_key: str
    stripe_webhook_secret: str


    STRIPE_PRICE_PRO: str
    STRIPE_PRICE_BASIC: Optional[str] = None


    STRIPE_SUCCESS_URL: str = "http://localhost:3000/success"
    STRIPE_CANCEL_URL: str = "http://localhost:3000/cancel"




    COMPANY_LOGO_PATH: Optional[str] = None





    RESEND_API_KEY: Optional[str] = None



    RESEND_FROM_EMAIL: Optional[str] = (
        "TraqConverter <notifications@onlinedoctranslator.ai>"
    )


    FRONTEND_URL: str = "http://localhost:3000"


    CREDIT_PRICE_CENTS: int = 100


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