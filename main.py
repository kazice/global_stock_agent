#!/usr/bin/env python3
"""
全球龙头上市公司行情监控 - 多数据源聚合系统

架构:
  watchlist.json → Market Router → [Finnhub, TWSE, J-Quants, Stooq, AKShare]
                                  → Cache Layer (cache/YYYY-MM-DD.json)
                                  → Reporter (Markdown/Text)
                                  → PushPlus 微信推送

GitHub Actions:
  定时: 周一至周五 北京时间 8:30 / 13:00
  触发: workflow_dispatch (GitHub 手动触发)

CLI 参数:
  python main.py              # 采集 + 推送
  python main.py --push-only  # 只用缓存推送, 不重新采集
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Optional

import requests

import config
from adapters import FinnhubAdapter, TWSEAdapter, JQuantsAdapter, StooqAdapter

# =====================================================================
#  市场路由
# =====================================================================

def route_symbol(symbol: str) -> str:
    """根据 symbol 后缀决定使用哪个数据源"""
    if "." not in symbol:
        return "finnhub"  # 美股
    suffix = symbol.rsplit(".", 1)[-1].upper()
    mapping = {
        "TW": "twse", "TWO": "twse",
        "T": "jquants",
        "KS": "stooq",
        "SH": "akshare", "SZ": "akshare",
        "DE": "stooq", "PA": "stooq", "SW": "stooq",
        "L": "stooq", "ST": "stooq", "CO": "stooq",
        "AS": "stooq", "SR": "stooq",
        "HK": "finnhub",
    }
    return mapping.get(suffix, "finnhub")


# 各数据源的备选方案 (主失败 → 备选)
# Stooq 可作通用兜底: 后缀必须小写, 美股需加 .us
FALLBACK_CHAIN = {
    "twse": ["stooq"],
    "jquants": ["stooq"],
    "akshare": [],
    "finnhub": ["stooq"],  # Finnhub 404 时用 stooq 再试
    "stooq": [],
}

# ADR/OTC 替代映射 (原代码 → 美股 ADR 代码)
# 所有主数据源+备选都失败后, 最后尝试通过 Finnhub 查 ADR
ADR_MAP = {
    "005930.KS": "SSNLF",       # 三星电子
    "034220.KS": "LPL",         # LG显示
    "LONN.SW": "LZAGY",        # Lonza
    "ROG.SW": "RHHBY",         # 罗氏 (Roche)
    "ABBN.SW": "ABBNY",        # ABB
    "VWS.CO": "VWDRY",         # 维斯塔斯 (Vestas)
    "MAERSK-B.CO": "AMKBY",    # 马士基 (Maersk)
    "DSV.CO": "DSDVY",         # DSV
    "GLEN.L": "GLNCY",         # 嘉能可 (Glencore)
    "RR.L": "RYCEY",           # 罗尔斯罗伊斯 (Rolls-Royce)
    "0175.HK": "GELYY",        # 吉利 (Geely)
    "0700.HK": "TCEHY",        # 腾讯 (Tencent)
    "SAND.ST": "SDVKY",        # 山特维克 (Sandvik)
    "ATCOA.ST": "ATLKY",       # 阿特拉斯科普柯 (Atlas Copco)
    "DPW.DE": "DHLGY",         # DHL (Deutsche Post)
}

# =====================================================================
#  缓存层
# =====================================================================

def get_cache_path(date_str: str = None) -> str:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(config.CACHE_DIR, f"{date_str}.json")


def load_cache(date_str: str = None) -> Optional[dict]:
    path = get_cache_path(date_str)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def save_cache(date_str: str, results: dict, pending: list):
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    path = get_cache_path(date_str)
    data = {
        "date": date_str,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "results": results,
        "pending": pending,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def load_close_history(symbol: str, target_days: int = 5) -> Optional[list]:
    """
    从历史缓存文件加载个股收盘价序列 (最近5个交易日)
    返回: [price1, price2, ...] 从远到近排列
    """
    import glob
    cache_files = sorted(glob.glob(os.path.join(config.CACHE_DIR, "[0-9]*.json")))
    closes = []
    for fpath in reversed(cache_files):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if symbol in data.get("results", {}):
            price = data["results"][symbol].get("price")
            if price and price > 0:
                closes.append(price)
                if len(closes) >= target_days:
                    break
    return closes[::-1] if closes else None

# =====================================================================
#  工具函数
# =====================================================================

def _setup_console():
    if os.name == "nt" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def load_watchlist(filepath: str) -> list[dict]:
    if not os.path.exists(filepath):
        print(f"[错误] 文件不存在: {filepath}")
        sys.exit(1)
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    stocks = data.get("stocks", [])
    if not stocks:
        print("[错误] 关注列表为空")
        sys.exit(1)
    return stocks


def fetch_with_fallback(
    symbol: str,
    adapters: dict,
    route_name: str,
) -> Optional[dict]:
    """按路由获取行情, 失败后按备选链重试, 最后尝试 ADR 兜底"""
    # 主数据源
    adapter = adapters.get(route_name)
    if adapter:
        result = adapter.fetch_quote(symbol)
        if result:
            return result

    # 备选链
    for fallback in FALLBACK_CHAIN.get(route_name, []):
        fb_adapter = adapters.get(fallback)
        if fb_adapter:
            result = fb_adapter.fetch_quote(symbol)
            if result:
                result["source"] = f"{result['source']}(fallback)"
                return result

    # ADR 最终兜底: 先试 Stooq (OTC粉单免费), 再试 Finnhub (主流ADR)
    adr_symbol = ADR_MAP.get(symbol)
    if adr_symbol:
        # 1) Stooq (支持 OTC 粉单)
        if "stooq" in adapters:
            result = adapters["stooq"].fetch_quote(adr_symbol)
            if result:
                result["source"] = "stooq(ADR)"
                return result
        # 2) Finnhub (主流 ADR)
        if "finnhub" in adapters:
            result = adapters["finnhub"].fetch_quote(adr_symbol)
            if result:
                result["source"] = "finnhub(ADR)"
                return result

    return None


def get_weekly_change(
    symbol: str, adapters: dict, route_name: str, current_price: float,
    days: int = 5,
) -> Optional[float]:
    """
    获取近一周涨跌幅 (%)
    优先级: 适配器历史API → 缓存历史收盘价
    """
    # 尝试1: 适配器的 fetch_history (Stooq/AKShare/JQuants)
    candidates = [route_name] + FALLBACK_CHAIN.get(route_name, [])
    for name in candidates:
        adapter = adapters.get(name)
        if adapter is None:
            continue
        try:
            history = adapter.fetch_history(symbol, days * 2)
            if history and len(history) >= 2:
                latest = history[-1]["close"]
                week_ago = history[0]["close"]
                if week_ago and latest > 0:
                    return round((latest - week_ago) / week_ago * 100, 2)
        except Exception:
            pass

    # 尝试2: 从缓存历史文件计算
    try:
        closes = load_close_history(symbol, target_days=days)
        if closes and len(closes) >= 2:
            week_ago_close = closes[0]
            if week_ago_close > 0:
                return round((current_price - week_ago_close) / week_ago_close * 100, 2)
    except Exception:
        pass

    return None

# =====================================================================
#  报告生成
# =====================================================================

def build_report(results: dict, stats: dict) -> str:
    """生成 Markdown 格式报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 全球龙头行情日报 ({now})",
        "",
        f"**成功** {stats['success']} | **待重试** {stats['pending']} | "
        f"**上涨** {stats['up']} | **下跌** {stats['down']}",
        "",
    ]

    # 日涨跌排行
    items = list(results.values())
    sorted_up = sorted(items, key=lambda x: x["change_pct"], reverse=True)
    sorted_down = sorted(items, key=lambda x: x["change_pct"])

    lines.append("## 今日涨幅 TOP 10")
    lines.append("| 名称 | 代码 | 最新价 | 涨跌幅 | 周涨跌 | 来源 |")
    lines.append("|------|------|--------|--------|--------|------|")
    for item in sorted_up[:10]:
        w = item.get("week_change")
        w_s = f"{w:+.2f}%" if w else "N/A"
        lines.append(f"| {item['name']} | {item['symbol']} | {item['price']:.2f} | "
                      f"{item['change_pct']:+.2f}% | {w_s} | {item['source']} |")
    lines.append("")

    lines.append("## 今日跌幅 TOP 10")
    lines.append("| 名称 | 代码 | 最新价 | 涨跌幅 | 周涨跌 | 来源 |")
    lines.append("|------|------|--------|--------|--------|------|")
    for item in sorted_down[:10]:
        w = item.get("week_change")
        w_s = f"{w:+.2f}%" if w else "N/A"
        lines.append(f"| {item['name']} | {item['symbol']} | {item['price']:.2f} | "
                      f"{item['change_pct']:+.2f}% | {w_s} | {item['source']} |")
    lines.append("")

    # 周涨跌排行 (只显示有周数据的)
    week_items = [it for it in items if it.get("week_change") is not None]
    if week_items:
        wk_up = sorted(week_items, key=lambda x: x["week_change"], reverse=True)
        wk_down = sorted(week_items, key=lambda x: x["week_change"])
        lines.append("## 近一周涨幅 TOP 10")
        lines.append("| 名称 | 代码 | 最新价 | 周涨跌 | 来源 |")
        lines.append("|------|------|--------|--------|------|")
        for item in wk_up[:10]:
            lines.append(f"| {item['name']} | {item['symbol']} | {item['price']:.2f} | "
                          f"{item['week_change']:+.2f}% | {item['source']} |")
        lines.append("")

        lines.append("## 近一周跌幅 TOP 10")
        lines.append("| 名称 | 代码 | 最新价 | 周涨跌 | 来源 |")
        lines.append("|------|------|--------|--------|------|")
        for item in wk_down[:10]:
            lines.append(f"| {item['name']} | {item['symbol']} | {item['price']:.2f} | "
                          f"{item['week_change']:+.2f}% | {item['source']} |")
        lines.append("")

    # 全量明细
    lines.append("## 全量明细")
    lines.append("| 名称 | 代码 | 最新价 | 涨跌幅 | 周涨跌 | 来源 |")
    lines.append("|------|------|--------|--------|--------|------|")
    for item in sorted(items, key=lambda x: x["symbol"]):
        w = item.get("week_change")
        w_s = f"{w:+.2f}%" if w else "N/A"
        lines.append(f"| {item['name']} | {item['symbol']} | {item['price']:.2f} | "
                      f"{item['change_pct']:+.2f}% | {w_s} | {item['source']} |")

    return "\n".join(lines)


def build_report_text(results: dict, stats: dict) -> str:
    """纯文本版 (推送到微信时使用)"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"全球龙头行情日报  {now}", "=" * 55, ""]
    lines.append(f"成功:{stats['success']}  待重试:{stats['pending']}  "
                 f"上涨:{stats['up']}  下跌:{stats['down']}")
    lines.append("")

    items = list(results.values())

    # 日涨幅 TOP 10
    lines.append("[今日涨幅 TOP 10]")
    for item in sorted(items, key=lambda x: x["change_pct"], reverse=True)[:10]:
        w = item.get("week_change")
        w_s = f" 周{w:+.2f}%" if w else ""
        lines.append(f"  [{item['source']}] {item['name']:<6s} "
                      f"{item['price']:>8.2f}  {item['change_pct']:+.2f}%{w_s}")
    lines.append("")

    # 日跌幅 TOP 10
    lines.append("[今日跌幅 TOP 10]")
    for item in sorted(items, key=lambda x: x["change_pct"])[:10]:
        w = item.get("week_change")
        w_s = f" 周{w:+.2f}%" if w else ""
        lines.append(f"  [{item['source']}] {item['name']:<6s} "
                      f"{item['price']:>8.2f}  {item['change_pct']:+.2f}%{w_s}")
    lines.append("")

    # 周涨跌排行
    week_items = [it for it in items if it.get("week_change") is not None]
    if week_items:
        lines.append("[近一周涨幅 TOP 5]")
        for item in sorted(week_items, key=lambda x: x["week_change"], reverse=True)[:5]:
            lines.append(f"  [{item['source']}] {item['name']:<6s} "
                          f"{item['price']:>8.2f}  周{item['week_change']:+.2f}%")
        lines.append("")

        lines.append("[近一周跌幅 TOP 5]")
        for item in sorted(week_items, key=lambda x: x["week_change"])[:5]:
            lines.append(f"  [{item['source']}] {item['name']:<6s} "
                          f"{item['price']:>8.2f}  周{item['week_change']:+.2f}%")
        lines.append("")

    # 全量
    lines.append("[全量明细]")
    for item in sorted(items, key=lambda x: x["symbol"]):
        w = item.get("week_change")
        w_s = f" 周{w:+.2f}%" if w else ""
        lines.append(f"  [{item['source']}] {item['name']:<6s} "
                      f"{item['price']:>8.2f}  {item['change_pct']:+.2f}%{w_s}")

    return "\n".join(lines)


def push_wx(title: str, content: str, template: str = "markdown"):
    """PushPlus 微信推送"""
    token = config.PUSHPLUS_TOKEN
    if not token:
        print("[跳过] 未配置 PUSHPLUS_TOKEN, 不推送微信")
        return
    try:
        r = requests.post(
            "https://www.pushplus.plus/send",
            json={"token": token, "title": title, "content": content, "template": template},
            timeout=15,
        )
        res = r.json()
        if res.get("code") == 200:
            print(f"[推送成功] {res.get('msg', '')}")
        else:
            print(f"[推送失败] {res}")
    except Exception as e:
        print(f"[推送异常] {e}")

# =====================================================================
#  结果汇总与输出
# =====================================================================

def finish(stocks: list, results: dict, pending: list):
    """生成报告、保存、推送"""
    total = len(stocks)
    success = len(results)
    up = sum(1 for r in results.values() if r.get("change_pct", 0) > 0)
    down = success - up
    stats = {"success": success, "pending": len(pending), "up": up, "down": down}

    print(f"\n{'=' * 60}")
    print(f"采集完成: 成功 {success}/{total}  |  上涨 {up}  下跌 {down}")

    # Markdown 报告
    md_report = build_report(results, stats)
    report_path = "report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md_report)
    print(f"[保存] {report_path}")

    # 纯文本版（微信推送用）
    txt_report = build_report_text(results, stats)
    txt_path = "report.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt_report)
    print(f"[保存] {txt_path}")

    # 控制台预览（前 30 行）
    preview = "\n".join(txt_report.splitlines()[:30])
    print(f"\n{preview}")
    print(f"\n... (完整报告见 report.md / report.txt)")

    if pending:
        print(f"\n[待重试] {len(pending)} 只:")
        name_map = {s["symbol"]: s["name"] for s in stocks}
        for sym in pending[:15]:
            print(f"  - {name_map.get(sym, sym)} ({sym})")
        if len(pending) > 15:
            print(f"  ... 共 {len(pending)} 只")

    # 推送
    push_wx(
        f"全球龙头行情日报 ({datetime.now().strftime('%m-%d')})",
        txt_report,
        template="html",  # PushPlus 纯文本用 html 模板
    )

    if success < total * 0.2:
        print("[警告] 获取成功率低于 20%")
        sys.exit(1)

# =====================================================================
#  主流程
# =====================================================================

def main():
    _setup_console()

    # CLI 参数解析
    parser = argparse.ArgumentParser(description="全球龙头行情监控")
    parser.add_argument("--push-only", action="store_true",
                        help="仅推送已有缓存, 不重新采集数据")
    args = parser.parse_args()

    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"[日期] {date_str}")

    stocks = load_watchlist(config.WATCHLIST_FILE)
    print(f"[加载] 关注列表: {config.WATCHLIST_FILE}")
    print(f"[完成] 共 {len(stocks)} 只股票")

    # ── --push-only 模式: 直接用缓存推送 ──
    if args.push_only:
        cached = load_cache(date_str)
        if not cached:
            # 也尝试用最近一天的缓存
            import glob as _glob
            cache_files = sorted(_glob.glob(os.path.join(config.CACHE_DIR, "*.json")))
            if cache_files:
                with open(cache_files[-1], "r", encoding="utf-8") as _f:
                    cached = json.load(_f)
                print(f"[缓存] 使用最近缓存: {os.path.basename(cache_files[-1])}")
            else:
                print("[错误] 没有缓存可用, 请先执行完整采集")
                sys.exit(1)
        results_cached = cached.get("results", {})
        pending_cached = cached.get("pending", [])
        name_map = {s["symbol"]: s["name"] for s in stocks}
        for sym, data in results_cached.items():
            data["name"] = name_map.get(sym, sym)
            data["symbol"] = sym
        print(f"[缓存] {len(results_cached)} 条数据")
        finish(stocks, results_cached, pending_cached)
        return

    print("")

    # ── 检查缓存 ──
    cached = load_cache(date_str) if not config.FORCE_REFRESH else None
    if cached:
        results_cached = cached.get("results", {})
        pending_cached = cached.get("pending", [])
        # 标记名称
        name_map = {s["symbol"]: s["name"] for s in stocks}
        for sym, data in results_cached.items():
            data["name"] = name_map.get(sym, sym)
            data["symbol"] = sym
        # 过滤出需要刷新(缓存中没有 或 pending 中)
        fresh_symbols = []
        for s in stocks:
            sym = s["symbol"]
            if sym not in results_cached or sym in pending_cached:
                fresh_symbols.append(s)

        print(f"[缓存] {len(results_cached)} 条已缓存")
        if fresh_symbols:
            print(f"[刷新] {len(fresh_symbols)} 条待获取\n")
            fresh_stocks = fresh_symbols
            results = dict(results_cached)
            pending = list(set(pending_cached))
        else:
            print("[完成] 全部数据已缓存")
            finish(stocks, results_cached, pending_cached)
            return
    else:
        fresh_stocks = list(stocks)
        results = {}
        pending = []

    # ── 初始化适配器 ──
    adapters = {
        "finnhub": FinnhubAdapter(config.FINNHUB_API_KEY, config.FINNHUB_BASE),
        "twse": TWSEAdapter(),
        "jquants": JQuantsAdapter(),
        "stooq": StooqAdapter(api_key=config.STOOQ_API_KEY),
    }
    # AKShare 按需加载
    try:
        from adapters.akshare import AkShareAdapter
        adapters["akshare"] = AkShareAdapter()
    except ImportError:
        print("[警告] akshare 未安装, A 股将跳过")
        adapters["akshare"] = None

    # ── 逐只获取行情 ──
    total = len(fresh_stocks)
    for i, stock in enumerate(fresh_stocks, 1):
        name = stock["name"]
        symbol = stock["symbol"]
        route = route_symbol(symbol)

        print(f"  [{i:>3}/{total:<3}] {name:<8s} {symbol:<12s}", end="", flush=True)

        quote = fetch_with_fallback(symbol, adapters, route)
        if quote:
            quote["name"] = name
            quote["symbol"] = symbol
            wc = get_weekly_change(symbol, adapters, route, quote["price"])
            if wc is not None:
                quote["week_change"] = wc
            results[symbol] = quote
            arrow = "+" if quote.get("change", 0) >= 0 else ""
            src = quote.get("source", "?")
            print(f"  {arrow}{quote['price']:.2f}  {quote['change_pct']:+.2f}%  [{src}]")
        else:
            if symbol not in pending:
                pending.append(symbol)
            print(f"  [无数据]")

        if i < total:
            time.sleep(config.REQUEST_INTERVAL)

    # ── 保存缓存 → 输出 ──
    save_cache(date_str, results, pending)
    print(f"\n[缓存] 已保存到 {get_cache_path(date_str)}")
    finish(stocks, results, pending)


if __name__ == "__main__":
    main()
