from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import json
from app import config
from app.services.universe import load_universe
from app.data_providers.tushare_provider import TushareProvider, DataProviderError
from app.calculators.review_calculator import calculate_review
from app.db.index import upsert_review, list_reviews
from app.services.limitup_review import fetch_limitup_review
from app.services.strong_trend import fetch_strong_trend
from app.services.pattern_signals import fetch_base_on_base_signals

router=APIRouter(prefix='/api', tags=['review'])
class UpdateRequest(BaseModel):
    trade_date: str = Field(..., pattern=r'^\d{8}$')
    force: bool = False

def _json_path(trade_date): return config.PROCESSED_REVIEW_DIR / f'{trade_date}.json'
def _read_review(trade_date):
    p=_json_path(trade_date)
    if not p.exists(): return None
    return json.loads(p.read_text(encoding='utf-8'))

def _save_review(trade_date, payload):
    p=_json_path(trade_date); p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    upsert_review(trade_date, str(p), payload)

@router.get('/health')
def health(): return {'status':'ok','service':'a-share-daily-review'}

@router.get('/trade/latest')
def latest_trade():
    try: return {'trade_date': TushareProvider().latest_trade_date()}
    except Exception as e: raise HTTPException(400, f'获取最近交易日失败：{e}')

@router.post('/review/update')
def update_review(req: UpdateRequest):
    try:
        universe, mapping = load_universe(True)
        provider=TushareProvider()
        if not config.LOCAL_DATA_MODE and not provider.is_trade_day(req.trade_date):
            raise ValueError(f'{req.trade_date} 不是交易日。')
        cached=_read_review(req.trade_date)
        if cached and not req.force:
            cached['cache_hit']=True; return cached
        daily=provider.fetch_daily(req.trade_date, req.force)
        moneyflow=provider.fetch_moneyflow(req.trade_date, req.force)
        stk_limit=provider.fetch_stk_limit(req.trade_date, req.force)
        review=calculate_review(req.trade_date, universe, daily, moneyflow, stk_limit)
        review['universe_field_mapping']=mapping
        review['cache_hit']=False
        _save_review(req.trade_date, review)
        return review
    except (DataProviderError, FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f'更新复盘失败：{e}')

@router.get('/review/daily')
def daily_review(trade_date: str = Query(..., pattern=r'^\d{8}$')):
    r=_read_review(trade_date)
    if not r: raise HTTPException(404, f'未找到 {trade_date} 的复盘结果，请先更新该交易日。')
    return r

@router.get('/review/list')
def review_list(limit: int = 60): return {'items': list_reviews(limit)}

@router.get('/review/trend')
def review_trend(start_date: str, end_date: str):
    items=[]
    for p in sorted(config.PROCESSED_REVIEW_DIR.glob('*.json')):
        d=p.stem
        if start_date <= d <= end_date:
            r=json.loads(p.read_text(encoding='utf-8'))
            items.append({k:r.get(k) for k in ['trade_date','market_state','risk_level','up_ratio','median_pct_chg','main_net_mf_amount','main_net_positive_ratio','data_coverage_ratio','moneyflow_coverage_ratio']})
    return {'items': items}

@router.get('/limitup/review')
def limitup_review(end: str, days: int = 60, force: bool = False):
    try:
        return fetch_limitup_review(end=end, days=days, force=force)
    except Exception as e:
        raise HTTPException(400, str(e))

@router.get('/trend/strong')
def strong_trend(end: str, top: int = 200, force: bool = False):
    try:
        return fetch_strong_trend(end=end, top=top, force=force)
    except Exception as e:
        raise HTTPException(400, str(e))

@router.get('/pattern/base-on-base')
def base_on_base_signals(days: int = 100, kline_days: int = 180, kline_limit: int = 50):
    try:
        return fetch_base_on_base_signals(days=days, kline_days=kline_days, kline_limit=kline_limit)
    except Exception as e:
        raise HTTPException(400, str(e))

@router.post('/data/import')
def data_import():
    return {'message':'请将 daily/moneyflow/stk_limit CSV 放到 data/raw 对应目录，文件名为 YYYYMMDD.csv；股票池放到 data/universe/a_stock_universe.csv。'}
