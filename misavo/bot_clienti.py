#!/usr/bin/env python3
"""
MISAVO – Bot de găsit clienți
Caută firme din București sau Oradea (construcții, sănătate & frumusețe, restaurante),
verifică dacă au site și cât de bun e, le dă un scor și pregătește un mesaj
personalizat de WhatsApp / email. Rezultatul: un raport HTML cu butoane + un CSV.

Rulare (nu trebuie instalat nimic în plus):
    python3 bot_clienti.py --nume Michael
    python3 bot_clienti.py --nume Michael --domenii constructii,restaurante --max 150
    python3 bot_clienti.py --nume Michael --oras oradea

Cu Google Maps (opțional, date mai bune):
    export GOOGLE_MAPS_API_KEY="cheia_ta"
    python3 bot_clienti.py --nume Michael --google

Mesajele se trimit MANUAL, din butoane (nu automat): așa respecți regulile
WhatsApp și GDPR, și fiecare mesaj pleacă de la un om, nu de la un robot.
"""
import argparse, csv, datetime, html, json, os, re, socket, ssl, sys, time
import urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

UA_OSM = "MisavoClientFinder/1.1 (Python urllib; +https://misavo.digital)"  # OSM cere un nume real de aplicație
ORASE = {   # zona de căutare în OpenStreetMap + numele folosit în mesaje
    "bucuresti": {"nume": "București", "area": 'area["ISO3166-2"="RO-B"]->.b;'},
    "oradea":    {"nume": "Oradea",    "area": 'area["name"="Oradea"]["boundary"="administrative"]->.b;'},
}
ORAS = ORASE["bucuresti"]   # se schimbă din --oras

# emailuri gratuite: dacă firma are alt domeniu în email, aproape sigur are și site
EMAIL_GRATUIT = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.ro", "ymail.com", "hotmail.com",
                 "outlook.com", "live.com", "icloud.com", "me.com", "mail.com", "gmx.com", "gmx.net",
                 "protonmail.com", "proton.me", "aol.com", "yandex.com", "mail.ru"}

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# ------------------------------------------------------------------ domenii
DOMENII = {
    "constructii": {
        "titlu": "Construcții & renovări",
        "cautare": "construcții și renovări",
        "osm": [
            'nwr["craft"~"^(builder|electrician|plumber|hvac|carpenter|roofer|tiler|painter|plasterer|'
            'glaziery|window_construction|insulation|floorer|stonemason|metal_construction|scaffolder)$"]["name"](area.b);',
            'nwr["office"~"^(construction_company|architect)$"]["name"](area.b);',
        ],
        "google": ["firmă construcții {oras}", "renovări apartamente {oras}",
                   "firmă instalații sanitare {oras}", "electrician autorizat {oras}"],
    },
    "sanatate": {
        "titlu": "Sănătate & frumusețe",
        "cautare": "clinică sau salon",
        "osm": [
            'nwr["amenity"~"^(dentist|clinic|doctors)$"]["name"](area.b);',
            'nwr["healthcare"~"^(dentist|clinic|doctor|physiotherapist|psychotherapist)$"]["name"](area.b);',
            'nwr["shop"~"^(hairdresser|beauty|massage|tattoo)$"]["name"](area.b);',
            'nwr["leisure"="spa"]["name"](area.b);',
        ],
        "google": ["clinică dentară {oras}", "cabinet medical {oras}",
                   "salon înfrumusețare {oras}", "barbershop {oras}"],
    },
    "restaurante": {
        "titlu": "Restaurante & cafenele",
        "cautare": "restaurant sau cafenea",
        "osm": [
            'nwr["amenity"~"^(restaurant|cafe)$"]["name"](area.b);',
            'nwr["shop"~"^(bakery|pastry|confectionery)$"]["name"](area.b);',
            'nwr["craft"="caterer"]["name"](area.b);',
        ],
        "google": ["restaurant {oras}", "cafenea {oras}", "patiserie {oras}", "catering {oras}"],
    },
}

FRAZA_CAUTARE = {"constructii": "firmă de construcții {oras}",
                 "sanatate": "clinică / salon {oras}",
                 "restaurante": "restaurant {oras}"}

# ------------------------------------------------------------------ utilitare
def http(url, data=None, headers=None, timeout=25):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)

def telefon_normalizat(tel):
    """Întoarce (afișare, cifre_internaționale, e_mobil)."""
    if not tel:
        return "", "", False
    tel = tel.split(";")[0].split(",")[0]
    cifre = re.sub(r"\D", "", tel)
    if cifre.startswith("0040"):
        cifre = cifre[2:]
    if cifre.startswith("0"):
        cifre = "4" + cifre
    if not cifre.startswith("40") or len(cifre) < 10:
        return tel.strip(), "", False
    mobil = cifre.startswith("407")
    afis = "0" + cifre[2:]
    afis = f"{afis[:4]} {afis[4:7]} {afis[7:]}" if mobil else afis
    return afis, cifre, mobil

def cheie_unica(f):
    _, cifre, _ = telefon_normalizat(f.get("telefon"))
    return cifre or re.sub(r"\W", "", f["nume"].lower())

# ------------------------------------------------------------------ surse de date
def din_osm(domenii):
    print("🔎 Caut firme în OpenStreetMap...", file=sys.stderr)
    rezultate = []
    servere = ["https://overpass-api.de/api/interpreter",
               "https://overpass.private.coffee/api/interpreter",
               "https://overpass.kumi.systems/api/interpreter"]
    for d in domenii:
        elemente = []
        for bucata in DOMENII[d]["osm"]:           # cereri mici = mai puține erori pe serverele gratuite
            q = '[out:json][timeout:60];' + ORAS["area"] + '(' + bucata + ');out center tags;'
            gasit = None
            for incercare in range(len(servere) * 2):
                server = servere[incercare % len(servere)]
                try:
                    r = http(server, data=urllib.parse.urlencode({"data": q}).encode(), timeout=110,
                             headers={"User-Agent": UA_OSM, "Accept": "application/json, */*"})
                    gasit = json.load(r)["elements"]
                    break
                except Exception as e:
                    print(f"   ({server.split('/')[2]} ocupat: {str(e)[:50]}), reîncerc...", file=sys.stderr)
                    time.sleep(4 + 3 * incercare)
            if gasit is None:
                print("   ⚠️  o parte din căutare n-a mers (servere ocupate) – rulează din nou mai târziu.",
                      file=sys.stderr)
            elemente += gasit or []
            time.sleep(2)
        for el in elemente:
            t = el.get("tags", {})
            adresa = " ".join(x for x in [t.get("addr:street", ""), t.get("addr:housenumber", "")] if x)
            site = t.get("website") or t.get("contact:website") or t.get("url") or ""
            fb = t.get("contact:facebook") or t.get("facebook") or ""
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")
            rezultate.append({
                "nume": t.get("name", "").strip(), "domeniu": d,
                "tip": t.get("craft") or t.get("amenity") or t.get("shop") or t.get("healthcare")
                       or t.get("office") or t.get("leisure") or "",
                "telefon": t.get("phone") or t.get("contact:phone") or t.get("contact:mobile") or "",
                "email": t.get("email") or t.get("contact:email") or "",
                "site": site, "facebook": fb, "adresa": adresa,
                "maps": f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(t.get('name',''))}%20{lat},{lon}" if lat else "",
                "rating": None, "recenzii": None, "sursa": "OpenStreetMap",
            })
        print(f"   {DOMENII[d]['titlu']}: {len(elemente)} firme", file=sys.stderr)
    return rezultate

def din_google(domenii, pagini=2):
    cheie = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not cheie:
        print("⚠️  Lipsește GOOGLE_MAPS_API_KEY – sar peste Google Maps.", file=sys.stderr)
        return []
    print("🔎 Caut firme în Google Maps...", file=sys.stderr)
    camp = ("places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.websiteUri,"
            "places.rating,places.userRatingCount,places.googleMapsUri,places.businessStatus,nextPageToken")
    rezultate = []
    for d in domenii:
        for intrebare in DOMENII[d]["google"]:
            token = None
            for _ in range(pagini):
                corp = {"textQuery": intrebare.format(oras=ORAS["nume"]), "languageCode": "ro", "regionCode": "RO", "pageSize": 20}
                if token:
                    corp["pageToken"] = token
                try:
                    r = http("https://places.googleapis.com/v1/places:searchText",
                             data=json.dumps(corp).encode(),
                             headers={"Content-Type": "application/json", "X-Goog-Api-Key": cheie,
                                      "X-Goog-FieldMask": camp})
                    raspuns = json.load(r)
                except urllib.error.HTTPError as e:
                    print("   Eroare Google:", e.read().decode()[:300], file=sys.stderr)
                    break
                for p in raspuns.get("places", []):
                    if p.get("businessStatus", "OPERATIONAL") != "OPERATIONAL":
                        continue
                    site = p.get("websiteUri", "")
                    rezultate.append({
                        "nume": p.get("displayName", {}).get("text", ""), "domeniu": d, "tip": intrebare,
                        "telefon": p.get("nationalPhoneNumber", ""), "email": "",
                        "site": "" if "facebook.com" in site or "instagram.com" in site else site,
                        "facebook": site if "facebook.com" in site or "instagram.com" in site else "",
                        "adresa": p.get("formattedAddress", ""), "maps": p.get("googleMapsUri", ""),
                        "rating": p.get("rating"), "recenzii": p.get("userRatingCount"), "sursa": "Google Maps",
                    })
                token = raspuns.get("nextPageToken")
                if not token:
                    break
                time.sleep(2)
        print(f"   {DOMENII[d]['titlu']}: gata", file=sys.stderr)
    return rezultate

# ------------------------------------------------------------------ analiza site-ului
def analizeaza_site(url):
    """Verifică site-ul firmei. Întoarce dict cu probleme găsite."""
    if not url:
        return {"stare": "fara_site", "probleme": ["Nu are site"]}
    if any(s in url for s in ("facebook.com", "instagram.com", "tiktok.com")):
        return {"stare": "doar_social", "probleme": ["Are doar pagină de social media"]}
    if not url.startswith("http"):
        url = "http://" + url
    probleme, info = [], {}
    try:
        t0 = time.time()
        r = http(url, timeout=12)
        corp = r.read(400_000).decode("utf-8", "ignore")
        durata = time.time() - t0
        final = r.geturl()
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, ConnectionError, ValueError) as e:
        return {"stare": "picat", "probleme": ["Site-ul nu se deschide / e picat"], "eroare": str(e)[:80]}
    except Exception as e:
        return {"stare": "picat", "probleme": ["Site-ul nu se deschide / e picat"], "eroare": str(e)[:80]}
    jos = corp.lower()
    if not final.startswith("https"):
        probleme.append("Fără HTTPS (apare „Nesigur” în browser)")
    if 'name="viewport"' not in jos and "name='viewport'" not in jos:
        probleme.append("Nu e adaptat pentru telefon")
    if durata > 3.5:
        probleme.append(f"Se încarcă greu ({durata:.1f}s)")
    ani = [int(a) for a in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(20[0-2]\d)", jos)]
    if ani and max(ani) <= datetime.date.today().year - 3:
        probleme.append(f"Pare neactualizat (© {max(ani)})")
    if len(re.sub(r"<[^>]+>", " ", corp).split()) < 80:
        probleme.append("Foarte puțin conținut")
    if any(x in jos for x in ("under construction", "în construcție", "coming soon", "domain is for sale",
                              "acest domeniu", "parked")):
        probleme.append("Site în construcție / domeniu parcat")
    info.update(durata=round(durata, 1))
    return {"stare": "slab" if probleme else "ok", "probleme": probleme or ["Site în regulă"], **info}

# ------------------------------------------------------------------ scor + mesaj
def scor(f):
    a = f["analiza"]
    s = {"fara_site": 55, "doar_social": 55, "picat": 50}.get(a["stare"], 0)
    if a["stare"] == "slab":
        s += min(15 * len(a["probleme"]), 45)
    _, _, mobil = telefon_normalizat(f["telefon"])
    if mobil: s += 20
    elif f["telefon"]: s += 12
    if f["email"]: s += 5
    if f["rating"] and f["recenzii"]:
        if f["recenzii"] >= 50: s += 10        # firmă activă, are bani de investit
        if f["rating"] >= 4.3: s += 5
    if not f["telefon"] and not f["email"]:
        s -= 30                                  # greu de contactat
    if a["stare"] == "ok":
        s = min(s, 25)
    return max(0, min(100, s))

def mesaj(f, nume_tau):
    eu = f"Sunt {nume_tau} de la MISAVO" if nume_tau else "Vă scriu de la MISAVO"
    firma, a = f["nume"], f["analiza"]
    cauta = FRAZA_CAUTARE[f["domeniu"]].format(oras=ORAS["nume"])
    if a["stare"] in ("fara_site", "doar_social"):
        problema = (f"am observat că {firma} nu are încă un site" if a["stare"] == "fara_site"
                    else f"am observat că {firma} are doar pagină de social media, fără site")
        impact = f"Cine caută „{cauta}” pe Google ajunge, din păcate, la concurență."
    elif a["stare"] == "picat" and f.get("site_din_email"):
        problema = (f"am vrut să vă scriu la {f['email']}, dar domeniul {f['site_din_email']} nu se mai deschide, "
                    f"deci probabil nici emailurile nu vă mai ajung. Dacă între timp aveți alt site, scuze pentru deranj")
        impact = "Dacă nu, clienții care vă caută acum nu vă găsesc."
    elif a["stare"] == "ok":
        problema = (f"m-am uitat pe site-ul {firma} și arată bine. Vă pot ajuta cu ce le lipsește multor site-uri: "
                    f"programare sau comandă online, buton de WhatsApp și recenziile Google puse în evidență")
        impact = "Astea transformă vizitatorii în clienți, fără să refaceți site-ul."
    elif a["stare"] == "picat":
        problema = f"am încercat să intru pe site-ul {firma} și nu se deschide"
        impact = "Clienții care vă caută acum văd o eroare și pleacă."
    else:
        p = [x.split(" (")[0].lower() for x in a["probleme"][:2]]
        problema = f"m-am uitat pe site-ul {firma} și am observat că {' și '.join(p)}"
        impact = "Peste 70% dintre clienți caută de pe telefon, iar un site greu sau vechi îi trimite la concurență."
    return (f"Bună ziua! {eu}, facem site-uri pentru firme din {ORAS['nume']}. "
            f"{problema[0].upper() + problema[1:]}. {impact}\n\n"
            f"Vă pot face GRATUIT, în 24 de ore, o machetă de site pentru {firma} — o vedeți și decideți "
            f"abia apoi, fără nicio obligație. Exemple: misavo.digital\n\n"
            f"Vă interesează? Dacă nu, nicio problemă, nu vă mai deranjez. O zi frumoasă!")

# ------------------------------------------------------------------ raport HTML
def raport(firme, cale, nume_tau):
    data = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    carduri = []
    for i, f in enumerate(firme):
        afis, cifre, mobil = telefon_normalizat(f["telefon"])
        m = f["mesaj"]
        butoane = []
        if mobil:
            butoane.append(f'<a class="b wa" target="_blank" href="https://wa.me/{cifre}?text={urllib.parse.quote(m)}">💬 WhatsApp</a>')
        if cifre:
            butoane.append(f'<a class="b" href="tel:+{cifre}">📞 {html.escape(afis)}</a>')
        if f["email"]:
            butoane.append(f'<a class="b" href="mailto:{html.escape(f["email"])}?subject={urllib.parse.quote("Machetă gratuită de site pentru " + f["nume"])}&body={urllib.parse.quote(m)}">✉️ Email</a>')
        if f["maps"]:
            butoane.append(f'<a class="b" target="_blank" href="{html.escape(f["maps"])}">📍 Hartă</a>')
        if f["site"]:
            butoane.append(f'<a class="b" target="_blank" href="{html.escape(f["site"] if f["site"].startswith("http") else "http://" + f["site"])}">🌐 Site</a>')
        if f["facebook"]:
            butoane.append(f'<a class="b" target="_blank" href="{html.escape(f["facebook"])}">👍 Social</a>')
        cls = "hot" if f["scor"] >= 70 else ("warm" if f["scor"] >= 45 else "cold")
        rating = f'⭐ {f["rating"]} ({f["recenzii"]})' if f["rating"] else ""
        probleme = "".join(f"<li>{html.escape(p)}</li>" for p in f["analiza"]["probleme"])
        carduri.append(f"""
<article class="card" data-id="{html.escape(cheie_unica(f))}" data-dom="{f['domeniu']}" data-scor="{f['scor']}">
  <div class="top"><div class="sc {cls}">{f['scor']}</div>
    <div class="t"><h2>{html.escape(f['nume'])}</h2>
    <p>{DOMENII[f['domeniu']]['titlu']} · {html.escape(f['tip'])} {rating}</p>
    <p class="adr">{html.escape(f['adresa'])}</p></div>
    <label class="chk"><input type="checkbox" class="contactat"> Contactat</label></div>
  <ul class="pr">{probleme}</ul>
  <details><summary>Mesaj pregătit</summary><textarea readonly>{html.escape(m)}</textarea>
    <button class="b copy">📋 Copiază mesajul</button></details>
  <div class="bt">{''.join(butoane)}</div>
</article>""")
    filtre = "".join(f'<button class="f" data-f="{k}">{v["titlu"]}</button>' for k, v in DOMENII.items())
    fierbinti = sum(1 for f in firme if f["scor"] >= 70)
    pagina = f"""<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Clienți MISAVO – {ORAS['nume']}</title>
<style>
:root{{--bg:#0b1020;--card:#141a2e;--line:#232b45;--txt:#e8ecf8;--mut:#8b94b3;--hot:#ef4444;--warm:#f59e0b;--cold:#64748b;--wa:#22c55e;--acc:#6366f1}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(1000px 500px at 0 -10%,#1e2550,transparent),var(--bg);color:var(--txt);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;padding:28px 16px}}
.wrap{{max-width:1100px;margin:auto}}h1{{margin:0;font-size:30px}}h1 span{{background:linear-gradient(90deg,#818cf8,#22d3ee);-webkit-background-clip:text;color:transparent}}
.sub{{color:var(--mut);margin:4px 0 18px}}
.stats{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}}.st{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px 16px}}
.st b{{font-size:22px;display:block}}.st small{{color:var(--mut)}}
.bar{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px;align-items:center}}
.f,.b{{background:#1f2745;color:var(--txt);border:1px solid var(--line);border-radius:999px;padding:7px 13px;font-size:13px;cursor:pointer;text-decoration:none;display:inline-block}}
.f.on{{background:var(--acc);border-color:var(--acc)}}.b:hover,.f:hover{{border-color:var(--acc)}}.b.wa{{background:var(--wa);color:#04210f;font-weight:700;border-color:var(--wa)}}
input[type=search]{{flex:1;min-width:180px;background:var(--card);border:1px solid var(--line);color:var(--txt);border-radius:999px;padding:8px 14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px}}.card.done{{opacity:.45}}
.top{{display:flex;gap:12px;align-items:flex-start}}.t{{flex:1;min-width:0}}.t h2{{font-size:16px;margin:0}}.t p{{margin:0;color:var(--mut);font-size:13px}}
.sc{{min-width:48px;height:48px;border-radius:50%;display:grid;place-content:center;font-weight:800;border:3px solid}}
.hot{{color:var(--hot);border-color:var(--hot)}}.warm{{color:var(--warm);border-color:var(--warm)}}.cold{{color:var(--cold);border-color:var(--cold)}}
.chk{{font-size:12px;color:var(--mut);white-space:nowrap;cursor:pointer}}
.pr{{margin:10px 0;padding-left:18px;color:#fca5a5;font-size:13px}}
details{{margin:8px 0}}summary{{cursor:pointer;color:var(--mut);font-size:13px}}
textarea{{width:100%;height:150px;margin-top:8px;background:#0e1427;color:var(--txt);border:1px solid var(--line);border-radius:10px;padding:10px;font:13px/1.4 inherit}}
.bt{{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}}
footer{{color:var(--mut);font-size:12px;margin-top:26px;text-align:center}}
</style></head><body><div class="wrap">
<h1>🎯 Clienți <span>MISAVO</span> · {ORAS['nume']}</h1>
<p class="sub">Generat la {data} · scorul arată cât de mult are nevoie firma de un site nou (🔴 70+ = client fierbinte)</p>
<div class="stats"><div class="st"><b>{len(firme)}</b><small>firme găsite</small></div>
<div class="st"><b>{fierbinti}</b><small>clienți fierbinți</small></div>
<div class="st"><b id="nrc">0</b><small>contactați</small></div></div>
<div class="bar"><button class="f on" data-f="toate">Toate</button>{filtre}
<button class="f" data-f="hot">🔴 Doar fierbinți</button><button class="f" data-f="necontactat">Necontactați</button>
<input type="search" id="q" placeholder="Caută după nume..."></div>
<div class="grid" id="g">{''.join(carduri)}</div>
<footer>Trimite mesajele manual, câte unul, și respectă un „nu” — așa rămâi în regulă cu WhatsApp și GDPR.</footer>
</div><script>
const K="misavo_contactati";let C={{}};try{{C=JSON.parse(localStorage.getItem(K)||"{{}}")}}catch(e){{}}
const save=()=>{{try{{localStorage.setItem(K,JSON.stringify(C))}}catch(e){{}};document.getElementById("nrc").textContent=Object.keys(C).length}};
document.querySelectorAll(".card").forEach(c=>{{const id=c.dataset.id,x=c.querySelector(".contactat");
 if(C[id]){{x.checked=true;c.classList.add("done")}}
 x.onchange=()=>{{if(x.checked)C[id]=Date.now();else delete C[id];c.classList.toggle("done",x.checked);save()}};
 c.querySelector(".copy").onclick=e=>{{navigator.clipboard.writeText(c.querySelector("textarea").value);e.target.textContent="✅ Copiat"}};
 c.querySelectorAll(".wa").forEach(a=>a.addEventListener("click",()=>{{if(!x.checked){{x.checked=true;x.onchange()}}}}));}});
save();let F="toate";
const apply=()=>{{const q=document.getElementById("q").value.toLowerCase();
 document.querySelectorAll(".card").forEach(c=>{{let ok=F=="toate"||c.dataset.dom==F||(F=="hot"&&+c.dataset.scor>=70)||(F=="necontactat"&&!C[c.dataset.id]);
 if(q&&!c.querySelector("h2").textContent.toLowerCase().includes(q))ok=false;c.style.display=ok?"":"none"}})}};
document.querySelectorAll(".f").forEach(b=>b.onclick=()=>{{document.querySelectorAll(".f").forEach(x=>x.classList.remove("on"));b.classList.add("on");F=b.dataset.f;apply()}});
document.getElementById("q").oninput=apply;
</script></body></html>"""
    with open(cale, "w", encoding="utf-8") as fh:
        fh.write(pagina)

# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="MISAVO – bot de găsit clienți")
    ap.add_argument("--nume", default="", help="prenumele tău, apare în mesaje (ex. Michael)")
    ap.add_argument("--oras", default="bucuresti", choices=sorted(ORASE), help="bucuresti sau oradea")
    ap.add_argument("--domenii", default="constructii,sanatate,restaurante")
    ap.add_argument("--google", action="store_true", help="caută și în Google Maps (cere GOOGLE_MAPS_API_KEY)")
    ap.add_argument("--max", type=int, default=200, help="câte firme să verifice (cele cu telefon au prioritate)")
    ap.add_argument("--iesire", default="clienti_misavo", help="folderul cu rezultate")
    ap.add_argument("--fara-browser", action="store_true")
    a = ap.parse_args()
    global ORAS
    ORAS = ORASE[a.oras]
    print(f"📍 Oraș: {ORAS['nume']}", file=sys.stderr)

    domenii = [d.strip() for d in a.domenii.split(",") if d.strip() in DOMENII]
    firme = din_osm(domenii) + (din_google(domenii) if a.google else [])

    # elimină duplicatele și firmele fără nume
    unice = {}
    for f in firme:
        if not f["nume"]:
            continue
        k = cheie_unica(f)
        if k not in unice:
            unice[k] = f
            continue
        vechi = unice[k]   # aceeași firmă din 2 surse: completăm datele (Google are prioritate)
        for x, y in f.items():
            if y not in ("", None) and (f["sursa"] == "Google Maps" or not vechi.get(x)):
                vechi[x] = y
    firme = list(unice.values())
    for f in firme:
        for camp in ("telefon", "email", "site", "facebook", "adresa", "maps", "tip"):
            f.setdefault(camp, "")
        f.setdefault("rating", None); f.setdefault("recenzii", None)
    # prioritate: cei pe care îi poți contacta
    firme.sort(key=lambda f: (not telefon_normalizat(f["telefon"])[2], not f["telefon"], not f["email"]))
    firme = firme[: a.max]

    for f in firme:   # email pe domeniu propriu (ex. office@firma.ro) => verificăm firma.ro
        dom = f["email"].split("@")[-1].strip().lower() if "@" in f["email"] else ""
        if not f["site"] and dom and dom not in EMAIL_GRATUIT:
            f["site_din_email"] = dom
            f["site"] = "https://" + dom

    print(f"🌐 Verific site-urile pentru {len(firme)} firme (durează 1–3 minute)...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=12) as ex:
        for f, an in zip(firme, ex.map(lambda f: analizeaza_site(f["site"]), firme)):
            if f.get("site_din_email"):
                if an["stare"] == "picat":
                    an["probleme"] = [f"Domeniul din email ({f['site_din_email']}) nu se deschide – NU trimite email, doar WhatsApp"]
                elif an["stare"] == "ok":
                    an["probleme"] = [f"Are site ({f['site_din_email']}, găsit din email) – probabil nu e client"]
            f["analiza"] = an
    for f in firme:
        f["scor"] = scor(f)
        f["mesaj"] = mesaj(f, a.nume)
    firme.sort(key=lambda f: -f["scor"])

    os.makedirs(a.iesire, exist_ok=True)
    zi = datetime.date.today().isoformat()
    cale_html = os.path.abspath(os.path.join(a.iesire, f"clienti_{a.oras}_{zi}.html"))
    cale_csv = os.path.abspath(os.path.join(a.iesire, f"clienti_{a.oras}_{zi}.csv"))
    raport(firme, cale_html, a.nume)
    with open(cale_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["Scor", "Firmă", "Domeniu", "Telefon", "Email", "Site", "Probleme", "Adresă",
                    "Rating", "Recenzii", "Sursă", "Mesaj", "Status", "Data contact", "Note"])
        for f in firme:
            w.writerow([f["scor"], f["nume"], DOMENII[f["domeniu"]]["titlu"], telefon_normalizat(f["telefon"])[0],
                        f["email"], f["site"] or f["facebook"], "; ".join(f["analiza"]["probleme"]), f["adresa"],
                        f["rating"] or "", f["recenzii"] or "", f["sursa"], f["mesaj"], "", "", ""])

    cale_json = os.path.abspath(os.path.join(a.iesire, f"clienti_{a.oras}_{zi}.json"))
    with open(cale_json, "w", encoding="utf-8") as fh:   # pentru importul în aplicația Misavo Clienți
        json.dump([{
            "id": cheie_unica(f), "nume": f["nume"], "domeniu": f["domeniu"], "tip": f["tip"],
            "telefon": telefon_normalizat(f["telefon"])[0], "tel_intl": telefon_normalizat(f["telefon"])[1],
            "mobil": telefon_normalizat(f["telefon"])[2], "email": f["email"], "site": f["site"],
            "social": f["facebook"], "adresa": f["adresa"], "maps": f["maps"], "rating": f["rating"],
            "recenzii": f["recenzii"], "scor": f["scor"], "probleme": f["analiza"]["probleme"],
            "mesaj": f["mesaj"], "sursa": f["sursa"], "oras": ORAS["nume"]} for f in firme], fh, ensure_ascii=False)

    fierbinti = sum(1 for f in firme if f["scor"] >= 70)
    print(f"\n✅ Gata! {len(firme)} firme analizate, {fierbinti} clienți fierbinți (scor 70+).")
    print("\nTop 5:")
    for f in firme[:5]:
        print(f"  {f['scor']:>3}  {f['nume'][:40]:<40} {telefon_normalizat(f['telefon'])[0]:<14} {f['analiza']['probleme'][0]}")
    print(f"\n📄 Raport: {cale_html}\n📊 Tabel (pentru Google Sheets / Excel): {cale_csv}")
    print(f"📲 Pentru aplicația Misavo Clienți (butonul Importă): {cale_json}")
    if not a.fara_browser:
        import webbrowser
        webbrowser.open("file://" + cale_html)

if __name__ == "__main__":
    main()
