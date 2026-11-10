"""All settings come from environment variables (see .env.example)."""
import os

def _e(k, d=""):
    return os.environ.get(k, d)

# HiveMQ Cloud (devices publish here, this server subscribes)
HIVEMQ_HOST = _e("HIVEMQ_HOST")
HIVEMQ_PORT = int(_e("HIVEMQ_PORT", "8883"))
HIVEMQ_TLS = _e("HIVEMQ_TLS", "1") == "1"      # 0 for a plain broker such as broker.emqx.io:1883
HIVEMQ_USER = _e("HIVEMQ_USER")
HIVEMQ_PASS = _e("HIVEMQ_PASS")
UPLINK_TOPIC = _e("UPLINK_TOPIC", "sos/+/uplink")

# Geolocation
GEO_MODE = _e("GEO_MODE", "unwired")          # unwired | mock
UNWIRED_TOKEN = _e("UNWIRED_TOKEN")
UNWIRED_URL = _e("UNWIRED_URL", "https://us1.unwiredlabs.com/v2/process")
MOCK_ROUTERS = _e("MOCK_ROUTERS", "mock_routers.json")

# Model
MODEL_PATH = _e("MODEL_PATH", "model.keras")   # falls back to RuleModel if missing
SCALER_PATH = _e("SCALER_PATH", "")            # optional json {"mean":[..],"std":[..]}

# ThingsBoard (device access token; plain MQTT)
TB_HOST = _e("TB_HOST", "demo.thingsboard.io")
TB_PORT = int(_e("TB_PORT", "1883"))
TB_TOKEN = _e("TB_TOKEN")

# Pipeline behaviour
FIX_INTERVAL_S = 10.0     # device sends one packet every 10 s while SOS is active
MIN_DT_S = 3.0            # ignore packets closer than this (button bounce / duplicates)
WINDOW = 5                # LSTM time steps
SMOOTH = int(_e("SMOOTH", "3"))       # trailing mean over positions (set 1 to match a notebook that did not smooth)
LATCH = int(_e("LATCH", "2"))         # consecutive threat windows before red alert
THREAT_MIN_PROB = 0.5
MAX_DEADRECKON = 6        # stop extrapolating after this many consecutive gaps
SESSION_TIMEOUT_S = 300.0
# Index order MUST match the label encoding used when the model was trained.
CLASS_NAMES = [c.strip() for c in _e("CLASS_NAMES", "stationary,foot_escape,vehicle_kidnap").split(",")]
THREAT_CLASSES = {1, 2}

# A threat class is ignored when the path over the window is shorter than ACC_GATE x the worst reported
# position error: that motion is indistinguishable from Wi-Fi location jitter. 0 disables the gate.
ACC_GATE = float(_e("ACC_GATE", "1.5"))

# Contact alerts (Telegram bot). Leave empty to disable.
TELEGRAM_TOKEN = _e("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = _e("TELEGRAM_CHAT_ID")
NOTIFY_UPDATE_S = float(_e("NOTIFY_UPDATE_S", "60"))

# Position source. mock | local | unwired | local+unwired (try the local database first, then Unwired Labs)
WIFI_DB = _e("WIFI_DB", "wifi_db.sqlite")
WIFI_MIN_APS = int(_e("WIFI_MIN_APS", "2"))        # known routers needed for a fix
WIFI_ACC_FLOOR_M = float(_e("WIFI_ACC_FLOOR_M", "20"))   # a Wi-Fi fix is never better than this

# Fast replay: >1 makes the server count simulated seconds, so a simulator run with --period 1 and REPLAY_SPEED=10
# looks like a 10 s device. Leave at 1 for anything real (Wokwi, hardware).
REPLAY_SPEED = float(_e("REPLAY_SPEED", "1"))
