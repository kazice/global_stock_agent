"""
Sina 港股适配器 - 新浪财经港股实时行情

直接调用新浪港股 API (hq.sinajs.cn), 绕过 akshare 的解析 bug
API 返回格式: var hq_str_hk00700="名称,开盘,昨收,当前,最高,最低,..."
"""
from typing import Optional

import requests

from .base import PriceAdapter, beijing_now


class SinaHKAdapter(PriceAdapter):
    name = "sinahk"
    API_URL = "https://hq.sinajs.cn/list="

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        """symbol 格式: 0700.HK"""
        code = symbol.split(".")[0].zfill(5)  # 0700 → 00700
        try:
            r = requests.get(
                f"{self.API_URL}hk{code}",
                headers={
                    "Referer": "https://finance.sina.com.cn",
                    "User-Agent": "Mozilla/5.0",
                },
                timeout=10,
            )
            if r.status_code != 200:
                return None

            text = r.text.strip()
            # 格式: var hq_str_hk00700="腾讯控股,386.800,388.000,387.000,...";
            if '"' not in text:
                return None
            fields = text.split('"')[1].split(",")
            if len(fields) < 7:
                return None

            name = fields[0]
            cur_str = fields[6]  # 当前价
            prev_close_str = fields[2]  # 昨收
            open_str = fields[1]        # 开盘
            high_str = fields[4]        # 最高
            low_str = fields[5]         # 最低

            try:
                cur = float(cur_str)
                prev_close = float(prev_close_str)
            except (ValueError, IndexError):
                return None

            if cur == 0 or prev_close == 0:
                return None

            change = cur - prev_close
            change_pct = change / prev_close * 100

            return {
                "price": cur,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "open": float(open_str) if open_str else cur,
                "high": float(high_str) if high_str else cur,
                "low": float(low_str) if low_str else cur,
                "prev_close": prev_close,
                "source": self.name,
                "updated_at": beijing_now(),
            }
        except Exception:
            return None

    def fetch_history(self, symbol: str, days: int = 7) -> Optional[list]:
        """港股历史数据通过 akshare 获取"""
        try:
            import akshare as ak
            import datetime

            code = symbol.split(".")[0].zfill(5)
            end = datetime.date.today()
            start = end - datetime.timedelta(days=days * 2)
            df = ak.stock_hk_hist(
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
