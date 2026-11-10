# SOS Wearable — Software Side

**Stand-Alone Wearable Safety Device with Hybrid Location Triangulation & Cloud Alerting**
Team TID70 · 23ECE381 Open Lab I · Amrita Vishwa Vidyapeetham · Guide: Dr. Harshit Srivastava
Last updated: 10 Nov 2026

This file takes you from "I just downloaded the zip from GitHub" to a working demo, and explains what every part does and why we built it that way. Read section 1 first. Do sections 2–4 in order. The rest is reference.

---

## Contents

1. [What this is, and where it stands](#1-what-this-is-and-where-it-stands)
2. [What you need installed](#2-what-you-need-installed)
3. [Get the code and set it up](#3-get-the-code-and-set-it-up)
4. [Run the demo](#4-run-the-demo)
5. [How it works, in plain English](#5-how-it-works-in-plain-english)
6. [What every file does](#6-what-every-file-does)
7. [Settings (`.env`)](#7-settings-env)
8. [Reading the output](#8-reading-the-output)
9. [The dashboard and Telegram](#9-the-dashboard-and-telegram)
10. [The Wi-Fi location database](#10-the-wi-fi-location-database)
11. [The model (LSTM)](#11-the-model-lstm)
12. [The firmware and Wokwi](#12-the-firmware-and-wokwi)
13. [Tests](#13-tests)
14. [Security and privacy](#14-security-and-privacy)
15. [Troubleshooting](#15-troubleshooting)
16. [How we got here](#16-how-we-got-here)
17. [Limits and what is left](#17-limits-and-what-is-left)
18. [Command cheat sheet](#18-command-cheat-sheet)

---

## 1. What this is, and where it stands

**The software side works end to end.** A simulated wearable presses SOS and sends a 21-byte Wi-Fi fingerprint over MQTT. A cloud server turns the fingerprint into a position, then a speed, then asks an LSTM whether the person is standing, running, or in a vehicle. A confirmed threat turns the dashboard red and sends a Telegram message with a map link to the saved contacts.

| Part | Status |
|---|---|
| MQTT transport, server, dashboard, Telegram alerts | Real. Tested on our machines. |
| Trained LSTM (`model.keras`) | Real. 73.9% accuracy on people it never saw. |
| The wearable | **Simulated** in Wokwi. No hardware yet. |
| Wi-Fi router database | **Synthetic** until we wardrive real routes (section 10). |
| Motion scenarios | **Generated**, not walked. |
| Cellular modem path (SIMCom A7670C) | Written, never run on a modem. |

What the numbers mean in plain English:

- **73.9% on unseen people** — it gets about three windows in four right.
- **224 of 297 vehicle windows caught** — about one vehicle window in four is missed. For a safety device that is the costly error.
- **About 60 s from SOS to red alert** — the model needs five steps of history, then two confirmed windows. It is not instant.
- **One packet every 10 s** — one location fix per ten seconds while SOS is active.

**Fastest path to seeing it work (about 15 minutes):** do section 3, then 4.1 (offline demo, no accounts) and 4.2 (full demo).

---

## 2. What you need installed

| Tool | Why | Notes |
|---|---|---|
| **Python 3.10, 3.11 or 3.12** | Runs everything | TensorFlow does not support newer versions. Check with `python --version`. |
| **VS Code** | Editor and terminal | Install the "Python" extension. |
| **A browser** | Wokwi, dashboard, MQTTX | Chrome or Edge. |
| **Telegram** on your phone | Receives the alerts | Optional but part of the demo. |
| **Git** | Only if you prefer `git clone` | The zip download works without it. |
| **A Google account** | Colab, to retrain or re-export the model | Only needed to change the model. |

Free accounts, no card: **Wokwi** (wokwi.com, to save the simulation) and optionally the **WiGLE** Android app for wardriving.

These instructions use **Windows PowerShell inside VS Code**. On Mac or Linux the commands are the same, except for activating the virtual environment and loading `.env` (see 4.0).

---

## 3. Get the code and set it up

### 3.1 Download from GitHub

**Zip:** open the repository page → green **Code** button → **Download ZIP** → right-click the file → **Extract All**.
**Git:** `git clone <repository-url>`

Open the extracted folder in VS Code (**File → Open Folder**). The **project folder** is the one that contains `cloud`, `dashboard`, `tools` and `README.md`. If you see another folder with the same name inside, open that one. Every command below runs from the project folder.


### 3.2 Create the virtual environment and install

Open a terminal in VS Code (**Terminal → New Terminal**). It should say `PowerShell` and end in the project folder.

```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell refuses to run the activate script ("running scripts is disabled"), run this once, then activate again:
```
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```
When it worked, the prompt starts with `(.venv)`. **Every new terminal needs the venv activated.** The install takes a few minutes because TensorFlow is large.

### 3.3 Check that the install is sound

```
python -m tools.test_pipeline
python -m tools.test_dashboard
```
You want **11 `PASS` lines**, then `PASS dashboard`. If any line fails, stop and fix that first (section 15).

### 3.4 The model file

The repository should include `model.keras`, our trained LSTM (input shape 5×2, 5,059 parameters). Check it loads:

```
python -c "import tensorflow as tf; print(tf.keras.models.load_model('model.keras').input_shape)"
```
It must print `(None, 5, 2)`.

If the file is missing, the server prints `using RuleModel fallback` and uses a crude speed-threshold rule instead. That is fine for a smoke test and **wrong for any result you report**. To make the file yourself, see section 11.3.

### 3.5 Create your `.env`

Copy `.env.example` to `.env` in the project folder (same folder as `cloud`). In PowerShell: `copy .env.example .env`. Open `.env` and change the topic to something unique to you:

```
UPLINK_TOPIC=sos/w01-abcd/uplink
```
Use your own letters instead of `abcd`. The middle part (`w01-abcd`) is the **device id**. It must match `DEVICE_ID` in the Wokwi sketch and the `--device` flag of the simulator. Section 7 explains every setting.

---

## 4. Run the demo

### 4.0 One thing to know about terminals

Every terminal is separate. A setting loaded in one terminal does not exist in another. So **every new terminal** needs two things: the venv activated, and `.env` loaded. Load `.env` with this line (it also trims stray spaces, which once cost us an hour):

```
Get-Content .env | Where-Object {$_ -match '^\w+='} | ForEach-Object { $k,$v = $_ -split '=',2; Set-Item "env:$k" $v.Trim() }
```
We call this **the loader** below. On Mac/Linux use `set -a; source .env; set +a`.

### 4.1 Offline demo (no accounts, no network)

```
python -m tools.demo_offline
```
It runs three scripted trips through the whole pipeline in one process: a person standing still (never red), a person on foot, and a vehicle (both go red). It uses the stand-in model if `model.keras` is missing.

### 4.2 Full demo with three terminals

**Prepare once.** Build the router database for the simulator (section 10 explains it):
```
python -m tools.wifi_db synthetic --n 100000
```

**Terminal 1 — the server** (venv active, then the loader):
```
python -m cloud.server
```
Wait for `[mqtt] connected: Success`. Leave it running.

**Terminal 2 — the dashboard** (venv active, then the loader):
```
$env:DASH_USER="admin"; $env:DASH_PASS="choose-a-password"
python -m dashboard.app
```
Open http://localhost:5000 and sign in. If you skip `DASH_PASS`, a one-time password is printed in the terminal.

**Terminal 3 — the simulated wearable** (venv active, then the loader):
```
python -m tools.simulate_device --scenario vehicle --period 10 --device w01-abcd
```
Use your own device id. After about 60 seconds the dashboard banner flashes red, the map shows a trail, the 112 card appears, and Telegram (if set up) gets "SOS pressed" and then "THREAT CONFIRMED". Then try `--scenario foot` and `--scenario stationary`. **Stationary must never turn red.**

The three scenarios are `stationary`, `foot` (about 2 m/s) and `vehicle` (about 11 m/s).

### 4.3 The fast version for demos (`REPLAY_SPEED`)

`--period 10` is real time, so a trip takes about 2 minutes. To run faster, make the server count faster too. In the **server** terminal, set the speed before starting it:

```
$env:REPLAY_SPEED="10"
python -m cloud.server
```
Then run the simulator with `--period 1`. The server counts each second as ten, so a walker still looks like a walker. **Never** run the simulator at a faster period without a matching `REPLAY_SPEED`: the server uses real time, so a walker would look like a car. (That was a real bug of ours; the simulator now warns you.) Do not put `REPLAY_SPEED` in `.env`, or real Wokwi packets would look ten times too fast. After a run, wait about 30 real seconds before the next one, or the second trip joins the first session.

### 4.4 Wokwi, the device half

Wokwi shows the device side: the button, the Wi-Fi scan, the packet, the publish. See section 12 for the full steps. In short: new ESP32-S3 project → paste the three files from `firmware/wokwi/` → set `DEVICE_ID` to your device id → press play → click the red button. **Keep the Wokwi tab in front.** A background tab pauses the simulation.

### 4.5 Watch the messages arrive (MQTTX)

Open the MQTTX web client (mqttx.app/web-client) and connect with: host `broker.emqx.io`, port `8084`, path `/mqtt`, protocol `wss://`, SSL/TLS **off**, no username or password. Subscribe to your exact topic (`sos/w01-abcd/uplink`). You should see a 42-character hex string about every 10 seconds while the device or simulator runs. This proves a packet reached the broker, which separates "the device is silent" from "the server is silent".

---

## 5. How it works, in plain English

### 5.1 The idea

A safety app fails when the phone is on a desk, charging, or out of reach. So the safety device is a wearable (a scrunchie, bracelet or pendant) with its own cellular link and **one button**. We chose a physical button because every trigger in the papers we reviewed (pressure sensors, EEG, heart rate, voice) produced false alarms.

GPS drains the battery and fails indoors. So the device does not carry a GPS chip. It listens for the **Wi-Fi routers around it** and sends the names (BSSIDs) and signal strengths of the three strongest. The cloud looks those routers up in a database to find where they are, and that is where the person is.

Our first review showed that LoRaWAN coverage in India is too thin to rely on, so the uplink is **cellular (SIMCom A7670C) over MQTT**. In the simulation, Wokwi uses its own Wi-Fi instead.

### 5.2 The data flow

```
 WEARABLE (Wokwi sim)              CLOUD (our laptop)                         PEOPLE
┌────────────────────┐  MQTT   ┌─────────────────────────────────┐
│ button on GPIO4    │ broker  │ cloud/server.py                 │      ┌───────────────┐
│ scan Wi-Fi, top 3  │ ──────► │  1 decode the 21-byte packet    │ ───► │ Telegram to   │
│ pack 21 bytes      │ (EMQX)  │  2 find position (database)     │      │ saved contacts│
│ publish every 10 s │         │  3 smooth, fill short gaps      │      └───────────────┘
└────────────────────┘         │  4 speed + acceleration         │      ┌───────────────┐
                               │  5 LSTM: 5 steps x 2 numbers    │ ───► │ Dashboard     │
                               │  6 accuracy gate                │      │ login, map,   │
                               │  7 two-window latch             │      │ contacts, 112 │
                               └─────────────────────────────────┘      └───────────────┘
                                  writes logs/results.jsonl ─────────────────► (dashboard reads it)
```

### 5.3 A packet, byte by byte

Every packet is 21 bytes, sent as 42 hexadecimal characters: three access points, each **6 bytes of BSSID plus 1 byte of signal strength**. The signal byte holds the strength with its minus sign dropped, so `0x3f` (63) means -63 dBm.

A real packet from our simulator:

```
02 00 00 03 06 22 3f   02 00 00 04 06 0d 42   02 00 00 03 05 f6 46
└── BSSID 1 ─────┘└sig┘ └── BSSID 2 ─────┘└sig┘ └── BSSID 3 ─────┘└sig┘
```
decodes to:

| Router | BSSID | Signal |
|---|---|---|
| 1 | `02:00:00:03:06:22` | -63 dBm |
| 2 | `02:00:00:04:06:0d` | -66 dBm |
| 3 | `02:00:00:03:05:f6` | -70 dBm |

The code for this is `cloud/payload.py` (server) and `buildPayloadHex()` in the sketch (device).

### 5.4 What the server does with each packet

1. **Decode** the hex into up to three (BSSID, signal) pairs.
2. **Find the position.** Look up each BSSID in the database. The position is the average of the routers' locations, where stronger signals count for more (a stronger signal means the router is closer). The position comes with an error estimate, never smaller than 20 m. At least two known routers are needed.
3. **Fill gaps.** If no packet arrives for 15 seconds, the server repeats the last position, carrying the last speed forward, for up to 6 missed fixes. It then stops guessing. This is **dead reckoning**.
4. **Smooth** the track with a 3-point trailing average, to take the jitter out.
5. **Compute the features.** Speed is the distance between two consecutive fixes divided by the time between them (using the **Haversine** formula, which measures distance on a sphere). Acceleration is the *change in speed from one step to the next*.
6. **Classify.** The last 5 steps (5 × 2 numbers) go into the LSTM. It returns three probabilities: stationary, foot escape, vehicle kidnap.
7. **Accuracy gate.** If the person moved less than 1.5 times the worst position error over the window, the threat class is ignored. Wi-Fi positions wobble by tens of metres, and without this rule a person standing still looks like they are running. (We measured it: with the gate off, 11 of 60 standing-still trips ended in a false red alert. With it on, 0 of 60.)
8. **Latch.** A red alert needs **two consecutive** threat windows. One bad window cannot trigger it.
9. **Notify.** First fix: "SOS pressed" with a map link. At the latch: "THREAT CONFIRMED". Then a location update every 60 seconds. Every attempt is written to `logs/dispatch.jsonl`.

A **session** starts at the first packet and ends after 300 seconds of silence.

### 5.5 Alert levels

| Level | Meaning | Dashboard |
|---|---|---|
| 0 | Nothing active | Grey banner |
| 1 | SOS pressed, tracking | Amber banner |
| 2 | Threat confirmed (two windows) | Flashing red banner, 112 card |

### 5.6 Words you will meet

- **BSSID** — the unique hardware address of a Wi-Fi router, like `02:00:00:03:06:22`.
- **RSSI** — received signal strength in dBm. Closer to zero is stronger (-40 is strong, -90 is weak).
- **MQTT** — a light messaging protocol. Devices *publish* to a *topic*; others *subscribe*. A *broker* sits in the middle.
- **Topic** — the address of a message stream, like `sos/w01-abcd/uplink`.
- **LSTM** — a neural network that reads a sequence (here, five steps of motion) rather than a single number.
- **Haversine** — the formula for distance between two latitude/longitude points.
- **Dead reckoning** — estimating where someone is from their last known position and speed.
- **QoS** — MQTT's delivery promise. The simulation publishes at QoS 0 (send and forget); use QoS 1 on the real modem so a lost packet is retried.

---

## 6. What every file does

```
project folder/
├── cloud/                      the server, in the order data flows through it
├── dashboard/                  the web console
├── firmware/wokwi/             the wearable's code, plus its Wokwi wiring
├── tools/                      simulator, database builder, tests
├── data/                       contacts.json (created by the dashboard)
├── logs/                       results.jsonl and dispatch.jsonl (created when running)
├── model.keras                 the trained LSTM
├── .env.example                template for your settings
├── .gitignore                  keeps secrets and generated files out of git
├── requirements.txt            Python packages
└── README.md                   this file
```

### `cloud/` — the server

| File | What it does and why |
|---|---|
| `config.py` | Every setting in one place, all read from environment variables so no secret lives in code. Also holds the fixed numbers: 10 s fix interval, 3 s bounce guard, 5-step window, 6 dead-reckoning fixes, 300 s session timeout. |
| `payload.py` | `encode()` and `decode()` for the 21-byte packet. Accepts either raw bytes or the 42-character hex text, because the firmware sends text. |
| `geo.py` | Turns routers into a position. `MockLocator` (the simulator's routers), `LocalDbLocator` (our SQLite database), `UnwiredLocator` (the Unwired Labs web API, kept as a backup that did not work for us), and `ChainLocator` (try one after another). Every fix carries an error estimate. |
| `kinematics.py` | The maths: Haversine distance, bearing, smoothing, and `features()`, which turns a track of fixes into speed and acceleration. |
| `threat.py` | `KerasModel` loads `model.keras` and returns three probabilities. `RuleModel` is a crude fallback used only when the file is missing. |
| `engine.py` | `DeviceTracker`, one per wearable. It owns the history, fills gaps, applies the accuracy gate, runs the model and holds the two-window latch. The heart of the server. |
| `notify.py` | `Notifier`. Reads the saved contacts, sends Telegram (and optional Twilio SMS), and logs every attempt. It sends to **personal** contacts only and never to the 112 entry. |
| `server.py` | Connects to the MQTT broker, feeds each packet to the right tracker, writes `results.jsonl`, runs a watchdog thread for missing packets, and triggers notifications. |
| `simlib.py` | The mock world: a grid of 1,440 routers around Bengaluru, scripted trips, and a Wi-Fi scan simulator with realistic noise. Used by the tests and the simulator. |

### `dashboard/`

| File | What it does and why |
|---|---|
| `app.py` | A Flask web app: login, contacts, live map, banner, 112 card, dispatch log. It reads `logs/results.jsonl` and `data/contacts.json`, so it does not need to talk to the server. The whole page is inside this one file. |

### `firmware/wokwi/`

| File | What it does |
|---|---|
| `sketch.ino` | The wearable's program (section 12). |
| `diagram.json` | Wokwi's wiring file: an ESP32-S3 and a push button on GPIO4. |
| `libraries.txt` | Tells Wokwi to install the `PubSubClient` MQTT library. |

### `tools/`

| File | What it does |
|---|---|
| `simulate_device.py` | Pretends to be the wearable: scans, packs and publishes a scripted trip to MQTT. Flags: `--scenario`, `--period`, `--device`. |
| `wifi_db.py` | Builds or imports our Wi-Fi location database (section 10). |
| `wokwi_aps.py` | Prints a `FAKE[3]` table for the sketch, using routers the mock database knows. |
| `demo_offline.py` | Runs all three scenarios in one process, no network. |
| `test_pipeline.py` | 11 tests of the server logic (section 13). |
| `test_dashboard.py` | Tests of the dashboard's login, contacts and feed. |
| `make_dummy_model.py` | Builds a stand-in LSTM for tests. **Never use it for results.** |

### Files you create while running

| File | Created by | Notes |
|---|---|---|
| `.env` | you, from `.env.example` | Holds secrets. Never commit or share it. |
| `wifi_db.sqlite` | `tools.wifi_db` | Router database. Rebuild any time. |
| `mock_routers.json` | `simulate_device` | The simulator's router list. Regenerates itself. |
| `logs/results.jsonl` | the server | One line per result. Delete to reset the dashboard's trail. |
| `logs/dispatch.jsonl` | the notifier | One line per alert attempt. |
| `data/contacts.json` | the dashboard | Your saved contacts. |

---

## 7. Settings (`.env`)

`.env` is a plain text file of `NAME=value` lines. Rules: **no spaces around `=`, and comments must be on their own line** (the loader would read an inline `# comment` as part of the value). Settings only take effect in a terminal where you ran the loader, and only for processes started afterwards. After editing `.env`, run the loader again and restart the server.

### A ready `.env` for development

```
HIVEMQ_HOST=broker.emqx.io
HIVEMQ_PORT=1883
HIVEMQ_TLS=0
UPLINK_TOPIC=sos/w01-abcd/uplink
GEO_MODE=local
WIFI_DB=wifi_db.sqlite
MODEL_PATH=model.keras
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=
```
(The variable names still say `HIVEMQ`. That is history: we started on HiveMQ Cloud. They work for any broker.)

### Full reference

| Variable | Default | What it does |
|---|---|---|
| `HIVEMQ_HOST`, `HIVEMQ_PORT` | – / 8883 | MQTT broker address. |
| `HIVEMQ_TLS` | 1 | `0` for a plain broker such as `broker.emqx.io:1883`. |
| `HIVEMQ_USER`, `HIVEMQ_PASS` | empty | Broker login. Leave empty for a public broker. |
| `UPLINK_TOPIC` | `sos/+/uplink` | The exact device topic. **On a public broker never use the wildcard.** |
| `MQTT_CLIENT_ID` | random | Must be unique on the broker, or two clients kick each other off. |
| `GEO_MODE` | `unwired` | `mock`, `local`, `unwired`, or `local+unwired` (database first, Unwired as backup). |
| `WIFI_DB`, `WIFI_MIN_APS` | `wifi_db.sqlite`, 2 | Our database and how many known routers a fix needs. |
| `WIFI_ACC_FLOOR_M` | 20 | A Wi-Fi fix is never reported as better than this many metres. |
| `UNWIRED_TOKEN`, `UNWIRED_URL` | – | Only if you use Unwired Labs. |
| `MODEL_PATH`, `SCALER_PATH` | `model.keras`, none | The trained LSTM. A scaler is only needed if features were scaled in training (ours were not). |
| `CLASS_NAMES` | `stationary,foot_escape,vehicle_kidnap` | Must match the training label order. |
| `SMOOTH` | 3 | Trailing-average length. `1` turns smoothing off. |
| `LATCH` | 2 | Consecutive threat windows before a red alert. |
| `ACC_GATE` | 1.5 | Accuracy-gate factor. `0` turns the gate off. |
| `ACC_PER_STEP` | 1 | Acceleration as speed change per step (matches the notebook). `0` gives m/s². |
| `REPLAY_SPEED` | 1 | Fast-demo multiplier (section 4.3). Set in the server terminal only. |
| `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` | – | The bot and the default chat. |
| `NOTIFY_UPDATE_S` | 60 | Seconds between location updates after the first alert. |
| `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_FROM` | – | Optional SMS. Trial accounts reach verified numbers only. |
| `DASH_USER`, `DASH_PASS` | `admin`, random | Dashboard login. Set in the dashboard terminal. |
| `TB_HOST`, `TB_TOKEN` | – | Optional ThingsBoard output. Without a token it is simply off. |

---

## 8. Reading the output

Each result in the server terminal looks like this:

```
[result] {'device': 'w01-abcd', 't': ..., 'n_aps': 3, 'sos': 1, 'lat': 12.97149, 'lon': 77.59455,
          'src': 'local', 'accuracy': 20.0, 'speed': 2.2, 'accel': 0.1,
          'class': 'foot_escape', 'prob': 0.9, 'gated': False, 'consec': 3, 'alert_level': 2}
```

| Field | Meaning |
|---|---|
| `device` | Which wearable (from the topic). |
| `n_aps` | How many routers were in the packet. `0` means the watchdog made this line because no packet arrived. |
| `sos` | 1 while an SOS session is active. |
| `lat`, `lon` | The position. |
| `src` | Where the position came from (list below). |
| `accuracy` | Estimated position error in metres. |
| `speed`, `accel` | In m/s and m/s per step. Empty until there are enough fixes. |
| `class`, `prob` | The model's answer and how sure it is. Empty until five steps of history exist. |
| `gated` | `True` if the accuracy gate overrode the model because the movement was inside the position error. |
| `consec` | How many windows in a row were a threat. |
| `alert_level` | 0, 1 or 2 (section 5.5). |

`src` values: `local` (our database), `mock` (the mock routers), `wifi` or `wifi-cache` (Unwired Labs), `dead-reckoning` (no known router; position extrapolated from the last speed), `hold` (no packet for 15 s and no speed to carry; last position repeated), `no-fix` (nothing to go on yet).

The first class appears after about 6 packets (about 60 seconds), because the model needs five steps of history.

---

## 9. The dashboard and Telegram

### 9.1 The dashboard

- **Login:** one admin account. Five wrong passwords lock that address for five minutes. Every form carries a CSRF token.
- **Banner:** grey when idle, amber on SOS, flashing red on a confirmed threat.
- **Map:** the trail is coloured by alert level, a circle shows the position error, and it follows the person during a red alert. The map tiles need internet in your browser.
- **Contacts:** add or remove them in the browser. The server reads the file fresh on every alert, so no restart is needed.
- **Emergency 112 card:** pinned and cannot be deleted. It shows a **Call 112** button and a ready-to-send message with the live map link. **The system never calls or messages 112 itself.** A person decides. A false alarm from a student project must not waste emergency resources.
- **Dispatch log:** who was alerted, on which channel, whether it worked, and the reason when it did not.

Run it from the project folder, because it looks for `logs/` and `data/` there. It listens on `127.0.0.1` only. Put HTTPS in front before exposing it on a network.

### 9.2 Telegram setup

1. In Telegram, message **@BotFather**, send `/newbot`, and follow the prompts. It gives you a **token**: ten digits, a colon, then 35 letters and symbols (46 characters).
2. Open your new bot in Telegram, press **Start**, and send any message like `hi`.
3. In a terminal, open the bot's update list (this builds the link so you do not mistype it):
   ```
   $t = Read-Host "Paste token"; Start-Process "https://api.telegram.org/bot$t/getUpdates"
   ```
   Look for `"chat":{"id":` followed by a number. That number is your **chat id**.
4. Put both in `.env`:
   ```
   TELEGRAM_TOKEN=<token>
   TELEGRAM_CHAT_ID=<chat id>
   ```
5. In the dashboard, add yourself as a contact with the same chat id, then press **Send test alert**. Your phone should buzz and the log should show a green "sent".

Every contact must press **Start** on the bot first, or Telegram refuses to deliver to them.
Check the token length with `$env:TELEGRAM_TOKEN.Length` after loading `.env`. It must print **46**. If it prints 47, a hidden character came along when you copied it. Paste it again with Ctrl+Shift+V.

---

## 10. The Wi-Fi location database

The server finds where the person is by looking up the routers in a database. The database is SQLite (one file, `wifi_db.sqlite`), built with `tools/wifi_db.py`, and used when `GEO_MODE=local`.

We built our own because the free public geolocation API (Unwired Labs) did not work for us, and a free API with a small quota is a weak base for a safety demo.

### 10.1 Synthetic (for the demo)

```
python -m tools.wifi_db synthetic --n 100000
python -m tools.wifi_db stats
```
This creates the simulator's own 1,440 routers plus 100,000 made-up ones across Bengaluru. **It is synthetic data.** It proves the pipeline works at scale. It proves nothing about real-world accuracy, and the report should say so.

### 10.2 Real (wardriving)

1. Install the free **WiGLE** app on an Android phone (the iPhone version is limited).
2. Walk or drive a route with the app logging. It records each router's BSSID, signal and your GPS position.
3. Export the CSV from the app and import it:
   ```
   python -m tools.wifi_db import-wigle my_walk.csv
   ```
Only Wi-Fi rows with a GPS error under 50 m are kept. Each router's position is the signal-weighted average of everything seen of it, and imports accumulate, so each extra walk makes the estimate sharper. A campus database built this way is honest, free and good enough for a demo on that campus.

You can also import a plain CSV with the columns `bssid,lat,lon` using `import-csv`.

### 10.3 Using it

Set `GEO_MODE=local` in `.env` and restart the server. Use `local+unwired` to try the database first and Unwired Labs as a backup. If the server prints `no-fix` rows, the database lacks at least two of the packet's routers.

`python -m tools.wifi_db sample --lat 12.9716 --lon 77.5946` prints a `FAKE[3]` table for the Wokwi sketch using routers from the database near that point, so Wokwi packets resolve to a real location.

---

## 11. The model (LSTM)

### 11.1 What it is

A small LSTM: 32 units, dropout 0.2, a 16-unit dense layer, then a 3-way softmax. **Input is 5 steps × 2 numbers** (speed and acceleration, 10 seconds apart). **Output is three probabilities**: 0 stationary, 1 foot escape, 2 vehicle kidnap.

### 11.2 How it was trained (Colab notebook)

1. The notebook downloads **GeoLife** (Microsoft Research, real GPS trips from 182 people in Beijing).
2. Walk and run trips become *foot escape*. Car, taxi and bus trips become *vehicle*. Stationary has no real data, so that class is synthetic.
3. Windows are built from 10-second GPS fixes. A window that crosses a gap of more than 20 seconds is dropped.
4. The split is **by person**, not by window (8 people train, 4 unseen people test), so a trip can never appear on both sides.
5. A model trained on synthetic data alone scored 61.1% on the unseen people. Training on real motion lifted that to **73.9%**.

### 11.3 Exporting the model

In Colab, add a cell at the bottom, after the one that prints "LSTM trained on real train-users":

```python
lstm_real.save("model.keras")
from google.colab import files
files.download("model.keras")
print(lstm_real.input_shape)      # must print (None, 5, 2)
import tensorflow as tf; print(tf.__version__)
```
Put the downloaded file in the project folder. If loading fails with a version error, install the TensorFlow version Colab printed: `pip install tensorflow==<version>`.

### 11.4 Rules that keep training and the server the same

A model only works if the server feeds it numbers made the same way as in training. Two rules:

- **Acceleration is the change in speed per step**, not metres per second squared. The notebook uses `np.diff`, so the server does too (`ACC_PER_STEP=1`).
- **Label order is stationary, foot escape, vehicle.** In the Colab results table, the columns look reordered (Foot Escape, Stationary, Vehicle). That is only because `crosstab` sorts columns alphabetically. The labels themselves are in the order above.

### 11.5 What it cannot do yet

- 73.9% comes from **one** split with four unseen people (545 windows). We have not cross-validated.
- About one vehicle window in four is not flagged.
- GeoLife is Beijing GPS data, much cleaner than our Wi-Fi positions. The accuracy gate protects against the noise, but a real foot escape can be suppressed when the position error is large (over roughly 50 m).
- Stationary has no real training data.
- Attention and genetic-algorithm tuning from our plan are not done.

---

## 12. The firmware and Wokwi

### 12.1 Running it in Wokwi

1. Go to wokwi.com and start a new **ESP32-S3** project.
2. Replace the contents of the three tabs with `sketch.ino`, `diagram.json` and `libraries.txt` from `firmware/wokwi/`.
3. In `sketch.ino`, set `DEVICE_ID` to your device id, for example `"w01-abcd"`. The topic is built from it: `sos/w01-abcd/uplink`.
4. In `transportUp()`, make the MQTT client id unique too, for example `"w01-abcd-dev"`. On a public broker two clients with the same id kick each other off.
5. Press play and click the red button. **Keep the tab in front.**
6. The serial monitor should show `SOS triggered`, `scan: 3 APs ...`, `wifi: connected`, `mqtt: connected state=0`, then a line every 10 seconds ending in `up=1 sent=1`.

If the line ends in `up=0 sent=0`, read the `mqtt: FAILED state=N` line above it: `-2` is a wrong host or no network, `4` or `5` is a refused login.

### 12.2 What the sketch does, step by step

1. **Wait** for the button on GPIO4 (a pull-up input: pressing it pulls the pin low).
2. **Scan Wi-Fi** and keep the three strongest routers. In Wokwi there is only one network (`Wokwi-GUEST`), so the sketch fills the three slots from a table of made-up routers, `FAKE[3]`, that the mock database knows.
3. **Pack** the three BSSIDs and signal bytes into 21 bytes, then into 42 hex characters.
4. **Connect and publish** to `sos/<device id>/uplink`.
5. **Repeat every 10 seconds** for 5 minutes. The next scan starts early, by the length of the last scan, so packets leave exactly 10 seconds apart. (We found that scheduling it the obvious way produced a second packet only 3 seconds after the first, which the server drops as button bounce.)

### 12.3 Two transports, one file

`#define USE_WOKWI_WIFI 1` publishes over Wi-Fi with PubSubClient (the simulation). `0` publishes through the **SIMCom A7670C** modem with AT commands (the real hardware, planned for January). `USE_DEEP_SLEEP 1` sleeps between presses and wakes on GPIO4 (also for hardware).

### 12.4 Not proven yet on hardware

- The AT-command path has never run on a modem.
- TLS certificate checking is switched off in the simulation. Pin the broker's certificate on hardware.
- The Wokwi scan takes 1.5–2 seconds, and Wokwi timing proves nothing about hardware. Our 0.4 s passive-scan target is unlikely as written: passive scanning needs roughly 100 ms or more per channel. Measure it on the real board and report the real number.
- Check the exact A7670C variant's LTE bands against Indian operators, the peak current of LTE bursts against a 150 mAh cell, and the room for the LTE antenna and the ESP32 antenna keep-out on a 25 × 25 mm board, **before** ordering the PCB.

---

## 13. Tests

```
python -m tools.test_pipeline     # 11 tests
python -m tools.test_dashboard    # 1 test script
```

`test_pipeline` checks: the packet round-trips; a vehicle trip latches after two windows; a stationary wearer never goes red; dead-zone filling stops at its cap; unmatched routers fall back to dead reckoning; button-bounce packets are ignored; Wi-Fi jitter inside the position error stays at level 1; the notifier sends press, then threat, then update in order; a raw MQTT message flows through the server; the local database imports a WiGLE file and locates from it; a walker stays a walker under `REPLAY_SPEED`.

`test_dashboard` checks: the login wall, CSRF protection, adding and deleting contacts, that 112 cannot be removed, and that the live feed reports level 2.

We also ran the whole chain through a real local MQTT broker (simulator → server → LSTM → red alert), and on our own machines through the public EMQX broker with Wokwi and Telegram.

Tests that pass on simulated data are a pipeline check, not a performance claim.

---

## 14. Security and privacy

- **Never commit or share `.env`.** It holds the Telegram token. The included `.gitignore` already excludes it. Check with `git status` before every commit.
- **Revoke the Telegram token after your demo or viva.** In Telegram: @BotFather → `/revoke` → choose the bot. Do the same if a token ever shows up in a screenshot, a chat or a notes file.
- **Public brokers are public.** Anyone can read or publish to a topic on `broker.emqx.io`. We use an unguessable device id and an exact topic, and send demo data only. **Never send real locations through a public broker.**
- **Keep phone numbers and tokens out of screenshots.**
- **The dashboard is single-admin and listens on localhost only.** Do not expose it without HTTPS.
- **112 is manual on purpose** (section 9.1).
- A wearable that reports where someone is raises real consent and misuse questions. The demo contacts must be people who agreed.

---

## 15. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `running scripts is disabled` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`, then activate again |
| `pip install` fails on tensorflow | Python is too new. Use 3.10–3.12 (`python --version`) |
| `No module named 'cloud'` | You are not in the project folder, or an `__init__.py` is missing in `cloud`, `dashboard` or `tools` |
| `Cannot find path '.env'` | `.env` is not in the project folder. `dir .env` to check |
| `using RuleModel fallback` | `model.keras` is missing or not in the folder you ran from |
| `NameError: secrets` or similar after pasting code | Missing `import` lines at the top of the file |
| `[mqtt] connected` never appears | Wrong `HIVEMQ_HOST`/`PORT`, or `HIVEMQ_TLS` does not match the port (1883 plain, 8883 TLS) |
| Server prints nothing after the button | Topic mismatch: compare `DEVICE_ID` in the sketch, `UPLINK_TOPIC` in `.env`, and `echo $env:UPLINK_TOPIC` |
| Only `src: hold` lines | No packets arriving: the Wokwi tab is in the background, or the broker dropped the connection. Check MQTTX |
| `no-fix` rows | The database lacks two of the packet's routers. Rebuild it (section 10) |
| Walker shows as `vehicle_kidnap` | Simulator ran faster than 10 s per packet without `REPLAY_SPEED`. Use `--period 10` or set `REPLAY_SPEED` |
| Red alert while standing still | Large position error. Look at `accuracy` and `gated`. Check the database |
| Wokwi `mqtt: FAILED state=-2` | Host typo or no network. Restart the simulation |
| Wokwi `state=4` or `5` | Refused login. Public brokers need no username or password |
| `no TELEGRAM_TOKEN` in the dispatch log | That terminal never loaded `.env`. Run the loader and restart the process |
| Telegram `404` page | The link is malformed: `https://api.telegram.org/bot<token>/getUpdates`, no angle brackets, no spaces |
| Telegram `Unauthorized` | Wrong or mangled token. Check its length is 46 |
| Telegram `chat not found` | Wrong chat id, or that person never pressed **Start** on the bot |
| Blank grey map | No internet for the map tiles |
| The dashboard shows an old trail | Delete `logs/results.jsonl` and refresh |

---

## 16. How we got here

| Step | What happened | What we decided |
|---|---|---|
| First review | LoRaWAN coverage in India is too thin | Move the uplink to cellular (A7670C) over MQTT |
| First zip from the AI assistant | The code ran offline but had never touched a real service | Kept the architecture; tested every path we could |
| Noise test | With a 10 m Wi-Fi error, a standing wearer raised a false red alert in 29 of 60 runs (stand-in model) | Added the accuracy gate |
| Alerts | A standing SOS press alerted nobody; nothing contacted anyone | Added `notify.py` with Telegram |
| Dashboard | We wanted login, contacts, 112 and a map | Built our own Flask app |
| Notebook parity | The server divided acceleration by the time gap; training did not | Switched to per-step acceleration |
| Label-order worry | The Colab table looked reordered | It was `crosstab`'s alphabetical columns |
| Wokwi | The Arduino IDE could not open the sketch as a project | Used Wokwi in the browser |
| Library error | `PubSubClient.h` not found | Added the library in Wokwi |
| HiveMQ login | `mqtt state=5` (refused) | Moved development to the public EMQX broker, added `HIVEMQ_TLS=0` |
| Public-broker risk | Anyone can read or inject; fixed client ids collide | Unique device id, exact topic, random server client id |
| Wokwi timing | The second packet came 3 s after the first and was dropped | The sketch now schedules scans so sends are 10 s apart |
| Packets stopped | The server showed only `hold` lines | Wokwi pauses in a background tab. Keep it in front |
| `.env` problems | The file was one folder too high; the token had a hidden character | Moved it; added `.Trim()` to the loader; check length 46 |
| Foot shown as vehicle | We ran the simulator at `--period 1`, so a 10 s step looked like 1 s | Added `REPLAY_SPEED`; the simulator warns |
| Standing false alarms | With the real model, 11 of 60 standing trips ended red | The locator now reports a position error, so the gate acts: 0 of 60 |
| Unwired Labs failing | A free API with a small quota and no control | Built our own Wi-Fi database and `GEO_MODE=local` |

---

## 17. Limits and what is left

**Limits, stated plainly:**

- **75% is a baseline.** One split, four unseen people. No cross-validation yet.
- **About one vehicle window in four is missed.**
- **Simulated results are friendlier than real ones.** On simulated trips with the real model, 60 of 60 standing, foot and vehicle runs classed correctly. Real Wi-Fi positions are noisier. This is a pipeline check, not a performance claim.
- **The router database is synthetic until we wardrive.** Wi-Fi positioning is also coarser than GPS: expect tens of metres.
- **The wearable is a simulation.** No hardware, no field test.
- **The cellular path is untested.**
- **"Removes false triggers" is too strong.** A deliberate button press reduces false triggers. The two-window latch adds a delay of about a minute.
- **BLE** appears in the original objectives but is not built.
- **Single-admin dashboard on localhost.**

**What is left:**

1. Rehearse the full demo once, start to finish.
2. Wardrive a short campus route, import it, and run `GEO_MODE=local` on real BSSIDs.
3. Update the slides and the report: the architecture is cellular, not LoRa; add the accuracy gate and the limits above.
4. Cross-validate the LSTM across users; attention and GA tuning if time allows.
5. **Phase 2 (January):** procurement and PCB, bring-up of the A7670C path, field data, and retraining on real Wi-Fi scans.

---

## 18. Command cheat sheet

Run from the project folder, venv active. Terminals 1–3 also need the loader first.

```
# one-time
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m tools.test_pipeline
python -m tools.test_dashboard
python -m tools.wifi_db synthetic --n 100000

# the loader (every new terminal)
Get-Content .env | Where-Object {$_ -match '^\w+='} | ForEach-Object { $k,$v = $_ -split '=',2; Set-Item "env:$k" $v.Trim() }

# terminal 1: server
python -m cloud.server

# terminal 2: dashboard
$env:DASH_USER="admin"; $env:DASH_PASS="choose-a-password"
python -m dashboard.app

# terminal 3: simulated wearable (real time)
python -m tools.simulate_device --scenario vehicle --period 10 --device w01-abcd

# fast demo: in the SERVER terminal before starting it
$env:REPLAY_SPEED="10"
# then in terminal 3
python -m tools.simulate_device --scenario foot --period 1 --device w01-abcd

# no accounts, no network
python -m tools.demo_offline
```

---

## References

1. M. R. Islam et al., "Machine learning-driven IoT device for women's safety: a real-time sexual harassment prevention system," *Multimedia Tools and Applications*, vol. 84, 2025.
2. K. S. Priya et al., "Blink talk: A machine learning-based method for women safety using EEG and eye blink signals," *Measurement: Sensors*, vol. 28, 2023.
3. N. R. Wagh et al., "Smart Security Solution for Women and Children Using Wearable IOT Systems," *Wireless Personal Communications*, vol. 138, 2024.
4. S. Umamaheswararao et al., "Smartguard an Intelligent Wearable for Women's Safety," *IEEE WAMS*, 2025.
5. A. Kiran et al., "Empowering Women: A Creative Approach to Integrated Safety with Machine Learning Algorithms," *IEEE IConSCEPT*, 2024.
6. Y. Zheng, X. Xie and W.-Y. Ma, "GeoLife: A collaborative social networking service among user, location and trajectory," *IEEE Data Eng. Bull.*, vol. 33, no. 2, 2010. Dataset: GeoLife GPS Trajectories 1.3, Microsoft Research.