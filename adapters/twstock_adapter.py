"""
twstock 适配器 - 台股实时报价 + 历史数据

底层使用 TWSE 官方数据源，纯 Python 实现，零外部 API Key。
实时报价: twstock.realtime.get(code)
历史数据: Stock(code).fetch_from(year, month)

twstock.realtime.get() 返回数据中没有 prev_close 字段，
因此 _prev_close() 通过 Stock 历史数据获取前一交易日收盘价。
"""
from typing import Optional

import twstock

from .base import PriceAdapter, beijing_now


class TWStockAdapter(PriceAdapter):
    name = "twstock"

    # ── 实时报价 ──
    def fetch_quote(self, symbol: str) -> Optional[dict]:
        code = self._extract_code(symbol)
        if not code:
            return None
        try:
            data = twstock.realtime.get(code)
            if not isinstance(data, dict) or not data.get("success"):
                return None

            rt = data.get("realtime", {})
            cur_str = rt.get("latest_trade_price", "0")
            cur = float(cur_str)
            if cur <= 0:
                return None

            prev = self._prev_close(code)
            open_ = float(rt.get("open", "0") or 0)
            high_ = float(rt.get("high", "0") or 0)
            low_ = float(rt.get("low", "0") or 0)

            if prev <= 0:
                prev = open_  # 兜底用开盘价

            change = cur - prev
            change_pct = change / prev * 100 if prev > 0 else 0
            return {
                "price": cur,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "open": open_,
                "high": high_,
                "low": low_,
                "prev_close": prev,
                "source": self.name,
                "updated_at": beijing_now(),
            }
        except Exception:
            return None

    # ── 历史数据 ──
    def fetch_history(self, symbol: str, days: int = 7) -> Optional[list]:
        code = self._extract_code(symbol)
        if not code:
            return None
        try:
            stock = twstock.Stock(code)
            stock.fetch_from(2025, 1)
            data = stock.data
            if not data:
                return None
            result = [
                {"date": d.date.strftime("%Y-%m-%d"), "close": d.close}
                for d in data[-days - 1 :]
            ]
            return result if result else None
        except Exception:
            return None

    def _prev_close(self, code: str) -> float:
        """获取前一交易日收盘价"""
        try:
            stock = twstock.Stock(code)
            stock.fetch_from(2025, 1)
            if not stock.data or len(stock.data) < 2:
                return 0
            # data[-1] = 最新交易日, data[-2] = 前一交易日
            return stock.data[-2].close
        except Exception:
            return 0

    @staticmethod
    def _extract_code(symbol: str) -> Optional[str]:
        """从 '2330.TW' 或 '6488.TWO' 中提取代码 '2330'"""
        if "." not in symbol:
            return symbol if symbol.isdigit() else None
        parts = symbol.rsplit(".", 1)
        code = parts[0]
        return code if code.isdigit() else None
