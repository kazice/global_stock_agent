"""
J-Quants 适配器 - 日本 TSE 股票 (V2 API)

J-Quants 是日本交易所集团官方免费 API
注册: https://jpx-jquants.com → 获取 API Key
认证: V2 使用 x-api-key 头
"""
import os
from typing import Optional

import requests

from .base import PriceAdapter, beijing_now


class JQuantsAdapter(PriceAdapter):
    name = "jquants"
    BASE_URL = "https://api.jquants.com/v2"
    BARS_URL = f"{BASE_URL}/equities/bars/daily"

    def __init__(self, api_key: str = ""):
        self._api_key = api_key or os.getenv("JQUANTS_API_KEY", "")
        # 兼容旧版: 如果只有邮箱密码，尝试用邮箱密码
        if not self._api_key:
            mail = os.getenv("JQUANTS_MAIL", "")
            pw = os.getenv("JQUANTS_PASS", "")
            if mail and pw:
                # 旧版凭据，尝试用 mail 作为 api_key（可能已迁移为 key）
                self._api_key = mail

    def _to_jquants_code(self, symbol: str) -> str:
        """
        7203.T → 72030 (J-Quants 用5位代码，末尾补0)
        """
        code = symbol.split(".")[0]
        if len(code) <= 4:
            code = code + "0"
        return code

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        code = self._to_jquants_code(symbol)
        if not self._api_key:
            return None

        try:
            r = requests.get(
                self.BARS_URL,
                params={"code": code, "limit": 2},
                headers={"x-api-key": self._api_key},
                timeout=15,
            )
            if r.status_code != 200:
                return None

            data = r.json()
            bars = data.get("data", [])
            if len(bars) < 2:
                return None

            # V2 字段: O/H/L/C (而非 Open/High/Low/Close)
            latest = bars[-1] if len(bars) > 1 else bars[0]
            prev = bars[-2] if len(bars) > 1 else bars[0]

            cur = float(latest.get("C", 0))
            prev_close = float(prev.get("C", 0))
            open_p = float(latest.get("O", cur))
            high = float(latest.get("H", cur))
            low = float(latest.get("L", cur))

            if cur == 0:
                return None

            change = cur - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0

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
        code = self._to_jquants_code(symbol)
        if not self._api_key:
            return None

        try:
            r = requests.get(
                self.BARS_URL,
                params={"code": code, "limit": days + 2},
                headers={"x-api-key": self._api_key},
                timeout=15,
            )
            if r.status_code != 200:
                return None

            data = r.json()
            bars = data.get("data", [])
            if not bars:
                return None

            result = []
            for b in bars:
                close = float(b.get("C", 0))
                date = b.get("Date", "")
                if close and date:
                    result.append({"date": date, "close": close})
            return result[-days:] if result else None
        except Exception:
            return None
