"""Contact dispatch. Reads data/contacts.json (managed from the dashboard) and alerts each contact
by Telegram and/or Twilio SMS. Every attempt is logged to logs/dispatch.jsonl for the dashboard.
Emergency-service entries (112) are NEVER auto-contacted: the dashboard shows them for a human to act on."""
import json, os, threading, time
import requests
from . import config as C

CONTACTS_PATH = os.environ.get("CONTACTS_FILE", "data/contacts.json")
DISPATCH_LOG = os.environ.get("DISPATCH_LOG", "logs/dispatch.jsonl")
TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM = (os.environ.get(k, "") for k in ("TWILIO_SID", "TWILIO_TOKEN", "TWILIO_FROM"))

def load_contacts(path=None):
    try:
        return json.load(open(path or CONTACTS_PATH))
    except (OSError, ValueError):
        return []

class Notifier:
    def __init__(self, token=None, chat_id=None, update_s=60.0, sender=None, contacts_path=None, log_path=None):
        self.token, self.chat, self.update_s = token or "", chat_id or "", update_s
        self.sender = sender                       # sender(text, recipient) -> bool ; default sends for real
        self.contacts_path, self.log_path = contacts_path or CONTACTS_PATH, log_path or DISPATCH_LOG
        self.state = {}

    # ---- channels -----------------------------------------------------------------
    def _telegram(self, chat_id, text):
        if not self.token:
            return False, "no TELEGRAM_TOKEN"
        try:
            r = requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                              json={"chat_id": chat_id, "text": text}, timeout=6)
            return r.ok, "" if r.ok else r.text[:100]
        except Exception as e:
            return False, str(e)[:100]

    def _sms(self, number, text):
        if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM):
            return False, "Twilio not configured"
        try:
            r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json",
                              data={"From": TWILIO_FROM, "To": number, "Body": text[:300]},
                              auth=(TWILIO_SID, TWILIO_TOKEN), timeout=8)
            return r.ok, "" if r.ok else r.text[:100]
        except Exception as e:
            return False, str(e)[:100]

    def recipients(self):
        rs = [c for c in load_contacts(self.contacts_path) if c.get("type", "personal") != "emergency"]
        if not rs and self.chat:                    # fallback: single chat id from .env
            rs = [{"name": "default", "telegram_chat_id": self.chat}]
        return rs

    def _log(self, row):
        os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
        with open(self.log_path, "a") as f:
            f.write(json.dumps(row) + "\n")

    def dispatch(self, device, level, text):
        """Send `text` to every personal contact. Returns list of result rows."""
        out = []
        for c in self.recipients():
            tries = []
            if self.sender:
                tries.append(("custom", lambda t, c=c: (self.sender(t, c), "")))
            else:
                if c.get("telegram_chat_id"):
                    tries.append(("telegram", lambda t, c=c: self._telegram(c["telegram_chat_id"], t)))
                if c.get("sms") and c.get("phone"):
                    tries.append(("sms", lambda t, c=c: self._sms(c["phone"], t)))
            for ch, fn in tries:
                ok, err = fn(text)
                row = {"t": time.time(), "device": device, "level": level, "to": c.get("name", "?"),
                       "channel": ch, "ok": bool(ok), "err": err}
                self._log(row); out.append(row)
        return out

    # ---- policy ---------------------------------------------------------------------
    @staticmethod
    def _where(res):
        if res.get("lat") is None:
            return "location unknown"
        acc = f" (+/-{res['accuracy']:.0f} m)" if res.get("accuracy") else ""
        return f"https://maps.google.com/?q={res['lat']:.6f},{res['lon']:.6f}{acc}"

    def on_result(self, res):
        """Call once per engine result. Returns the text it sent (or None)."""
        st = self.state.setdefault(res["device"], {"sent_first": False, "sent_red": False, "last_t": 0.0, "last_loc": 0.0})
        if res["t"] - st["last_t"] > C.SESSION_TIMEOUT_S:
            st.update(sent_first=False, sent_red=False, last_loc=0.0)
        st["last_t"] = res["t"]
        msg, lvl = None, res["alert_level"]
        if lvl == 2 and not st["sent_red"]:
            st["sent_red"] = True
            msg = f"SOS THREAT CONFIRMED ({res['device']}): {res['class']}. {self._where(res)}"
        elif res.get("lat") is not None and not st["sent_first"]:
            st["sent_first"] = True
            msg = f"SOS pressed ({res['device']}). {self._where(res)}"
        elif res.get("lat") is not None and st["sent_first"] and res["t"] - st["last_loc"] >= self.update_s:
            msg = f"SOS update ({res['device']}, {res['class'] or 'tracking'}): {self._where(res)}"
        if msg:
            st["last_loc"] = res["t"]
            if self.sender:                         # tests: synchronous
                self.dispatch(res["device"], lvl, msg)
            else:
                threading.Thread(target=self.dispatch, args=(res["device"], lvl, msg), daemon=True).start()
        return msg
