"""
Borse Frankfurt adapter - fallback quotes for selected German stocks.

This is intentionally small and used as a verification fallback for the
Taiwan/Europe test branch when generic quote providers are rate-limited.
"""
from typing import Optional

import requests

from .base import PriceAdapter, beijing_now


class BoerseFrankfurtAdapter(PriceAdapter):
    name = "boerse_frankfurt"
    API_URL = "https://api.boerse-frankfurt.de/v1/data/quote_box/single"

    ISIN_MAP = {
        "ADS.DE": "DE000A1EWWW0",
        "ALV.DE": "DE0008404005",
        "BAS.DE": "DE000BASF111",
        "BMW.DE": "DE0005190003",
        "DTE.DE": "DE0005557508",
        "ENR.DE": "DE000ENER6Y0",
        "IFX.DE": "DE0006231004",
        "MBG.DE": "DE0007100000",
        "SAP.DE": "DE0007164600",
        "SHL.DE": "DE000SHL1006",
        "SIE.DE": "DE0007236101",
        "VOW3.DE": "DE0007664039",
    }

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        isin = self.ISIN_MAP.get(symbol.upper())
        if not isin:
            return None
        try:
            r = requests.get(
                self.API_URL,
                params={"isin": isin, "mic": "XETR"},
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            cur = data.get("lastPrice")
            change = data.get("changeToPrevDayAbsolute")
            change_pct = data.get("changeToPrevDayInPercent")
            if cur is None or change_pct is None:
                return None
            prev_close = cur - change if change is not None else cur / (1 + change_pct / 100)
            return {
                "price": float(cur),
                "change": round(float(change or 0), 2),
                "change_pct": round(float(change_pct), 2),
                "open": float(data.get("open") or cur),
                "high": float(data.get("high") or cur),
                "low": float(data.get("low") or cur),
                "prev_close": round(float(prev_close), 2),
                "source": self.name,
                "updated_at": beijing_now(),
            }
        except Exception:
            return None
