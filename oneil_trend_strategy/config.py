from __future__ import annotations

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
PARENT_PROJECT_DIR = PROJECT_DIR.parent

DAILY_DATA_DIR = PARENT_PROJECT_DIR / "data" / "raw" / "daily"
UNIVERSE_DIR = PARENT_PROJECT_DIR / "data" / "universe"
START_DATE = "2024-01-01"
END_DATE = "2026-12-31"
LOOKBACK_DAYS = 300
OUTPUT_DIR = PROJECT_DIR / "outputs"

FIELD_MAP = {
    "date": "trade_date",
    "code": "ts_code",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "amount": "amount",
    "volume": "vol",
    "pctChg": "pct_chg",
    "pre_close": "pre_close",
    "tradestatus": "tradestatus",
    "isST": "isST",
    "industry_l1": "industry_l1",
}

UNIVERSE_CODE_CANDIDATES = ["ts_code", "code", "symbol"]
UNIVERSE_INDUSTRY_CANDIDATES = ["industry_l1", "industry_L1_name", "industry", "industry_name"]

AMOUNT_MIN_YUAN = 50_000_000
TUSHARE_AMOUNT_IS_THOUSAND_YUAN = True
PRICE_ADJUST_MODE = "hfq"  # raw / hfq
KEEP_RAW_PRICE_COLUMNS = True
TREND_FILTER_MODE = "loose"
MAX_HOLD_DAYS = 60
USE_WEEKLY_FILTER = True
WEEKLY_FILTER_MODE = "loose"
ENABLE_FAILED_BREAKOUT_EXIT = True
ENABLE_BREAK_MA20_EXIT_AFTER_DAYS = 0

PATTERN_QUALITY = {
    "flat_base": 0.90,
    "double_bottom": 0.85,
    "cup_with_handle": 0.85,
    "base_on_base": 0.80,
    "cup_without_handle": 0.75,
    "ascending_base": 0.75,
    "high_tight_flag": 0.65,
}

RETURN_BUCKETS = [
    ("<= -20%", None, -0.20),
    ("-20% ~ -10%", -0.20, -0.10),
    ("-10% ~ -5%", -0.10, -0.05),
    ("-5% ~ 0%", -0.05, 0.0),
    ("0% ~ 5%", 0.0, 0.05),
    ("5% ~ 10%", 0.05, 0.10),
    ("10% ~ 20%", 0.10, 0.20),
    ("20% ~ 50%", 0.20, 0.50),
    ("> 50%", 0.50, None),
]
