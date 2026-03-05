from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):

    # --------------------------------
    # App
    # --------------------------------
    app_name: str = "TraqConverter"
    environment: str = "development"

    # --------------------------------
    # Database
    # --------------------------------
    database_url: str

    # --------------------------------
    # Security
    # --------------------------------
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # --------------------------------
    # Stripe
    # --------------------------------
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None

    # --------------------------------
    # AWS
    # --------------------------------
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    AWS_REGION: str = "us-east-1"

    # --------------------------------
    # Storage
    # --------------------------------
    S3_BUCKET_NAME: str

    # --------------------------------
    # Queue
    # --------------------------------
    SQS_QUEUE_URL: str

    # --------------------------------
    # OpenAI
    # --------------------------------
    openai_api_key: str | None = None

    model_config = ConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()