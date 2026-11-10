"""No network, no keys: runs scenarios through the real engine. Run from project root:
   python -m tools.demo_offline [--model model.keras]"""
import argparse, random
from cloud import config as C
from cloud.engine import DeviceTracker
from cloud.geo import MockLocator
from cloud.payload import encode
from cloud.simlib import build_routers, trajectory, scan
from cloud.threat import load_model

def run(kind, model, verbose=True):
    routers = build_routers()
    tr, rnd, last = DeviceTracker("demo", MockLocator(routers), model), random.Random(1), None
    for i, pos in enumerate(trajectory(kind)):
        res = tr.on_uplink(encode(scan(routers, pos, rnd)), 1000.0 + i * C.FIX_INTERVAL_S)
        last = res
        if verbose:
            print(f"  t={i*10:3d}s src={res['src']:<5} speed={res['speed'] and round(res['speed'],1)} "
                  f"class={res['class']} consec={res['consec']} alert={res['alert_level']}")
    return last

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--model", default=C.MODEL_PATH); a = ap.parse_args()
    m = load_model(a.model, C.SCALER_PATH)
    for kind in ("stationary", "foot", "vehicle"):
        print(kind); r = run(kind, m)
        print("  ->", kind, "final alert_level", r["alert_level"], "\n")
