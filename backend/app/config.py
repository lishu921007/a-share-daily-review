from pathlib import Path
from dotenv import load_dotenv
import os

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DATA_ROOT = PROJECT_ROOT / "data"
load_dotenv(BACKEND_ROOT / ".env")

TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "").strip()
DATA_SOURCE = os.getenv("DATA_SOURCE", "tushare").strip().lower()
LOCAL_DATA_MODE = os.getenv("LOCAL_DATA_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
UNIVERSE_PATH = DATA_ROOT / "universe" / "a_stock_universe.csv"
RAW_DAILY_DIR = DATA_ROOT / "raw" / "daily"
RAW_MONEYFLOW_DIR = DATA_ROOT / "raw" / "moneyflow"
RAW_LIMIT_DIR = DATA_ROOT / "raw" / "stk_limit"
PROCESSED_REVIEW_DIR = DATA_ROOT / "processed" / "review"
CACHE_DIR = DATA_ROOT / "cache"
DB_PATH = CACHE_DIR / "review_index.sqlite3"
for p in [RAW_DAILY_DIR, RAW_MONEYFLOW_DIR, RAW_LIMIT_DIR, PROCESSED_REVIEW_DIR, CACHE_DIR]:
    p.mkdir(parents=True, exist_ok=True)
