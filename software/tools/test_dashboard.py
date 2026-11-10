"""Dashboard tests: auth wall, CSRF, contact CRUD, 112 pinned, state feed, XSS-safe storage."""
import os, json, tempfile, time
d = tempfile.mkdtemp()
os.environ.update(DASH_USER="admin", DASH_PASS="pw123", CONTACTS_FILE=f"{d}/c.json", DISPATCH_LOG=f"{d}/d.jsonl", RESULT_LOG=f"{d}/r.jsonl")
from dashboard import app as A

def run():
    A.ensure_112(); c = A.app.test_client()
    assert c.get("/api/state").status_code == 401 and c.get("/").status_code == 302
    c.get("/login")
    with c.session_transaction() as s: tok = s["csrf"]
    assert "Wrong" in c.post("/login", data={"u": "admin", "p": "bad", "csrf": tok}).get_data(as_text=True)
    assert c.post("/login", data={"u": "admin", "p": "pw123", "csrf": tok}).status_code == 302
    with c.session_transaction() as s: tok = s["csrf"]; H = {"X-CSRF": tok}
    assert c.post("/api/contacts", json={"name": "Mom", "phone": "+919999999999"}).status_code == 403          # no CSRF
    assert c.post("/api/contacts", json={"name": "Mom", "phone": "abc"}, headers=H).status_code == 400
    assert c.post("/api/contacts", json={"name": "<b>Mom</b>", "phone": "+91 99999-99999", "telegram_chat_id": "123", "sms": True}, headers=H).status_code == 200
    cs = c.get("/api/state").json["contacts"]; assert [x["name"] for x in cs] == ["Emergency 112 (India ERSS)", "<b>Mom</b>"]
    assert c.delete("/api/contacts/112", headers=H).status_code == 400
    # feed: write two result rows, expect level 2 and trail
    now = time.time()
    with open(f"{d}/r.jsonl", "w") as f:
        for i, lv in enumerate((1, 2)):
            f.write(json.dumps({"device": "w01", "t": now - 10 + i, "lat": 12.97 + i * 1e-3, "lon": 77.59, "accuracy": 20, "class": "vehicle_kidnap", "alert_level": lv, "speed": 11.0, "src": "wifi"}) + "\n")
    s = c.get("/api/state").json; assert s["level"] == 2 and len(s["trail"]) == 2 and not s["stale"]
    assert c.delete(f"/api/contacts/{cs[1]['id']}", headers=H).status_code == 200
    print("PASS dashboard")
run()
