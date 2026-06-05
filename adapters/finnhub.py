"""
Finnhub 适配器 - 美股 / 港股 / 欧股 ADR
免费版: 60次/分钟, 支持美股及部分国际股票
"""
import time
from typing import Optional

import requests

from .base import PriceAdapter, ts_to_beijing


class FinnhubAdapter(PriceAdapter):
    name = "finnhub"

    def __init__(self, api_key: str, base_url: str):
        self._api_key = api_key
        self._base_url = base_url

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        url = f"{self._base_url}/quote"
        params = {"symbol": symbol, "token": self._api_key}
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 429:
                time.sleep(5)
                r = requests.get(url, params=params, timeout=10)
            if r.status_code in (403, 404):
                return None
            if r.status_code != 200:
                return None
            data = r.json()
            cur = data.get("c")
            if cur is None or cur == 0:
                return None
            ts = data.get("t", 0)
            updated = ts_to_beijing(ts)
            return {
                "price": cur,
                "change": data.get("d", 0),
                "change_pct": data.get("dp", 0),
                "open": data.get("o", cur),
                "high": data.get("h", cur),
                "low": data.get("l", cur),
                "prev_close": data.get("pc", cur),
                "source": self.name,
                "updated_at": updated,
            }
        except Exception:
            return None

    def fetch_history(self, symbol: str, days: int = 7) -> Optional[list]:
        """Finnhub 暂不支持免费历史数据"""
        return None
