from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    app_name: str
    environment: str
    database_url: str
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int

    # --- Stripe ---
    stripe_secret_key: str
    stripe_webhook_secret: str

    model_config = ConfigDict(
        env_file=".env",
        extra="ignore"  # Ignore unexpected env vars safely
    )


settings = Settings()