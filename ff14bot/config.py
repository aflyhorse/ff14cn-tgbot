from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


# Load .env if present (silent)
load_dotenv()


def _default_db_url() -> str:
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{data_dir.joinpath('bot.db').resolve()}"


@dataclass
class Settings:
    telegram_token: str
    database_url: str
    source_url: str = "https://actff1.web.sdo.com/Project/20181018ffactive/index.html"


def load_settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    db_url = os.getenv("DATABASE_URL", _default_db_url())
    return Settings(telegram_token=token, database_url=db_url)
