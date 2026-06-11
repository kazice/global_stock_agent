"""
港股适配器 - 多源兜底

数据源优先级:
  1. 腾讯证券 API (qt.gtimg.cn) - 最稳定, CI 可用
  2. 新浪财经 API (hq.sinajs.cn) - 兜底
"""
from typing import Optional

import requests

from .base import PriceAdapter, beijing_now


class HKAdapter(PriceAdapter):
    name = "hk"

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        """symbol 格式: 0700.HK"""
        code = symbol.split(".")[0].zfill(5)

        # 1) 腾讯证券 API (首选, 非常稳定)
        result = self._try_tencent(code)
        if result:
            return result

        # 2) 新浪 API (兜底)
        result = self._try_sina(code)
        if result:
            return result

        return None

    # ── 腾讯证券 API ──

    def _try_tencent(self, code: str) -> Optional[dict]:
        """
        腾讯证券 API: https://qt.gtimg.cn/q=hk00700
        返回: v_hk00700="name~open~prev_close~current~high~low~bid~ask~volume~amount~...";
        字段以 ~ 分隔
        """
        try:
            r = requests.get(
                f"https://qt.gtimg.cn/q=hk{code}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            text = r.text.strip()
            if '"' not in text:
                return None
            fields = text.split('"')[1].split("~")
            # 腾讯返的字段: name, open, prev_close, current, high, low, bid, ask, volume, amount
            if len(fields) < 6:
                return None
            return self._parse(fields, 0, 1, 2, 3, 4, 5)
        except Exception:
            return None

    # ── 新浪财经 API ──

    def _try_sina(self, code: str) -> Optional[dict]:
        """
        新浪港股 API: https://hq.sinajs.cn/list=hk00700
        返回: var hq_str_hk00700="name,open,prev_close,current,high,low,...";
        字段以 , 分隔
        """
        try:
            r = requests.get(
                f"https://hq.sinajs.cn/list=hk{code}",
                headers={
                    "Referer": "https://finance.sina.com.cn",
                    "User-Agent": "Mozilla/5.0",
                },
                timeout=10,
            )
            if r.status_code != 200:
                return None
            text = r.text.strip()
            if '"' not in text:
                return None
            fields = text.split('"')[1].split(",")
            # 新浪字段: name, open, prev_close, current, high, low, ...
            if len(fields) < 7:
                return None
            return self._parse(fields, 0, 1, 2, 6, 4, 5)
        except Exception:
            return None

    # ── 统一解析 ──

    @staticmethod
    def _parse(fields, idx_name, idx_open, idx_pc, idx_cur, idx_high, idx_low) -> Optional[dict]:
        try:
            cur = float(fields[idx_cur])
            prev_close = float(fields[idx_pc])
        except (ValueError, IndexError):
            return None
        if cur == 0 or prev_close == 0:
            return None
        change = cur - prev_close
        change_pct = change / prev_close * 100
        open_p = float(fields[idx_open]) if fields[idx_open] else cur
        high = float(fields[idx_high]) if idx_high < len(fields) and fields[idx_high] else cur
        low = float(fields[idx_low]) if idx_low < len(fields) and fields[idx_low] else cur
        return {
            "price": cur,
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "open": open_p,
            "high": high,
            "low": low,
            "prev_close": prev_close,
            "source": "hk",
            "updated_at": beijing_now(),
        }

    # ── 历史数据 ──

    def fetch_history(self, symbol: str, days: int = 7) -> Optional[list]:
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
