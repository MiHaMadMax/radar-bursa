"""MISAVO Instagram design template (4:5, 1080x1350).
Usage: from template import CSS, page, mac  (see README.md)
page(n, body, swipe=True) returns full HTML; replace '/ 6' counter as needed with page_total().
"""
CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{width:1080px;height:1350px;font-family:'Inter';color:#fff;overflow:hidden;position:relative;background:#0E0B2E}
.bg{position:absolute;inset:0;background:
 radial-gradient(700px 600px at 85% 8%, #FF4D8D 0%, transparent 60%),
 radial-gradient(800px 700px at 10% 30%, #3B5BFF 0%, transparent 62%),
 radial-gradient(900px 800px at 70% 95%, #A040FF 0%, transparent 60%),
 linear-gradient(160deg,#1A1060,#0E0B2E)}
.grain{position:absolute;inset:0;background-image:radial-gradient(rgba(255,255,255,.06) 1px,transparent 1px);background-size:6px 6px;opacity:.5}
.wrap{position:absolute;inset:0;padding:80px 80px}
.top{display:flex;justify-content:space-between;align-items:center;font-size:28px;font-weight:600}
.pill{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.28);backdrop-filter:blur(10px);padding:12px 26px;border-radius:999px;font-size:26px;font-weight:600}
h1{font-family:'Inter Display';font-weight:900;letter-spacing:-.04em;line-height:.98}
.hl{background:#fff;color:#2A1A8A;padding:0 18px;border-radius:18px;display:inline-block;transform:rotate(-2deg);margin:6px 0}
.y{color:#FFE14D}
.card{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.25);border-radius:32px;backdrop-filter:blur(16px)}
.laptop{position:absolute;border-radius:22px 22px 0 0;background:#111;padding:16px 16px 0;box-shadow:0 40px 80px rgba(0,0,0,.5)}
.laptop img{display:block;border-radius:8px 8px 0 0;width:100%}
.base{position:absolute;height:26px;background:linear-gradient(#d9dbe6,#9a9db0);border-radius:0 0 30px 30px;box-shadow:0 30px 60px rgba(0,0,0,.4)}
.phone{position:absolute;background:#0a0a0a;border-radius:42px;padding:12px;box-shadow:0 40px 90px rgba(0,0,0,.55),0 0 0 3px rgba(255,255,255,.15)}
.phone img{display:block;width:100%;border-radius:30px}
.sticker{position:absolute;background:#FFE14D;color:#1A1060;font-weight:800;border-radius:999px;padding:16px 30px;font-size:30px;box-shadow:0 14px 30px rgba(0,0,0,.35)}
.swipe{position:absolute;bottom:70px;right:80px;font-size:30px;font-weight:700;display:flex;align-items:center;gap:14px}
.swipe span{background:#fff;color:#2A1A8A;width:64px;height:64px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:34px}
.foot{position:absolute;bottom:80px;left:80px;font-size:28px;font-weight:600;opacity:.85}
.chk{display:flex;gap:22px;align-items:center;font-size:36px;font-weight:600;margin:20px 0}
.chk b{flex:none;width:56px;height:56px;border-radius:50%;background:#FFE14D;color:#1A1060;display:flex;align-items:center;justify-content:center;font-size:32px}

.mac{position:absolute}
.mac .scr{position:relative;background:#0b0b0d;border-radius:26px 26px 6px 6px;padding:16px 16px 22px;box-shadow:0 0 0 2px #2b2b30, 0 40px 90px rgba(0,0,0,.55)}
.mac .scr img{display:block;width:100%;border-radius:6px}
.mac .notch{position:absolute;top:16px;left:50%;transform:translateX(-50%);width:15%;height:20px;background:#0b0b0d;border-radius:0 0 12px 12px;z-index:2}
.mac .notch:after{content:'';position:absolute;left:50%;top:5px;width:8px;height:8px;margin-left:-4px;border-radius:50%;background:#1d2235}
.mac .base{position:relative;margin:0 -7%;height:24px;background:linear-gradient(#e7e8ee 0%,#c5c7d1 45%,#8e91a0 100%);border-radius:2px 2px 26px 26px;box-shadow:0 26px 50px rgba(0,0,0,.45)}
.mac .base:before{content:'';position:absolute;left:50%;top:0;width:16%;height:9px;margin-left:-8%;background:linear-gradient(#a9acb8,#c9cbd4);border-radius:0 0 12px 12px}
"""
def page(n, body, swipe=True):
    s = "<div class='swipe'>Glisează <span>→</span></div>" if swipe else ""
    return f"""<html><head><meta charset='utf-8'><style>{CSS}</style></head><body><div class='bg'></div><div class='grain'></div>
<div class='wrap'><div class='top'><span>@misavo.digital</span><span class='pill'>{n} / 6</span></div>{body}</div>
<div class='foot'>misavo.digital</div>{s}</body></html>"""


def mac(left,top,width,img,rot=0):
    return f"<div class='mac' style='left:{left}px;top:{top}px;width:{width}px;transform:rotate({rot}deg)'><div class='scr'><div class='notch'></div><img src='{img}'></div><div class='base'></div></div>"

def page_total(n, total, body, swipe=True, foot=True):
    html = page(n, body, swipe=swipe).replace("/ 6</span>", f"/ {total}</span>")
    if not foot:
        html = html.replace("<div class='foot'>misavo.digital</div>", "")
    return html

def story(body):
    """9:16 story (1080x1920) in the same style."""
    return f"<html><head><meta charset='utf-8'><style>{CSS} body{{height:1920px}} .wrap{{padding:230px 90px 200px}}</style></head><body><div class='bg'></div><div class='grain'></div><div class='wrap'>{body}</div></body></html>"
