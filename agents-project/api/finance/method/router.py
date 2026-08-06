import datetime
import logging
import os
import time
import threading

os.environ["TQDM_DISABLE"] = "1"

import akshare as ak
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/finance/method", tags=["金融数据方法"])

_cache = {"data": None}

# ── 交易日历 ──────────────────────────────────────────
_TRADE_CALENDAR: set[str] = set()
_CALENDAR_LOCK = threading.Lock()
_CALENDAR_FETCHED_AT: float = 0
_CALENDAR_TTL = 86400  # 24h 重新拉一次

# A 股交易时段（北京时间）
_MORNING = ("09:30", "11:30")
_AFTERNOON = ("13:00", "15:00")


def _ensure_calendar():
    """懒加载交易日历，每年拉一次。"""
    global _CALENDAR_FETCHED_AT
    now = time.time()
    if _CALENDAR_FETCHED_AT and now - _CALENDAR_FETCHED_AT < _CALENDAR_TTL:
        return
    with _CALENDAR_LOCK:
        if _CALENDAR_FETCHED_AT and now - _CALENDAR_FETCHED_AT < _CALENDAR_TTL:
            return
        try:
            # 拉今年 + 去年，覆盖年初/年末边界
            records: list[str] = []
            for year in (2025, 2026):
                df = ak.tool_trade_date_hist_sse(year=year)
                open_days = df[df["is_open"] == 1]["trade_date"]
                records.extend(open_days.dt.strftime("%Y-%m-%d").tolist())
            _TRADE_CALENDAR.clear()
            _TRADE_CALENDAR.update(records)
            _CALENDAR_FETCHED_AT = now
            logger.info("交易日历已加载: %d 个交易日", len(_TRADE_CALENDAR))
        except Exception as e:
            logger.warning("加载交易日历失败, 仅靠规则判断: %s", e)


def _is_trade_time() -> bool:
    """判断当前是否在 A 股交易时段 + 交易日。"""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))

    # 1. 交易日历判断（有缓存时）
    _ensure_calendar()
    date_str = now.strftime("%Y-%m-%d")
    if _TRADE_CALENDAR:
        if date_str not in _TRADE_CALENDAR:
            return False
    else:
        # 回退：基本规则
        if now.weekday() >= 5:
            return False

    # 2. 精确时段判断
    t = now.strftime("%H:%M")
    return (_MORNING[0] <= t <= _MORNING[1]) or (_AFTERNOON[0] <= t <= _AFTERNOON[1])


def _fetch_all_stocks():
    df = ak.stock_zh_a_spot()
    records = df.to_dict(orient="records")
    result = []
    for row in records:
        result.append({
            "symbol": row["代码"],
            "name": row["名称"],
            "price": row["最新价"],
            "change": row["涨跌额"],
            "changePercent": row["涨跌幅"],
            "volume": row["成交量"],
            "amount": row["成交额"],
        })
    _cache["data"] = result


_fetch_all_stocks()


def _background_updater():
    while True:
        time.sleep(30)
        if not _is_trade_time():
            continue
        try:
            _fetch_all_stocks()
        except Exception:
            logger.exception("刷新股票数据失败")


threading.Thread(target=_background_updater, daemon=True).start()


@router.get("/latest")
def latest_stocks(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
):
    all_stocks = _cache["data"]
    if all_stocks is None:
        return {"stocks": [], "total": 0, "page": page, "page_size": page_size}
    total = len(all_stocks)
    start = (page - 1) * page_size
    end = start + page_size
    page_stocks = all_stocks[start:end]
    return {"stocks": page_stocks, "total": total, "page": page, "page_size": page_size}


@router.get("/query")
def query_stock(symbol: str = Query(..., description="6位A股代码，如 600519")):
    all_stocks = _cache["data"]
    if all_stocks is None:
        raise HTTPException(status_code=503, detail="数据正在初始化，请稍候重试")
    for row in all_stocks:
        if row["symbol"] == symbol:
            return row
    raise HTTPException(status_code=404, detail=f"股票 {symbol} 未找到")
