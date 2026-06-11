from dataclasses import dataclass
from functools import lru_cache
import os

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    google_cloud_project: str | None
    firestore_database: str | None
    webhook_secret: str
    port: int


@lru_cache
def get_settings() -> Settings:
    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT") or None,
        firestore_database=os.getenv("FIRESTORE_DATABASE") or None,
        webhook_secret=os.getenv("WEBHOOK_SECRET", ""),
        port=int(os.getenv("PORT", "8080")),
    )
