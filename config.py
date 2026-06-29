"""
配置模块 - 从环境变量读取配置
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Finnhub API Key (美股/部分港股)
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "d8gesfhr01qlgcuj3d20d8gesfhr01qlgcuj3d2g")

# PushPlus Token (微信推送，从 https://www.pushplus.plus/ 获取)
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")

# 关注列表文件
WATCHLIST_FILE = os.getenv("WATCHLIST_FILE", "watchlist.json")

# 缓存目录
CACHE_DIR = os.getenv("CACHE_DIR", "cache")

# 请求间隔(秒) - 各数据源限速
REQUEST_INTERVAL = float(os.getenv("REQUEST_INTERVAL", "0.35"))

# Finnhub API 地址
FINNHUB_BASE = "https://finnhub.io/api/v1"

# 报告格式: markdown / text
REPORT_FORMAT = os.getenv("REPORT_FORMAT", "markdown")

# 当日报价已缓存时是否强制刷新
FORCE_REFRESH = os.getenv("FORCE_REFRESH", "1") == "1"

# Stooq API Key (可选, 部分IP需 Key 才能访问 Stooq CSV)
# 获取: https://stooq.com → 搜任意股票 → 下载CSV → 复制URL中的 apikey 参数
STOOQ_API_KEY = os.getenv("STOOQ_API_KEY", "")
