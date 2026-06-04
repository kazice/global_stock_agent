#!/usr/bin/env python3
"""
全球龙头上市公司行情监控 - 多数据源聚合系统
"""
import argparse, json, os, sys, time
from datetime import datetime
from typing import Optional
import requests
import config
from adapters import FinnhubAdapter, TWSEAdapter, JQuantsAdapter, StooqAdapter

def route_symbol(symbol: str) -> str:
    if "." not in symbol: return "finnhub"
    suffix = symbol.rsplit(".", 1)[-1].upper()
    m = {"TW":"twse","TWO":"twse","T":"jquants","KS":"stooq",
         "SH":"akshare","SZ":"akshare","DE":"stooq","PA":"stooq",
         "SW":"stooq","L":"stooq","ST":"stooq","CO":"stooq",
         "AS":"stooq","SR":"stooq","HK":"finnhub"}
    return m.get(suffix, "finnhub")
FALLBACK_CHAIN = {"twse":["stooq"],"jquants":["stooq"],"akshare":[],"finnhub":["stooq"],"stooq":[]}
SECTORS = [(0,60,"半导体"),(61,84,"锂电/电池材料"),(85,99,"汽车"),(100,110,"算力/服务器"),
           (111,124,"互联网/软件"),(125,146,"屏幕/光学/电子制造"),(147,177,"医药/医疗"),
           (178,188,"军工/航空"),(189,204,"能源/光伏"),(205,217,"金融"),(218,228,"通信"),
           (229,240,"互联网平台"),(241,251,"工业/自动化"),(252,261,"工程机械"),
           (262,271,"化工"),(272,281,"物流/运输"),(282,287,"消费")]
def get_sector(i: int) -> str:
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
            h = a.fetch_history(sym, days*2)
            if h and len(h) >= 2:
                l = h[-1]["close"]; wa = h[0]["close"]
                if wa and l > 0: return round((l-wa)/wa*100,2)
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
        sec = get_sector(i)
        groups.setdefault(sec, []).append((s["name"], s["symbol"], results[s["symbol"]]))
    ordered, seen = [], set()
    for _,_,sn in SECTORS:
        if sn in groups: ordered.append((sn, groups[sn])); seen.add(sn)
    for sn in groups:
        if sn not in seen: ordered.append((sn, groups[sn]))
    return ordered

def build_report(stocks, results, stats):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# 全球龙头行情日报 ({now})", "",
             f"**成功** {stats['success']} | **待重试** {stats['pending']} | **上涨** {stats['up']} | **下跌** {stats['down']}", ""]
    items = list(results.values())
    su = sorted(items, key=lambda x: x["change_pct"], reverse=True)
    sd = sorted(items, key=lambda x: x["change_pct"])
    lines.append("## 今日涨幅 TOP 10"); lines.append("| 名称 | 代码 | 最新价 | 涨跌幅 | 时间 | 来源 |")
    lines.append("|------|------|--------|--------|------|------|")
    for it in su[:10]:
        t = it.get("updated_at",""); ts = f" {t}" if t else ""
        lines.append(f"| {it['name']} | {it['symbol']} | {it['price']:.2f} | {it['change_pct']:+.2f}%{ts} | {it['source']} |")
    lines.append("")
    lines.append("## 今日跌幅 TOP 10"); lines.append("| 名称 | 代码 | 最新价 | 涨跌幅 | 时间 | 来源 |")
    lines.append("|------|------|--------|--------|------|------|")
    for it in sd[:10]:
        t = it.get("updated_at",""); ts = f" {t}" if t else ""
        lines.append(f"| {it['name']} | {it['symbol']} | {it['price']:.2f} | {it['change_pct']:+.2f}%{ts} | {it['source']} |")
    lines.append("")
    wk = [i for i in items if i.get("week_change") is not None]
    if wk:
        lines.append("## 近一周涨幅 TOP 10"); lines.append("| 名称 | 代码 | 最新价 | 周涨跌 | 来源 |")
        lines.append("|------|------|--------|--------|------|")
        for it in sorted(wk, key=lambda x: x["week_change"], reverse=True)[:10]:
            lines.append(f"| {it['name']} | {it['symbol']} | {it['price']:.2f} | {it['week_change']:+.2f}% | {it['source']} |")
        lines.append(""); lines.append("## 近一周跌幅 TOP 10")
        for it in sorted(wk, key=lambda x: x["week_change"])[:10]:
            lines.append(f"| {it['name']} | {it['symbol']} | {it['price']:.2f} | {it['week_change']:+.2f}% | {it['source']} |")
        lines.append("")
    lines.append("## 全量明细（按板块）")
    for sn, grp in _sector_items(stocks, results):
        lines.append(""); lines.append(f"### {sn}")
        for name,sym,it in grp:
            t = it.get("updated_at",""); ts = f" [{t}]" if t else ""
            w = it.get("week_change"); ws = f" 周{w:+.2f}%" if w else ""
            lines.append(f"- {name} {sym} {it['price']:.2f} {it['change_pct']:+.2f}%{ts}{ws} [{it['source']}]")
    return "\n".join(lines)

def _color(v: float) -> str:
    return f'<font color="#e74c3c">+{v:.2f}%</font>' if v > 0 else f'<font color="#27ae60">{v:.2f}%</font>'

def build_report_html(stocks, results, stats):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f'<h3>全球龙头行情日报 ({now})</h3>',
             f'<p>成功 {stats["success"]} | 待重试 {stats["pending"]} | <font color="#e74c3c">上涨 {stats["up"]}</font> | <font color="#27ae60">下跌 {stats["down"]}</font></p><hr>']
    items = list(results.values())
    su = sorted(items, key=lambda x: x["change_pct"], reverse=True)
    sd = sorted(items, key=lambda x: x["change_pct"])
    lines.append("<b>涨幅 TOP 10</b><br>")
    for it in su[:10]:
        t = it.get("updated_at",""); ts = f" ({t})" if t else ""
        lines.append(f'{it["name"]} {it["price"]:.2f} {_color(it["change_pct"])}{ts}<br>')
    lines.append("<br><b>跌幅 TOP 10</b><br>")
    for it in sd[:10]:
        t = it.get("updated_at",""); ts = f" ({t})" if t else ""
        lines.append(f'{it["name"]} {it["price"]:.2f} {_color(it["change_pct"])}{ts}<br>')
    lines.append("<hr>")
    for sn, grp in _sector_items(stocks, results):
        lines.append(f'<b>\u3010{sn}\u3011</b><br>')
        for name,_,it in grp:
            t = it.get("updated_at",""); ts = f" ({t})" if t else ""
            wk = it.get("week_change"); wks = f' \u5468{_color(wk)}' if wk else ""
            lines.append(f'{name} {it["price"]:.2f} {_color(it["change_pct"])}{ts}{wks}<br>')
        lines.append("<br>")
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
    md = build_report(stocks, results, stats)
    with open("report.md","w",encoding="utf-8") as f: f.write(md)
    print("[保存] report.md")
    html = build_report_html(stocks, results, stats)
    with open("report.html","w",encoding="utf-8") as f: f.write(html)
    print("[保存] report.html")
    print(f"全球龙头行情日报 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n{'='*55}\n成功:{success}  待重试:{len(pending)}  上涨:{up}  下跌:{down}")
    if pending:
        nm = {s["symbol"]:s["name"] for s in stocks}
        print(f"\n[待重试] {len(pending)} 只 (前10):")
        for sym in pending[:10]: print(f"  - {nm.get(sym,sym)} ({sym})")
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
             "stooq":StooqAdapter(api_key=config.STOOQ_API_KEY)}
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
