from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    # Database - explicitly check env var first
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./clawdir.db")
    
    # Auth
    secret_key: str = "change-me-in-production"
    api_key_prefix: str = "claw_"
    
    # App
    app_name: str = "ClawDir"
    debug: bool = False
    
    # Trust defaults
    default_trust_score: float = 0.0
    max_trust_score: float = 10.0
    min_trust_score: float = 0.0
    
    # Stripe
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_pro: str = ""  # Stripe Price ID for Pro tier
    stripe_price_team: str = ""  # Stripe Price ID for Team tier
    
    # URLs
    frontend_url: str = "https://www.clawdir.xyz"
    
    # Error tracking
    sentry_dsn: str = ""  # Set to enable Sentry
    
    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
