"""
Yahoo Finance 适配器 - 全局兜底数据源

作为最后保底手段, 覆盖所有主流市场:
  台股: 2330.TW  日股: 7203.T  欧股: IFX.DE
  港股: 0700.HK  美股: AAPL     A股: 600519.SS

API: query1.finance.yahoo.com/v8/finance/chart/{symbol}
免费, 无需 Key, CI 通常可访问
"""
from typing import Optional

import requests

from .base import PriceAdapter, beijing_now


class YahooAdapter(PriceAdapter):
    name = "yahoo"
    API_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

    def _yahoo_symbol(self, symbol: str) -> str:
        """将统一 symbol 转为 Yahoo 格式"""
        if "." not in symbol:
            return symbol  # 美股直接返回
        parts = symbol.rsplit(".", 1)
        code, suffix = parts[0], parts[1].upper()
        # A 股: 600519.SH → 600519.SS, 000001.SZ → 000001.SZ
        if suffix == "SH":
            return f"{code}.SS"
        return symbol  # 其余直接返回

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        yahoo_sym = self._yahoo_symbol(symbol)
        try:
            r = requests.get(
                f"{self.API_URL}/{yahoo_sym}?interval=1d&range=5d",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            result = data.get("chart", {}).get("result", [{}])[0]
            meta = result.get("meta", {})
            cur = meta.get("regularMarketPrice")
            prev_close = meta.get("previousClose")
            if not cur or not prev_close or cur == 0 or prev_close == 0:
                return None
            change = cur - prev_close
            change_pct = change / prev_close * 100
            # 从历史数据中取 open/high/low
            quotes = result.get("indicators", {}).get("quote", [{}])[0]
            opens = quotes.get("open", [])
            highs = quotes.get("high", [])
            lows = quotes.get("low", [])
            open_p = opens[-1] if opens else cur
            high = max([h for h in highs if h]) if any(highs) else cur
            low = min([l for l in lows if l]) if any(lows) else cur
            return {
                "price": cur,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "open": open_p,
                "high": high,
                "low": low,
                "prev_close": prev_close,
                "source": self.name,
                "updated_at": beijing_now(),
            }
        except Exception:
            return None

    def fetch_history(self, symbol: str, days: int = 7) -> Optional[list]:
        yahoo_sym = self._yahoo_symbol(symbol)
        try:
            r = requests.get(
                f"{self.API_URL}/{yahoo_sym}?interval=1d&range=1mo",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            result = data.get("chart", {}).get("result", [{}])[0]
            timestamps = result.get("timestamp", [])
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            if not timestamps or not closes:
                return None
            from datetime import datetime
            result_list = []
            for ts, c in zip(timestamps, closes):
                if c:
                    dt = datetime.fromtimestamp(ts)
                    result_list.append({"date": dt.strftime("%Y-%m-%d"), "close": c})
            return result_list[-days:] if result_list else None
        except Exception:
            return None
