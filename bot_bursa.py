#!/usr/bin/env python3
"""
Bot de analiză a pieței de acțiuni (global).
Descarcă date de pe Yahoo Finance, calculează indicatori tehnici + fundamentali
și face un clasament al acțiunilor cu cel mai bun profil în acest moment.

ATENȚIE: Nu este sfat financiar. Scorurile se bazează pe date istorice;
nimeni nu poate garanta profitul. Fă-ți propria analiză înainte de a investi.

Instalare:  pip install yfinance pandas
Rulare:     python bot_bursa.py            (date reale)
            python bot_bursa.py --top 15   (afișează primele 15)
            python bot_bursa.py --demo     (date simulate, fără internet)
"""
import argparse, sys, os, json, urllib.request, urllib.parse
import numpy as np
import pandas as pd

# Univers global: SUA, Europa, Asia, plus Bursa de Valori București (.RO)
UNIVERS = {
    "SUA":    ["AAPL","MSFT","NVDA","GOOGL","AMZN","META","AVGO","JPM","V","MA",
               "LLY","UNH","JNJ","XOM","COST","WMT","PG","HD","NFLX","AMD"],
    "Europa": ["ASML.AS","SAP.DE","NOVO-B.CO","MC.PA","SIE.DE","NESN.SW",
               "AZN.L","SHEL.L","TTE.PA","ALV.DE","OR.PA"],
    "Asia":   ["TSM","7203.T","6758.T","BABA","0700.HK","005930.KS","INFY"],
    "România":["TLV.RO","SNP.RO","H2O.RO","SNG.RO","BRD.RO","TGN.RO"],
}

def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))

def indicatori_tehnici(close):
    if len(close) < 200:
        return None
    p = close.iloc[-1]
    sma50, sma200 = close.rolling(50).mean().iloc[-1], close.rolling(200).mean().iloc[-1]
    ret = close.pct_change().dropna()
    return {
        "pret": p,
        "azi": p / close.iloc[-2] - 1,
        "rand_3l": p / close.iloc[-63] - 1,
        "rand_6l": p / close.iloc[-126] - 1,
        "rand_12l": p / close.iloc[0] - 1,
        "peste_sma200": p > sma200,
        "golden_cross": sma50 > sma200,
        "rsi": rsi(close).iloc[-1],
        "volatilitate": ret.std() * np.sqrt(252),
        "drawdown_max": (close / close.cummax() - 1).min(),
    }

def scor(r):
    """Scor 0-100: momentum (40%), trend (20%), risc (20%), fundamental (20%)."""
    s = 0.0
    # Momentum
    s += 20 * np.clip((r["rand_6l"] + 0.2) / 0.8, 0, 1)
    s += 20 * np.clip((r["rand_3l"] + 0.1) / 0.4, 0, 1)
    # Trend
    s += 10 * r["peste_sma200"] + 10 * r["golden_cross"]
    # Risc: volatilitate mică e mai bine; RSI > 75 = supra-cumpărat (penalizare)
    s += 15 * np.clip((0.6 - r["volatilitate"]) / 0.45, 0, 1)
    s += 5 if 40 <= r["rsi"] <= 70 else (0 if r["rsi"] > 75 else 2)
    # Fundamental (dacă există)
    pe, roe, marja = r.get("pe"), r.get("roe"), r.get("marja")
    if pe and 0 < pe < 35: s += 8 * np.clip((35 - pe) / 25, 0, 1)
    if roe: s += 7 * np.clip(roe / 0.3, 0, 1)
    if marja: s += 5 * np.clip(marja / 0.25, 0, 1)
    return round(float(s), 1)

def motive(r):
    m = []
    if r["rand_6l"] > 0.2: m.append(f"momentum puternic (+{r['rand_6l']:.0%} în 6 luni)")
    if r["golden_cross"]: m.append("trend ascendent (SMA50 > SMA200)")
    if r["rsi"] > 75: m.append(f"ATENȚIE: supra-cumpărat (RSI {r['rsi']:.0f})")
    if r["volatilitate"] < 0.25: m.append("volatilitate scăzută")
    if r.get("pe") and r["pe"] < 18: m.append(f"evaluare atractivă (P/E {r['pe']:.1f})")
    if r.get("roe") and r["roe"] > 0.2: m.append(f"rentabilitate ridicată (ROE {r['roe']:.0%})")
    return "; ".join(m) or "-"

def date_reale():
    import yfinance as yf
    toate = [t for l in UNIVERS.values() for t in l]
    print(f"Descarc date pentru {len(toate)} acțiuni...", file=sys.stderr)
    px = yf.download(toate, period="1y", auto_adjust=True, progress=False)["Close"]
    # reîncearcă, pe rând, simbolurile care au eșuat (ex. "database is locked")
    for t in [t for t in toate if t not in px or px[t].dropna().empty]:
        try:
            px[t] = yf.download(t, period="1y", auto_adjust=True, progress=False,
                                threads=False)["Close"].squeeze()
        except Exception:
            pass
    rez = {}
    for t in toate:
        info = {}
        try:
            i = yf.Ticker(t).info
            info = {"nume": i.get("shortName", t), "pe": i.get("trailingPE"),
                    "roe": i.get("returnOnEquity"), "marja": i.get("profitMargins")}
        except Exception:
            pass
        rez[t] = (px[t].dropna() if t in px else pd.Series(dtype=float), info)
    return rez

def date_demo():
    rng = np.random.default_rng(7)
    rez = {}
    for t in [t for l in UNIVERS.values() for t in l]:
        drift, vol = rng.normal(0.0005, 0.001), rng.uniform(0.01, 0.03)
        close = pd.Series(100 * np.exp(np.cumsum(rng.normal(drift, vol, 252))))
        rez[t] = (close, {"nume": t, "pe": rng.uniform(8, 60),
                          "roe": rng.uniform(-0.05, 0.45), "marja": rng.uniform(0, 0.4)})
    return rez

def sparkline(vals, w=260, h=70):
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    pts = " ".join(f"{i*w/(len(vals)-1):.1f},{h-4-(v-lo)/rng*(h-8):.1f}" for i, v in enumerate(vals))
    cls = "up" if vals[-1] >= vals[0] else "down"
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" class="spark {cls}">'
            f'<polygon points="0,{h} {pts} {w},{h}" class="fill"/>'
            f'<polyline points="{pts}" class="line"/></svg>')

def raport_html(df, grafice, top, demo, iesire="raport_bursa.html"):
    import os, html, datetime
    def culoare(sc): return "hi" if sc >= 70 else ("mid" if sc >= 55 else "lo")
    carduri = []
    for poz, r in df.head(top).iterrows():
        tags = "".join(
            f'<span class="tag{" warn" if "ATENȚIE" in m else ""}">{html.escape(m.strip())}</span>'
            for m in r["Motive"].split(";") if m.strip() and m.strip() != "-")
        semn = "pos" if r["6 luni"].startswith("+") else "neg"
        carduri.append(f"""
        <article class="card">
          <div class="head">
            <div class="rank">#{poz}</div>
            <div class="title"><h2>{html.escape(r['Nume'])}</h2>
              <p>{html.escape(r['Simbol'])} · {r['Regiune']}</p></div>
            <div class="score {culoare(r['Scor'])}"><b>{r['Scor']:.0f}</b><small>scor</small></div>
          </div>
          {sparkline(grafice[r['Simbol']])}
          <div class="stats">
            <div><small>Preț</small><b>{r['Preț']:,.2f}</b></div>
            <div><small>6 luni</small><b class="{semn}">{r['6 luni']}</b></div>
            <div><small>RSI</small><b>{r['RSI']}</b></div>
            <div><small>Volatilitate</small><b>{r['Volat.']}</b></div>
          </div>
          <div class="tags">{tags}</div>
        </article>""")
    rest = "".join(
        f"<tr><td>{p}</td><td><b>{html.escape(r['Simbol'])}</b></td><td>{html.escape(r['Nume'])}</td>"
        f"<td>{r['Regiune']}</td><td><span class='pill {culoare(r['Scor'])}'>{r['Scor']:.0f}</span></td>"
        f"<td>{r['6 luni']}</td><td>{r['RSI']}</td><td>{r['Volat.']}</td></tr>"
        for p, r in df.iterrows())
    try:
        from zoneinfo import ZoneInfo
        acum = datetime.datetime.now(ZoneInfo("Europe/Bucharest"))
    except Exception:
        acum = datetime.datetime.now()
    data = acum.strftime("%d.%m.%Y, %H:%M") + " (ora României)"
    pagina = f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Radar Bursă</title>
<style>
:root{{--bg:#0b1020;--card:#141a2e;--line:#232b45;--txt:#e8ecf8;--mut:#8b94b3;
--green:#22c55e;--red:#ef4444;--amber:#f59e0b;--accent:#6366f1}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(1200px 600px at 10% -10%,#1e2550,transparent),var(--bg);
color:var(--txt);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;padding:32px 16px}}
.wrap{{max-width:1200px;margin:auto}}
header h1{{font-size:34px;margin:0;letter-spacing:-.02em}}
header h1 span{{background:linear-gradient(90deg,#818cf8,#22d3ee);-webkit-background-clip:text;color:transparent}}
header p{{color:var(--mut);margin:6px 0 28px}}
.badge{{display:inline-block;background:var(--amber);color:#000;border-radius:6px;padding:2px 8px;font-size:12px;font-weight:700;margin-left:8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:18px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px;transition:.2s}}
.card:hover{{transform:translateY(-3px);border-color:var(--accent)}}
.head{{display:flex;align-items:center;gap:12px}}
.rank{{font-weight:800;color:var(--mut);font-size:18px;width:34px}}
.title{{flex:1;min-width:0}}.title h2{{font-size:17px;margin:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.title p{{margin:0;color:var(--mut);font-size:13px}}
.score{{width:62px;height:62px;border-radius:50%;display:grid;place-content:center;text-align:center;border:3px solid}}
.score b{{font-size:20px;line-height:1}}.score small{{font-size:10px;color:var(--mut)}}
.hi{{border-color:var(--green);color:var(--green)}}.mid{{border-color:var(--amber);color:var(--amber)}}.lo{{border-color:var(--red);color:var(--red)}}
.spark{{width:100%;height:70px;margin:14px 0 6px}}
.spark .line{{fill:none;stroke-width:2.2;vector-effect:non-scaling-stroke}}
.spark.up .line{{stroke:var(--green)}}.spark.down .line{{stroke:var(--red)}}
.spark.up .fill{{fill:rgba(34,197,94,.12)}}.spark.down .fill{{fill:rgba(239,68,68,.12)}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;padding:10px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}}
.stats small{{display:block;color:var(--mut);font-size:11px}}.stats b{{font-size:15px}}
.pos{{color:var(--green)}}.neg{{color:var(--red)}}
.tags{{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}}
.tag{{background:#1f2745;color:#c7cdf0;border-radius:999px;padding:3px 10px;font-size:12px}}
.tag.warn{{background:rgba(245,158,11,.15);color:var(--amber)}}
h3{{margin:40px 0 12px}}
.tbl{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:14px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}}
th{{color:var(--mut);font-weight:600}}
.pill{{border:2px solid;border-radius:999px;padding:1px 9px;font-weight:700}}
footer{{color:var(--mut);font-size:13px;margin-top:28px;text-align:center}}
</style></head><body><div class="wrap">
<header><h1>📈 Radar <span>Bursă</span>{'<span class="badge">DEMO</span>' if demo else ''}</h1>
<p>Actualizat la {data} · {len(df)} acțiuni analizate din SUA, Europa, Asia și România</p></header>
<div class="grid">{''.join(carduri)}</div>
<h3>Clasament complet</h3>
<div class="tbl"><table><tr><th>#</th><th>Simbol</th><th>Nume</th><th>Regiune</th><th>Scor</th><th>6 luni</th><th>RSI</th><th>Volatilitate</th></tr>{rest}</table></div>
<footer>Graficele arată ultimele 6 luni. Nu este sfat financiar — diversifică și investește doar ce îți permiți să pierzi.</footer>
</div></body></html>"""
    cale = os.path.abspath(iesire)
    os.makedirs(os.path.dirname(cale), exist_ok=True)
    with open(cale, "w", encoding="utf-8") as f:
        f.write(pagina)
    return cale

def trimite_telegram(df, prag_alerta=0.04):
    token = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
    chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat:
        print("Telegram: lipsesc TELEGRAM_TOKEN / TELEGRAM_CHAT_ID, nu trimit nimic.")
        return
    medalii = ["🥇", "🥈", "🥉", "4.", "5."]
    txt = ["📈 *Radar Bursă — raport zilnic*", ""]
    for i, (_, r) in enumerate(df.head(5).iterrows()):
        txt.append(f"{medalii[i]} *{r['Nume']}* ({r['Simbol']}) — scor {r['Scor']:.0f}, azi {r['Azi']}, 6 luni {r['6 luni']}")
    alerte = []
    for _, r in df.iterrows():
        v = float(r["Azi"].strip("%")) / 100
        if abs(v) >= prag_alerta:
            alerte.append(f"{'🚀' if v > 0 else '⚠️'} {r['Nume']} ({r['Simbol']}) {r['Azi']} azi")
    if alerte:
        txt += ["", "*Mișcări mari azi:*"] + alerte
    site = os.environ.get("SITE_URL")
    if site:
        txt += ["", f"🔗 Raportul complet: {site}"]
    txt += ["", "_Nu este sfat financiar._"]
    date = urllib.parse.urlencode({"chat_id": chat, "text": "\n".join(txt),
                                   "parse_mode": "Markdown", "disable_web_page_preview": "true"}).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        urllib.request.urlopen(url, date, timeout=20)
        print("Telegram: mesaj trimis.")
    except Exception:
        try:  # reîncearcă fără formatare, în caz că un nume conține caractere speciale
            simplu = urllib.parse.urlencode({"chat_id": chat, "text": "\n".join(txt).replace("*", "").replace("_", "")}).encode()
            urllib.request.urlopen(url, simplu, timeout=20)
            print("Telegram: mesaj trimis (fără formatare).")
        except Exception as e:
            print("Telegram: eroare la trimitere:", e)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--csv", help="salvează tot clasamentul într-un fișier CSV")
    ap.add_argument("--fara-browser", action="store_true", help="nu deschide raportul în browser")
    ap.add_argument("--iesire", default="raport_bursa.html", help="unde se salvează raportul HTML")
    ap.add_argument("--telegram", action="store_true", help="trimite rezumatul pe Telegram")
    a = ap.parse_args()

    regiune = {t: reg for reg, l in UNIVERS.items() for t in l}
    linii, grafice = [], {}
    for t, (close, info) in (date_demo() if a.demo else date_reale()).items():
        r = indicatori_tehnici(close)
        if not r: continue
        r.update({k: v for k, v in info.items() if v is not None})
        grafice[t] = close.iloc[-126:].tolist()
        linii.append({"Simbol": t, "Nume": info.get("nume", t)[:22], "Regiune": regiune[t],
                      "Scor": scor(r), "Preț": round(r["pret"], 2),
                      "Azi": f"{r['azi']:+.1%}", "6 luni": f"{r['rand_6l']:+.0%}", "RSI": round(r["rsi"]),
                      "Volat.": f"{r['volatilitate']:.0%}", "Motive": motive(r)})
    df = pd.DataFrame(linii).sort_values("Scor", ascending=False).reset_index(drop=True)
    df.index += 1
    if a.csv: df.to_csv(a.csv)
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 90)
    print(f"\n=== TOP {a.top} ACȚIUNI DUPĂ SCOR {'(DEMO - date simulate)' if a.demo else ''} ===\n")
    print(df.head(a.top).to_string())
    print("\nNu este sfat financiar. Diversifică, investește doar ce îți permiți să pierzi.")
    cale = raport_html(df, grafice, a.top, a.demo, a.iesire)
    if a.telegram:
        trimite_telegram(df)
    print(f"\nRaport vizual salvat: {cale}")
    if not a.fara_browser:
        import webbrowser; webbrowser.open("file://" + cale)

if __name__ == "__main__":
    main()
