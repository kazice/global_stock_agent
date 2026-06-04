"""
AkShare 适配器 - A 股 (SSE/SZSE/STAR)

用 stock_zh_a_hist() 按个股查最新日线 (已验证可用)
"""
import datetime
from typing import Optional

from .base import PriceAdapter


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
            today = datetime.date.today()
            # 取最近3天确保有数据（可能跨周末/假期）
            start = today - datetime.timedelta(days=5)
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=today.strftime("%Y%m%d"),
                adjust="qfq",
            )
            if df.empty:
                return None

            row = df.iloc[-1]  # 最新交易日
            cur = float(row["收盘"])
            prev_close = float(row["开盘"])  # 用开盘当参考
            change_pct = float(row.get("涨跌幅", 0))

            # 计算涨跌额
            change_pct_v = row.get("涨跌额")
            change = float(change_pct_v) if change_pct_v else (cur - prev_close)
            prev = cur - change if change else cur

            return {
                "price": cur,
                "change": round(change, 2),
                "change_pct": change_pct,
                "open": float(row["开盘"]),
                "high": float(row["最高"]),
                "low": float(row["最低"]),
                "prev_close": prev,
                "source": self.name,
            }
        except Exception:
            return None

    def fetch_history(self, symbol: str, days: int = 10) -> Optional[list]:
        code = symbol.split(".")[0]
        ak = self._get_ak()
        if ak is None:
            return None

        try:
            end = datetime.date.today()
            start = end - datetime.timedelta(days=days * 2)
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )
            if df.empty:
                return None
            result = [
                {"date": str(r["日期"]), "close": float(r["收盘"])}
                for _, r in df.iterrows()
                if float(r["收盘"])
            ]
            return result[-days:] if result else None
        except Exception:
            return None
