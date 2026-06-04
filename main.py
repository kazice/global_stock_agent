#!/usr/bin/env python3
"""
全球龙头上市公司行情监控 - 多数据源聚合系统

架构:
  watchlist.json → Market Router → [Finnhub, TWSE, J-Quants, Stooq, AKShare]
                                  → Cache Layer (cache/YYYY-MM-DD.json)
                                  → Reporter (Markdown/HTML)
                                  → PushPlus 微信推送

GitHub Actions:
  定时: 周一至周五 北京时间 8:30 / 13:00
  触发: workflow_dispatch / repository_dispatch

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
        return "finnhub"
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


FALLBACK_CHAIN = {
    "twse": ["stooq"],
    "jquants": ["stooq"],
    "akshare": [],
    "finnhub": ["stooq"],
    "stooq": [],
}


# 板块分组 (对应 watchlist.json 中股票的顺序索引)
SECTORS = [
    (0, 60, "半导体"),
    (61, 84, "锂电/电池材料"),
    (85, 99, "汽车"),
    (100, 110, "算力/服务器"),
    (111, 124, "互联网/软件"),
    (125, 146, "屏幕/光学/电子制造"),
    (147, 177, "医药/医疗"),
    (178, 188, "军工/航空"),
    (189, 204, "能源/光伏"),
    (205, 217, "金融"),
    (218, 228, "通信"),
    (229, 240, "互联网平台"),
    (241, 251, "工业/自动化"),
    (252, 261, "工程机械"),
    (262, 271, "化工"),
    (272, 281, "物流/运输"),
    (282, 287, "消费"),
]


def get_sector(index: int) -> str:
    for start, end, name in SECTORS:
        if start <= index <= end:
            return name
    return "其他"


# ADR/OTC 替代映射
ADR_MAP = {
    "005930.KS": "SSNLF",
    "034220.KS": "LPL",
    "LONN.SW": "LZAGY",
    "ROG.SW": "RHHBY",
    "ABBN.SW": "ABBNY",
    "VWS.CO": "VWDRY",
    "MAERSK-B.CO": "AMKBY",
    "DSV.CO": "DSDVY",
    "GLEN.L": "GLNCY",
    "RR.L": "RYCEY",
    "0175.HK": "GELYY",
    "0700.HK": "TCEHY",
    "SAND.ST": "SDVKY",
    "ATCOA.ST": "ATLKY",
    "DPW.DE": "DHLGY",
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
    """从历史缓存文件加载个股收盘价序列 (最近5个交易日)"""
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
    symbol: str, adapters: dict, route_name: str,
) -> Optional[dict]:
    """按路由获取行情, 失败后按备选链重试, 最后尝试 ADR 兜底"""
    adapter = adapters.get(route_name)
    if adapter:
        result = adapter.fetch_quote(symbol)
        if result:
            return result

    for fb in FALLBACK_CHAIN.get(route_name, []):
        fb_a = adapters.get(fb)
        if fb_a:
            result = fb_a.fetch_quote(symbol)
            if result:
                result["source"] = f"{result['source']}(fallback)"
                return result

    adr = ADR_MAP.get(symbol)
    if adr:
        if "stooq" in adapters:
            result = adapters["stooq"].fetch_quote(adr)
            if result:
                result["source"] = "stooq(ADR)"
                return result
        if "finnhub" in adapters:
            result = adapters["finnhub"].fetch_quote(adr)
            if result:
                result["source"] = "finnhub(ADR)"
                return result
    return None


def get_weekly_change(
    symbol: str, adapters: dict, route_name: str, current_price: float,
    days: int = 5,
) -> Optional[float]:
    """近一周涨跌幅: 适配器历史API -> 缓存历史收盘价"""
    candidates = [route_name] + FALLBACK_CHAIN.get(route_name, [])
    for name in candidates:
        a = adapters.get(name)
        if a is None:
            continue
        try:
            hist = a.fetch_history(symbol, days * 2)
            if hist and len(hist) >= 2:
                latest = hist[-1]["close"]
                week_ago = hist[0]["close"]
                if week_ago and latest > 0:
                    return round((latest - week_ago) / week_ago * 100, 2)
        except Exception:
            pass

    try:
        closes = load_close_history(symbol, target_days=days)
        if closes and len(closes) >= 2:
            wa = closes[0]
            if wa > 0:
                return round((current_price - wa) / wa * 100, 2)
    except Exception:
        pass
    return None


# =====================================================================
#  报告生成
# =====================================================================

def _sector_items(stocks: list, results: dict):
    """按 watchlist 顺序生成 (sector, [(name, symbol, data), ...]) 分组"""
    groups = {}
    for i, s in enumerate(stocks):
        sym = s["symbol"]
        if sym not in results:
            continue
        sec = get_sector(i)
        groups.setdefault(sec, []).append((s["name"], sym, results[sym]))
    ordered = []
    seen = set()
    for _, _, sn in SECTORS:
        if sn in groups:
            ordered.append((sn, groups[sn]))
            seen.add(sn)
    for sn in groups:
        if sn not in seen:
            ordered.append((sn, groups[sn]))
    return ordered


def build_report(stocks: list, results: dict, stats: dict) -> str:
    """Markdown 报告 (板块分组 + 红绿箭头)"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 全球龙头行情日报 ({now})",
        "",
        f"**成功** {stats['success']} | **待重试** {stats['pending']} | "
        f"**上涨** {stats['up']} | **下跌** {stats['down']}",
        "",
    ]
    items = list(results.values())
    su = sorted(items, key=lambda x: x["change_pct"], reverse=True)
    sd = sorted(items, key=lambda x: x["change_pct"])

    lines.append("## 今日涨幅 TOP 10")
    lines.append("| 名称 | 代码 | 最新价 | 涨跌幅 | 周涨跌 | 来源 |")
    lines.append("|------|------|--------|--------|--------|------|")
    for it in su[:10]:
        w = it.get("week_change")
        ws = f"{w:+.2f}%" if w else "N/A"
        lines.append(f"| {it['name']} | {it['symbol']} | {it['price']:.2f} | "
                      f"🟢{it['change_pct']:+.2f}% | {ws} | {it['source']} |")
    lines.append("")

    lines.append("## 今日跌幅 TOP 10")
    lines.append("| 名称 | 代码 | 最新价 | 涨跌幅 | 周涨跌 | 来源 |")
    lines.append("|------|------|--------|--------|--------|------|")
    for it in sd[:10]:
        w = it.get("week_change")
        ws = f"{w:+.2f}%" if w else "N/A"
        lines.append(f"| {it['name']} | {it['symbol']} | {it['price']:.2f} | "
                      f"🔴{it['change_pct']:+.2f}% | {ws} | {it['source']} |")
    lines.append("")

    wk = [i for i in items if i.get("week_change") is not None]
    if wk:
        lines.append("## 近一周涨幅 TOP 10")
        lines.append("| 名称 | 代码 | 最新价 | 周涨跌 | 来源 |")
        lines.append("|------|------|--------|--------|------|")
        for it in sorted(wk, key=lambda x: x["week_change"], reverse=True)[:10]:
            lines.append(f"| {it['name']} | {it['symbol']} | {it['price']:.2f} | "
                          f"{it['week_change']:+.2f}% | {it['source']} |")
        lines.append("")
        lines.append("## 近一周跌幅 TOP 10")
        for it in sorted(wk, key=lambda x: x["week_change"])[:10]:
            lines.append(f"| {it['name']} | {it['symbol']} | {it['price']:.2f} | "
                          f"{it['week_change']:+.2f}% | {it['source']} |")
        lines.append("")

    lines.append("## 全量明细（按板块）")
    for sec_name, group in _sector_items(stocks, results):
        lines.append("")
        lines.append(f"### {sec_name}")
        lines.append("| 名称 | 代码 | 最新价 | 涨跌幅 | 周涨跌 | 来源 |")
        lines.append("|------|------|--------|--------|--------|------|")
        for name, sym, it in group:
            w = it.get("week_change")
            ws = f"{w:+.2f}%" if w else "N/A"
            cp = it["change_pct"]
            arrow = "🟢" if cp >= 0 else "🔴"
            lines.append(f"| {name} | {sym} | {it['price']:.2f} | "
                          f"{arrow}{cp:+.2f}% | {ws} | {it['source']} |")
    return "\n".join(lines)


def _color(val: float) -> str:
    if val > 0:
        return f'<font color="#e74c3c">+{val:.2f}%</font>'
    return f'<font color="#27ae60">{val:.2f}%</font>'


def build_report_html(stocks: list, results: dict, stats: dict) -> str:
    """HTML 版 (微信推送用, 红涨绿跌)"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f'<h3>全球龙头行情日报 ({now})</h3>',
        f'<p>成功 {stats["success"]} | 待重试 {stats["pending"]} | '
        f'<font color="#e74c3c">上涨 {stats["up"]}</font> | '
        f'<font color="#27ae60">下跌 {stats["down"]}</font></p>',
        "<hr>",
    ]
    items = list(results.values())
    su = sorted(items, key=lambda x: x["change_pct"], reverse=True)
    sd = sorted(items, key=lambda x: x["change_pct"])

    lines.append("<b>涨幅 TOP 10</b><br>")
    for it in su[:10]:
        lines.append(f'{it["name"]} {it["price"]:.2f} {_color(it["change_pct"])}<br>')
    lines.append("<br><b>跌幅 TOP 10</b><br>")
    for it in sd[:10]:
        lines.append(f'{it["name"]} {it["price"]:.2f} {_color(it["change_pct"])}<br>')
    lines.append("<hr>")

    for sec_name, group in _sector_items(stocks, results):
        lines.append(f'<b>【{sec_name}】</b><br>')
        for name, _sym, it in group:
            wk = it.get("week_change")
            wks = f' 周{_color(wk)}' if wk else ""
            lines.append(f'{name} {it["price"]:.2f} {_color(it["change_pct"])}{wks}<br>')
        lines.append("<br>")
    return "\n".join(lines)


def push_wx(title: str, content: str, template: str = "markdown"):
    """PushPlus 微信推送"""
    token = config.PUSHPLUS_TOKEN
    if not token:
        print("[跳过] 未配置 PUSHPLUS_TOKEN")
        return
    try:
        r = requests.post(
            "https://www.pushplus.plus/send",
            json={"token": token, "title": title, "content": content,
                  "template": template},
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
    md = build_report(stocks, results, stats)
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(md)
    print("[保存] report.md")

    # HTML 报告 (微信推送用)
    html = build_report_html(stocks, results, stats)
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("[保存] report.html")

    # 控制台预览
    simple = [
        f"全球龙头行情日报 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 55,
        f"成功:{success}  待重试:{len(pending)}  上涨:{up}  下跌:{down}",
    ]
    print("\n".join(simple))

    if pending:
        nm = {s["symbol"]: s["name"] for s in stocks}
        print(f"\n[待重试] {len(pending)} 只 (前10):")
        for sym in pending[:10]:
            print(f"  - {nm.get(sym, sym)} ({sym})")

    push_wx(
        f"全球龙头行情日报 ({datetime.now().strftime('%m-%d')})",
        html,
        template="html",
    )

    if success < total * 0.2:
        print("[警告] 获取成功率低于 20%")
        sys.exit(1)


# =====================================================================
#  主流程
# =====================================================================

def main():
    _setup_console()

    parser = argparse.ArgumentParser(description="全球龙头行情监控")
    parser.add_argument("--push-only", action="store_true",
                        help="仅推送已有缓存, 不重新采集")
    args = parser.parse_args()

    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"[日期] {date_str}")

    stocks = load_watchlist(config.WATCHLIST_FILE)
    print(f"[加载] 关注列表: {config.WATCHLIST_FILE}")
    print(f"[完成] 共 {len(stocks)} 只股票")

    # --push-only 模式
    if args.push_only:
        cached = load_cache(date_str)
        if not cached:
            import glob as _g
            cfs = sorted(_g.glob(os.path.join(config.CACHE_DIR, "*.json")))
            if cfs:
                with open(cfs[-1], "r", encoding="utf-8") as _f:
                    cached = json.load(_f)
                print(f"[缓存] 使用最近: {os.path.basename(cfs[-1])}")
            else:
                print("[错误] 无缓存可用, 请先执行完整采集")
                sys.exit(1)
        rc = cached.get("results", {})
        pc = cached.get("pending", [])
        nm = {s["symbol"]: s["name"] for s in stocks}
        for sym, d in rc.items():
            d["name"] = nm.get(sym, sym)
            d["symbol"] = sym
        print(f"[缓存] {len(rc)} 条数据")
        finish(stocks, rc, pc)
        return

    print("")

    # 检查缓存
    cached = load_cache(date_str) if not config.FORCE_REFRESH else None
    if cached:
        rc = cached.get("results", {})
        pc = cached.get("pending", [])
        nm = {s["symbol"]: s["name"] for s in stocks}
        for sym, d in rc.items():
            d["name"] = nm.get(sym, sym)
            d["symbol"] = sym
        fresh = []
        for s in stocks:
            sym = s["symbol"]
            if sym not in rc or sym in pc:
                fresh.append(s)
        print(f"[缓存] {len(rc)} 条已缓存")
        if fresh:
            print(f"[刷新] {len(fresh)} 条待获取\n")
            fresh_stocks = fresh
            results = dict(rc)
            pending = list(set(pc))
        else:
            print("[完成] 全部数据已缓存")
            finish(stocks, rc, pc)
            return
    else:
        fresh_stocks = list(stocks)
        results = {}
        pending = []

    # 初始化适配器
    adapters = {
        "finnhub": FinnhubAdapter(config.FINNHUB_API_KEY, config.FINNHUB_BASE),
        "twse": TWSEAdapter(),
        "jquants": JQuantsAdapter(),
        "stooq": StooqAdapter(api_key=config.STOOQ_API_KEY),
    }
    try:
        from adapters.akshare import AkShareAdapter
        adapters["akshare"] = AkShareAdapter()
    except ImportError:
        print("[警告] akshare 未安装, A 股跳过")
        adapters["akshare"] = None

    # 逐只获取行情
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
            print(f"  {arrow}{quote['price']:.2f}  {quote['change_pct']:+.2f}%  [{quote['source']}]")
        else:
            if symbol not in pending:
                pending.append(symbol)
            print(f"  [无数据]")

        if i < total:
            time.sleep(config.REQUEST_INTERVAL)

    save_cache(date_str, results, pending)
    print(f"\n[缓存] 已保存到 {get_cache_path(date_str)}")
    finish(stocks, results, pending)


if __name__ == "__main__":
    main()
