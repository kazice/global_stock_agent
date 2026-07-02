"""
腾讯财经适配器 - 日本股票行情

接口: http://qt.gtimg.cn/q=jp{code}
免费, 无需 API Key, 返回准实时日股数据
"""
from typing import Optional

import requests

from .base import PriceAdapter, beijing_now


class TencentJPAdapter(PriceAdapter):
    name = "tencent_jp"
    QUOTE_URL = "http://qt.gtimg.cn/q=jp{code}"

    @staticmethod
    def _to_code(symbol: str) -> str:
        """7203.T → 7203"""
        return symbol.split(".")[0]

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        code = self._to_code(symbol)
        try:
            r = requests.get(
                self.QUOTE_URL.format(code=code),
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            text = r.text.strip()
            if not text or "none_match" in text:
                return None

            # 腾讯格式: v_jp7203="351~名称~代码.T~当前价~昨收~开盘~成交量~...~日期 时间~涨跌额~涨跌幅%"
            # 数据以 ~ 分隔
            data = text.split("~")
            if len(data) < 6:
                return None

            try:
                price = float(data[3])
            except (ValueError, TypeError):
                return None

            prev_close = self._pf(data[4]) or price
            open_p = self._pf(data[5]) or price

            # 成交量在 data[6]
            # 涨跌额和涨跌幅在末尾
            change = self._pf(data[-2]) if len(data) >= 3 else None
            change_pct = self._pf(data[-1]) if len(data) >= 3 else None

            # 如果没有涨跌幅，自己算
            if change is None or change_pct is None:
                change = price - prev_close
                change_pct = (change / prev_close * 100) if prev_close else 0

            return {
                "price": price,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "open": open_p,
                "high": price,  # 腾讯日股不提供 high/low
                "low": price,
                "prev_close": prev_close,
                "source": self.name,
                "updated_at": beijing_now(),
            }
        except Exception:
            return None

    @staticmethod
    def _pf(s: str) -> Optional[float]:
        """parse float, strip quotes and percent"""
        s = s.strip().strip('"').strip(";").replace("%", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
