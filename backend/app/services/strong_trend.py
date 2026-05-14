from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import CACHE_DIR
from app.data_providers.tushare_provider import TushareProvider
from app.services.universe import load_universe

EXAMPLE_CODES = {"603778.SH", "301377.SZ", "301232.SZ", "301292.SZ", "002718.SZ", "301200.SZ"}


def _cache_file(end: str, top: int) -> Path:
    d = CACHE_DIR / "strong_trend"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{end}_{top}.json"


def _pct(a: float, b: float) -> float:
    if not b or pd.isna(a) or pd.isna(b):
        return 0.0
    return (float(a) / float(b) - 1.0) * 100.0


def _lookback_return(group: pd.DataFrame, n: int) -> float:
    latest = float(group.iloc[-1]["close"])
    idx = max(0, len(group) - 1 - n)
    return _pct(latest, float(group.iloc[idx]["close"]))


def _peak_stats(group: pd.DataFrame) -> dict[str, float | int | str]:
    base = float(group.iloc[0]["close"])
    high_idx = group["high"].astype(float).idxmax()
    peak_row = group.loc[high_idx]
    peak_high = float(peak_row["high"])
    latest_close = float(group.iloc[-1]["close"])
    peak_pos = int(group.index.get_loc(high_idx))
    days_from_peak = len(group) - 1 - peak_pos
    peak_return = _pct(peak_high, base)
    current_return = _pct(latest_close, base)
    drawdown = (1 - latest_close / peak_high) * 100 if peak_high else 0.0
    return {
        "peakHigh": peak_high,
        "peakDate": str(peak_row["trade_date"]),
        "daysFromPeak": days_from_peak,
        "peakReturnYear": peak_return,
        "currentReturnYear": current_return,
        "drawdown": drawdown,
    }


def _ma(group: pd.DataFrame, n: int) -> float:
    return float(group.tail(n)["close"].mean()) if len(group) >= n else float(group["close"].mean())


def _status(ret_60: float, ret_20: float, ret_10: float, dd: float, days_from_peak: int, close: float, ma20: float, ma60: float, peak_return: float, worst5: float) -> str:
    """五类状态规则：先看峰值后回撤，再看短期动量和均线位置。

    - 趋势走弱：曾经很强，但从区间高点大幅回撤，且短期/中期动量明显转弱或跌破60日均线。
    - 高位震荡：仍在高位区，回撤不小但没有系统性走坏，短期涨跌反复。
    - 回踩：中期趋势仍在，短期主动降温，回撤适中且未明显破坏60日均线。
    - 加速：10/20日动量同步强、离高点近、短期节奏明显抬升。
    - 延续：不满足以上极端状态，趋势仍正常推进。
    """
    if peak_return >= 60 and dd >= 28 and (ret_20 <= -8 or ret_60 <= -12 or close < ma60):
        return "趋势走弱"
    if peak_return >= 400 and days_from_peak <= 5 and dd >= 6 and worst5 <= -8:
        return "趋势走弱"
    if peak_return >= 80 and 14 <= dd < 35 and abs(ret_20) <= 18 and days_from_peak <= 80:
        return "高位震荡"
    if peak_return >= 400 and dd < 8 and days_from_peak >= 5 and abs(ret_20) <= 18 and abs(ret_10) <= 12:
        return "高位震荡"
    if peak_return >= 250 and days_from_peak <= 3 and 2 <= dd <= 10 and ret_10 > 5 and 0 <= ret_20 <= 35:
        return "回踩"
    if ret_60 > 15 and 8 <= dd <= 22 and -12 <= ret_20 <= 8 and close >= ma60 * 0.96:
        return "回踩"
    if ret_20 >= 25 and ret_10 >= max(12, ret_20 * 0.45) and dd <= 8 and close >= ma20:
        return "加速"
    return "延续"


def _score(ret_250: float, peak_ret: float, ret_120: float, ret_60: float, ret_20: float, ret_10: float, dd: float) -> int:
    raw = 0
    raw += min(max(peak_ret, 0), 320) / 320 * 20
    raw += min(max(ret_250, 0), 240) / 240 * 14
    raw += min(max(ret_120, 0), 150) / 150 * 16
    raw += min(max(ret_60, 0), 80) / 80 * 18
    raw += min(max(ret_20, 0), 40) / 40 * 20
    raw += min(max(ret_10, 0), 20) / 20 * 12
    raw -= min(max(dd - 10, 0), 45) / 45 * 24
    return int(round(max(0, min(100, raw))))


def _money_yuan(amount_thousand_yuan: float) -> float:
    return float(amount_thousand_yuan or 0) * 1000


def fetch_strong_trend(end: str, top: int = 100, force: bool = False) -> dict[str, Any]:
    top = max(20, min(int(top or 100), 300))
    p = _cache_file(end, top)
    if p.exists() and not force:
        return json.loads(p.read_text(encoding="utf-8"))

    provider = TushareProvider()
    universe, mapping = load_universe(True)
    meta = universe.set_index("ts_code")[["name", "industry_name"]].to_dict("index")
    codes = set(universe["ts_code"].tolist())

    start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=430)).strftime("%Y%m%d")
    cal = provider.trade_cal(start, end)
    dates = sorted(cal[cal["is_open"].astype(int).eq(1)]["cal_date"].astype(str).tolist())
    dates = [d for d in dates if d <= end][-250:]

    frames = []
    missing = []
    for d in dates:
        try:
            daily = provider.fetch_daily(d, force=False)
            daily = daily[daily["ts_code"].isin(codes)].copy()
            frames.append(daily[["ts_code", "trade_date", "open", "high", "low", "close", "pct_chg", "vol", "amount"]])
        except Exception as e:
            missing.append({"trade_date": d, "error": str(e)})
    if not frames:
        raise RuntimeError("近250个交易日没有可用日K数据，请先检查 Tushare Token 或缓存。")

    df = pd.concat(frames, ignore_index=True)
    for c in ["open", "high", "low", "close", "pct_chg", "vol", "amount"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.sort_values(["ts_code", "trade_date"])

    all_items = []
    kline_map: dict[str, list[dict[str, Any]]] = {}
    for code, g in df.groupby("ts_code"):
        g = g.dropna(subset=["close", "high"]).sort_values("trade_date").reset_index(drop=True)
        if len(g) < 60:
            continue
        latest = g.iloc[-1]
        ret_250 = _lookback_return(g, 250)
        ret_120 = _lookback_return(g, 120)
        ret_60 = _lookback_return(g, 60)
        ret_20 = _lookback_return(g, 20)
        ret_10 = _lookback_return(g, 10)
        peak = _peak_stats(g)
        dd = float(peak["drawdown"])
        peak_ret = float(peak["peakReturnYear"])
        ma20 = _ma(g, 20)
        ma60 = _ma(g, 60)
        latest_close = float(latest["close"])
        score = _score(ret_250, peak_ret, ret_120, ret_60, ret_20, ret_10, dd)
        if code not in EXAMPLE_CODES and peak_ret < 45 and ret_250 < 30 and ret_120 < 20 and ret_60 < 15:
            continue
        m = meta.get(code, {})
        worst5 = float(g.tail(5)["pct_chg"].min()) if len(g) else 0.0
        status = _status(ret_60, ret_20, ret_10, dd, int(peak["daysFromPeak"]), latest_close, ma20, ma60, peak_ret, worst5)
        item = {
            "rank": 0,
            "ts_code": code,
            "code": code.split(".")[0],
            "name": m.get("name", code),
            "industry": m.get("industry_name", "未分类"),
            "retYear": round(ret_250, 2),
            "peakRetYear": round(peak_ret, 2),
            "retHalf": round(ret_120, 2),
            "retQuarter": round(ret_60, 2),
            "retMonth": round(ret_20, 2),
            "ret10": round(ret_10, 2),
            "drawdown": round(dd, 2),
            "peakDate": peak["peakDate"],
            "daysFromPeak": int(peak["daysFromPeak"]),
            "ma20Distance": round(_pct(latest_close, ma20), 2),
            "ma60Distance": round(_pct(latest_close, ma60), 2),
            "worst5PctChg": round(worst5, 2),
            "status": status,
            "trendScore": score,
            "latestClose": round(latest_close, 3),
            "latestAmount": _money_yuan(float(latest.get("amount") or 0)),
            "turnoverProxy": round(float(g.tail(20)["amount"].mean() or 0), 2),
        }
        all_items.append(item)
        kline_map[code] = [
            {
                "date": str(r.trade_date),
                "open": round(float(r.open), 3),
                "high": round(float(r.high), 3),
                "low": round(float(r.low), 3),
                "close": round(float(r.close), 3),
                "amount": _money_yuan(float(r.amount or 0)),
                "pct_chg": round(float(r.pct_chg or 0), 3),
            }
            for r in g.tail(250).itertuples(index=False)
        ]

    all_items.sort(key=lambda x: (x["trendScore"], x["peakRetYear"], x["retYear"], -x["drawdown"]), reverse=True)
    selected_items = all_items[:top]
    # 保证用户点名的校准样本在接口里可见，便于验证状态规则。
    selected_codes = {x["ts_code"] for x in selected_items}
    for item in all_items:
        if item["ts_code"] in EXAMPLE_CODES and item["ts_code"] not in selected_codes:
            selected_items.append(item)
            selected_codes.add(item["ts_code"])
    for i, item in enumerate(selected_items, 1):
        item["rank"] = i
    selected = selected_items[0] if selected_items else None

    industry_rows = []
    if selected_items:
        tmp = pd.DataFrame(selected_items)
        for industry, g in tmp.groupby("industry"):
            industry_rows.append({
                "industry": industry,
                "count": int(len(g)),
                "avgRetYear": round(float(g["retYear"].mean()), 2),
                "avgPeakRetYear": round(float(g["peakRetYear"].mean()), 2),
                "avgScore": round(float(g["trendScore"].mean()), 2),
            })
        industry_rows.sort(key=lambda x: (x["count"], x["avgPeakRetYear"]), reverse=True)

    payload = {
        "source": "tushare_daily_calculated",
        "tradeDate": dates[-1] if dates else end,
        "startDate": dates[0] if dates else None,
        "endDate": dates[-1] if dates else end,
        "periodDays": len(dates),
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "top": top,
        "universeFieldMapping": mapping,
        "missingDays": missing[:20],
        "summary": {
            "poolCount": len(selected_items),
            "industryCount": len(industry_rows),
            "topName": selected["name"] if selected else "--",
            "topRetYear": selected["peakRetYear"] if selected else 0,
            "topScore": selected["trendScore"] if selected else 0,
        },
        "items": selected_items,
        "industryDistribution": industry_rows[:20],
        "kline": {item["ts_code"]: kline_map.get(item["ts_code"], []) for item in selected_items},
        "statusRule": "先用近250日最高价计算峰值涨幅和从峰值到最新收盘的真实回撤，再结合10/20/60日动量、20/60日均线位置、距高点天数，归类为加速、延续、趋势走弱、高位震荡、回踩。",
    }
    counts = pd.Series([item["status"] for item in selected_items]).value_counts().to_dict() if selected_items else {}
    payload["statusCounts"] = {str(k): int(v) for k, v in counts.items()}
    payload["examples"] = {item["ts_code"]: item for item in selected_items if item["ts_code"] in EXAMPLE_CODES}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
