"""
TWSE/TPEx 适配器 - 台股

TWSE官方实时报价 API:
  - 上市: mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{code}.tw
  - 上柜: mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=otc_{code}.tw
  - 支持批量查询: 用 | 分隔
"""
from typing import Optional

import requests

from .base import PriceAdapter


class TWSEAdapter(PriceAdapter):
    name = "twse"
    API_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"

    # 上市/上柜映射: (后缀, ex_ch前缀)
    EXCHANGE_MAP = {
        "TW": "tse",    # 上市
        "TWO": "otc",   # 上柜
    }

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        """
        symbol 格式: "2330.TW" 或 "6488.TWO"
        """
        # 解析代码和后缀
        parts = symbol.rsplit(".", 1)
        if len(parts) != 2:
            return None
        code, suffix = parts
        ex_prefix = self.EXCHANGE_MAP.get(suffix.upper())
        if not ex_prefix:
            return None

        ex_ch = f"{ex_prefix}_{code}.tw"
        try:
            r = requests.get(
                self.API_URL,
                params={"ex_ch": ex_ch, "json": "1"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            msg_arr = data.get("msgArray", [])
            if not msg_arr:
                return None
            item = msg_arr[0]

            # TWSE 返回的字段: z=当前价, y=昨收, o=开盘, h=最高, l=最低
            cur_str = item.get("z", "-")
            if cur_str in ("-", ""):
                return None
            cur = float(cur_str.replace(",", ""))
            prev_close = float(item.get("y", "0").replace(",", ""))
            if prev_close == 0:
                return None
            change = cur - prev_close
            change_pct = change / prev_close * 100

            return {
                "price": cur,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "open": float(item.get("o", "0").replace(",", "") or 0),
                "high": float(item.get("h", "0").replace(",", "") or 0),
                "low": float(item.get("l", "0").replace(",", "") or 0),
                "prev_close": prev_close,
                "source": self.name,
            }
        except Exception:
            return None

    def fetch_history(self, symbol: str, days: int = 7) -> Optional[list]:
        """TWSE 官方 API 不提供多日历史"""
        return None
