"""多数据源行情适配器"""

from .finnhub import FinnhubAdapter
from .twse import TWSEAdapter
from .twse_openapi import TWSEOpenAPIAdapter
from .twstock_adapter import TWStockAdapter
from .jquants import JQuantsAdapter
from .stooq import StooqAdapter
from .sinahk import HKAdapter
from .yahoo import YahooAdapter
from .naver import NaverAdapter
from .tencent_jp import TencentJPAdapter
from .tencent_us import TencentUSAdapter
from .boerse_frankfurt import BoerseFrankfurtAdapter

__all__ = ["FinnhubAdapter", "TWSEAdapter", "TWSEOpenAPIAdapter", "TWStockAdapter", "JQuantsAdapter", "StooqAdapter", "HKAdapter", "YahooAdapter", "NaverAdapter", "TencentJPAdapter", "TencentUSAdapter", "BoerseFrankfurtAdapter"]
