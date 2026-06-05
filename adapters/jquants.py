"""
J-Quants 适配器 - 日本 TSE 股票

J-Quants 是日本交易所集团官方免费 API
需注册: https://jquants.com/
认证流程: email+password → refresh_token → id_token
"""
import json
import os
import time
from typing import Optional

import requests

from .base import PriceAdapter, beijing_now

TOKEN_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "cache", ".jquants_token.json"
)


class JQuantsAdapter(PriceAdapter):
    name = "jquants"
    AUTH_URL = "https://api.jquants.com/v1/token/auth_user"
    REFRESH_URL = "https://api.jquants.com/v1/token/auth_refresh"
    QUOTE_URL = "https://api.jquants.com/v1/prices/daily_quotes"

    def __init__(self, mail: str = "", password: str = ""):
        self._mail = mail or os.getenv("JQUANTS_MAIL", "")
        self._password = password or os.getenv("JQUANTS_PASS", "")
        self._id_token = None

    def _load_cached_token(self) -> Optional[str]:
        try:
            if os.path.exists(TOKEN_CACHE_FILE):
                data = json.load(open(TOKEN_CACHE_FILE))
                expire = data.get("expire_at", 0)
                if time.time() < expire:
                    return data.get("id_token")
        except Exception:
            pass
        return None

    def _save_token(self, id_token: str, expires_in: int = 86400):
        try:
            os.makedirs(os.path.dirname(TOKEN_CACHE_FILE), exist_ok=True)
            json.dump(
                {
                    "id_token": id_token,
                    "expire_at": time.time() + expires_in - 300,  # 提前5分钟过期
                },
                open(TOKEN_CACHE_FILE, "w"),
            )
        except Exception:
            pass

    def _authenticate(self) -> Optional[str]:
        """J-Quants 认证流程"""
        # 1. 尝试缓存token
        cached = self._load_cached_token()
        if cached:
            self._id_token = cached
            return cached

        if not self._mail or not self._password:
            return None

        try:
            # 获取 refresh token
            r = requests.post(
                self.AUTH_URL,
                json={"mailaddress": self._mail, "password": self._password},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            refresh_token = r.json().get("refreshToken")
            if not refresh_token:
                return None

            # 用 refresh token 获取 id token
            r = requests.post(
                self.REFRESH_URL,
                params={"refreshtoken": refresh_token},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            id_token = r.json().get("idToken")
            if id_token:
                self._id_token = id_token
                self._save_token(id_token)
                return id_token
        except Exception:
            pass
        return None

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        """
        symbol 格式: "7203.T" → 提取 code="72030" (J-Quants 用5位代码)
        """
        code = symbol.split(".")[0]

        # 自动填充到5位 (J-Quants 格式)
        if len(code) < 5:
            code = code.zfill(5)

        id_token = self._authenticate()
        if not id_token:
            return None

        try:
            r = requests.get(
                self.QUOTE_URL,
                params={"code": code},
                headers={"Authorization": f"Bearer {id_token}"},
                timeout=10,
            )
            if r.status_code == 401:
                # token 过期, 重新认证
                self._id_token = None
                return self.fetch_quote(symbol)
            if r.status_code != 200:
                return None

            data = r.json()
            quotes = data.get("daily_quote", [])
            if not quotes:
                return None

            # 最新交易日
            latest = quotes[0]
            cur = float(latest.get("Close", 0))
            prev_close = float(latest.get("PreviousClose", 0) or 0)
            if cur == 0:
                return None

            change = cur - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0

            return {
                "price": cur,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "open": float(latest.get("Open", 0)),
                "high": float(latest.get("High", 0)),
                "low": float(latest.get("Low", 0)),
                "prev_close": prev_close,
                "source": self.name,
                "updated_at": beijing_now(),
            }
        except Exception:
            return None

    def fetch_history(self, symbol: str, days: int = 7) -> Optional[list]:
        """J-Quants 历史数据"""
        code = symbol.split(".")[0]
        if len(code) < 5:
            code = code.zfill(5)

        id_token = self._authenticate()
        if not id_token:
            return None

        try:
            r = requests.get(
                self.QUOTE_URL,
                params={"code": code},
                headers={"Authorization": f"Bearer {id_token}"},
                timeout=10,
            )
            if r.status_code != 200:
                return None

            data = r.json()
            quotes = data.get("daily_quote", [])
            result = []
            for q in quotes[:days]:
                close = float(q.get("Close", 0))
                if close:
                    result.append({"date": q.get("Date", ""), "close": close})
            return result if result else None
        except Exception:
            return None
