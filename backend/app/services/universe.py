from pathlib import Path
from datetime import datetime
import pandas as pd
from app.config import UNIVERSE_PATH

LAST_LOAD = None
LAST_MAPPING = None

CODE_FIELDS = ["ts_code", "code", "symbol", "证券代码", "股票代码"]
NAME_FIELDS = ["name", "stock_name", "code_name", "证券简称", "股票名称"]
INDUSTRY_FIELDS = ["industry", "industry_name", "sw_industry", "ths_industry", "industry_L2_name", "industry_L1_name", "行业", "申万行业"]

def _pick(cols, candidates):
    lower = {c.lower(): c for c in cols}
    for x in candidates:
        if x in cols: return x
        if x.lower() in lower: return lower[x.lower()]
    return None

def normalize_code(value: str) -> str:
    s = str(value).strip()
    if not s or s.lower() == "nan": return ""
    s = s.replace(" ", "")
    if "." in s and len(s.split(".")) == 2:
        a,b = s.split(".")
        if a.lower() in {"sh","sz","bj"}: return f"{b.zfill(6)}.{a.upper()}"
        if b.upper() in {"SH","SZ","BJ"}: return f"{a.zfill(6)}.{b.upper()}"
    digits = ''.join(ch for ch in s if ch.isdigit())
    if len(digits) >= 6: digits = digits[-6:]
    if digits.startswith(("000","001","002","003","300")): suffix="SZ"
    elif digits.startswith(("600","601","603","605","688")): suffix="SH"
    elif digits.startswith(("8","4","9")): suffix="BJ"
    else: suffix="SZ"
    return f"{digits}.{suffix}" if digits else ""

def load_universe(force: bool=False):
    global LAST_LOAD, LAST_MAPPING
    if not UNIVERSE_PATH.exists():
        raise FileNotFoundError(f"股票池文件不存在：{UNIVERSE_PATH}。请放置 data/universe/a_stock_universe.csv")
    df = pd.read_csv(UNIVERSE_PATH, dtype=str).fillna("")
    code_col = _pick(df.columns, CODE_FIELDS)
    name_col = _pick(df.columns, NAME_FIELDS)
    industry_col = _pick(df.columns, INDUSTRY_FIELDS)
    missing=[]
    if not code_col: missing.append("股票代码")
    if not name_col: missing.append("股票名称")
    if not industry_col: missing.append("行业名称")
    if missing:
        raise ValueError(f"a_stock_universe.csv 字段无法识别，缺少：{', '.join(missing)}。当前字段：{', '.join(df.columns)}")
    work = df.copy()
    work["ts_code"] = work[code_col].map(normalize_code)
    work["name"] = work[name_col].astype(str).str.strip()
    work["industry_name"] = work[industry_col].astype(str).str.strip().replace("", "未分类")
    if "if_out" in work.columns:
        work = work[work["if_out"].astype(str).str.strip().isin(["0", "", "False", "false"])]
    if "status" in work.columns:
        bad={"退市","暂停上市","终止上市","D","delisted","inactive"}
        work = work[~work["status"].astype(str).str.strip().isin(bad)]
    work = work[work["ts_code"].ne("")].drop_duplicates("ts_code")
    mapping = {"code": code_col, "name": name_col, "industry": industry_col, "recognized_fields": list(df.columns)}
    LAST_LOAD = datetime.now().isoformat(timespec="seconds")
    LAST_MAPPING = mapping
    return work[["ts_code","name","industry_name"] + [c for c in ["tradestatus","status","if_out"] if c in work.columns]], mapping

def info():
    df, mapping = load_universe(True)
    return {
        "exists": UNIVERSE_PATH.exists(),
        "path": str(UNIVERSE_PATH),
        "stock_count": int(len(df)),
        "industry_count": int(df["industry_name"].nunique()),
        "field_mapping": mapping,
        "last_loaded_at": LAST_LOAD,
        "sample": df.head(5).to_dict("records"),
    }
