from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import CACHE_DIR
from app.data_providers.tushare_provider import TushareProvider
from app.services.universe import load_universe


def _cache_file(end: str, top: int) -> Path:
    d = CACHE_DIR / "strong_trend"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{end}_{top}_strategy_v1.json"


def _safe_pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or pd.isna(a) or pd.isna(b) or float(b) == 0:
        return None
    return float(a) / float(b) - 1.0


def _score_bool(v: bool, pts: int) -> int:
    return pts if bool(v) else 0


def _trend_level(score: int) -> str:
    if score >= 85:
        return "极强趋势"
    if score >= 75:
        return "强趋势"
    if score >= 65:
        return "趋势良好"
    if score >= 50:
        return "趋势一般"
    return "弱趋势"


def _entry_level(score: int) -> str:
    if score >= 80:
        return "优先观察"
    if score >= 65:
        return "可观察"
    if score >= 50:
        return "一般"
    return "暂缓"


def _market_position_level(score: int) -> str:
    if score >= 80:
        return "强势市场：建议仓位 80%-100%"
    if score >= 65:
        return "普通偏强：建议仓位 50%-70%"
    if score >= 50:
        return "普通震荡：建议仓位 30%-50%"
    if score >= 35:
        return "弱势市场：建议仓位 10%-30%"
    return "退潮市场：建议仓位 0%-10%"


def _trend_state(row: pd.Series) -> str:
    close = float(row.close)
    ma5 = row.ma5
    ma10 = row.ma10
    ma20 = row.ma20
    ma60 = row.ma60
    ma120 = row.ma120
    ret10 = row.ret10
    ret20 = row.ret20
    ret60 = row.ret60
    drawdown60 = row.drawdown60
    drawdown120 = row.drawdown120
    high_pos120 = row.high_pos120
    dist_ma20 = row.dist_ma20
    ma20_slope = row.ma20_slope
    ma60_slope = row.ma60_slope
    amp20 = row.amp20
    hhv60 = row.hhv60
    hhv120 = row.hhv120

    # 1. 趋势走弱
    if pd.notna(ma60) and close < ma60:
        return "趋势走弱"
    if pd.notna(ma20) and pd.notna(ma60) and ma20 < ma60:
        return "趋势走弱"
    if pd.notna(drawdown120) and drawdown120 < -0.20:
        return "趋势走弱"
    if pd.notna(ma20) and pd.notna(ret20) and pd.notna(ma20_slope) and close < ma20 and ret20 < 0 and ma20_slope <= 0:
        return "趋势走弱"

    # 2. 加速
    if (
        pd.notna(ma5) and pd.notna(ma10) and pd.notna(ma20) and pd.notna(ma60)
        and pd.notna(ret20) and pd.notna(ma20_slope) and pd.notna(hhv60) and pd.notna(dist_ma20)
        and close > ma5 and ma5 > ma10 and ma10 > ma20 and ma20 > ma60
        and ret20 > 0.15 and ma20_slope > 0.05
        and close / hhv60 > 0.97 and dist_ma20 > 0.05
    ):
        return "加速"

    # 3. 回踩
    if (
        pd.notna(ma60_slope) and pd.notna(ret60) and pd.notna(drawdown60) and pd.notna(ma60) and pd.notna(ret10)
        and ma60_slope > 0 and ret60 > 0.10
        and drawdown60 <= -0.05 and drawdown60 >= -0.15
        and close > ma60 * 0.97 and ret10 < 0
    ):
        return "回踩"

    # 4. 高位震荡
    if (
        pd.notna(high_pos120) and pd.notna(hhv120) and pd.notna(ret20) and pd.notna(ma20_slope)
        and pd.notna(ma60_slope) and pd.notna(ma60) and pd.notna(amp20)
        and high_pos120 > 0.75 and close / hhv120 > 0.85
        and abs(ret20) < 0.08 and abs(ma20_slope) < 0.03
        and ma60_slope > 0 and close > ma60
        and amp20 >= 0.08 and amp20 <= 0.25
    ):
        return "高位震荡"

    # 5. 延续
    if (
        pd.notna(ma20) and pd.notna(ma60) and pd.notna(ma120) and pd.notna(ma20_slope)
        and pd.notna(ma60_slope) and pd.notna(ret20) and pd.notna(drawdown60)
        and close > ma20 and ma20 > ma60 and ma60 > ma120
        and ma20_slope > 0 and ma60_slope > 0
        and ret20 > 0 and drawdown60 > -0.10
    ):
        return "延续"

    return "未分类"


def _money_yuan(amount_thousand_yuan: float) -> float:
    return float(amount_thousand_yuan or 0) * 1000


def _calc_latest_features(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for code, g in df.groupby("ts_code"):
        g = g.dropna(subset=["close"]).sort_values("trade_date").reset_index(drop=True).copy()
        if len(g) < 120:
            continue
        close = g["close"].astype(float)
        high = g["high"].astype(float)
        low = g["low"].astype(float)
        for n in [5, 10, 20, 60, 120, 250]:
            g[f"ma{n}"] = close.rolling(n, min_periods=n).mean()
        for n in [10, 20, 60, 120, 240]:
            g[f"ret{n}"] = close / close.shift(n) - 1
        g["hhv20"] = close.rolling(20, min_periods=20).max()
        g["hhv60"] = close.rolling(60, min_periods=60).max()
        g["hhv120"] = close.rolling(120, min_periods=120).max()
        g["llv120"] = close.rolling(120, min_periods=120).min()
        g["drawdown60"] = close / g["hhv60"] - 1
        g["drawdown120"] = close / g["hhv120"] - 1
        denom = g["hhv120"] - g["llv120"]
        g["high_pos120"] = (close - g["llv120"]) / denom
        g.loc[denom.eq(0), "high_pos120"] = 0.5
        g["dist_ma20"] = close / g["ma20"] - 1
        g["dist_ma60"] = close / g["ma60"] - 1
        g["ma20_slope"] = g["ma20"] / g["ma20"].shift(20) - 1
        g["ma60_slope"] = g["ma60"] / g["ma60"].shift(20) - 1
        g["ma120_slope"] = g["ma120"] / g["ma120"].shift(20) - 1
        g["amp20"] = high.rolling(20, min_periods=20).max() / low.rolling(20, min_periods=20).min() - 1
        g["above_ma60"] = close > g["ma60"]
        g["above_ma60_ratio_60"] = g["above_ma60"].rolling(60, min_periods=60).mean()
        latest = g.iloc[-1].copy()
        latest["kline"] = g.tail(250).to_dict("records")
        out.append(latest)
    return pd.DataFrame(out)


def _add_scores(latest: pd.DataFrame) -> pd.DataFrame:
    latest = latest.copy()
    latest["ret120_rank_pct"] = latest["ret120"].rank(pct=True, na_option="bottom")
    above_ma20_ratio = float((latest["close"] > latest["ma20"]).mean()) if len(latest) else 0.0
    above_ma60_ratio = float((latest["close"] > latest["ma60"]).mean()) if len(latest) else 0.0
    ret20_positive_ratio = float((latest["ret20"] > 0).mean()) if len(latest) else 0.0
    market_score = int(max(0, min(100, round(
        above_ma20_ratio * 35 + above_ma60_ratio * 40 + ret20_positive_ratio * 25
    ))))
    market_level = _market_position_level(market_score)

    rows = []
    for _, r in latest.iterrows():
        close = float(r.close)
        structure = 0
        structure += _score_bool(pd.notna(r.ma20) and close > r.ma20, 5)
        structure += _score_bool(pd.notna(r.ma20) and pd.notna(r.ma60) and r.ma20 > r.ma60, 5)
        structure += _score_bool(pd.notna(r.ma60) and pd.notna(r.ma120) and r.ma60 > r.ma120, 5)
        structure += _score_bool(pd.notna(r.ma120) and pd.notna(r.ma250) and r.ma120 > r.ma250, 5)
        structure += _score_bool(pd.notna(r.ma20_slope) and r.ma20_slope > 0, 5)
        structure += _score_bool(pd.notna(r.above_ma60_ratio_60) and r.above_ma60_ratio_60 > 0.70, 5)

        momentum = 0
        momentum += _score_bool(pd.notna(r.ret20) and r.ret20 > 0, 5)
        momentum += _score_bool(pd.notna(r.ret20) and r.ret20 > 0.08, 5)
        momentum += _score_bool(pd.notna(r.ret60) and r.ret60 > 0.10, 5)
        momentum += _score_bool(pd.notna(r.ret120) and r.ret120 > 0.20, 5)
        momentum += _score_bool(pd.notna(r.ret120_rank_pct) and r.ret120_rank_pct >= 0.70, 5)

        slope = 0
        slope += _score_bool(pd.notna(r.ma20_slope) and r.ma20_slope > 0, 4)
        slope += _score_bool(pd.notna(r.ma20_slope) and r.ma20_slope > 0.03, 4)
        slope += _score_bool(pd.notna(r.ma60_slope) and r.ma60_slope > 0, 4)
        slope += _score_bool(pd.notna(r.ma60_slope) and r.ma60_slope > 0.03, 4)
        slope += _score_bool(pd.notna(r.ma120_slope) and r.ma120_slope > 0, 4)

        position = 0
        position += _score_bool(pd.notna(r.high_pos120) and r.high_pos120 > 0.60, 5)
        position += _score_bool(pd.notna(r.high_pos120) and r.high_pos120 > 0.75, 5)
        position += _score_bool(pd.notna(r.hhv120) and r.hhv120 and close / r.hhv120 > 0.90, 5)

        penalty = 0
        penalty += _score_bool(pd.notna(r.ma20) and close < r.ma20, 5)
        penalty += _score_bool(pd.notna(r.ma60) and close < r.ma60, 10)
        penalty += _score_bool(pd.notna(r.drawdown60) and r.drawdown60 < -0.12, 5)
        penalty += _score_bool(pd.notna(r.drawdown120) and r.drawdown120 < -0.20, 10)
        penalty += _score_bool(pd.notna(r.dist_ma60) and r.dist_ma60 > 0.35, 5)
        penalty = min(penalty, 20)

        strong_checks = [
            pd.notna(r.ma20) and close > r.ma20,
            pd.notna(r.ma20) and pd.notna(r.ma60) and r.ma20 > r.ma60,
            pd.notna(r.ma60) and pd.notna(r.ma120) and r.ma60 > r.ma120,
            pd.notna(r.ma60_slope) and r.ma60_slope > 0,
            pd.notna(r.ma120_slope) and r.ma120_slope > 0,
            pd.notna(r.ret120) and r.ret120 > 0.20,
            pd.notna(r.high_pos120) and r.high_pos120 > 0.65,
            pd.notna(r.drawdown120) and r.drawdown120 > -0.25,
        ]
        strong_score = sum(1 for x in strong_checks if x)
        strict_strong = all(strong_checks)
        is_strong = strong_score >= 6
        score = max(0, min(100, structure + momentum + slope + position - penalty))

        entry = 0
        state = _trend_state(r) if is_strong else "未分类"
        entry += {"回踩": 30, "延续": 26, "高位震荡": 18, "加速": 8, "趋势走弱": 0, "未分类": 10}.get(state, 0)
        entry += _score_bool(pd.notna(r.dist_ma20) and -0.03 <= r.dist_ma20 <= 0.06, 15)
        entry += _score_bool(pd.notna(r.dist_ma60) and 0 <= r.dist_ma60 <= 0.25, 12)
        entry += _score_bool(pd.notna(r.drawdown60) and -0.12 <= r.drawdown60 <= -0.03, 12)
        entry += _score_bool(pd.notna(r.ret20) and -0.03 <= r.ret20 <= 0.12, 10)
        entry += _score_bool(pd.notna(r.ma60_slope) and r.ma60_slope > 0, 8)
        entry += _score_bool(pd.notna(r.above_ma60_ratio_60) and r.above_ma60_ratio_60 > 0.70, 8)
        entry += _score_bool(pd.notna(r.amp20) and 0.06 <= r.amp20 <= 0.22, 5)

        overheat_penalty = 0
        overheat_penalty += _score_bool(pd.notna(r.dist_ma60) and r.dist_ma60 > 0.35, 12)
        overheat_penalty += _score_bool(pd.notna(r.dist_ma20) and r.dist_ma20 > 0.12, 8)
        overheat_penalty += _score_bool(pd.notna(r.ret20) and r.ret20 > 0.25, 8)
        overheat_penalty += _score_bool(state == "加速", 5)
        entry_score = int(max(0, min(100, entry - overheat_penalty)))
        strategy_score = int(max(0, min(100, round(score * 0.35 + entry_score * 0.45 + market_score * 0.20))))
        rr = r.to_dict()
        rr.update({
            "structure_score": structure,
            "momentum_score": momentum,
            "slope_score": slope,
            "position_score": position,
            "risk_penalty": penalty,
            "trend_score": int(score),
            "trend_level": _trend_level(int(score)),
            "entry_score": entry_score,
            "entry_level": _entry_level(entry_score),
            "overheat_penalty": int(overheat_penalty),
            "market_env_score": market_score,
            "market_env_level": market_level,
            "strategy_score": strategy_score,
            "strong_score": int(strong_score),
            "is_strict_strong_trend": bool(strict_strong),
            "is_strong_trend": bool(is_strong),
            "trend_state": state,
        })
        rows.append(rr)
    return pd.DataFrame(rows)


def _round_pct(v: Any) -> float | None:
    if v is None or pd.isna(v):
        return None
    return round(float(v) * 100, 2)


def fetch_strong_trend(end: str, top: int = 200, force: bool = False) -> dict[str, Any]:
    top = max(20, min(int(top or 200), 300))
    p = _cache_file(end, top)
    if p.exists() and not force:
        return json.loads(p.read_text(encoding="utf-8"))

    provider = TushareProvider()
    universe, mapping = load_universe(True)
    meta = universe.set_index("ts_code")[["name", "industry_name"]].to_dict("index")
    codes = set(universe["ts_code"].tolist())

    start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=520)).strftime("%Y%m%d")
    cal = provider.trade_cal(start, end)
    dates = sorted(cal[cal["is_open"].astype(int).eq(1)]["cal_date"].astype(str).tolist())
    dates = [d for d in dates if d <= end][-300:]

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
        raise RuntimeError("没有可用日K数据，请先检查 Tushare Token 或缓存。")

    df = pd.concat(frames, ignore_index=True)
    for c in ["open", "high", "low", "close", "pct_chg", "vol", "amount"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.sort_values(["ts_code", "trade_date"])

    latest = _add_scores(_calc_latest_features(df))
    latest = latest.sort_values(["is_strong_trend", "ret240", "trend_score", "strong_score"], ascending=[False, False, False, False])
    display = latest[latest["is_strong_trend"].eq(True)].sort_values(
        ["ret240", "trend_score", "strong_score"], ascending=[False, False, False]
    ).head(top).copy()

    items = []
    kline_map: dict[str, list[dict[str, Any]]] = {}
    for rank, (_, r) in enumerate(display.iterrows(), 1):
        code = str(r.ts_code)
        m = meta.get(code, {})
        item = {
            "rank": rank,
            "ts_code": code,
            "code": code.split(".")[0],
            "name": m.get("name", code),
            "industry": m.get("industry_name", "未分类"),
            "retYear": _round_pct(r.ret240),
            "ret240": _round_pct(r.ret240),
            "retHalf": _round_pct(r.ret120),
            "ret120": _round_pct(r.ret120),
            "retQuarter": _round_pct(r.ret60),
            "ret60": _round_pct(r.ret60),
            "retMonth": _round_pct(r.ret20),
            "ret20": _round_pct(r.ret20),
            "ret10": _round_pct(r.ret10),
            "drawdown": _round_pct(r.drawdown120),
            "drawdown60": _round_pct(r.drawdown60),
            "drawdown120": _round_pct(r.drawdown120),
            "highPos120": _round_pct(r.high_pos120),
            "amp20": _round_pct(r.amp20),
            "distMa20": _round_pct(r.dist_ma20),
            "distMa60": _round_pct(r.dist_ma60),
            "ma20Slope": _round_pct(r.ma20_slope),
            "ma60Slope": _round_pct(r.ma60_slope),
            "ma120Slope": _round_pct(r.ma120_slope),
            "aboveMa60Ratio60": _round_pct(r.above_ma60_ratio_60),
            "strongScore": int(r.strong_score),
            "isStrongTrend": bool(r.is_strong_trend),
            "isStrictStrongTrend": bool(r.is_strict_strong_trend),
            "status": r.trend_state,
            "trendState": r.trend_state,
            "trendScore": int(r.trend_score),
            "trendLevel": r.trend_level,
            "entryScore": int(r.entry_score),
            "entryLevel": r.entry_level,
            "overheatPenalty": int(r.overheat_penalty),
            "marketEnvScore": int(r.market_env_score),
            "marketEnvLevel": r.market_env_level,
            "strategyScore": int(r.strategy_score),
            "structureScore": int(r.structure_score),
            "momentumScore": int(r.momentum_score),
            "slopeScore": int(r.slope_score),
            "positionScore": int(r.position_score),
            "riskPenalty": int(r.risk_penalty),
            "ret120RankPct": _round_pct(r.ret120_rank_pct),
            "latestClose": round(float(r.close), 3),
            "latestAmount": _money_yuan(float(r.get("amount") or 0)),
        }
        items.append(item)
        kline_map[code] = [
            {
                "date": str(x["trade_date"]),
                "open": round(float(x["open"]), 3),
                "high": round(float(x["high"]), 3),
                "low": round(float(x["low"]), 3),
                "close": round(float(x["close"]), 3),
                "amount": _money_yuan(float(x.get("amount") or 0)),
                "pct_chg": round(float(x.get("pct_chg") or 0), 3),
            }
            for x in r.kline
        ]

    industry_rows = []
    if items:
        tmp = pd.DataFrame(items)
        for industry, g in tmp.groupby("industry"):
            industry_rows.append({
                "industry": industry,
                "count": int(len(g)),
                "avgRetYear": round(float(g["retYear"].dropna().mean() or 0), 2),
                "avgScore": round(float(g["trendScore"].mean()), 2),
            })
        industry_rows.sort(key=lambda x: (x["count"], x["avgScore"]), reverse=True)

    counts = pd.Series([item["status"] for item in items]).value_counts().to_dict() if items else {}
    strict_count = int(latest["is_strict_strong_trend"].sum()) if len(latest) else 0
    loose_count = int(latest["is_strong_trend"].sum()) if len(latest) else 0
    selected = items[0] if items else None

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
            "poolCount": len(items),
            "strictStrongCount": strict_count,
            "looseStrongCount": loose_count,
            "industryCount": len(industry_rows),
            "topName": selected["name"] if selected else "--",
            "topRetYear": selected["retYear"] if selected and selected["retYear"] is not None else 0,
            "topScore": selected["trendScore"] if selected else 0,
            "topStrategyScore": int(display["strategy_score"].max()) if len(display) else 0,
            "marketEnvScore": int(display["market_env_score"].iloc[0]) if len(display) else 0,
            "marketEnvLevel": str(display["market_env_level"].iloc[0]) if len(display) else "--",
        },
        "items": items,
        "industryDistribution": industry_rows[:20],
        "kline": {item["ts_code"]: kline_map.get(item["ts_code"], []) for item in items},
        "statusCounts": {str(k): int(v) for k, v in counts.items()},
        "statusRule": "先计算 MA/收益率/高低点/回撤/位置/斜率/震荡/站上60日线比例；以 strong_score>=6 识别宽松强趋势，完整条件识别严格强趋势；展示池不区分严格或宽松，统一在 is_strong_trend=true 的股票中按240日涨幅取前200；trend_score 衡量趋势质量，entry_score 衡量当前买点性价比，market_env_score 给出全局仓位环境，strategy_score 用于趋势交易综合排序；只对强趋势上涨股按趋势走弱、加速、回踩、高位震荡、延续、未分类优先级分类。",
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
