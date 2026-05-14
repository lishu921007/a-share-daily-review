import sqlite3, json
from datetime import datetime
from app.config import DB_PATH

def conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS review_index(
        trade_date TEXT PRIMARY KEY,
        market_state TEXT,
        risk_level TEXT,
        summary_text TEXT,
        valid_stock_count INTEGER,
        universe_stock_count INTEGER,
        updated_at TEXT,
        payload_path TEXT
    )""")
    return c

def upsert_review(trade_date: str, payload_path: str, review: dict):
    with conn() as c:
        c.execute("""INSERT INTO review_index VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(trade_date) DO UPDATE SET market_state=excluded.market_state,risk_level=excluded.risk_level,
        summary_text=excluded.summary_text,valid_stock_count=excluded.valid_stock_count,universe_stock_count=excluded.universe_stock_count,
        updated_at=excluded.updated_at,payload_path=excluded.payload_path""", (
            trade_date, review.get("market_state"), review.get("risk_level"), review.get("summary_text"),
            review.get("valid_stock_count"), review.get("universe_stock_count"), datetime.now().isoformat(timespec="seconds"), payload_path
        ))

def list_reviews(limit: int = 60):
    with conn() as c:
        cur = c.execute("SELECT trade_date,market_state,risk_level,summary_text,valid_stock_count,universe_stock_count,updated_at FROM review_index ORDER BY trade_date DESC LIMIT ?", (limit,))
        cols=[d[0] for d in cur.description]
        return [dict(zip(cols,row)) for row in cur.fetchall()]
