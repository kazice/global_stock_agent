#!/usr/bin/env python3
"""
全球龙头上市公司行情监控 - 多数据源聚合系统
"""
import argparse, json, os, sys, time
from datetime import datetime
from typing import Optional
import requests
import config
from adapters import FinnhubAdapter, TWSEAdapter, JQuantsAdapter, StooqAdapter, HKAdapter, YahooAdapter

def route_symbol(symbol: str) -> str:
    if "." not in symbol: return "finnhub"
    suffix = symbol.rsplit(".", 1)[-1].upper()
    m = {"TW":"twse","TWO":"twse","T":"jquants","KS":"stooq",
         "SH":"akshare","SZ":"akshare","DE":"stooq","PA":"stooq",
         "SW":"stooq","L":"stooq","ST":"stooq","CO":"stooq",
         "AS":"stooq","SR":"stooq","HK":"hk"}
    return m.get(suffix, "finnhub")
FALLBACK_CHAIN = {"twse":["stooq","yahoo"],"jquants":["stooq","yahoo"],"akshare":["stooq","yahoo"],"hk":["stooq","yahoo"],"finnhub":["stooq","yahoo"],"stooq":["yahoo"]}
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
    a = adpts.get(rt)
    if a:
        r = a.fetch_quote(sym)
        if r: return r
    for fb in FALLBACK_CHAIN.get(rt,[]):
        fa = adpts.get(fb)
        if fa:
            r = fa.fetch_quote(sym)
            if r: r["source"] = f"{r['source']}(fallback)"; return r
    adr = ADR_MAP.get(sym)
    if adr:
        if "stooq" in adpts:
            r = adpts["stooq"].fetch_quote(adr)
            if r: r["source"] = "stooq(ADR)"; return r
        if "finnhub" in adpts:
            r = adpts["finnhub"].fetch_quote(adr)
            if r: r["source"] = "finnhub(ADR)"; return r
    return None

def get_weekly_change(sym: str, adpts: dict, rt: str, cur_p: float, days: int = 5) -> Optional[float]:
    for nm in [rt] + FALLBACK_CHAIN.get(rt,[]):
        a = adpts.get(nm)
        if a is None: continue
        try:
            h = a.fetch_history(sym, days + 1)
            if h and len(h) >= 2:
                wa = h[0]["close"]  # h[0]=5个交易日前收盘价
                # 用 cur_p(实时报价)而非 h[-1](历史收盘),避免美股历史数据未更新导致偏差
                if wa > 0: return round((cur_p-wa)/wa*100,2)
        except: pass
    try:
        cs = load_close_history(sym, n=days)
        if cs and len(cs) >= 2 and cs[0] > 0:
            return round((cur_p-cs[0])/cs[0]*100,2)
    except: pass
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
    lines.append("## 全量明细（按板块）")
    for sn, grp in _sector_items(stocks, results):
        up = sum(1 for _,_,it,_ in grp if it.get("change_pct",0) > 0)
        dn = len(grp) - up
        lines.append(f"### {sn} (↑{up} ↓{dn})")
        for name,sym,it,desc in grp:
            t = it.get("updated_at",""); ts = f" [{t}]" if t else ""
            w = it.get("week_change"); ws = f" 周{w:+.2f}%" if w else ""
            lines.append(f"  {name} {sym} {it['price']:.2f} {it['change_pct']:+.2f}%{ws} [{it['source']}]")
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
    lines = [f'<h3>全球龙头行情日报 ({now})</h3>',
             f'<p>成功 {stats["success"]} | 待重试 {stats["pending"]} | <font color="#e74c3c">上涨 {stats["up"]}</font> | <font color="#27ae60">下跌 {stats["down"]}</font></p><hr>']

    items = list(results.values())
    su = sorted(items, key=lambda x: x["change_pct"], reverse=True)
    sd = sorted(items, key=lambda x: x["change_pct"])

    # 样式: 紧凑大字体居中对齐
    T = 'style="font-size:15px;text-align:center;padding:2px 6px"'
    TH = 'style="font-size:15px;font-weight:bold;text-align:center;padding:3px 6px;background:#eee"'

    # TOP 10 (表格)
    for title, data in [("涨幅 TOP 10", su), ("跌幅 TOP 10", sd)]:
        lines.append(f'<b>{title}</b>')
        lines.append(f'<table border="0" cellpadding="0" cellspacing="0" width="100%">'
                     f'<tr><td {TH}>名称</td><td {TH}>代码</td><td {TH}>涨跌幅</td><td {TH}>周涨跌</td></tr>')
        for it in data[:10]:
            lines.append(f'<tr><td {T}>{it["name"]}</td><td {T} style="font-size:13px;color:#555;text-align:center;padding:2px 6px">{it["symbol"]}</td>'
                         f'<td {T}>{_color(it["change_pct"])}</td>'
                         f'<td {T}>{_wk_color(it.get("week_change"))}</td></tr>')
        lines.append('</table><br>')

    # 全量板块表格
    lines.append('<hr>')
    lines.append(f'<table border="0" cellpadding="0" cellspacing="0" width="100%" style="font-size:15px">')
    lines.append(f'<tr><td {TH} colspan="5">名称</td><td {TH}>代码</td><td {TH}>涨跌幅</td><td {TH}>周涨跌</td><td {TH}>简介</td></tr>')
    for ci, (sn, grp) in enumerate(_sector_items(stocks, results)):
        bg = SECTOR_COLORS[ci % len(SECTOR_COLORS)]
        up = sum(1 for _,_,it,_ in grp if it.get("change_pct",0) > 0)
        dn = len(grp) - up
        lines.append(f'<tr><td colspan="9" style="font-size:15px;font-weight:bold;text-align:left;padding:3px 6px;background:{bg}">【{sn}】↑{up}↓{dn}</td></tr>')
        for name, sym, it, desc in grp:
            wk = it.get("week_change")
            d = _wk_color(wk)
            desc_txt = desc if desc else "—"
            lines.append(f'<tr style="text-align:center;background:{bg}">'
                         f'<td colspan="5" style="font-size:15px;padding:2px 6px;text-align:left">{name}</td>'
                         f'<td style="font-size:13px;color:#555;padding:2px 6px">{sym}</td>'
                         f'<td style="font-size:15px;padding:2px 6px">{_color(it["change_pct"])}</td>'
                         f'<td style="font-size:15px;padding:2px 6px">{d}</td>'
                         f'<td style="font-size:12px;color:#999;padding:2px 6px">{desc_txt}</td></tr>')
    lines.append('</table>')

    if pending:
        nm = {s["symbol"]: s["name"] for s in stocks}
        lines.append(f'<hr><b>【待重试】{len(pending)} 支</b><br>')
        for sym in pending:
            lines.append(f'{nm.get(sym, sym)} [{sym}]<br>')
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
             "twse":TWSEAdapter(),"jquants":JQuantsAdapter(),
             "stooq":StooqAdapter(api_key=config.STOOQ_API_KEY),
             "hk":HKAdapter(),
             "yahoo":YahooAdapter()}
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
            wc = get_weekly_change(sym, adpts, rt, q["price"])
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
