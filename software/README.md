# SOS Wearable — Software Side

Team TID70 · 23ECE381 Open Lab I · Amrita Vishwa Vidyapeetham · Guide: Dr. Harshit Srivastava

Project: *Stand-Alone Wearable Safety Device with Hybrid Location Triangulation & Cloud Alerting*


---

## 1. Where we stand

**The software side runs end to end.** A simulated wearable presses SOS, sends a 21-byte Wi-Fi fingerprint over MQTT, the cloud server turns it into a position and a speed, an LSTM classifies the motion, and a confirmed threat flashes red on our dashboard and sends a Telegram message to the saved contacts. We watched this work on our own machines on 6 Nov 2026.

1. What is **real**: the MQTT transport, the server, the trained LSTM (`model.keras`), the dashboard, and Telegram delivery.
2. What is **simulated**: the wearable (Wokwi, not hardware), the Wi-Fi router database (a mock one), and the motion scenarios (generated, not walked).
3. What is **not done**: hardware, the cellular modem path, a live Unwired Labs lookup, and any field test. Section 10 lists these honestly.

Plain-English numbers worth remembering:

| Fact | In plain English |
|---|---|
| LSTM accuracy 73.9% on unseen people | It gets about three windows in four right on people it never trained on. |
| 224 of 297 vehicle windows caught | About one vehicle window in four is missed. This is the costly error. |
| Alert latency about 60 s | The red alert needs two confirmed windows after a 5-step history, so it is not instant. |
| Packet every 10 s | One location fix per 10 seconds while SOS is active. |

---

## 2. How the system works

```
  Wearable (Wokwi sim)                Cloud (our laptop)                       People
 ┌──────────────────────┐   MQTT   ┌────────────────────────────────┐
 │ GPIO4 button         │  broker  │ cloud/server.py                │     ┌────────────┐
 │ Wi-Fi scan, top 3 AP │ ───────► │  decode 21-byte payload        │ ──► │ Telegram   │
 │ 21-byte hex payload  │  (EMQX)  │  geolocate (mock / Unwired)    │     │ to contacts│
 │ publish every 10 s   │          │  smooth + fill gaps            │     └────────────┘
 └──────────────────────┘          │  speed + acceleration          │     ┌────────────┐
                                   │  LSTM (5 steps x 2 features)   │ ──► │ Dashboard  │
                                   │  accuracy gate + 2-window latch│     │ login, map │
                                   └────────────────────────────────┘     │ contacts   │
                                          │ logs/results.jsonl            │ 112 card   │
                                          └──────────────────────────────►└────────────┘
```

**Why this design.** Our first review showed LoRaWAN coverage in India is too thin to depend on, so the device now uplinks over cellular (SIMCom A7670C) to an MQTT broker. A GPS chip fails indoors and drains the battery, so we locate the wearer from the Wi-Fi routers around it. A physical button replaces pressure, voice and heart-rate triggers, because the five papers we reviewed all had false-alarm problems with those.

### The packet

21 bytes, sent as 42 hex characters: three access points, each 6 bytes of BSSID plus 1 byte holding the signal strength with its sign dropped (so -48 dBm is `0x30`).
Example: `42133755aa01 37 ...`. Code: `cloud/payload.py` (decode) and the sketch's `buildPayloadHex()` (encode).

### What the server does with each packet

1. **Decode** the hex into up to three (BSSID, signal) pairs.
2. **Locate.** `GEO_MODE=mock` matches BSSIDs against a generated router database (`mock_routers.json`). `GEO_MODE=unwired` asks the Unwired Labs API. If no router is recognised, it falls back to dead reckoning.
3. **Fill gaps.** If packets stop for 15 s (1.5 × the 10 s interval), the server carries the last speed forward for up to 6 missed fixes, then stops. These show as `src: hold`.
4. **Smooth** positions with a 3-point trailing mean.
5. **Features.** Haversine distance gives speed; the change in speed between steps gives acceleration. These are the model's two inputs.
6. **Classify.** Last 5 steps go into the LSTM, which outputs three probabilities: stationary, foot escape, vehicle kidnap.
7. **Accuracy gate.** A threat class is ignored if the path over the window is shorter than 1.5 × the worst reported position error. Wi-Fi jitter alone then cannot look like running.
8. **Latch.** Two consecutive threat windows are required for a red alert (`alert_level 2`). One SOS press with no confirmed threat stays at `alert_level 1`.
9. **Notify.** First fix: "SOS pressed" with a map link. Latch: "THREAT CONFIRMED". Then a location update every 60 s. All of it is logged to `logs/dispatch.jsonl`.

Alert levels: `0` nothing active, `1` SOS pressed and tracking, `2` threat confirmed.
A session ends after 300 s without packets.

---

## 3. What is in the folder

```
sos/
├── cloud/                    the server, in the order data flows through it
│   ├── config.py             every setting; all read from environment variables
│   ├── payload.py            decode the 21-byte packet
│   ├── geo.py                MockLocator, LocalDbLocator (our database), UnwiredLocator, ChainLocator
│   ├── kinematics.py         Haversine, smoothing, speed and acceleration features
│   ├── threat.py             loads model.keras; RuleModel dev fallback if it is missing
│   ├── engine.py             per-device tracker: windows, gap fill, gate, latch
│   ├── notify.py             contact dispatch (Telegram, optional Twilio SMS) + dispatch log
│   ├── server.py             MQTT client; ties the above together; writes results.jsonl
│   └── simlib.py             mock router database + trajectory generator (tests, simulator)
├── dashboard/
│   └── app.py                Flask app: login, contacts, live map, 112 card, dispatch log
├── firmware/wokwi/
│   ├── sketch.ino            ESP32-S3 firmware (Wi-Fi/MQTT in Wokwi; A7670C AT path for hardware)
│   ├── diagram.json          Wokwi wiring: button on GPIO4
│   └── libraries.txt         PubSubClient
├── tools/
│   ├── test_pipeline.py      9 offline tests (decode, latch, gate, notifier, server path)
│   ├── test_dashboard.py     dashboard test (auth wall, CSRF, contacts, 112 pinned, feed)
│   ├── simulate_device.py    publishes a scripted trip (stationary / foot / vehicle) to MQTT
│   ├── wokwi_aps.py          prints a FAKE[] router table that the mock database recognises
│   ├── wifi_db.py            builds/imports our own Wi-Fi location database (synthetic or WiGLE wardriving)
│   ├── demo_offline.py       runs all three scenarios in-process, no network
│   └── make_dummy_model.py   stand-in LSTM for tests; never ship it
├── data/contacts.json        saved contacts (created by the dashboard)
├── logs/                     results.jsonl (every server result), dispatch.jsonl (every alert sent)
├── model.keras               our trained LSTM (input 5x2, 5,059 parameters)
├── mock_routers.json         generated by the command in section 5
├── wifi_db.sqlite            our Wi-Fi location database, built by tools/wifi_db.py (GEO_MODE=local)
├── .env.example              template for .env
└── requirements.txt
```

**Why `model.keras` has two inputs.** The Colab notebook trains on (speed, acceleration) windows of 5 steps, so the server feeds exactly that. Acceleration is the *change in speed per step* (`np.diff`), not m/s², to match training. If your notebook ever divides by the time gap, set `ACC_PER_STEP=0`.

**Why the class order matters.** Labels are `0 stationary, 1 foot_escape, 2 vehicle_kidnap`. The confusion matrix in Colab lists columns alphabetically because `crosstab` sorts them; that is display order, not label order.

---

## 4. First-time setup (Windows, PowerShell, VS Code)

Python 3.10–3.12 (TensorFlow does not support newer versions).

```
cd sos
python -m venv ..\run_environment        # skip if you already have one
..\run_environment\Scripts\Activate.ps1
pip install -r requirements.txt
python -m tools.test_pipeline            # expect 9 PASS lines
python -m tools.test_dashboard           # expect PASS dashboard
```

**Get the model out of Colab.** Add this cell at the bottom of the notebook, after "LSTM trained on real train-users":

```python
lstm_real.save("model.keras")
from google.colab import files
files.download("model.keras")
print(lstm_real.input_shape)      # must print (None, 5, 2)
```

Put `model.keras` in `sos/`, next to `README.md`. Check it loads:
`python -c "import tensorflow as tf; print(tf.keras.models.load_model('model.keras').input_shape)"`
If loading fails with a version error, install the TensorFlow version Colab printed.

---

## 5. Running the demo

Each terminal needs the venv active **and** its own copy of the settings. Use this loader every time you open a new terminal (it trims stray spaces, which once cost us an hour):

```
Get-Content .env | Where-Object {$_ -match '^\w+='} | ForEach-Object { $k,$v = $_ -split '=',2; Set-Item "env:$k" $v.Trim() }
```

### `.env` (lives in `sos/`, same folder as `cloud/`)

```
HIVEMQ_HOST=broker.emqx.io
HIVEMQ_PORT=1883
HIVEMQ_TLS=0
UPLINK_TOPIC=sos/w01-k7f3/uplink
GEO_MODE=mock
MODEL_PATH=model.keras
TELEGRAM_TOKEN=<from BotFather>
TELEGRAM_CHAT_ID=<your chat id>
```

No spaces around `=`, no comments. The topic must match `DEVICE_ID` in the sketch (`"w01-k7f3"` gives `sos/w01-k7f3/uplink`).

### Loader Line
```
Get-Content .env | Where-Object {$_ -match '^\w+='} | ForEach-Object { $k,$v = $_ -split '=',2; Set-Item "env:$k" $v.Trim() }
```

### Terminal 1 — server

```
<loader line>
python -c "import json;from cloud.simlib import build_routers;json.dump(build_routers(),open('mock_routers.json','w'))"
python -m cloud.server
```
Wait for `[mqtt] connected: Success`. Leave it running.

### Terminal 2 — dashboard

```
<loader line>
$env:DASH_USER="admin"; $env:DASH_PASS="choose-a-password"
python -m dashboard.app
```
Open http://localhost:5000 and sign in. Add yourself as a contact (name, phone with country code, Telegram chat id) and press **Send test alert**. Your phone should buzz and the dispatch log should show a green "sent".

### Terminal 3 — motion demo

```
<loader line>
python -m tools.simulate_device --scenario vehicle --period 10 --device w01-k7f3
```
After about 60 s the banner flashes red, the map shows a trail, the 112 card appears, and Telegram gets "SOS pressed" then "THREAT CONFIRMED". Run `--scenario stationary` afterwards: it must never reach level 2.
Keep `--period 10`. The server stamps packets with real time, so a faster period gives wrong speeds.

### Wokwi (device half)

1. New ESP32-S3 project on wokwi.com; paste `sketch.ino`, `diagram.json`, `libraries.txt`. Keep the Wokwi tab in front — a background tab pauses the simulation.
2. Run `python -m tools.wokwi_aps --lat 12.9716 --lon 77.5946` and paste the printed `const AP FAKE[3] = ...` line over the one in the sketch. These are mock-database routers, so Wokwi packets land on the map.
3. In the sketch, the scan fill loop should read `for (int i = 0; i < 3; i++) out[i] = FAKE[i];` so all three slots hold mock routers (Wokwi's own network is not in the database).
4. Press play, click the red button. The serial monitor shows `mqtt: connected state=0`, then `up=1 sent=1` about every 10 s.

---

## 6. Settings reference

| Variable | Default | What it does |
|---|---|---|
| `HIVEMQ_HOST`, `HIVEMQ_PORT` | – / 8883 | MQTT broker address |
| `HIVEMQ_TLS` | 1 | `0` for a plain broker such as `broker.emqx.io:1883` |
| `HIVEMQ_USER`, `HIVEMQ_PASS` | empty | Broker login; leave empty for a public broker |
| `UPLINK_TOPIC` | `sos/+/uplink` | Exact device topic. On a public broker never use the wildcard |
| `MQTT_CLIENT_ID` | random | Must be unique per broker |
| `GEO_MODE` | `unwired` | `mock` or `unwired` |
| `UNWIRED_TOKEN`, `UNWIRED_URL` | – | Unwired Labs API (free plan has a small daily quota) |
| `MODEL_PATH`, `SCALER_PATH` | `model.keras`, none | Trained LSTM; scaler only if you scaled features |
| `CLASS_NAMES` | `stationary,foot_escape,vehicle_kidnap` | Must match training label order |
| `SMOOTH` | 3 | Trailing-mean length; `1` turns smoothing off |
| `LATCH` | 2 | Consecutive threat windows before a red alert |
| `ACC_GATE` | 1.5 | Gate factor against position error; `0` disables |
| `ACC_PER_STEP` | 1 | Acceleration as speed change per step (matches the notebook) |
| `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` | – | Bot token and default chat |
| `NOTIFY_UPDATE_S` | 60 | Location update interval after the first alert |
| `TWILIO_SID/TOKEN/FROM` | – | Optional SMS (trial accounts reach verified numbers only) |
| `DASH_USER`, `DASH_PASS` | `admin`, random | Dashboard login; a random password is printed if unset |

Fixed in code (`cloud/config.py`): 10 s fix interval, 3 s bounce guard, 5-step window, 6 dead-reckoning fixes, 300 s session timeout.

---

## 7. The dashboard

- **Login** with one admin account; five wrong passwords lock that address for five minutes; forms carry a CSRF token.
- **Banner:** grey idle, amber "SOS pressed", flashing red "THREAT CONFIRMED".
- **Map:** trail coloured by alert level, a circle for the reported position error, auto-follows during a red alert. Needs internet for the map tiles.
- **Stats:** speed, class, fix source, position error.
- **Contacts:** add or remove from the browser. The server reads them fresh on every alert, so no restart is needed. Telegram contacts must message the bot first.
- **Emergency 112 card:** pinned and cannot be deleted. It shows a call button and a ready message with the live map link. **It never calls or messages 112 by itself — a person decides.** A false alarm from a student project should not tie up emergency services.
- **Dispatch log:** who was alerted, on which channel, and whether it worked (with the reason when it did not).

Telegram setup in short: @BotFather → `/newbot` → copy the token → message your bot → open `https://api.telegram.org/bot<TOKEN>/getUpdates` → copy the number after `"chat":{"id":`.

---

## 8. Tests and what they prove

`python -m tools.test_pipeline` (9 tests): payload round-trip; a vehicle trip latches after two windows; a stationary wearer never goes red; dead-zone filling stops at its cap; unmatched routers fall back to dead reckoning; button-bounce packets are ignored; Wi-Fi jitter inside the reported error stays at level 1; the notifier sends press / threat / update in order; a raw MQTT message flows through `server.on_message`.
`python -m tools.test_dashboard`: login wall, CSRF, contact add and delete, 112 cannot be removed, the live feed reports level 2.

Also run once through a real local MQTT broker (simulator → server → LSTM → red alert), and on your machine through the public EMQX broker with Wokwi and Telegram.

---

## 9. What is hardcoded and what isn’t

Hardcoded, meaning synthetic input:

The trip in simlib.py. The vehicle moves in a straight line east at a constant 11 m/s from a fixed point in Bengaluru.
The router positions, which are a fake grid of routers around that point, saved in mock_routers.json. That is why the fix source says mock.
Wokwi, which pads its scan with 3 fixed fake addresses. It always reports the same spot, so on its own it only produces “stationary”.

Not hardcoded, meaning real processing:

Decoding the payload, the position lookup, the speed and acceleration maths, the LSTM, the gate, the latch, the banner and the Telegram alerts.


To show it isn’t faked:

Run `python -m tools.simulate_device --scenario foot --device w01-k7f3` with the server running. The class changes to foot escape. Then run --scenario stationary and the banner never turns red. 

---
