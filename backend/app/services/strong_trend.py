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


def _trend_features(group: pd.DataFrame, peak_high: float, latest_close: float, ma20: float, ma60: float) -> dict[str, Any]:
    latest = group.iloc[-1]
    low = float(latest["low"])
    yearly_low = float(group["low"].min())
    ma5 = _ma(group, 5)
    ma10 = _ma(group, 10)
    ma20_prev = float(group.iloc[-6:-1]["close"].mean()) if len(group) >= 25 else ma20
    ma60_prev = float(group.iloc[-21:-1]["close"].mean()) if len(group) >= 80 else ma60
    ma5_prev = float(group.iloc[-10:-5]["close"].mean()) if len(group) >= 10 else ma5
    ma10_prev = float(group.iloc[-15:-5]["close"].mean()) if len(group) >= 15 else ma10
    ma5_slope = _pct(ma5, ma5_prev)
    ma10_slope = _pct(ma10, ma10_prev)
    ma20_slope = _pct(ma20, ma20_prev)
    ma60_slope = _pct(ma60, ma60_prev)
    ma20_distance = _pct(latest_close, ma20)
    ma60_distance = _pct(latest_close, ma60)
    high_position = (latest_close - yearly_low) / (peak_high - yearly_low) * 100 if peak_high > yearly_low else 0.0
    recent = group.tail(20)
    recent_high = float(recent["high"].max())
    recent_low = float(recent["low"].min())
    recent_amp = (recent_high / recent_low - 1) * 100 if recent_low else 0.0
    ma5_distance = _pct(latest_close, ma5)
    ma10_distance = _pct(latest_close, ma10)
    touches = [
        ("MA5", low <= ma5 * 1.025 and latest_close >= ma5 * 0.985 and ma5_slope >= -3, ma5_distance),
        ("MA10", low <= ma10 * 1.025 and latest_close >= ma10 * 0.985 and ma10_slope >= -3, ma10_distance),
        ("MA20", low <= ma20 * 1.025 and latest_close >= ma20 * 0.985 and ma20_slope >= -2, ma20_distance),
        ("MA60", low <= ma60 * 1.025 and latest_close >= ma60 * 0.98 and ma60_slope >= -2, ma60_distance),
    ]
    touched = [x for x in touches if x[1]]
    if touched:
        line_type, _, line_distance = min(touched, key=lambda x: abs(x[2]))
    else:
        candidates = [("MA5", ma5_distance), ("MA10", ma10_distance), ("MA20", ma20_distance), ("MA60", ma60_distance)]
        line_type, line_distance = "--", min(candidates, key=lambda x: abs(x[1]))[1]
    return {
        "yearlyLow": yearly_low,
        "ma5Distance": ma5_distance,
        "ma10Distance": ma10_distance,
        "ma20Slope": ma20_slope,
        "ma60Slope": ma60_slope,
        "ma20Distance": ma20_distance,
        "ma60Distance": ma60_distance,
        "highPosition": high_position,
        "recentAmplitude20": recent_amp,
        "trendLineType": line_type,
        "trendLineDistance": line_distance,
        "trendLineTouched": bool(touched),
    }


def _status(ret_60: float, ret_20: float, ret_10: float, dd: float, days_from_peak: int, close: float, ma20: float, ma60: float, peak_return: float, worst5: float, features: dict[str, Any]) -> str:
    """五类状态规则：先看峰值后回撤，再看短期动量和均线位置。

    - 趋势走弱：曾经很强，但从区间高点大幅回撤，且短期/中期动量明显转弱或跌破60日均线。
    - 高位震荡：仍在高位区，回撤不小但没有系统性走坏，短期涨跌反复。
    - 回踩：中期趋势仍在，短期主动降温，回撤适中且未明显破坏60日均线。
    - 加速：10/20日动量同步强、离高点近、短期节奏明显抬升。
    - 延续：不满足以上极端状态，趋势仍正常推进。
    """
    high_pos = float(features.get("highPosition") or 0)
    recent_amp = float(features.get("recentAmplitude20") or 0)
    touched_line = bool(features.get("trendLineTouched"))
    ma20_slope = float(features.get("ma20Slope") or 0)
    ma60_slope = float(features.get("ma60Slope") or 0)

    if peak_return >= 60 and dd >= 28 and (ret_20 <= -8 or ret_60 <= -12 or close < ma60):
        return "趋势走弱"
    if peak_return >= 400 and days_from_peak <= 5 and dd >= 6 and worst5 <= -8:
        return "趋势走弱"
    if close < ma60 * 0.94 and ret_20 < -10 and ma60_slope < 0:
        return "趋势走弱"

    # 高动量优先判加速：20日/10日同步大幅抬升且贴近高点。
    if ret_20 >= 35 and ret_10 >= 15 and dd <= 8 and close >= ma20:
        return "加速"

    # 高位震荡看的是高位区间内的曲线形态：仍处高位、近20日振幅较大、涨跌反复，但没有跌破趋势结构，也没有继续加速。
    if peak_return >= 80 and high_pos >= 68 and 8 <= dd < 35 and recent_amp >= 12 and -18 <= ret_20 <= 18 and -12 <= ret_10 <= 15 and close >= ma60 * 0.96:
        return "高位震荡"
    if peak_return >= 350 and high_pos >= 75 and recent_amp >= 10 and abs(ret_20) <= 18 and abs(ret_10) <= 15 and days_from_peak >= 4:
        return "高位震荡"

    # 回踩必须“碰到/接近趋势线”：当日最低价回踩 MA5/MA10/MA20/MA60 附近，收盘没有有效跌破，且趋势线本身没有明显下弯。
    if touched_line and high_pos >= 60 and ret_60 > 0 and -8 <= ret_20 <= 35 and dd <= 24 and (ma20_slope >= -1.5 or ma60_slope >= -1):
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
        features = _trend_features(g, float(peak["peakHigh"]), latest_close, ma20, ma60)
        score = _score(ret_250, peak_ret, ret_120, ret_60, ret_20, ret_10, dd)
        avg20_amount_yuan = _money_yuan(float(g.tail(20)["amount"].mean() or 0))
        strong_candidate = (peak_ret >= 80) or (ret_250 >= 40 and ret_120 >= 25) or (ret_60 >= 30 and ret_20 >= 10)
        broken_fake_strong = (dd >= 45 and ret_20 < 0) or (latest_close < ma60 * 0.9 and ret_20 < -10)
        if avg20_amount_yuan < 50_000_000 or not strong_candidate or broken_fake_strong:
            if code not in EXAMPLE_CODES:
                continue
        m = meta.get(code, {})
        worst5 = float(g.tail(5)["pct_chg"].min()) if len(g) else 0.0
        status = _status(ret_60, ret_20, ret_10, dd, int(peak["daysFromPeak"]), latest_close, ma20, ma60, peak_ret, worst5, features)
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
            "ma20Distance": round(float(features["ma20Distance"]), 2),
            "ma60Distance": round(float(features["ma60Distance"]), 2),
            "ma20Slope": round(float(features["ma20Slope"]), 2),
            "ma60Slope": round(float(features["ma60Slope"]), 2),
            "highPosition": round(float(features["highPosition"]), 2),
            "recentAmplitude20": round(float(features["recentAmplitude20"]), 2),
            "trendLineType": features["trendLineType"],
            "trendLineDistance": round(float(features["trendLineDistance"]), 2),
            "trendLineTouched": bool(features["trendLineTouched"]),
            "worst5PctChg": round(worst5, 2),
            "status": status,
            "trendScore": score,
            "latestClose": round(latest_close, 3),
            "latestAmount": _money_yuan(float(latest.get("amount") or 0)),
            "avg20Amount": avg20_amount_yuan,
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
    examples = {item["ts_code"]: item for item in all_items if item["ts_code"] in EXAMPLE_CODES}
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
        "statusRule": "先用近250日最高价计算峰值涨幅和真实回撤；入选候选需满足流动性和强趋势条件；回踩必须判断当日最低价是否触及/接近MA5/MA10/MA20/MA60趋势线且收盘未有效跌破；高位震荡要求处于高位区间、近20日有振幅、短期涨跌反复且未明显加速或走坏。",
    }
    counts = pd.Series([item["status"] for item in selected_items]).value_counts().to_dict() if selected_items else {}
    payload["statusCounts"] = {str(k): int(v) for k, v in counts.items()}
    payload["examples"] = examples
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
