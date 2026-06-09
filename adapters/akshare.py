"""
AkShare 适配器 - A 股 (SSE/SZSE/STAR)

使用 stock_zh_a_spot() 新浪数据源 (公司网络也能通)
首次调用会全量拉取一次(约30s), 之后走缓存
"""
from typing import Optional

from .base import PriceAdapter, beijing_now


class AkShareAdapter(PriceAdapter):
    name = "akshare"
    _a_spot_df = None   # 类级别缓存, A 股全量行情
    _hk_spot_df = None  # 类级别缓存, 港股全量行情

    def _get_ak(self):
        try:
            import akshare as ak
            return ak
        except ImportError:
            return None

    # ── 判断股票市场 ──

    @staticmethod
    def _is_hk(symbol: str) -> bool:
        return symbol.upper().endswith(".HK")

    @staticmethod
    def _is_a(symbol: str) -> bool:
        suffix = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else ""
        return suffix in ("SH", "SZ")

    # ── A 股行情 ──

    def _fetch_a_quote(self, symbol: str, ak) -> Optional[dict]:
        code = symbol.split(".")[0]
        if self._a_spot_df is None:
            print("  [AKShare] 首次加载 A 股全量行情...", flush=True)
            AkShareAdapter._a_spot_df = ak.stock_zh_a_spot()
        df = self._a_spot_df
        # 代码列是 sh600519/sz000001 格式
        row = df[df["代码"].str.endswith(code)]
        if row.empty:
            return None
        return self._parse_a_item(row.iloc[0])

    def _parse_a_item(self, item) -> dict:
        cur = float(item["最新价"])
        prev_close = float(item["昨收"])
        if prev_close == 0:
            return None
        change = cur - prev_close
        return {
            "price": cur,
            "change": round(change, 2),
            "change_pct": float(item["涨跌幅"]),
            "open": float(item["今开"]),
            "high": float(item["最高"]),
            "low": float(item["最低"]),
            "prev_close": prev_close,
            "source": self.name,
            "updated_at": beijing_now(),
        }

    # ── 港股行情 (新浪源) ──

    def _fetch_hk_quote(self, symbol: str, ak) -> Optional[dict]:
        code = symbol.split(".")[0]
        if self._hk_spot_df is None:
            print("  [AKShare] 首次加载港股全量行情...", flush=True)
            AkShareAdapter._hk_spot_df = ak.stock_hk_spot()
        df = self._hk_spot_df
        # 港股代码为 5 位数字, 如 00700
        hk_code = code.zfill(5)
        row = df[df["代码"] == hk_code]
        if row.empty:
            return None
        return self._parse_hk_item(row.iloc[0])

    def _parse_hk_item(self, item) -> dict:
        cur = float(item["最新价"])
        prev_close = float(item["昨收"])
        if prev_close == 0:
            return None
        change = cur - prev_close
        return {
            "price": cur,
            "change": round(change, 2),
            "change_pct": float(item["涨跌幅"]),
            "open": float(item["今开"]),
            "high": float(item["最高"]),
            "low": float(item["最低"]),
            "prev_close": prev_close,
            "source": self.name,
            "updated_at": beijing_now(),
        }

    # ── 统一入口 ──

    def fetch_quote(self, symbol: str) -> Optional[dict]:
        ak = self._get_ak()
        if ak is None:
            return None
        try:
            if self._is_hk(symbol):
                return self._fetch_hk_quote(symbol, ak)
            return self._fetch_a_quote(symbol, ak)
        except Exception:
            return None

    def fetch_history(self, symbol: str, days: int = 7) -> Optional[list]:
        """历史数据: A股用 stock_zh_a_hist, 港股用 stock_hk_hist"""
        code = symbol.split(".")[0]
        ak = self._get_ak()
        if ak is None:
            return None
        try:
            import datetime
            end = datetime.date.today()
            start = end - datetime.timedelta(days=days * 2)
            if self._is_hk(symbol):
                hk_code = code.zfill(5)
                df = ak.stock_hk_hist(
                    symbol=hk_code, period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",
                )
                date_col = "日期"
                close_col = "收盘"
            else:
                df = ak.stock_zh_a_hist(
                    symbol=code, period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",
                )
                date_col = "日期"
                close_col = "收盘"
            if df.empty:
                return None
            result = [
                {"date": str(r[date_col]), "close": float(r[close_col])}
                for _, r in df.iterrows() if float(r[close_col])
            ]
            return result[-days:] if result else None
        except Exception:
            return None
