"""
数据源适配器基类

所有适配器统一接口:
  - fetch_quote(symbol) → dict | None
  - fetch_history(symbol, days) → list[dict] | None
"""
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Optional

# 北京时区 (UTC+8)
BJ_TZ = timezone(timedelta(hours=8))

def beijing_now() -> str:
    """返回当前北京时间字符串 (MM-DD HH:MM)"""
    return datetime.now(BJ_TZ).strftime("%m-%d %H:%M")

def utc_to_beijing(utc_dt_str: str, utc_time_str: str) -> str:
    """
    将 Stooq 返回的 UTC 日期时间转为北京时间字符串 (MM-DD HH:MM)
    支持多种输入格式:
      date="2026-06-05", time="03:19:00"
      date="0605",       time="03:19"
    """
    dt_str = utc_dt_str.strip()
    tm_str = utc_time_str.strip()
    now = datetime.now(BJ_TZ)
    # 尝试多种日期/时间格式组合
    formats = [
        (f"{dt_str} {tm_str}", "%Y-%m-%d %H:%M:%S"),
        (f"{dt_str} {tm_str}", "%Y-%m-%d %H:%M"),
        (f"{now.year}{dt_str} {tm_str}", "%Y%m%d %H:%M:%S"),
        (f"{now.year}{dt_str} {tm_str}", "%Y%m%d %H:%M"),
    ]
    for s, fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            dt = dt.replace(tzinfo=timezone.utc).astimezone(BJ_TZ)
            return dt.strftime("%m-%d %H:%M")
        except (ValueError, IndexError):
            continue
    return ""

def ts_to_beijing(ts: int) -> str:
    """将 Unix 时间戳转为北京时间字符串 (MM-DD HH:MM)"""
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(BJ_TZ)
    return dt.strftime("%m-%d %H:%M")


class PriceAdapter(ABC):
    """行情数据源适配器基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """数据源名称"""

    @abstractmethod
    def fetch_quote(self, symbol: str) -> Optional[dict]:
        """
        获取实时行情

        返回统一格式:
        {
            "price": float,      # 当前价
            "change": float,     # 涨跌额
            "change_pct": float, # 涨跌幅(%)
            "open": float,       # 开盘价
            "high": float,       # 最高
            "low": float,        # 最低
            "prev_close": float, # 昨收
            "source": str,       # 数据源名称
        }
        """

    def fetch_history(self, symbol: str, days: int = 7) -> Optional[list]:
        """
        获取历史收盘价 (用于计算周涨跌幅)

        返回: [{"date": str, "close": float}, ...] 按日期降序
        """
        return None
