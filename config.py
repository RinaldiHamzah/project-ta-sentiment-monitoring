# config.py
import os
from dotenv import load_dotenv
load_dotenv()

def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = env_int("APP_PORT", 5000)
# Database
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = env_int("DB_PORT", 3306)
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "monitoring_review")
# External API
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "").strip()  # wajib untuk scraping
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()  # opsional
# Runtime
MIN_SCRAPE_INTERVAL_SEC = env_int("MIN_SCRAPE_INTERVAL_SEC", 30)
DATA_DIR = os.getenv("DATA_DIR", ".")