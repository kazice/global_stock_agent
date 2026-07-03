#!/usr/bin/env python3
"""
全球龙头上市公司行情监控 - 多数据源聚合系统
"""
import argparse, json, os, sys, time
from datetime import datetime
from typing import Optional
import requests
import config
from adapters import FinnhubAdapter, TWSEAdapter, TWStockAdapter, JQuantsAdapter, StooqAdapter, HKAdapter, YahooAdapter, NaverAdapter, TencentJPAdapter, TencentUSAdapter, BoerseFrankfurtAdapter

TAIWAN_SUFFIXES = {"TW", "TWO"}
EUROPE_SUFFIXES = {"DE", "PA", "SW", "L", "ST", "CO", "AS"}

def route_symbol(symbol: str) -> str:
    if "." not in symbol: return "tencent_us"
    suffix = symbol.rsplit(".", 1)[-1].upper()
    if suffix in TAIWAN_SUFFIXES:
        return "taiwan"
    if suffix in EUROPE_SUFFIXES:
        return "europe"
    m = {"T":"tencent_jp","KS":"naver",
         "SH":"akshare","SZ":"akshare",
         "SR":"stooq","HK":"hk"}
    return m.get(suffix, "finnhub")
FALLBACK_CHAIN = {
    "taiwan":["twse","twstock","yahoo","stooq"],
    "europe":["stooq","yahoo","boerse_frankfurt","finnhub"],
    "twse":["twstock","yahoo","stooq"],
    "twstock":["yahoo","stooq"],
    "jquants":["yahoo"],
    "akshare":["stooq","yahoo"],
    "hk":["hk","stooq","yahoo"],
    "finnhub":["finnhub","stooq","yahoo"],
    "stooq":["stooq","yahoo"],
    "naver":["naver","stooq","yahoo"],
    "yahoo":["yahoo","stooq"],
    "tencent_jp":["tencent_jp","stooq","yahoo"],
    "tencent_us":["tencent_us","finnhub","yahoo"],
}
# ============================================================
# 板块分类: 优先按 symbol 精确匹配, 兜底按 watchlist 索引范围
# 索引范围由 watchlist.json 按空行分隔的段落精确计算得出
# ============================================================
SECTORS = [
    (  0,  57, "半导体"),           # 58支: 台积电~通富微电
    ( 58,  80, "锂电/电池材料"),    # 23支: 雅保~拓普集团
    ( 81,  95, "汽车"),             # 15支: 特斯拉~赛力斯
    ( 96, 106, "算力/服务器"),      # 11支: 超微电脑~新易盛
    (107, 120, "互联网/软件"),      # 14支: 微软~索尼
    (121, 142, "屏幕/光学/电子制造"),  # 22支: LG显示~华硕
    (143, 172, "医药/医疗"),        # 30支: 药明康德~联影医疗
    (173, 182, "军工/航空"),        # 10支: 波音~中航沈飞
    (183, 197, "能源/光伏"),        # 15支: 埃克森美孚~西门子能源
    (198, 209, "金融"),             # 12支: 摩根大通~招商银行
    (210, 219, "通信"),             # 10支: 中兴通讯~T-Mobile
    (220, 230, "互联网平台"),       # 11支: 拼多多~B站
    (231, 240, "工业/自动化"),      # 10支: 发那科~三菱电机
    (241, 249, "工程机械"),         # 9支: 卡特彼勒~阿特拉斯科普柯
    (250, 258, "化工"),             # 9支: 陶氏~阿克苏诺贝尔
    (259, 267, "物流/运输"),        # 9支: UPS~商船三井
    (268, 272, "消费"),             # 5支: LVMH~耐克
]

# 在所属板块范围内但分类明显不合理的 symbol → 手动修正
SECTOR_OVERRIDES = {
    "SONY": "消费电子",             # 索尼 → 不应在"互联网/软件"
    "300124.SZ": "工业/自动化",     # 汇川技术 → 不应在"锂电/电池材料"
    "002050.SZ": "汽车",            # 三花智控 → 不应在"锂电/电池材料"
    "601689.SH": "汽车",            # 拓普集团 → 不应在"锂电/电池材料"
    "CSCO": "通信",                 # 思科 → 不应在"算力/服务器"
    "ANET": "通信",                 # Arista → 不应在"算力/服务器"
    "COHR": "通信",                 # Coherent → 不应在"算力/服务器"
    "300308.SZ": "通信",            # 中际旭创 → 不应在"算力/服务器"
    "300502.SZ": "通信",            # 新易盛 → 不应在"算力/服务器"
}

def get_sector(i: int, symbol: str = "") -> str:
    # 优先使用 symbol 精确覆盖
    if symbol and symbol in SECTOR_OVERRIDES:
        return SECTOR_OVERRIDES[symbol]
    # 兜底: 按索引范围
    for s,e,n in SECTORS:
        if s <= i <= e: return n
    return "其他"
ADR_MAP = {"005930.KS":"SSNLF","034220.KS":"LPL","LONN.SW":"LZAGY","ROG.SW":"RHHBY",
           "ABBN.SW":"ABBNY","VWS.CO":"VWDRY","MAERSK-B.CO":"AMKBY","DSV.CO":"DSDVY",
           "GLEN.L":"GLNCY","RR.L":"RYCEY","0175.HK":"GELYY","0700.HK":"TCEHY",
           "SAND.ST":"SDVKY","ATCOA.ST":"ATLKY","DPW.DE":"DHLGY"}

def get_cache_path(d: str = None) -> str:
    return os.path.join(config.CACHE_DIR, f"{(d or datetime.now().strftime('%Y-%m-%d'))}.json")
def load_cache(d: str = None) -> Optional[dict]:
    p = get_cache_path(d)
    if os.path.exists(p):
        try:
            with open(p,"r",encoding="utf-8") as f: return json.load(f)
        except: pass
    return None
def save_cache(d: str, results: dict, pending: list):
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    with open(get_cache_path(d),"w",encoding="utf-8") as f:
        json.dump({"date":d,"fetched_at":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "results":results,"pending":pending}, f, ensure_ascii=False, indent=2)
def load_close_history(sym: str, n: int = 5) -> Optional[list]:
    import glob
    cs = []
    for fp in reversed(sorted(glob.glob(os.path.join(config.CACHE_DIR,"[0-9]*.json")))):
        try:
            with open(fp,"r",encoding="utf-8") as f: d = json.load(f)
        except: continue
        if sym in d.get("results",{}):
            p = d["results"][sym].get("price")
            if p and p > 0:
                cs.append(p)
                if len(cs) >= n: break
    return cs[::-1] if cs else None
def _setup_console():
    if os.name == "nt" and hasattr(sys.stdout,"reconfigure"):
        try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except: pass
def load_watchlist(fp: str) -> list:
    if not os.path.exists(fp): print(f"[错误] 文件不存在: {fp}"); sys.exit(1)
    with open(fp,"r",encoding="utf-8") as f: s = json.load(f).get("stocks",[])
    if not s: print("[错误] 关注列表为空"); sys.exit(1)
    return s

def fetch_with_fallback(sym: str, adpts: dict, rt: str) -> Optional[dict]:
    tried = set()
    synthetic_route = rt not in adpts
    a = adpts.get(rt)
    if a:
        tried.add(rt)
        r = a.fetch_quote(sym)
        if r: return r
    for fb in FALLBACK_CHAIN.get(rt,[]):
        if fb in tried:
            continue
        tried.add(fb)
        fa = adpts.get(fb)
        if fa:
            r = fa.fetch_quote(sym)
            if r:
                if not synthetic_route:
                    r["source"] = f"{r['source']}(fallback)"
                return r
    adr = ADR_MAP.get(sym)
    if adr:
        if "stooq" in adpts:
            r = adpts["stooq"].fetch_quote(adr)
            if r: r["source"] = "stooq(ADR)"; return r
        if "finnhub" in adpts:
            r = adpts["finnhub"].fetch_quote(adr)
            if r: r["source"] = "finnhub(ADR)"; return r
    return None

def history_source_candidates(sym: str, adpts: dict, src_nm: str = "") -> list:
    suffix = sym.rsplit(".", 1)[-1].upper() if "." in sym else "US"
    if suffix in TAIWAN_SUFFIXES:
        chain = ["twstock", "yahoo", "stooq"]
    elif suffix in EUROPE_SUFFIXES:
        chain = ["stooq", "yahoo", "boerse_frankfurt"]
    elif suffix == "T":
        chain = ["tencent_jp", "stooq", "yahoo", "jquants"]
    elif suffix == "KS":
        chain = ["naver", "stooq", "yahoo"]
    elif suffix in {"SH", "SZ"}:
        chain = ["akshare", "stooq", "yahoo"]
    elif suffix == "HK":
        chain = ["hk", "stooq", "yahoo"]
    else:
        chain = [src_nm] if src_nm else []
        chain += ["stooq", "yahoo", "jquants"]

    ordered = []
    for nm in ([src_nm] if src_nm else []) + chain:
        if nm and nm not in ordered and nm in adpts:
            ordered.append(nm)
    return ordered

def get_weekly_change(sym: str, adpts: dict, cur_p: float,
                      src_nm: str = "", days: int = 5) -> Optional[float]:
    """
    计算周涨跌幅。
    src_nm: 成功获取实时报价的适配器名称, 优先用它查历史(保证币种一致)
    """
    # 优先使用同市场/同币种的历史数据源，避免跨市场源串到周涨跌计算。
    candidates = history_source_candidates(sym, adpts, src_nm=src_nm)
    for nm in candidates:
        a = adpts.get(nm)
        if a is None:
            continue
        try:
            h = a.fetch_history(sym, days + 1)
            if h and len(h) >= 2:
                wa = h[0]["close"]
                if wa > 0:
                    pct = round((cur_p - wa) / wa * 100, 2)
                    # 单周涨跌幅超过 50% 几乎肯定是数据源交叉错位, 丢弃
                    if abs(pct) > 50:
                        continue
                    return pct
        except:
            pass
    # 兜底: 缓存
    try:
        cs = load_close_history(sym, n=days)
        if cs and len(cs) >= 2 and cs[0] > 0:
            pct = round((cur_p - cs[0]) / cs[0] * 100, 2)
            if abs(pct) <= 50:
                return pct
    except:
        pass
    return None

def _sector_items(stocks: list, results: dict):
    groups = {}
    for i,s in enumerate(stocks):
        if s["symbol"] not in results: continue
        sec = s.get("sector") or get_sector(i, symbol=s["symbol"])
        desc = s.get("desc", "")
        groups.setdefault(sec, []).append((s["name"], s["symbol"], results[s["symbol"]], desc))
    sector_order = [sn for _,_,sn in SECTORS] + ["消费电子"]
    ordered, seen = [], set()
    for sn in sector_order:
        if sn in groups: ordered.append((sn, groups[sn])); seen.add(sn)
    for sn in groups:
        if sn not in seen: ordered.append((sn, groups[sn]))
    return ordered

def build_report(stocks, results, stats):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# 全球龙头行情日报 ({now})", "",
             f"**成功** {stats['success']} | **待重试** {stats['pending']} | **上涨** {stats['up']} | **下跌** {stats['down']}"]
    items = list(results.values())
    su = sorted(items, key=lambda x: x["change_pct"], reverse=True)
    sd = sorted(items, key=lambda x: x["change_pct"])
    lines.append("## 今日涨幅 TOP 10"); lines.append("| 名称 | 代码 | 最新价 | 涨跌幅 | 时间 | 来源 |")
    lines.append("|------|------|--------|--------|------|------|")
    for it in su[:10]:
        t = it.get("updated_at",""); ts = f" {t}" if t else ""
        lines.append(f"| {it['name']} | {it['symbol']} | {it['price']:.2f} | {it['change_pct']:+.2f}%{ts} | {it['source']} |")
    lines.append("## 今日跌幅 TOP 10"); lines.append("| 名称 | 代码 | 最新价 | 涨跌幅 | 时间 | 来源 |")
    lines.append("|------|------|--------|--------|------|------|")
    for it in sd[:10]:
        t = it.get("updated_at",""); ts = f" {t}" if t else ""
        lines.append(f"| {it['name']} | {it['symbol']} | {it['price']:.2f} | {it['change_pct']:+.2f}%{ts} | {it['source']} |")
    wk = [i for i in items if i.get("week_change") is not None]
    if wk:
        lines.append("## 近一周涨幅 TOP 10"); lines.append("| 名称 | 代码 | 最新价 | 周涨跌 | 来源 |")
        lines.append("|------|------|--------|--------|------|")
        for it in sorted(wk, key=lambda x: x["week_change"], reverse=True)[:10]:
            lines.append(f"| {it['name']} | {it['symbol']} | {it['price']:.2f} | {it['week_change']:+.2f}% | {it['source']} |")
        lines.append("## 近一周跌幅 TOP 10")
        for it in sorted(wk, key=lambda x: x["week_change"])[:10]:
            lines.append(f"| {it['name']} | {it['symbol']} | {it['price']:.2f} | {it['week_change']:+.2f}% | {it['source']} |")
    # 先构建全量明细（暂不合并，用于体积判断）
    detail_lines = []
    detail_lines.append("## 全量明细（按板块）")
    for sn, grp in _sector_items(stocks, results):
        up = sum(1 for _,_,it,_ in grp if it.get("change_pct",0) > 0)
        dn = len(grp) - up
        detail_lines.append(f"### {sn} (↑{up} ↓{dn})")
        for name,sym,it,desc in grp:
            t = it.get("updated_at",""); ts = f" [{t}]" if t else ""
            w = it.get("week_change"); ws = f" 周{w:+.2f}%" if w else ""
            detail_lines.append(f"  {name} {sym} {it['price']:.2f} {it['change_pct']:+.2f}%{ws} [{it['source']}]")
    # 体积保护: 如果全量内容超过 40KB，只保留板块摘要（避免 PushPlus 推送失败）
    full_text = "\n".join(lines + detail_lines)
    if len(full_text.encode("utf-8")) > 40000:
        detail_lines = ["## 全量明细（按板块）"]
        for sn, grp in _sector_items(stocks, results):
            up = sum(1 for _,_,it,_ in grp if it.get("change_pct",0) > 0)
            dn = len(grp) - up
            detail_lines.append(f"### {sn} (↑{up} ↓{dn})")
            # 只展示板块内 TOP5 涨跌幅
            top5 = sorted(grp, key=lambda x: x[2]["change_pct"], reverse=True)[:5]
            detail_lines.append(f"  **涨幅前5:**")
            for name,sym,it,desc in top5:
                w = it.get("week_change"); ws = f" 周{w:+.2f}%" if w else ""
                detail_lines.append(f"  {name} {sym} {it['price']:.2f} {it['change_pct']:+.2f}%{ws}")
            bottom5 = sorted(grp, key=lambda x: x[2]["change_pct"])[:5]
            detail_lines.append(f"  **跌幅前5:**")
            for name,sym,it,desc in bottom5:
                w = it.get("week_change"); ws = f" 周{w:+.2f}%" if w else ""
                detail_lines.append(f"  {name} {sym} {it['price']:.2f} {it['change_pct']:+.2f}%{ws}")
            detail_lines.append("")  # 板块间空行
        detail_lines.append(f"> 内容过长，已截断。完整明细见 report.html")
    lines.extend(detail_lines)
    return "\n".join(lines)

# 板块配色 (17 个板块各一个背景色)
SECTOR_COLORS = [
    "#e3f2fd", "#f3e5f5", "#fff3e0", "#e8f5e9", "#fbe9e7",
    "#e0f7fa", "#fce4ec", "#e8eaf6", "#fff8e1", "#efebe9",
    "#e0f2f1", "#fffde7", "#f1f8e9", "#e1f5fe", "#f9fbe7",
    "#ede7f6", "#fce4ec",
]

def _color(v: float) -> str:
    return f'<font color="#e74c3c">+{v:.2f}%</font>' if v > 0 else f'<font color="#27ae60">{v:.2f}%</font>'

def _wk_color(v: float) -> str:
    """周涨跌颜色 (显示 "↑" "↓" 前缀)"""
    if v is None:
        return '<font color="#999">—</font>'
    if v > 0:
        return f'<font color="#e74c3c">↑{v:.2f}%</font>'
    return f'<font color="#27ae60">↓{abs(v):.2f}%</font>'

def build_report_html(stocks, results, stats, pending=None):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    # CSS class 复用，大幅压缩体积
    css = ('<style>'
           'td{padding:1px 3px;font-size:13px;text-align:center}'
           'th{font-size:13px;font-weight:bold;text-align:center;padding:2px 3px;background:#eee}'
           '.l{text-align:left}.s{font-size:11px;color:#888}.r{color:#e74c3c}.g{color:#27ae60}.b{color:#999}'
           '.bg0{background:#e3f2fd}.bg1{background:#f3e5f5}.bg2{background:#fff3e0}.bg3{background:#e8f5e9}'
           '.bg4{background:#fbe9e7}.bg5{background:#e0f7fa}.bg6{background:#fce4ec}.bg7{background:#e8eaf6}'
           '.bg8{background:#fff8e1}.bg9{background:#efebe9}.bg10{background:#e0f2f1}.bg11{background:#fffde7}'
           '.bg12{background:#f1f8e9}.bg13{background:#e1f5fe}.bg14{background:#f9fbe7}.bg15{background:#ede7f6}'
           '.bg16{background:#fce4ec}'
           '</style>')

    def _cc(v):
        return f'<span class="r">+{v:.2f}%</span>' if v > 0 else f'<span class="g">{v:.2f}%</span>'

    def _wc(v):
        if v is None: return '<span class="b">—</span>'
        return f'<span class="r">↑{v:.2f}%</span>' if v > 0 else f'<span class="g">↓{abs(v):.2f}%</span>'

    lines = [css,
             f'<b>全球龙头行情日报 ({now})</b><br>',
             f'成功{stats["success"]} | 待重试{stats["pending"]} | '
             f'<span class="r">上涨{stats["up"]}</span> | <span class="g">下跌{stats["down"]}</span><hr>']

    items = list(results.values())
    su = sorted(items, key=lambda x: x["change_pct"], reverse=True)
    sd = sorted(items, key=lambda x: x["change_pct"])

    # TOP 10
    for title, data in [("涨幅TOP10", su), ("跌幅TOP10", sd)]:
        rows = ''.join(f'<tr><td class="l">{it["name"]}</td><td class="s">{it["symbol"]}</td>'
                       f'<td>{_cc(it["change_pct"])}</td><td>{_wc(it.get("week_change"))}</td></tr>'
                       for it in data[:10])
        lines.append(f'<b>{title}</b>'
                     f'<table width="100%" cellpadding="0" cellspacing="0">'
                     f'<tr><th>名称</th><th>代码</th><th>涨跌幅</th><th>周涨跌</th></tr>'
                     f'{rows}</table><br>')

    # 全量板块
    lines.append('<hr>')
    rows_all = []
    for ci, (sn, grp) in enumerate(_sector_items(stocks, results)):
        bg = f'bg{ci%17}'
        up = sum(1 for _,_,it,_ in grp if it.get("change_pct",0) > 0)
        dn = len(grp) - up
        rows_all.append(f'<tr><td class="l" style="font-weight:bold;background:{SECTOR_COLORS[ci%17]}" '
                        f'colspan="4">【{sn}】↑{up}↓{dn}</td></tr>')
        for name, sym, it, desc in grp:
            rows_all.append(f'<tr class="{bg}"><td class="l">{name}</td><td class="s">{sym}</td>'
                            f'<td>{_cc(it["change_pct"])}</td><td>{_wc(it.get("week_change"))}</td></tr>')
    lines.append(f'<table width="100%" cellpadding="0" cellspacing="0">'
                 f'<tr><th>名称</th><th>代码</th><th>涨跌幅</th><th>周涨跌</th></tr>'
                 f'{"".join(rows_all)}</table>')

    if pending:
        nm = {s["symbol"]: s["name"] for s in stocks}
        items = ' | '.join(f'{nm.get(s,s)}' for s in pending[:20])
        more = f' ...等{len(pending)}支' if len(pending) > 20 else ''
        lines.append(f'<hr><b>待重试{len(pending)}支:</b> {items}{more}')
    return "\n".join(lines)

def push_wx(title: str, content: str, template: str = "markdown"):
    tk = config.PUSHPLUS_TOKEN
    if not tk: print("[跳过] 未配置 PUSHPLUS_TOKEN"); return
    try:
        r = requests.post("https://www.pushplus.plus/send",
            json={"token":tk,"title":title,"content":content,"template":template}, timeout=15)
        res = r.json()
        if res.get("code") == 200: print(f"[推送成功] {res.get('msg','')}")
        else: print(f"[推送失败] {res}")
    except Exception as e: print(f"[推送异常] {e}")

def finish(stocks, results, pending):
    total = len(stocks); success = len(results)
    up = sum(1 for r in results.values() if r.get("change_pct",0) > 0); down = success-up
    stats = {"success":success,"pending":len(pending),"up":up,"down":down}
    print(f"\n{'='*60}\n采集完成: 成功 {success}/{total}  |  上涨 {up}  下跌 {down}")
    if pending:
        nm = {s["symbol"]:s["name"] for s in stocks}
        rt_map = {s["symbol"]:route_symbol(s["symbol"]) for s in stocks}
        print(f"\n[待重试] {len(pending)} 只:")
        by_route = {}
        for sym in pending:
            r = rt_map.get(sym, "?")
            by_route.setdefault(r, []).append(f"  {nm.get(sym,sym)} ({sym})")
        for route, items in sorted(by_route.items()):
            print(f"  数据源 [{route}]: {len(items)} 只")
            for item in items[:5]: print(item)
            if len(items) > 5: print(f"    ... 还有 {len(items)-5} 只")
    md = build_report(stocks, results, stats)
    with open("report.md","w",encoding="utf-8") as f: f.write(md)
    print("[保存] report.md")
    html = build_report_html(stocks, results, stats, pending=pending)
    with open("report.html","w",encoding="utf-8") as f: f.write(html)
    print("[保存] report.html")
    print(f"全球龙头行情日报 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n{'='*55}\n成功:{success}  待重试:{len(pending)}  上涨:{up}  下跌:{down}")
    push_wx(f"全球龙头行情日报 ({datetime.now().strftime('%m-%d')})", html, template="html")
    if success < total * 0.2: print("[警告] 成功率低于20%"); sys.exit(1)

def main():
    _setup_console()
    parser = argparse.ArgumentParser(description="全球龙头行情监控")
    parser.add_argument("--push-only", action="store_true", help="仅推送缓存")
    args = parser.parse_args()
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"[日期] {date_str}")
    stocks = load_watchlist(config.WATCHLIST_FILE)
    print(f"[加载] {config.WATCHLIST_FILE} - {len(stocks)} 只股票")
    if args.push_only:
        cached = load_cache(date_str)
        if not cached:
            import glob as _g
            cfs = sorted(_g.glob(os.path.join(config.CACHE_DIR,"*.json")))
            if cfs:
                with open(cfs[-1],"r",encoding="utf-8") as _f: cached = json.load(_f)
                print(f"[缓存] 使用最近: {os.path.basename(cfs[-1])}")
            else: print("[错误] 无缓存"); sys.exit(1)
        rc = cached.get("results",{}); pc = cached.get("pending",[])
        nm = {s["symbol"]:s["name"] for s in stocks}
        for sym,d in rc.items(): d["name"]=nm.get(sym,sym); d["symbol"]=sym
        print(f"[缓存] {len(rc)} 条"); finish(stocks,rc,pc); return
    print("")
    cached = load_cache(date_str) if not config.FORCE_REFRESH else None
    if cached:
        rc = cached.get("results",{}); pc = cached.get("pending",[])
        nm = {s["symbol"]:s["name"] for s in stocks}
        for sym,d in rc.items(): d["name"]=nm.get(sym,sym); d["symbol"]=sym
        fresh = [s for s in stocks if s["symbol"] not in rc or s["symbol"] in pc]
        print(f"[缓存] {len(rc)} 条已缓存")
        if fresh: print(f"[刷新] {len(fresh)} 条\n"); fs, rs, pd = fresh, dict(rc), list(set(pc))
        else: print("[完成] 全部已缓存"); finish(stocks,rc,pc); return
    else: fs, rs, pd = list(stocks), {}, []
    adpts = {"finnhub":FinnhubAdapter(config.FINNHUB_API_KEY,config.FINNHUB_BASE),
             "twse":TWSEAdapter(),"twstock":TWStockAdapter(),
             "jquants":JQuantsAdapter(),
             "stooq":StooqAdapter(api_key=config.STOOQ_API_KEY),
             "hk":HKAdapter(),
             "yahoo":YahooAdapter(),
             "boerse_frankfurt":BoerseFrankfurtAdapter(),
             "naver":NaverAdapter(),
             "tencent_jp":TencentJPAdapter(),
             "tencent_us":TencentUSAdapter()}
    try:
        from adapters.akshare import AkShareAdapter
        adpts["akshare"] = AkShareAdapter()
    except ImportError: print("[警告] akshare 未安装"); adpts["akshare"] = None
    total = len(fs)
    for i,stk in enumerate(fs,1):
        sym = stk["symbol"]; rt = route_symbol(sym)
        print(f"  [{i:>3}/{total:<3}] {stk['name']:<8s} {sym:<12s}", end="", flush=True)
        q = fetch_with_fallback(sym, adpts, rt)
        if q:
            q["name"] = stk["name"]; q["symbol"] = sym
            # 从 source 中提取适配器名称(去掉 fallback/ADR 后缀)
            src = q.get("source", "").split("(")[0].strip()
            wc = get_weekly_change(sym, adpts, q["price"], src_nm=src)
            if wc is not None: q["week_change"] = wc
            rs[sym] = q
            print(f"  {'+' if q.get('change',0)>=0 else ''}{q['price']:.2f}  {q['change_pct']:+.2f}%  [{q['source']}]")
        else:
            if sym not in pd: pd.append(sym)
            print("  [无数据]")
        if i < total: time.sleep(config.REQUEST_INTERVAL)
    pd = [s for s in pd if s not in rs]  # 从待重试中移除已成功的
    save_cache(date_str, rs, pd)
    print(f"\n[缓存] {get_cache_path(date_str)}")
    finish(stocks, rs, pd)

if __name__ == "__main__":
    main()
