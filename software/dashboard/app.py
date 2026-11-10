"""SOS Guardian dashboard: login, emergency contacts (+112 card), live map, dispatch log.
Run:  DASH_USER=admin DASH_PASS=yourpassword python -m dashboard.app     ->  http://localhost:5000
Reads logs/results.jsonl (written by cloud.server) and data/contacts.json (shared with the notifier)."""
import json, os, re, secrets, time, threading
from collections import defaultdict
from flask import Flask, request, session, redirect, jsonify, render_template_string, abort
from werkzeug.security import generate_password_hash, check_password_hash
from cloud.notify import Notifier, load_contacts, CONTACTS_PATH, DISPATCH_LOG
from cloud import config as C

RESULT_LOG = os.environ.get("RESULT_LOG", "logs/results.jsonl")
USER = os.environ.get("DASH_USER", "admin")
PASS = os.environ.get("DASH_PASS") or secrets.token_urlsafe(8)
if not os.environ.get("DASH_PASS"):
    print(f"[dashboard] DASH_PASS not set. One-time password for '{USER}': {PASS}")
PW_HASH = generate_password_hash(PASS)
STALE_S = 90
LOCK = threading.Lock()
FAILS = defaultdict(list)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(16)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

def tail(path, n):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 200_000))
            lines = f.read().decode(errors="ignore").splitlines()
    except OSError:
        return []
    out = []
    for l in lines[-n:]:
        try: out.append(json.loads(l))
        except ValueError: pass
    return out

def save_contacts(cs):
    os.makedirs(os.path.dirname(CONTACTS_PATH) or ".", exist_ok=True)
    tmp = CONTACTS_PATH + ".tmp"
    json.dump(cs, open(tmp, "w"), indent=1); os.replace(tmp, CONTACTS_PATH)

def ensure_112():
    cs = load_contacts()
    if not any(c.get("type") == "emergency" for c in cs):
        cs.insert(0, {"id": "112", "name": "Emergency 112 (India ERSS)", "phone": "112", "type": "emergency",
                      "relation": "Police / Fire / Ambulance"})
        save_contacts(cs)

def authed(): return session.get("u") == USER
def csrf(): return session.setdefault("csrf", secrets.token_hex(16))
def need_auth():
    if not authed(): abort(401)
def need_csrf():
    if request.headers.get("X-CSRF") != session.get("csrf"): abort(403)

@app.route("/login", methods=["GET", "POST"])
def login():
    err = ""
    if request.method == "POST":
        ip = request.remote_addr; now = time.time()
        FAILS[ip] = [t for t in FAILS[ip] if now - t < 300]
        if len(FAILS[ip]) >= 5:
            err = "Too many attempts. Wait 5 minutes."
        elif request.form.get("csrf") == session.get("csrf") and request.form.get("u") == USER \
                and check_password_hash(PW_HASH, request.form.get("p", "")):
            session.clear(); session["u"] = USER; csrf()
            return redirect("/")
        else:
            FAILS[ip].append(now); err = "Wrong username or password."
    return render_template_string(LOGIN, err=err, csrf=csrf())

@app.route("/logout")
def logout():
    session.clear(); return redirect("/login")

@app.route("/")
def home():
    if not authed(): return redirect("/login")
    return render_template_string(PAGE, csrf=csrf(), user=USER)

@app.route("/api/state")
def state():
    need_auth()
    rows = tail(RESULT_LOG, 400)
    dev = rows[-1]["device"] if rows else None
    trail = [r for r in rows if r["device"] == dev]
    last = trail[-1] if trail else None
    now = time.time()
    age = (now - last.get("wall", last["t"])) if last else None
    level = last["alert_level"] if last and age < STALE_S else 0
    return jsonify({
        "device": dev, "age": age, "stale": age is None or age >= STALE_S, "level": level, "last": last,
        "trail": [{"lat": r["lat"], "lon": r["lon"], "cls": r["class"], "lvl": r["alert_level"]}
                  for r in trail[-120:] if r.get("lat") is not None],
        "dispatch": tail(DISPATCH_LOG, 15)[::-1],
        "contacts": load_contacts(),
        "classes": C.CLASS_NAMES,
    })

PHONE = re.compile(r"^\+?[0-9]{3,15}$")
@app.route("/api/contacts", methods=["POST"])
def add_contact():
    need_auth(); need_csrf()
    d = request.get_json(silent=True) or {}
    name = str(d.get("name", "")).strip()[:40]
    phone = re.sub(r"[ \-()]", "", str(d.get("phone", "")))
    chat = str(d.get("telegram_chat_id", "")).strip()[:20]
    if not name or not PHONE.match(phone): return jsonify(error="Name and a valid phone number are required"), 400
    if chat and not re.match(r"^-?[0-9]+$", chat): return jsonify(error="Telegram chat id must be a number"), 400
    with LOCK:
        cs = load_contacts()
        cs.append({"id": secrets.token_hex(4), "name": name, "phone": phone, "relation": str(d.get("relation", ""))[:30],
                   "type": "personal", "telegram_chat_id": chat, "sms": bool(d.get("sms"))})
        save_contacts(cs)
    return jsonify(ok=True)

@app.route("/api/contacts/<cid>", methods=["DELETE"])
def del_contact(cid):
    need_auth(); need_csrf()
    with LOCK:
        cs = load_contacts()
        if any(c["id"] == cid and c.get("type") == "emergency" for c in cs):
            return jsonify(error="112 stays pinned"), 400
        save_contacts([c for c in cs if c["id"] != cid])
    return jsonify(ok=True)

@app.route("/api/test", methods=["POST"])
def test_alert():
    need_auth(); need_csrf()
    n = Notifier(C.TELEGRAM_TOKEN, C.TELEGRAM_CHAT_ID)
    res = n.dispatch("dashboard", 0, "TEST from SOS Guardian dashboard: contacts are reachable. No emergency.")
    return jsonify(sent=len(res), ok=sum(r["ok"] for r in res))

LOGIN = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><title>SOS Guardian</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b1220;font:16px system-ui;color:#e8eefc}
form{background:#141d33;padding:32px;border-radius:16px;width:300px;box-shadow:0 10px 40px #0008}
h1{margin:0 0 4px;font-size:22px}p{margin:0 0 20px;color:#8fa3c8;font-size:13px}
input,button{width:100%;box-sizing:border-box;padding:11px;margin:6px 0;border-radius:8px;border:1px solid #2a3960;background:#0b1220;color:#e8eefc;font-size:15px}
button{background:#e5484d;border:0;font-weight:600;cursor:pointer}.e{color:#ff8a8a;font-size:13px;min-height:18px}</style>
<form method=post><h1>SOS Guardian</h1><p>Wearable safety console</p>
<input type=hidden name=csrf value="{{csrf}}"><input name=u placeholder=Username autofocus autocomplete=username>
<input name=p type=password placeholder=Password autocomplete=current-password><div class=e>{{err}}</div><button>Sign in</button></form>"""

PAGE = """<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<meta name=csrf content="{{csrf}}"><title>SOS Guardian</title>
<link rel=stylesheet href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{--bg:#0b1220;--card:#141d33;--line:#2a3960;--tx:#e8eefc;--mut:#8fa3c8;--red:#e5484d;--amb:#f5a524;--grn:#30c48d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px system-ui}
header{display:flex;justify-content:space-between;align-items:center;padding:12px 20px;border-bottom:1px solid var(--line)}
header b{font-size:18px}header a{color:var(--mut);text-decoration:none}
#banner{padding:14px 20px;font-weight:700;font-size:17px;background:#16324a;transition:background .3s}
#banner.l1{background:#5a4210}#banner.l2{background:var(--red);animation:fl 0.9s infinite}#banner.idle{background:#16222f;color:var(--mut)}
@keyframes fl{50%{background:#7a1418}}
main{display:grid;grid-template-columns:2fr 1fr;gap:16px;padding:16px 20px}@media(max-width:900px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px}
#map{height:430px;border-radius:10px}h3{margin:0 0 10px;font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}.st{background:#0f1830;border-radius:10px;padding:10px}
.st small{color:var(--mut);display:block}.st span{font-size:19px;font-weight:700}
.c{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)}
.c small{color:var(--mut);display:block}.tag{font-size:11px;padding:2px 7px;border-radius:99px;background:#22305a;margin-left:4px}
button,input{font:inherit;border-radius:8px;border:1px solid var(--line);background:#0b1220;color:var(--tx);padding:8px}
button{cursor:pointer;background:#22305a}button.d{background:none;color:var(--mut);padding:4px 8px}button.go{background:var(--red);border:0;font-weight:600}
form#f{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px}form#f .w{grid-column:1/3}
.e112{border:2px solid var(--red);border-radius:12px;padding:12px;margin-bottom:12px}.e112 a{display:block;text-align:center;background:var(--red);color:#fff;padding:10px;border-radius:8px;text-decoration:none;font-weight:700;margin:8px 0}
.e112 p{margin:6px 0;color:var(--mut);font-size:12px}pre{white-space:pre-wrap;background:#0b1220;padding:8px;border-radius:8px;font-size:12px;margin:6px 0}
.ok{color:var(--grn)}.no{color:var(--red)}
</style></head><body>
<header><b>SOS Guardian</b><span>{{user}} &middot; <a href=/logout>Sign out</a></span></header>
<div id=banner class=idle>No active session</div>
<main><section class=card><div class=stats>
<div class=st><small>Speed</small><span id=sp>-</span></div><div class=st><small>Class</small><span id=cl>-</span></div>
<div class=st><small>Fix source</small><span id=src>-</span></div><div class=st><small>Position error</small><span id=ac>-</span></div></div>
<div id=map></div></section>
<aside><div class=card style="margin-bottom:16px"><div class=e112 id=e112 style="display:none"><b>Emergency services (112)</b>
<p>This system never calls 112 by itself. A person must decide. One tap on a phone:</p><a href="tel:112">Call 112</a>
<p>Read or send this:</p><pre id=msg></pre><button id=cp>Copy message</button></div>
<h3>Emergency contacts <button id=tst style="float:right;font-size:12px">Send test alert</button></h3><div id=cs></div>
<form id=f><input id=n placeholder=Name required><input id=ph placeholder="+91..." required><input id=rel placeholder=Relation>
<input id=tg placeholder="Telegram chat id"><label class=w><input type=checkbox id=sms> also SMS (needs Twilio)</label>
<button class="go w">Add contact</button></form></div>
<div class=card><h3>Alert dispatch log</h3><div id=dl style="max-height:230px;overflow:auto"></div></div></aside></main>
<script>
const H={"X-CSRF":document.querySelector('meta[name=csrf]').content,"Content-Type":"application/json"};
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const map=L.map("map").setView([20.59,78.96],5);L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:"&copy; OpenStreetMap"}).addTo(map);
let line=null,dot=null,circ=null,fit=false;const COL={0:"#8fa3c8",1:"#f5a524",2:"#e5484d"};
function draw(d){const t=d.trail;if(!t.length)return;const pts=t.map(p=>[p.lat,p.lon]);
 if(line)line.remove();line=L.polyline(pts,{color:COL[d.level]||"#8fa3c8",weight:4}).addTo(map);
 const p=pts[pts.length-1];if(dot)dot.remove();dot=L.circleMarker(p,{radius:9,color:"#fff",weight:2,fillColor:COL[d.level]||"#30c48d",fillOpacity:1}).addTo(map);
 if(circ)circ.remove();const a=d.last&&d.last.accuracy;if(a)circ=L.circle(p,{radius:a,color:"#4d8dff",weight:1,fillOpacity:.1}).addTo(map);
 if(!fit){map.setView(p,16);fit=true}else if(d.level==2)map.panTo(p)}
function render(d){const b=document.getElementById("banner"),l=d.last;
 let cls="idle",txt="No active session";
 if(!d.stale&&l){if(d.level==2){cls="l2";txt="THREAT CONFIRMED: "+(l.class||"").replace("_"," ").toUpperCase()+" - contacts alerted"}
  else{cls="l1";txt="SOS pressed - tracking live"}}else if(l){txt="Last session ended "+Math.round(d.age)+" s ago"}
 b.className=cls;b.textContent=txt;
 document.getElementById("sp").textContent=l&&l.speed!=null?(l.speed*3.6).toFixed(1)+" km/h":"-";
 document.getElementById("cl").textContent=l&&l.class?l.class.replace("_"," "):"-";
 document.getElementById("src").textContent=l?l.src||"-":"-";
 document.getElementById("ac").textContent=l&&l.accuracy?"+/-"+Math.round(l.accuracy)+" m":"-";
 draw(d);
 const e=document.getElementById("e112");e.style.display=(!d.stale&&d.level>=1)?"block":"none";
 if(l&&l.lat!=null)document.getElementById("msg").textContent="Wearable SOS alert. Person may be in danger"+(d.level==2?" ("+(l.class||"").replace("_"," ")+")":"")+". Live location: https://maps.google.com/?q="+l.lat.toFixed(6)+","+l.lon.toFixed(6);
 document.getElementById("cs").innerHTML=d.contacts.map(c=>`<div class=c><div><b>${esc(c.name)}</b>${c.type=="emergency"?'<span class=tag>manual only</span>':(c.telegram_chat_id?'<span class=tag>Telegram</span>':'')+(c.sms?'<span class=tag>SMS</span>':'')}<small>${esc(c.phone)} ${esc(c.relation)}</small></div>${c.type=="emergency"?"":`<button class=d data-id="${esc(c.id)}">remove</button>`}</div>`).join("");
 document.getElementById("dl").innerHTML=d.dispatch.length?d.dispatch.map(r=>`<div class=c><div>${esc(r.to)} <span class=tag>${esc(r.channel)}</span><small>${new Date(r.t*1000).toLocaleTimeString()} - level ${esc(r.level)}${r.err?" - "+esc(r.err):""}</small></div><span class="${r.ok?"ok":"no"}">${r.ok?"sent":"failed"}</span></div>`).join(""):"<small>Nothing sent yet</small>"}
async function tick(){try{const r=await fetch("/api/state");if(r.status==401){location="/login";return}render(await r.json())}catch(e){}}
document.getElementById("cs").onclick=async e=>{const id=e.target.dataset.id;if(id){await fetch("/api/contacts/"+id,{method:"DELETE",headers:H});tick()}};
document.getElementById("f").onsubmit=async e=>{e.preventDefault();const r=await fetch("/api/contacts",{method:"POST",headers:H,body:JSON.stringify({name:n.value,phone:ph.value,relation:rel.value,telegram_chat_id:tg.value,sms:sms.checked})});
 if(!r.ok)alert((await r.json()).error);else{e.target.reset();tick()}};
document.getElementById("tst").onclick=async()=>{const r=await(await fetch("/api/test",{method:"POST",headers:H})).json();alert(`Test sent to ${r.sent} channel(s), ${r.ok} succeeded`);tick()};
document.getElementById("cp").onclick=()=>navigator.clipboard.writeText(document.getElementById("msg").textContent);
tick();setInterval(tick,2000);
</script></body></html>"""

if __name__ == "__main__":
    ensure_112()
    app.run(host=os.environ.get("DASH_HOST", "127.0.0.1"), port=int(os.environ.get("DASH_PORT", "5000")))
