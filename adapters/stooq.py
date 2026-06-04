"""
Stooq 适配器 - 全球行情实时接口

实时行情: /q/l/  → 不需要 Key ✅
历史数据: /q/d/l/ → 先试免 Key, 再试 API Key
"""
import os
from typing import Optional

import requests

from .base import PriceAdapter


class StooqAdapter(PriceAdapter):
    name = "stooq"
    QUOTE_URL = "https://stooq.com/q/l/"
    HISTORY_URL = "https://stooq.com/q/d/l/"

    # watchlist 后缀 → Stooq 后缀 (实测)
    SUFFIX_MAP = {
        "TW": "tw", "TWO": "two",
        "T": "jp",
        "DE": "de",
        "PA": "fr",
        "AS": "nl",
        "KS": "ks", "SW": "sw", "L": "l",
        "HK": "hk", "ST": "st", "CO": "co", "SR": "sr",
    }

    def __init__(self, api_key: str = ""):
        self._api_key = api_key or os.getenv("STOOQ_API_KEY", "")

    def _to_stooq_symbol(self, symbol: str) -> str:
        if "." not in symbol:
            return f"{symbol.lower()}.us"
        base, suffix = symbol.rsplit(".", 1)
        mapped = self.SUFFIX_MAP.get(suffix.upper())
        return f"{base.lower()}.{mapped}" if mapped else symbol.lower()

    # ── 实时行情 ──

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        stooq_sym = self._to_stooq_symbol(symbol)
        try:
            r = requests.get(
                self.QUOTE_URL, params={"s": stooq_sym},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=10,
            )
            if r.status_code != 200:
                return None
            text = r.text.strip()
            if not text:
                return None
            fields = text.split(",")
            if len(fields) < 8:
                return None
            close_str = fields[6].strip()
            if close_str in ("", "N/D"):
                return None
            try:
                close = float(close_str)
            except ValueError:
                return None
            open_p = self._pf(fields[3]) or close
            high = self._pf(fields[4]) or close
            low = self._pf(fields[5]) or close

            prev_close = self._fetch_prev_close(symbol, stooq_sym)
            prev = prev_close if (prev_close and prev_close > 0) else open_p
            change = close - prev
            change_pct = (change / prev * 100) if prev else 0

            return {
                "price": close, "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "open": open_p, "high": high, "low": low,
                "prev_close": prev, "source": self.name,
            }
        except Exception:
            return None

    def _fetch_prev_close(self, symbol: str, stooq_sym: str) -> Optional[float]:
        hist = self._fetch_history_raw(stooq_sym, limit=3)
        if hist and len(hist) >= 2:
            return hist[-2]["close"]
        if self._api_key:
            hist = self._fetch_history_raw(stooq_sym, limit=3, api_key=self._api_key)
            if hist and len(hist) >= 2:
                return hist[-2]["close"]
        return None

    # ── 历史数据 (先试免Key, 再试API Key) ──

    def fetch_history(self, symbol: str, days: int = 7) -> Optional[list]:
        stooq_sym = self._to_stooq_symbol(symbol)
        result = self._fetch_history_raw(stooq_sym, limit=days + 2)
        if result:
            return result[-days:]
        if self._api_key:
            result = self._fetch_history_raw(stooq_sym, limit=days + 2, api_key=self._api_key)
            if result:
                return result[-days:]
        return None

    def _fetch_history_raw(self, stooq_sym: str, limit: int = 10,
                           api_key: str = None) -> Optional[list]:
        params = {"s": stooq_sym, "i": "d"}
        if api_key:
            params["apikey"] = api_key
        try:
            r = requests.get(self.HISTORY_URL, params=params, timeout=10)
            if r.status_code != 200:
                return None
            text = r.text.strip()
            if "apikey" in text.lower()[:60] or "error" in text.lower()[:50]:
                return None
            lines = text.splitlines()
            if len(lines) < 2:
                return None
            result = []
            for line in lines[1:]:
                parts = line.split(",")
                if len(parts) >= 2 and parts[1]:
                    try:
                        close = float(parts[1])
                        if close:
                            result.append({"date": parts[0], "close": close})
                    except (ValueError, IndexError):
                        continue
            return result[-limit:] if result else None
        except Exception:
            return None

    @staticmethod
    def _pf(s: str) -> Optional[float]:
        s = s.strip()
        if s and s != "N/D":
            try:
                return float(s)
            except ValueError:
                pass
        return None
