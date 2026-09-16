import tickflow
from datetime import date

from langchain_core.tools import tool


tf = tickflow.TickFlow.free()
_SUFFIX_MAP = {"6": ".SH", "0": ".SZ", "3": ".SZ"}


def _to_symbol(code: str) -> str:
    return code + _SUFFIX_MAP.get(code[0], ".SZ")


def _date_to_ms(d: date) -> int:
    return int(d.timestamp() * 1000)


@tool
def get_a_stock_price(symbol: str) -> str:
    """
    获取 A 股股票行情信息。
    symbol: 6位A股代码，如 600519(沪)、000001(深)
    返回包含名称、日期、开盘价、最高价、最低价、收盘价、涨跌幅、成交量、成交额等信息
    """ 
    try:
        df = tf.klines.get(
            _to_symbol(symbol),
            period="1d",
            count=60,
            adjust="forward",
            as_dataframe=True,
        )
        if df.empty:
            return f"{symbol} 无数据"
        row = df.iloc[-1]
        name = row["name"]
        close = round(float(row["close"]), 2)
        price_date = row["trade_date"]
        prev_close = round(float(df["close"].iloc[-2]), 2) if len(df) > 1 else None
        change = round(close - prev_close, 2) if prev_close else 0.0
        change_pct = round(change / prev_close * 100, 2) if prev_close and prev_close != 0 else 0.0
        open_p = round(float(row["open"]), 2)
        high = round(float(row["high"]), 2)
        low = round(float(row["low"]), 2)
        volume = int(row["volume"])
        amount = round(float(row["amount"]) / 1e8, 2)
        chg_sign = "+" if change > 0 else ""
        return (
            f"{name}({symbol}) {price_date}\n"
            f"收盘：¥{close} ({chg_sign}{change:.2f} / {chg_sign}{change_pct:.2f}%)\n"
            f"开盘：¥{open_p}  最高：¥{high}  最低：¥{low}\n"
            f"成交量：{volume:,}  成交额：¥{amount}亿"
        )
    except Exception as e:
        return f"查询 A 股 {symbol} 失败：{e}"