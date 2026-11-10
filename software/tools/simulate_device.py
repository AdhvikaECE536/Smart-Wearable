"""Pretend to be the wearable: publishes a scenario to HiveMQ using the mock router DB.
Run the server with GEO_MODE=mock MOCK_ROUTERS=mock_routers.json.
   python -m tools.simulate_device --scenario vehicle --period 10     (use --period 1 for a fast demo)"""
import argparse, json, os, random, ssl, time
import paho.mqtt.client as mqtt
from cloud.payload import encode
from cloud.simlib import build_routers, trajectory, scan

ap = argparse.ArgumentParser()
ap.add_argument("--scenario", choices=["stationary", "foot", "vehicle"], default="vehicle")
ap.add_argument("--period", type=float, default=10.0)
ap.add_argument("--device", default="w01")
a = ap.parse_args()
if a.period < 8:
    print(f"NOTE: --period {a.period} is faster than the real 10 s. Start the server with REPLAY_SPEED={10 / a.period:g} or speeds will look {10 / a.period:g}x too high (a walker will look like a car).")
routers = build_routers()
json.dump(routers, open("mock_routers.json", "w"))
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sim-" + a.device)
if os.environ.get("HIVEMQ_USER"):
    c.username_pw_set(os.environ["HIVEMQ_USER"], os.environ.get("HIVEMQ_PASS", ""))
if os.environ.get("HIVEMQ_TLS", "1") == "1":
    c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
c.connect(os.environ["HIVEMQ_HOST"], int(os.environ.get("HIVEMQ_PORT", "8883")), 60); c.loop_start()
rnd = random.Random(1)
for pos in trajectory(a.scenario, steps=16):
    hexs = encode(scan(routers, pos, rnd))
    c.publish(f"sos/{a.device}/uplink", hexs, qos=1).wait_for_publish()
    print("sent", hexs); time.sleep(a.period)
