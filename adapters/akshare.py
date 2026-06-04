"""
AkShare 适配器 - A 股 (SSE/SZSE/STAR)

使用 stock_zh_a_spot() 新浪数据源 (公司网络也能通)
首次调用会全量拉取一次(约30s), 之后走缓存
"""
from datetime import datetime
from typing import Optional

from .base import PriceAdapter


class AkShareAdapter(PriceAdapter):
    name = "akshare"
    _spot_df = None  # 类级别缓存, 全部 A 股共用

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
            if self._spot_df is None:
                # 首次: 全量拉取(约30s)
                print("  [AKShare] 首次加载 A 股全量行情...", flush=True)
                df = ak.stock_zh_a_spot()
                AkShareAdapter._spot_df = df
            else:
                df = self._spot_df

            # 筛目标股票 (代码列是 sh600519/sz000001 格式)
            row = df[df["代码"].str.endswith(code)]
            if row.empty:
                return None
            item = row.iloc[0]
            cur = float(item["最新价"])
            prev_close = float(item["昨收"])
            if prev_close == 0:
                return None
            change = cur - prev_close
            change_pct = float(item["涨跌幅"])

            return {
                "price": cur,
                "change": round(change, 2),
                "change_pct": change_pct,
                "open": float(item["今开"]),
                "high": float(item["最高"]),
                "low": float(item["最低"]),
                "prev_close": prev_close,
                "source": self.name,
                "updated_at": datetime.now().strftime("%m-%d %H:%M"),
            }
        except Exception:
            return None

    def fetch_history(self, symbol: str, days: int = 7) -> Optional[list]:
        """A 股历史用 stock_zh_a_hist (可能被公司墙, 失败返回 None)"""
        code = symbol.split(".")[0]
        ak = self._get_ak()
        if ak is None:
            return None
        try:
            import datetime
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
