from pathlib import Path
import pandas as pd
from app import config

class DataProviderError(RuntimeError): pass

class TushareProvider:
    def __init__(self):
        if config.LOCAL_DATA_MODE:
            self.pro = None; return
        if not config.TUSHARE_TOKEN or "请填写" in config.TUSHARE_TOKEN:
            raise DataProviderError("Tushare Token 未配置。请复制 backend/.env.example 为 backend/.env 并填写 TUSHARE_TOKEN。")
        try:
            import tushare as ts
            ts.set_token(config.TUSHARE_TOKEN)
            self.pro = ts.pro_api()
        except Exception as e:
            raise DataProviderError(f"Tushare 初始化失败：{e}")

    def _cache_path(self, kind, trade_date):
        mp={"daily":config.RAW_DAILY_DIR,"moneyflow":config.RAW_MONEYFLOW_DIR,"stk_limit":config.RAW_LIMIT_DIR}
        return mp[kind] / f"{trade_date}.parquet"

    def _read_cache(self, kind, trade_date):
        p=self._cache_path(kind, trade_date)
        if p.exists(): return pd.read_parquet(p)
        csv=p.with_suffix('.csv')
        if csv.exists(): return pd.read_csv(csv, dtype={"trade_date":str})
        return None

    def _write_cache(self, kind, trade_date, df):
        p=self._cache_path(kind, trade_date)
        try: df.to_parquet(p, index=False)
        except Exception: df.to_csv(p.with_suffix('.csv'), index=False)

    def trade_cal(self, start_date=None, end_date=None):
        if config.LOCAL_DATA_MODE:
            raise DataProviderError("本地数据模式下未提供交易日历，请关闭 LOCAL_DATA_MODE 或导入日历。")
        return self.pro.trade_cal(exchange='', start_date=start_date, end_date=end_date, fields='cal_date,is_open,pretrade_date')

    def latest_trade_date(self):
        import datetime as dt
        end=dt.datetime.now().strftime('%Y%m%d')
        start=(dt.datetime.now()-dt.timedelta(days=30)).strftime('%Y%m%d')
        cal=self.trade_cal(start,end)
        opens=cal[cal['is_open'].astype(int).eq(1)]['cal_date'].astype(str).tolist()
        if not opens: raise DataProviderError("最近30天未获取到交易日历。")
        return max(opens)

    def is_trade_day(self, trade_date):
        cal=self.trade_cal(trade_date, trade_date)
        return not cal.empty and int(cal.iloc[0]['is_open']) == 1

    def fetch_daily(self, trade_date, force=False):
        c=self._read_cache('daily',trade_date)
        if c is not None and not force: return c
        if config.LOCAL_DATA_MODE: raise DataProviderError(f"本地缺少 daily 缓存：{trade_date}")
        df=self.pro.daily(trade_date=trade_date, fields='ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount')
        if df is None or df.empty: raise DataProviderError(f"当日 daily 数据缺失：{trade_date}")
        self._write_cache('daily',trade_date,df); return df

    def fetch_moneyflow(self, trade_date, force=False):
        c=self._read_cache('moneyflow',trade_date)
        if c is not None and not force: return c
        if config.LOCAL_DATA_MODE: raise DataProviderError(f"本地缺少 moneyflow 缓存：{trade_date}")
        fields='ts_code,trade_date,buy_sm_amount,sell_sm_amount,buy_md_amount,sell_md_amount,buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount,net_mf_amount'
        df=self.pro.moneyflow(trade_date=trade_date, fields=fields)
        if df is None or df.empty: raise DataProviderError(f"当日 moneyflow 数据缺失或接口无权限：{trade_date}")
        self._write_cache('moneyflow',trade_date,df); return df

    def fetch_stk_limit(self, trade_date, force=False):
        c=self._read_cache('stk_limit',trade_date)
        if c is not None and not force: return c
        if config.LOCAL_DATA_MODE: return pd.DataFrame()
        try:
            df=self.pro.stk_limit(trade_date=trade_date, fields='ts_code,trade_date,up_limit,down_limit')
            if df is None: df=pd.DataFrame()
            if not df.empty: self._write_cache('stk_limit',trade_date,df)
            return df
        except Exception:
            return pd.DataFrame()
