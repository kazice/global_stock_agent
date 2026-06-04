"""
数据源适配器基类

所有适配器统一接口:
  - fetch_quote(symbol) → dict | None
  - fetch_history(symbol, days) → list[dict] | None
"""
from abc import ABC, abstractmethod
from typing import Optional


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
