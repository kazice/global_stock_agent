"""
AkShare 适配器 - A 股 (SSE/SZSE/STAR)

逐股查询 stock_zh_a_hist()，不再全量加载
"""
import datetime
from typing import Optional

from .base import PriceAdapter, beijing_now


class AkShareAdapter(PriceAdapter):
    name = "akshare"

    def _get_ak(self):
        try:
            import akshare as ak
            return ak
        except ImportError:
            return None

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        code = symbol.split(".")[0]
        ak = self._get_ak()
        if ak is None:
            return None
        try:
            end = datetime.date.today()
            start = end - datetime.timedelta(days=7)
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )
            if df.empty:
                return None
            item = df.iloc[-1]  # 最新交易日
            cur = float(item["收盘"])
            change_pct = float(item["涨跌幅"])

            # 从涨跌幅反推昨收
            prev_close = cur / (1 + change_pct / 100) if abs(change_pct) > 0 else cur
            change = cur - prev_close

            return {
                "price": cur,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "open": float(item["开盘"]),
                "high": float(item["最高"]),
                "low": float(item["最低"]),
                "prev_close": round(prev_close, 2),
                "source": self.name,
                "updated_at": beijing_now(),
            }
        except Exception:
            return None

    def fetch_history(self, symbol: str, days: int = 7) -> Optional[list]:
        code = symbol.split(".")[0]
        ak = self._get_ak()
        if ak is None:
            return None
        try:
            end = datetime.date.today()
            start = end - datetime.timedelta(days=days * 2)
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )
            if df.empty:
                return None
            result = [
                {"date": str(r["日期"]), "close": float(r["收盘"])}
                for _, r in df.iterrows() if float(r["收盘"])
            ]
            return result[-days:] if result else None
        except Exception:
            return None
