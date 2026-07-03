"""
TWSE OpenAPI adapter - listed Taiwan stocks daily quotes.

The MIS realtime endpoint is fragile on CI runners. This adapter uses the
official TWSE OpenAPI daily quote endpoint as a stable fallback for .TW stocks.
"""
from typing import Optional

import requests

from .base import PriceAdapter, beijing_now


class TWSEOpenAPIAdapter(PriceAdapter):
    name = "twse_openapi"
    API_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"

    def __init__(self):
        self._cache = None

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        code = self._extract_twse_code(symbol)
        if not code:
            return None
        row = self._get_rows().get(code)
        if not row:
            return None
        try:
            price = self._pf(row.get("ClosingPrice"))
            change = self._pf(row.get("Change"))
            open_p = self._pf(row.get("OpeningPrice")) or price
            high = self._pf(row.get("HighestPrice")) or price
            low = self._pf(row.get("LowestPrice")) or price
            if price is None or change is None:
                return None
            prev_close = price - change
            change_pct = change / prev_close * 100 if prev_close else 0.0
            return {
                "price": price,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "open": open_p,
                "high": high,
                "low": low,
                "prev_close": round(prev_close, 2),
                "source": self.name,
                "updated_at": beijing_now(),
            }
        except Exception:
            return None

    def _get_rows(self) -> dict:
        if self._cache is not None:
            return self._cache
        self._cache = {}
        try:
            r = requests.get(
                self.API_URL,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                timeout=15,
            )
            if r.status_code != 200:
                return self._cache
            rows = r.json()
            self._cache = {str(row.get("Code", "")).strip(): row for row in rows}
        except Exception:
            pass
        return self._cache

    @staticmethod
    def _extract_twse_code(symbol: str) -> Optional[str]:
        if "." not in symbol:
            return symbol if symbol.isdigit() else None
        code, suffix = symbol.rsplit(".", 1)
        if suffix.upper() != "TW":
            return None
        return code if code.isdigit() else None

    @staticmethod
    def _pf(value) -> Optional[float]:
        if value is None:
            return None
        text = str(value).replace(",", "").strip()
        if not text or text == "--":
            return None
        try:
            return float(text)
        except ValueError:
            return None
