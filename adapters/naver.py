"""
Naver Finance 适配器 - 韩国股市 (KOSPI/KOSDAQ)

Naver 是韩国最大门户网站，其财经板块 finance.naver.com 提供未公开的移动端 JSON API。
完全免费，无需 API Key。

实时行情: m.stock.naver.com/api/stock/{code}/basic
历史K线:  api.stock.naver.com/chart/domestic/item/{code}?periodType=dayCandle

symbol 格式: 纯6位数字代码，如 "005930"（三星电子）
"""
from datetime import datetime
from typing import Optional

import requests

from .base import PriceAdapter, beijing_now


class NaverAdapter(PriceAdapter):
    name = "naver"

    QUOTE_URL = "https://m.stock.naver.com/api/stock/{code}/basic"
    CHART_URL = "https://api.stock.naver.com/chart/domestic/item/{code}"
    # 实时轮询（价格更新更快）
    POLLING_URL = "https://polling.finance.naver.com/api/realtime"

    @staticmethod
    def _to_naver_code(symbol: str) -> str:
        """005930.KS → 005930"""
        return symbol.split(".")[0] if "." in symbol else symbol

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        code = self._to_naver_code(symbol)
        try:
            r = requests.get(
                self.QUOTE_URL.format(code=code),
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            data = r.json()

            # 解析 basic 接口返回
            price = data.get("closePrice")
            if price is None:
                return None
            try:
                price = float(str(price).replace(",", ""))
            except (ValueError, TypeError):
                return None

            change_val = data.get("compareToPreviousClosePrice", "0")
            try:
                change_val = float(str(change_val).replace(",", ""))
            except (ValueError, TypeError):
                change_val = 0.0

            change_pct_str = data.get("fluctuationsRatio", "0")
            try:
                change_pct = float(str(change_pct_str).replace(",", ""))
            except (ValueError, TypeError):
                change_pct = 0.0

            prev_close = price - change_val if change_val else price

            # 获取 open/high/low（从历史 K 线当天数据）
            open_p = price
            high = price
            low = price
            try:
                today_data = self._get_today_ohlc(code)
                if today_data:
                    open_p = today_data.get("open", price)
                    high = today_data.get("high", price)
                    low = today_data.get("low", price)
            except Exception:
                pass

            return {
                "price": price,
                "change": round(change_val, 2),
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
        code = self._to_naver_code(symbol)
        try:
            r = requests.get(
                self.CHART_URL.format(code=code),
                params={"periodType": "dayCandle", "limit": days + 2},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            candles = data if isinstance(data, list) else data.get("candles", [])
            if not candles:
                return None

            result = []
            for c in candles:
                close = c.get("closePrice")
                date = c.get("localDate") or c.get("date")
                if close and date:
                    try:
                        close_f = float(close)
                        # 日期格式: "20260630" → "2026-06-30"
                        date_str = str(date)
                        if len(date_str) == 8:
                            date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
                        result.append({"date": date_str, "close": close_f})
                    except (ValueError, TypeError):
                        continue
            return result[-days:] if result else None
        except Exception:
            return None

    def _get_today_ohlc(self, code: str) -> Optional[dict]:
        """获取当天 OHLC 数据"""
        try:
            r = requests.get(
                self.CHART_URL.format(code=code),
                params={"periodType": "dayCandle", "limit": 1},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=8,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            candles = data if isinstance(data, list) else data.get("candles", [])
            if not candles:
                return None
            c = candles[-1]
            return {
                "open": float(c.get("openPrice", 0)),
                "high": float(c.get("highPrice", 0)),
                "low": float(c.get("lowPrice", 0)),
            }
        except Exception:
            return None
