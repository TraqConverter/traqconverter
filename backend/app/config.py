from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    # --- App ---
    app_name: str
    environment: str
    database_url: str
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int

    # --- Stripe ---
    stripe_secret_key: str
    stripe_webhook_secret: str

    # --- AWS ---
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
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