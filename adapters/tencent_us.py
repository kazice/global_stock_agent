"""
腾讯财经适配器 - 美股行情

接口: http://qt.gtimg.cn/q=us{code}
免费, 无需 API Key, 返回准实时美股数据
"""
from typing import Optional

import requests

from .base import PriceAdapter, beijing_now


class TencentUSAdapter(PriceAdapter):
    name = "tencent_us"
    QUOTE_URL = "http://qt.gtimg.cn/q=us{code}"

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        try:
            r = requests.get(
                self.QUOTE_URL.format(code=symbol),
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            text = r.text.strip()
            if not text or "none_match" in text:
                return None

            # 腾讯美股格式: v_usAAPL="351~名称~代码~当前价~昨收~开盘~成交量~...~涨跌幅%"
            data = text.split("~")
            if len(data) < 6:
                return None

            try:
                price = float(data[3])
            except (ValueError, TypeError):
                return None

            prev_close = self._pf(data[4]) or price
            open_p = self._pf(data[5]) or price

            # 涨跌幅在 data[32]
            change_pct = self._pf(data[32]) if len(data) > 32 else None

            if change_pct is not None:
                change = price - prev_close
            else:
                change = price - prev_close
                change_pct = (change / prev_close * 100) if prev_close else 0

            return {
                "price": price,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "open": open_p,
                "high": price,
                "low": price,
                "prev_close": prev_close,
                "source": self.name,
                "updated_at": beijing_now(),
            }
        except Exception:
            return None

    @staticmethod
    def _pf(s: str) -> Optional[float]:
        s = s.strip().strip('"').strip(";").replace("%", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
