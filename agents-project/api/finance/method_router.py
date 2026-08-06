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

# A 股交易时段（北京时间）
_MORNING = ("09:30", "11:30")
_AFTERNOON = ("13:00", "15:00")

# ── 分时缓存 ─────────────────────────────────────────
_tick_cache: dict[str, dict] = {}
_TICK_TTL = 30  # 交易时段内 30s 刷新一次


def _is_trade_time() -> bool:
    """判断当前是否在 A 股交易时段（仅判断工作日+时间，不依赖交易日历接口）。"""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    if now.weekday() >= 5:
        return False
    t = now.strftime("%H:%M")
    return (_MORNING[0] <= t <= _MORNING[1]) or (_AFTERNOON[0] <= t <= _AFTERNOON[1])


def _is_9am_clear_time() -> bool:
    """判断是否刚过 9:00，需要清除分时缓存。"""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    return now.hour == 9 and now.minute == 0 and now.second < 10


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
        # 每天早上 9:00 清除分时缓存
        if _is_9am_clear_time():
            _tick_cache.clear()
            logger.info("分时缓存已清除 (09:00)")

        if not _is_trade_time():
            continue
        try:
            _fetch_all_stocks()
        except Exception:
            logger.exception("刷新股票数据失败")


threading.Thread(target=_background_updater, daemon=True).start()

# 排序字段白名单
_SORT_FIELDS = {"price", "change", "changePercent", "volume", "amount"}



@router.get("/latest")
def latest_stocks(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    keyword: str = Query("", description="搜索关键词（匹配代码或名称）"),
    sort_by: str = Query("", description="排序字段: price/change/changePercent/volume/amount"),
    sort_dir: str = Query("asc", description="排序方向: asc/desc"),
):
    all_stocks = _cache["data"]
    if all_stocks is None:
        return {"stocks": [], "total": 0, "page": page, "page_size": page_size}

    # ── 搜索 ──
    if keyword:
        kw = keyword.strip()
        all_stocks = [
            s for s in all_stocks
            if kw in s["symbol"] or kw in s["name"]
        ]

    # ── 排序 ──
    if sort_by in _SORT_FIELDS:
        reverse = sort_dir.lower() == "desc"
        all_stocks = sorted(
            all_stocks,
            key=lambda s: (s.get(sort_by) if s.get(sort_by) is not None else 0),
            reverse=reverse,
        )

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


@router.get("/tick")
def get_tick_chart(symbol: str = Query(..., description="6位股票代码")):
    """获取个股分时数据，交易时段内缓存 30s，每天 9:00 清除。"""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    today = now.strftime("%Y-%m-%d")

    # 9:00 清除
    if _is_9am_clear_time():
        _tick_cache.clear()

    # ── 检查缓存 ──
    entry = _tick_cache.get(symbol)
    now_ts = time.time()
    if entry and entry.get("date") == today:
        ttl = _TICK_TTL if _is_trade_time() else 300
        if now_ts - entry["fetched_at"] < ttl:
            return entry["data"]

    # ── 从 akshare 拉取 ──
    try:
        df = ak.stock_intraday_em(symbol)
    except Exception as e:
        logger.warning("获取 %s 分时数据失败: %s", symbol, e)
        # 有旧缓存则返回
        if entry:
            return entry["data"]
        raise HTTPException(status_code=503, detail=f"获取 {symbol} 分时数据失败")

    if df is None or df.empty:
        if entry:
            return entry["data"]
        raise HTTPException(status_code=404, detail=f"股票 {symbol} 今日无分时数据")

    records = df.to_dict(orient="records")
    ticks = []
    for row in records:
        # stock_intraday_em 列名: 时间, 成交价, 均价, 成交量, 成交额
        price = float(row.get("成交价", 0) or 0)
        volume = float(row.get("成交量", 0) or 0)
        avg_price = float(row.get("均价", 0) or 0)
        if price <= 0:
            continue
        ticks.append({
            "time": str(row.get("时间", "")),
            "price": round(price, 2),
            "volume": volume,
            "avg_price": round(avg_price, 2) if avg_price else None,
        })
        if len(ticks) >= 480:
            break

    result = {
        "symbol": symbol,
        "date": today,
        "ticks": ticks,
    }

    _tick_cache[symbol] = {"date": today, "fetched_at": now_ts, "data": result}
    return result
