from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app import config
from app.services.universe import load_universe


ONEIL_DIR = config.PROJECT_ROOT / "oneil_trend_strategy"
LAB_DIR = ONEIL_DIR / "outputs" / "base_on_base_lab"


def _latest(pattern: str) -> Path | None:
    files = sorted(LAB_DIR.glob(pattern))
    return files[-1] if files else None


def _money_yuan(amount_thousand_yuan: float) -> float:
    return float(amount_thousand_yuan or 0) * 1000


def _read_blotter(path: Path, version: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"signal_date": str, "entry_date": str, "exit_date": str, "code": str})
    df["version"] = version
    df["signal_date"] = df["signal_date"].astype(str).str.replace(".0", "", regex=False).str[:8]
    return df


def _load_signal_versions() -> pd.DataFrame:
    frames = []
    v5 = _latest("base_on_base_trade_blotter_v5_realistic_*.csv")
    v6 = _latest("base_on_base_trade_blotter_v6_structure_*.csv")
    if v5:
        frames.append(_read_blotter(v5, "V5"))
    if v6:
        frames.append(_read_blotter(v6, "V6"))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _recent_trade_dates(days: int) -> list[str]:
    dates = sorted(p.stem for p in config.RAW_DAILY_DIR.glob("*.parquet") if p.stem.isdigit())
    if not dates:
        dates = sorted(p.stem for p in config.RAW_DAILY_DIR.glob("*.csv") if p.stem.isdigit())
    return dates[-days:]


def _load_daily_window(dates: list[str]) -> pd.DataFrame:
    frames = []
    for d in dates:
        p = config.RAW_DAILY_DIR / f"{d}.parquet"
        if p.exists():
            frames.append(pd.read_parquet(p))
            continue
        c = config.RAW_DAILY_DIR / f"{d}.csv"
        if c.exists():
            frames.append(pd.read_csv(c, dtype={"trade_date": str}))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    for col in ["open", "high", "low", "close", "amount", "pct_chg"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trade_date"] = df["trade_date"].astype(str)
    return df


EXIT_REASON_LABELS = {
    "trailing_stop": "移动止盈/回撤止盈",
    "break_ma20_confirmed": "跌破 MA20 确认",
    "pivot_failed": "突破失败",
    "hard_stop": "硬止损",
    "data_end_exit": "样本截止，未触发卖出",
}


def _clean_date(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).replace(".0", "")[:8]


def _exit_reason_label(reason: Any) -> str:
    key = "" if pd.isna(reason) else str(reason)
    return EXIT_REASON_LABELS.get(key, key or "未触发卖出")


def _is_real_exit(reason: Any, exit_date: Any) -> bool:
    return bool(_clean_date(exit_date)) and ("" if pd.isna(reason) else str(reason)) != "data_end_exit"


def _float_or_none(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dynamic_open_position_metrics(
    daily: pd.DataFrame,
    code: str,
    entry_date: str,
    entry_price: float | None,
    valuation_date: str,
) -> dict[str, Any]:
    if daily.empty or not code or not entry_date or not entry_price or entry_price <= 0:
        return {}
    g = daily[
        (daily["ts_code"].astype(str) == str(code))
        & (daily["trade_date"].astype(str) >= str(entry_date))
        & (daily["trade_date"].astype(str) <= str(valuation_date))
    ].sort_values("trade_date")
    if g.empty:
        return {}
    latest = g.iloc[-1]
    latest_close = _float_or_none(latest.get("close"))
    max_high = _float_or_none(g["high"].max()) if "high" in g else None
    if latest_close is None:
        return {}
    out: dict[str, Any] = {
        "valuationDate": str(latest.get("trade_date")),
        "valuationClose": round(latest_close, 3),
        "tradeReturn": round((latest_close / entry_price - 1.0) * 100, 2),
    }
    if max_high is not None:
        out["maxReturnDuringHold"] = round((max_high / entry_price - 1.0) * 100, 2)
    return out


def fetch_base_on_base_signals(days: int = 100, kline_days: int = 180, kline_limit: int = 50) -> dict[str, Any]:
    days = max(20, min(int(days or 100), 250))
    kline_days = max(80, min(int(kline_days or 180), 300))
    kline_limit = max(0, min(int(kline_limit or 0), 200))
    recent_dates = _recent_trade_dates(max(days, kline_days))
    if not recent_dates:
        raise RuntimeError("未找到日K缓存，请先导入或下载 data/raw/daily。")
    signal_dates = set(recent_dates[-days:])

    blotter = _load_signal_versions()
    if blotter.empty:
        return {
            "updatedAt": datetime.now().isoformat(timespec="seconds"),
            "days": days,
            "startDate": recent_dates[-days],
            "endDate": recent_dates[-1],
            "items": [],
            "kline": {},
            "summary": {"signalCount": 0, "stockCount": 0, "v5Count": 0, "v6Count": 0, "bothCount": 0},
        }
    blotter = blotter[blotter["signal_date"].isin(signal_dates)].copy()
    if blotter.empty:
        return {
            "updatedAt": datetime.now().isoformat(timespec="seconds"),
            "days": days,
            "startDate": recent_dates[-days],
            "endDate": recent_dates[-1],
            "items": [],
            "kline": {},
            "summary": {"signalCount": 0, "stockCount": 0, "v5Count": 0, "v6Count": 0, "bothCount": 0},
        }

    daily_window = _load_daily_window(recent_dates)
    valuation_date = recent_dates[-1]
    universe, _ = load_universe(True)
    meta = universe.set_index("ts_code")[["name", "industry_name"]].to_dict("index")
    grouped = []
    for (signal_date, code), g in blotter.groupby(["signal_date", "code"], sort=False):
        versions = sorted(set(g["version"].astype(str)))
        best = g.sort_values("version").iloc[-1]
        m = meta.get(code, {})
        entry_date = _clean_date(best.get("entry_date", ""))
        entry_price = _float_or_none(best.get("entry_price_raw")) or _float_or_none(best.get("entry_price")) or 0.0
        real_exit = _is_real_exit(best.get("exit_reason", ""), best.get("exit_date", ""))
        dynamic_metrics = {} if real_exit else _dynamic_open_position_metrics(
            daily_window,
            code,
            entry_date,
            entry_price,
            valuation_date,
        )
        display_date = _clean_date(best.get("exit_date", ""))
        date_label = "退出日"
        if not real_exit:
            display_date = dynamic_metrics.get("valuationDate") or valuation_date
            date_label = "估值日"
        trade_return = round(float(best.get("trade_return_adj") if pd.notna(best.get("trade_return_adj")) else best.get("trend_return", 0)) * 100, 2)
        max_return = round(float(best.get("max_return_during_hold") or 0) * 100, 2)
        if dynamic_metrics:
            trade_return = dynamic_metrics.get("tradeReturn", trade_return)
            max_return = dynamic_metrics.get("maxReturnDuringHold", max_return)
        grouped.append({
            "signalDate": signal_date,
            "signalType": "buy",
            "signalLabel": "买入信号",
            "code": code,
            "shortCode": code.split(".")[0],
            "name": m.get("name", code),
            "industry": m.get("industry_name", best.get("industry_l1", "未分类")),
            "versions": versions,
            "versionLabel": "/".join(versions),
            "entryDate": entry_date,
            "entryPrice": round(float(entry_price or 0), 3),
            "exitSignalDate": _clean_date(best.get("exit_signal_date", "")),
            "exitDate": display_date,
            "dateLabel": date_label,
            "valuationDate": dynamic_metrics.get("valuationDate", "") if not real_exit else "",
            "valuationClose": dynamic_metrics.get("valuationClose") if not real_exit else None,
            "isOpenPosition": not real_exit,
            "exitSignalLabel": "卖出信号" if real_exit else "",
            "exitReason": best.get("exit_reason", ""),
            "exitReasonLabel": _exit_reason_label(best.get("exit_reason", "")),
            "tradeReturn": trade_return,
            "maxReturnDuringHold": max_return,
            "base2Days": int(best.get("base2_days")) if pd.notna(best.get("base2_days")) else None,
            "base2VolumeContract": round(float(best.get("base2_volume_contract")), 3) if pd.notna(best.get("base2_volume_contract")) else None,
            "priorLegReturn": round(float(best.get("prior_leg_return")) * 100, 2) if pd.notna(best.get("prior_leg_return")) else None,
            "hasExDividend": bool(best.get("has_ex_dividend_during_holding")) if "has_ex_dividend_during_holding" in best else False,
        })
    items = sorted(grouped, key=lambda x: (x["signalDate"], x["code"]), reverse=True)

    kline: dict[str, list[dict[str, Any]]] = {}
    if kline_limit > 0:
        daily = daily_window
        codes = [x["code"] for x in items[:kline_limit]]
        daily = daily[daily["ts_code"].isin(set(codes))].sort_values(["ts_code", "trade_date"])
        for code, g in daily.groupby("ts_code"):
            kline[code] = [
                {
                    "date": str(r.trade_date),
                    "open": round(float(r.open), 3),
                    "high": round(float(r.high), 3),
                    "low": round(float(r.low), 3),
                    "close": round(float(r.close), 3),
                    "amount": _money_yuan(float(getattr(r, "amount", 0) or 0)),
                    "pct_chg": round(float(getattr(r, "pct_chg", 0) or 0), 3),
                }
                for r in g.itertuples(index=False)
            ]

    version_sets = [set(x["versions"]) for x in items]
    return {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "days": days,
        "startDate": recent_dates[-days],
        "endDate": recent_dates[-1],
        "items": items,
        "kline": kline,
        "summary": {
            "signalCount": len(items),
            "stockCount": len({x["code"] for x in items}),
            "v5Count": sum(1 for s in version_sets if "V5" in s),
            "v6Count": sum(1 for s in version_sets if "V6" in s),
            "bothCount": sum(1 for s in version_sets if {"V5", "V6"}.issubset(s)),
        },
    }
