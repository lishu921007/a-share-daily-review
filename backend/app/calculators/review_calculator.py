import math
import pandas as pd
from app.calculators.rules import classify

def _num(df, cols):
    for c in cols:
        if c in df.columns: df[c]=pd.to_numeric(df[c], errors='coerce').fillna(0)

def _ratio(a,b): return float(a)/float(b) if b else 0.0

def _fmt_pct(x): return f"{x*100:.2f}%"
def _fmt_chg(x): return f"{x:+.2f}%"
def _fmt_money(x):
    x=float(x or 0)
    return f"{x/10000:.2f}亿元" if abs(x)>=10000 else f"{x:.2f}万元"

def calculate_review(trade_date: str, universe: pd.DataFrame, daily: pd.DataFrame, moneyflow: pd.DataFrame, stk_limit: pd.DataFrame):
    daily=daily.copy(); moneyflow=moneyflow.copy(); stk_limit=stk_limit.copy()
    _num(daily,['pct_chg','close','amount','vol','open','high','low','pre_close','change'])
    mf_cols=['buy_sm_amount','sell_sm_amount','buy_md_amount','sell_md_amount','buy_lg_amount','sell_lg_amount','buy_elg_amount','sell_elg_amount','net_mf_amount']
    _num(moneyflow,mf_cols)
    base=universe[['ts_code','name','industry_name']].drop_duplicates('ts_code')
    merged=base.merge(daily, on='ts_code', how='left', suffixes=('','_daily'))
    valid=merged[merged['pct_chg'].notna()].copy()
    valid_count=len(valid); universe_count=len(base)
    if valid_count == 0: raise ValueError(f"{trade_date} 没有可参与计算的有效日K数据。")
    limit_method='stk_limit'
    if not stk_limit.empty and {'ts_code','up_limit','down_limit'}.issubset(stk_limit.columns):
        _num(stk_limit,['up_limit','down_limit'])
        valid=valid.merge(stk_limit[['ts_code','up_limit','down_limit']],on='ts_code',how='left')
        valid['is_limit_up']=valid['up_limit'].gt(0) & (valid['close'] >= valid['up_limit'] - 1e-4)
        valid['is_limit_down']=valid['down_limit'].gt(0) & (valid['close'] <= valid['down_limit'] + 1e-4)
    else:
        limit_method='pct_chg_estimated'
        valid['is_limit_up']=valid['pct_chg'] >= 9.8
        valid['is_limit_down']=valid['pct_chg'] <= -9.8
    mf=base.merge(moneyflow, on='ts_code', how='left')
    for c in mf_cols: 
        if c not in mf.columns: mf[c]=0
    mf['elg_net_amount']=mf['buy_elg_amount']-mf['sell_elg_amount']
    mf['lg_net_amount']=mf['buy_lg_amount']-mf['sell_lg_amount']
    mf['md_net_amount']=mf['buy_md_amount']-mf['sell_md_amount']
    mf['sm_net_amount']=mf['buy_sm_amount']-mf['sell_sm_amount']
    mf['main_net_amount']=mf['elg_net_amount']+mf['lg_net_amount']
    mf_valid=mf[mf['net_mf_amount'].notna()].copy()
    mf_count=len(mf_valid)
    up_count=int((valid['pct_chg']>0).sum()); down_count=int((valid['pct_chg']<0).sum()); flat_count=int((valid['pct_chg']==0).sum())
    gt3=int((valid['pct_chg']>3).sum()); lt3=int((valid['pct_chg']<-3).sum())
    review={
        'trade_date': trade_date,
        'valid_stock_count': valid_count, 'universe_stock_count': universe_count, 'data_coverage_ratio': _ratio(valid_count, universe_count),
        'up_count': up_count, 'down_count': down_count, 'flat_count': flat_count,
        'up_ratio': _ratio(up_count, valid_count), 'down_ratio': _ratio(down_count, valid_count), 'flat_ratio': _ratio(flat_count, valid_count),
        'median_pct_chg': float(valid['pct_chg'].median()), 'mean_pct_chg': float(valid['pct_chg'].mean()),
        'gt_3_count': gt3, 'lt_minus_3_count': lt3, 'gt_3_ratio': _ratio(gt3, valid_count), 'lt_minus_3_ratio': _ratio(lt3, valid_count),
        'limit_up_count': int(valid['is_limit_up'].sum()), 'limit_down_count': int(valid['is_limit_down'].sum()), 'limit_calc_method': limit_method,
        'total_net_mf_amount': float(mf_valid['net_mf_amount'].sum()) if mf_count else 0.0,
        'main_net_mf_amount': float(mf_valid['main_net_amount'].sum()) if mf_count else 0.0,
        'elg_net_mf_amount': float(mf_valid['elg_net_amount'].sum()) if mf_count else 0.0,
        'lg_net_mf_amount': float(mf_valid['lg_net_amount'].sum()) if mf_count else 0.0,
        'md_net_mf_amount': float(mf_valid['md_net_amount'].sum()) if mf_count else 0.0,
        'sm_net_mf_amount': float(mf_valid['sm_net_amount'].sum()) if mf_count else 0.0,
        'main_net_positive_count': int((mf_valid['main_net_amount']>0).sum()) if mf_count else 0,
        'main_net_positive_ratio': _ratio(int((mf_valid['main_net_amount']>0).sum()), mf_count),
        'net_mf_positive_count': int((mf_valid['net_mf_amount']>0).sum()) if mf_count else 0,
        'net_mf_positive_ratio': _ratio(int((mf_valid['net_mf_amount']>0).sum()), mf_count),
        'moneyflow_coverage_ratio': _ratio(mf_count, universe_count),
    }
    market_state, price_state, moneyflow_state, risk_level = classify(review)
    review.update({'market_state':market_state,'price_state':price_state,'moneyflow_state':moneyflow_state,'risk_level':risk_level})
    review['summary_text']=(f"今日市场处于{market_state}，上涨个股占比为 {_fmt_pct(review['up_ratio'])}，"
        f"涨跌幅中位数为 {_fmt_chg(review['median_pct_chg'])}。涨超3%个股占比 {_fmt_pct(review['gt_3_ratio'])}，"
        f"跌超3%个股占比 {_fmt_pct(review['lt_minus_3_ratio'])}。资金面{moneyflow_state}，"
        f"主力净流为 {_fmt_money(review['main_net_mf_amount'])}，主力净流为正个股占比 {_fmt_pct(review['main_net_positive_ratio'])}。")
    both=valid.merge(mf[['ts_code','main_net_amount','elg_net_amount','lg_net_amount','net_mf_amount']],on='ts_code',how='left')
    inds=[]
    for name,g in both.groupby('industry_name'):
        n=len(g); stock_count=int((base['industry_name']==name).sum())
        item={'industry_name':name,'stock_count':stock_count,'valid_stock_count':n,
            'up_ratio':_ratio(int((g['pct_chg']>0).sum()),n),'down_ratio':_ratio(int((g['pct_chg']<0).sum()),n),
            'median_pct_chg':float(g['pct_chg'].median()),'mean_pct_chg':float(g['pct_chg'].mean()),
            'gt_3_ratio':_ratio(int((g['pct_chg']>3).sum()),n),'lt_minus_3_ratio':_ratio(int((g['pct_chg']<-3).sum()),n),
            'limit_up_count':int(g['is_limit_up'].sum()),'limit_down_count':int(g['is_limit_down'].sum()),
            'total_net_mf_amount':float(g['net_mf_amount'].fillna(0).sum()),'main_net_mf_amount':float(g['main_net_amount'].fillna(0).sum()),
            'elg_net_mf_amount':float(g['elg_net_amount'].fillna(0).sum()),'lg_net_mf_amount':float(g['lg_net_amount'].fillna(0).sum()),
            'main_net_positive_ratio':_ratio(int((g['main_net_amount'].fillna(0)>0).sum()),n)}
        inds.append(item)
    ind_df=pd.DataFrame(inds)
    if not ind_df.empty:
        for col in ['up_ratio','median_pct_chg','main_net_mf_amount','elg_net_mf_amount','main_net_positive_ratio']:
            ind_df[col+'_rank_pct']=ind_df[col].rank(pct=True)
        ind_df['resonance_score']=(ind_df['up_ratio_rank_pct']*25+ind_df['median_pct_chg_rank_pct']*20+ind_df['main_net_mf_amount_rank_pct']*25+ind_df['elg_net_mf_amount_rank_pct']*15+ind_df['main_net_positive_ratio_rank_pct']*15).round(2)
    industries=ind_df.drop(columns=[c for c in ind_df.columns if c.endswith('_rank_pct')], errors='ignore').sort_values('resonance_score',ascending=False).to_dict('records') if not ind_df.empty else []
    review['industries']=industries
    review['industry_resonance_top']=industries[:10]
    review['industry_moneyflow_top']=sorted(industries,key=lambda x:x['main_net_mf_amount'], reverse=True)[:10]
    review['industry_price_width_top']=sorted(industries,key=lambda x:x['up_ratio'], reverse=True)[:10]
    review['industry_weak_top']=sorted(industries,key=lambda x:(x['up_ratio'], x['median_pct_chg']))[:10]
    return review
