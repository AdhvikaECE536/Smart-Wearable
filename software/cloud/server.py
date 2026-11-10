"""Run:  python -m cloud.server     (reads env vars, see .env.example)"""
import os
import secrets
import json, os, ssl, threading, time
import paho.mqtt.client as mqtt
from . import config as C
from .engine import DeviceTracker
from .geo import UnwiredLocator, MockLocator, LocalDbLocator, ChainLocator
from .payload import decode
from .threat import load_model
from .notify import Notifier

LOCK, TRACKERS = threading.Lock(), {}
LOG_PATH = os.environ.get("RESULT_LOG", "logs/results.jsonl")

def make_locator():
    mode = C.GEO_MODE
    if mode == "mock":
        return MockLocator.from_file(C.MOCK_ROUTERS)
    parts = []
    if "local" in mode:
        parts.append(LocalDbLocator(C.WIFI_DB, C.WIFI_MIN_APS))
    if "unwired" in mode:
        if not C.UNWIRED_TOKEN:
            raise SystemExit("UNWIRED_TOKEN not set (use GEO_MODE=local or mock)")
        parts.append(UnwiredLocator(C.UNWIRED_TOKEN, C.UNWIRED_URL))
    if not parts:
        raise SystemExit(f"unknown GEO_MODE {mode!r} (mock | local | unwired | local+unwired)")
    return parts[0] if len(parts) == 1 else ChainLocator(*parts)

LOCATOR, MODEL = None, None
tb = None
NOTIFY = Notifier(C.TELEGRAM_TOKEN, C.TELEGRAM_CHAT_ID, C.NOTIFY_UPDATE_S)

T0 = time.time()
def clock():
    """Server time. REPLAY_SPEED > 1 speeds simulated time up so a fast simulator looks like a 10 s device."""
    return T0 + (time.time() - T0) * C.REPLAY_SPEED

def publish_result(res):
    res["wall"] = time.time()          # real clock, for the dashboard (res["t"] may be replay-scaled)
    os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(res) + "\n")
    print("[result]", {k: (round(v, 5) if isinstance(v, float) else v) for k, v in res.items()})
    if NOTIFY is not None:
        NOTIFY.on_result(res)
    if tb is not None:
        tele = {"latitude": res["lat"], "longitude": res["lon"], "speed": res["speed"],
                "accel": res["accel"], "threat_class": res["class"], "threat_prob": res["prob"],
                "alert_level": res["alert_level"], "sos_alert": 1 if res["alert_level"] == 2 else 0,
                "sos_pressed": res["sos"], "gated": int(res["gated"]), "fix_source": res["src"], "accuracy_m": res["accuracy"]}
        tele = {k: v for k, v in tele.items() if v is not None}
        tb.publish("v1/devices/me/telemetry", json.dumps(tele), qos=1)

def on_connect(client, userdata, flags, rc, props=None):
    print("[mqtt] connected:", rc)
    client.subscribe(C.UPLINK_TOPIC, qos=1)

def on_message(client, userdata, msg):
    device = msg.topic.split("/")[1] if msg.topic.count("/") >= 2 else "device"
    try:
        decode(msg.payload)  # validate early
    except Exception as e:
        print("[mqtt] bad payload on", msg.topic, e)
        return
    with LOCK:
        tr = TRACKERS.setdefault(device, DeviceTracker(device, LOCATOR, MODEL))
        res = tr.on_uplink(msg.payload, clock())
    if res:
        publish_result(res)

def watchdog():
    while True:
        time.sleep(3)
        with LOCK:
            outs = [r for r in (t.tick(clock()) for t in TRACKERS.values()) if r]
        for r in outs:
            publish_result(r)

def main():
    global LOCATOR, MODEL, tb
    LOCATOR, MODEL = make_locator(), load_model(C.MODEL_PATH, C.SCALER_PATH)
    if C.TB_TOKEN:
        tb = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sos-server-tb")
        tb.username_pw_set(C.TB_TOKEN)
        tb.connect(C.TB_HOST, C.TB_PORT, 60)
        tb.loop_start()
    else:
        print("[tb] TB_TOKEN not set -> dashboard publishing disabled")
    threading.Thread(target=watchdog, daemon=True).start()
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=os.environ.get("MQTT_CLIENT_ID") or "sos-server-" + secrets.token_hex(3))
    if C.HIVEMQ_USER:
        c.username_pw_set(C.HIVEMQ_USER, C.HIVEMQ_PASS)
    if C.HIVEMQ_TLS:
        c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    elif "+" in C.UPLINK_TOPIC or "#" in C.UPLINK_TOPIC:
        print("[mqtt] WARNING: plain broker + wildcard topic: anyone can inject packets. Set UPLINK_TOPIC to your exact device topic.")
    c.on_connect, c.on_message = on_connect, on_message
    c.connect(C.HIVEMQ_HOST, C.HIVEMQ_PORT, 60)
    c.loop_forever()

if __name__ == "__main__":
    main()
