#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import pandas as pd

from app import config
from app.data_providers.tushare_provider import TushareProvider
from app.services.universe import load_universe


def recent_trade_dates(provider: TushareProvider, days: int) -> list[str]:
    end = datetime.now()
    start = end - timedelta(days=max(days * 2, days + 120))
    cal = provider.trade_cal(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    dates = (
        cal[cal["is_open"].astype(int).eq(1)]["cal_date"]
        .astype(str)
        .sort_values()
        .tolist()
    )
    return dates[-days:]


def filter_universe(df: pd.DataFrame, universe_codes: set[str]) -> pd.DataFrame:
    if df.empty or "ts_code" not in df.columns:
        return df
    return df[df["ts_code"].astype(str).isin(universe_codes)].copy()


def write_manifest(payload: dict) -> None:
    manifest_dir = config.DATA_ROOT / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    latest = manifest_dir / "recent_300d_download_latest.json"
    stamped = manifest_dir / f"recent_300d_download_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    latest.write_text(text, encoding="utf-8")
    stamped.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download recent daily and moneyflow data for the universe.")
    parser.add_argument("--days", type=int, default=300, help="recent trading days to download")
    parser.add_argument("--sleep", type=float, default=0.18, help="sleep seconds between API calls")
    parser.add_argument("--force", action="store_true", help="overwrite existing raw caches")
    args = parser.parse_args()

    universe, mapping = load_universe(True)
    universe_codes = set(universe["ts_code"].astype(str))
    provider = TushareProvider()
    dates = recent_trade_dates(provider, args.days)

    stats = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "days_requested": args.days,
        "trade_days": dates,
        "trade_day_count": len(dates),
        "universe_count": len(universe_codes),
        "universe_mapping": mapping,
        "directories": {
            "daily": str(config.RAW_DAILY_DIR),
            "moneyflow": str(config.RAW_MONEYFLOW_DIR),
            "stk_limit": str(config.RAW_LIMIT_DIR),
            "processed_review": str(config.PROCESSED_REVIEW_DIR),
            "cache": str(config.CACHE_DIR),
            "manifests": str(config.DATA_ROOT / "manifests"),
        },
        "items": [],
    }

    for i, trade_date in enumerate(dates, 1):
        item = {"trade_date": trade_date, "daily_rows": 0, "moneyflow_rows": 0, "status": "ok", "errors": []}
        try:
            daily = filter_universe(provider.fetch_daily(trade_date, args.force), universe_codes)
            provider._write_cache("daily", trade_date, daily)
            item["daily_rows"] = int(len(daily))
        except Exception as exc:
            item["status"] = "partial_failed"
            item["errors"].append(f"daily: {exc}")
        time.sleep(args.sleep)

        try:
            moneyflow = filter_universe(provider.fetch_moneyflow(trade_date, args.force), universe_codes)
            provider._write_cache("moneyflow", trade_date, moneyflow)
            item["moneyflow_rows"] = int(len(moneyflow))
        except Exception as exc:
            item["status"] = "partial_failed"
            item["errors"].append(f"moneyflow: {exc}")
        time.sleep(args.sleep)

        stats["items"].append(item)
        if i % 10 == 0 or item["errors"]:
            print(
                f"[{i}/{len(dates)}] {trade_date} "
                f"daily={item['daily_rows']} moneyflow={item['moneyflow_rows']} status={item['status']}",
                flush=True,
            )
            if item["errors"]:
                print("  " + " | ".join(item["errors"]), flush=True)
        write_manifest({**stats, "finished_at": datetime.now().isoformat(timespec="seconds")})

    stats["finished_at"] = datetime.now().isoformat(timespec="seconds")
    write_manifest(stats)
    failed = [x for x in stats["items"] if x["status"] != "ok"]
    print(f"done trade_days={len(dates)} failed={len(failed)} manifest=data/manifests/recent_300d_download_latest.json")


if __name__ == "__main__":
    main()
