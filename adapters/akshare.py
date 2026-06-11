"""
AkShare 适配器 - A 股 (SSE/SZSE/STAR)

实时报价: 直连新浪单股实时 API (hq.sinajs.cn)
历史数据: akshare.stock_zh_a_hist()
"""
import datetime
from typing import Optional

import requests

from .base import PriceAdapter, beijing_now


# 新浪交易所前缀映射
_EX_PREFIX = {"SH": "sh", "SZ": "sz"}


class AkShareAdapter(PriceAdapter):
    name = "akshare"
    SINA_URL = "https://hq.sinajs.cn/list"

    def _get_ak(self):
        try:
            import akshare as ak
            return ak
        except ImportError:
            return None

    # ── 实时报价 (直连新浪 API，无需 akshare) ──

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        parts = symbol.split(".")
        if len(parts) != 2:
            return None
        code, suffix = parts[0], parts[1].upper()
        prefix = _EX_PREFIX.get(suffix)
        if not prefix:
            return None

        sina_sym = f"{prefix}{code}"
        try:
            r = requests.get(
                f"{self.SINA_URL}={sina_sym}",
                headers={"Referer": "https://finance.sina.com.cn"},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            text = r.text.strip()
            if not text or '"' not in text:
                return None
            fields = text.split('"')[1].split(",")
            if len(fields) < 8:
                return None

            # fields: 0=名称,1=今开,2=昨收,3=当前价,4=最高,5=最低,6=日期,7=时间
            name = fields[0]
            cur = float(fields[3]) if fields[3] else 0
            prev_close = float(fields[2]) if fields[2] else 0
            if cur == 0 or prev_close == 0:
                return None

            open_p = float(fields[1]) if fields[1] else cur
            high = float(fields[4]) if fields[4] else cur
            low = float(fields[5]) if fields[5] else cur
            change = cur - prev_close
            change_pct = change / prev_close * 100

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

    # ── 历史数据 (akshare) ──

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
