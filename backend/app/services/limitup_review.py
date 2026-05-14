import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from app.config import CACHE_DIR
from app.data_providers.tushare_provider import TushareProvider
from app.services.universe import load_universe


def _cache_file(end: str, days: int) -> Path:
    d = CACHE_DIR / "limitup_review_tushare"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{end}_{days}.json"


def _date_label(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def _safe_float(v, default=0.0):
    try:
        if pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default


def _safe_int(v, default=0):
    try:
        if pd.isna(v):
            return default
        return int(v)
    except Exception:
        return default


def _money_amount_to_yuan(amount_in_thousand_yuan: float) -> float:
    # Tushare daily.amount 单位是千元，前端 money() 输入单位为万元。
    return float(amount_in_thousand_yuan or 0) * 1000


def _is_st_name(name: str) -> bool:
    """自行判断 ST / *ST / SST / 退市整理股名称，避免污染连板情绪口径。"""
    s = str(name or "").upper().replace(" ", "")
    return s.startswith("ST") or s.startswith("*ST") or s.startswith("SST") or s.startswith("S*ST") or "退" in s


def fetch_limitup_review(end: str, days: int = 60, force: bool = False) -> dict:
    """用 Tushare daily + stk_limit + a_stock_universe.csv 实际计算情绪温度与涨停天梯。

    不使用截图样本；不展示封单等日K/stk_limit无法计算字段。
    """
    days = max(int(days or 60), 60)
    p = _cache_file(end, days)
    if p.exists() and not force:
        return json.loads(p.read_text(encoding="utf-8"))

    provider = TushareProvider()
    universe, mapping = load_universe(True)
    universe_map = universe.set_index("ts_code")[["name", "industry_name"]].to_dict("index")
    st_codes = {code for code, meta in universe_map.items() if _is_st_name(meta.get("name", ""))}
    universe_codes = set(universe["ts_code"].tolist()) - st_codes

    start = (datetime.strptime(end, "%Y%m%d") - timedelta(days=140)).strftime("%Y%m%d")
    cal = provider.trade_cal(start, end)
    trade_dates = cal[cal["is_open"].astype(int).eq(1)]["cal_date"].astype(str).tolist()
    trade_dates = sorted([d for d in trade_dates if d <= end])[-days:]

    rows = []
    prev_streak: dict[str, int] = {}
    prev_start: dict[str, str] = {}
    for trade_date in trade_dates:
        try:
            daily = provider.fetch_daily(trade_date, force=False)
        except Exception as e:
            rows.append(_empty_row(trade_date, f"daily缺失：{e}"))
            prev_streak = {}
            prev_start = {}
            continue
        limit = provider.fetch_stk_limit(trade_date, force=False)
        daily = daily[daily["ts_code"].isin(universe_codes)].copy()
        for c in ["close", "pct_chg", "amount", "pre_close"]:
            if c in daily.columns:
                daily[c] = pd.to_numeric(daily[c], errors="coerce")
        if not limit.empty and {"ts_code", "up_limit", "down_limit"}.issubset(limit.columns):
            limit = limit.copy()
            limit["up_limit"] = pd.to_numeric(limit["up_limit"], errors="coerce")
            limit["down_limit"] = pd.to_numeric(limit["down_limit"], errors="coerce")
            daily = daily.merge(limit[["ts_code", "up_limit", "down_limit"]], on="ts_code", how="left")
            daily["is_limit_up"] = daily["up_limit"].gt(0) & (daily["close"] >= daily["up_limit"] - 1e-4)
            daily["is_limit_down"] = daily["down_limit"].gt(0) & (daily["close"] <= daily["down_limit"] + 1e-4)
            # ST 股涨跌停幅度通常约为 5%。用户提供的股票池不含 ST 标识，因此按当日涨停价/昨收价自行识别。
            ratio = daily["up_limit"] / daily["pre_close"].replace(0, pd.NA)
            daily["is_st_like_limit"] = ratio.between(1.045, 1.055, inclusive="both")
            calc_method = "stk_limit"
        else:
            daily["is_limit_up"] = daily["pct_chg"] >= 9.8
            daily["is_limit_down"] = daily["pct_chg"] <= -9.8
            # 无 stk_limit 时无法直接取涨停价幅度，降级用涨幅约 5% 识别 ST 涨停。
            daily["is_st_like_limit"] = daily["pct_chg"].between(4.7, 5.3, inclusive="both")
            calc_method = "pct_chg_estimated"

        current_streak: dict[str, int] = {}
        current_start: dict[str, str] = {}
        pool = []
        # 连板天梯和连板奖励剔除 ST：名称识别 + 涨停幅度约5%识别。
        daily["is_st_by_name"] = daily["ts_code"].isin(st_codes)
        daily["is_st_excluded"] = daily["is_st_by_name"] | daily["is_st_like_limit"].fillna(False)
        limit_up_df = daily[daily["is_limit_up"] & ~daily["is_st_excluded"]].copy()
        for _, r in limit_up_df.iterrows():
            code = str(r["ts_code"])
            streak = prev_streak.get(code, 0) + 1
            start_date = prev_start.get(code, trade_date) if prev_streak.get(code, 0) else trade_date
            current_streak[code] = streak
            current_start[code] = start_date
            meta = universe_map.get(code, {})
            pool.append({
                "ts_code": code,
                "code": code.split(".")[0],
                "name": meta.get("name", code),
                "price": _safe_float(r.get("close")),
                "changePercent": _safe_float(r.get("pct_chg")),
                "amount": _money_amount_to_yuan(_safe_float(r.get("amount"))),
                "industry": meta.get("industry_name", "未分类"),
                "streak": streak,
                "startDate": start_date,
                "startLabel": _date_label(start_date),
                "endDate": trade_date,
                "endLabel": _date_label(trade_date),
                "duration": streak,
                "roles": [],
                "dataSource": calc_method,
            })
        max_streak = max([x["streak"] for x in pool] or [0])
        for x in pool:
            if max_streak > 0 and x["streak"] == max_streak:
                x["roles"] = [{"type": "leader", "label": "最高标"}]
        pool.sort(key=lambda x: (-x["streak"], -x["amount"], x["code"]))
        ladder = [x for x in pool if x["streak"] >= 3]
        limit_up_count = len(pool)
        limit_down_count = int(daily["is_limit_down"].sum())
        third_count = len(ladder)
        # 自有情绪口径：基础涨跌停温度 + 连板扩散奖励。只依赖实际计算字段。
        emotion = limit_up_count - limit_down_count + third_count * 2 + max(max_streak - 2, 0) * 3
        rows.append({
            "date": trade_date,
            "label": _date_label(trade_date),
            "available": True,
            "provider": "tushare",
            "calcMethod": calc_method,
            "limitUpCount": limit_up_count,
            "limitDownCount": limit_down_count,
            "limitUpScore": limit_up_count + third_count * 2 + max(max_streak - 2, 0) * 3,
            "limitDownScore": limit_down_count,
            "mood": emotion,
            "thirdBoardPlusCount": third_count,
            "maxStreak": max_streak,
            "leaderNames": "、".join([x["name"] for x in pool if x["streak"] == max_streak]) if max_streak else "--",
            "ladder": ladder,
            "candidatePool": pool,
        })
        prev_streak = current_streak
        prev_start = current_start

    selected = next((x for x in rows if x["date"] == end), rows[-1] if rows else None)
    leader_segments = _build_leader_segments(rows)
    payload = {
        "source": "tushare_calculated",
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "requestedDays": days,
        "availableDays": len([r for r in rows if r.get("available")]),
        "rows": rows,
        "leaderSegments": leader_segments,
        "leaderSegmentsWindow": _build_leader_segments(rows[-20:]),
        "selectedDay": summarize_day(selected),
        "universeFieldMapping": mapping,
        "emotionFormula": "先剔除 ST：优先按 stk_limit 涨停幅度约5%识别，缺失时用 pct_chg 约5%估算，并辅以名称规则；emotion = 涨停数量 - 跌停数量 + 三板以上数量×2 + max(最高连板-2,0)×3",
        "displayLimitations": "本模块只展示 Tushare daily/stk_limit 可计算字段，不展示封单、首次封板时间等盘口字段；连板天梯和最高连板持续条已按5%涨停幅度剔除 ST 股。", 
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _build_leader_segments(rows: list[dict]) -> list[dict]:
    date_to_index = {r.get("date"): i for i, r in enumerate(rows)}
    segments = []
    for idx, row in enumerate(rows):
        next_pool = [] if idx + 1 >= len(rows) else rows[idx + 1].get("candidatePool", [])
        next_by_code = {s.get("ts_code") or s.get("code"): s for s in next_pool}
        for stock in row.get("candidatePool", []):
            code = stock.get("ts_code") or stock.get("code")
            streak = _safe_int(stock.get("streak"))
            if streak < 3:
                continue
            nxt = next_by_code.get(code)
            if nxt and _safe_int(nxt.get("streak")) > streak:
                continue  # 连板仍在延续，只在结束日画一次完整持续条
            start_date = stock.get("startDate") or row.get("date")
            start_index = date_to_index.get(start_date, max(0, idx - streak + 1))
            segments.append({
                "code": stock.get("code"),
                "ts_code": stock.get("ts_code"),
                "name": stock.get("name"),
                "industry": stock.get("industry"),
                "startDate": start_date,
                "startLabel": _date_label(start_date),
                "endDate": row.get("date"),
                "endLabel": row.get("label"),
                "startIndex": start_index,
                "endIndex": idx,
                "duration": idx - start_index + 1,
                "maxStreak": streak,
            })
    segments.sort(key=lambda x: (-x["maxStreak"], -x["endIndex"], x["startIndex"], x["name"] or ""))
    return segments[:12]


def _empty_row(trade_date: str, reason: str) -> dict:
    return {
        "date": trade_date,
        "label": _date_label(trade_date),
        "available": False,
        "provider": "tushare",
        "error": reason,
        "limitUpCount": 0,
        "limitDownCount": 0,
        "limitUpScore": 0,
        "limitDownScore": 0,
        "mood": 0,
        "thirdBoardPlusCount": 0,
        "maxStreak": 0,
        "leaderNames": "--",
        "ladder": [],
        "candidatePool": [],
    }


def summarize_day(r: dict | None) -> dict | None:
    if not r:
        return None
    return {
        "date": r.get("date"),
        "label": r.get("label"),
        "limitUpCount": _safe_int(r.get("limitUpCount")),
        "limitDownCount": _safe_int(r.get("limitDownCount")),
        "emotionValue": _safe_int(r.get("mood")),
        "thirdBoardPlusCount": _safe_int(r.get("thirdBoardPlusCount")),
        "maxStreak": _safe_int(r.get("maxStreak")),
        "leaderNames": r.get("leaderNames") or "--",
    }
