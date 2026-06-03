# 字段映射

默认字段映射见 `config.py`：

```python
FIELD_MAP = {
    "date": "trade_date",
    "code": "ts_code",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "amount": "amount",
    "volume": "vol",
    "pctChg": "pct_chg",
    "pre_close": "pre_close",
    "tradestatus": "tradestatus",
    "isST": "isST",
    "industry_l1": "industry_l1",
}
```

当前父项目 Tushare 日线 `amount` 单位按千元处理，程序会乘以 1000 后用于成交额过滤。

股票池会自动识别 `code`，并将 `sh.600000` 转换为 `600000.SH`，以匹配 Tushare 日线代码。
