"""Print a FAKE[3] table for sketch.ino whose BSSIDs exist in the mock router DB near a point,
so Wokwi packets resolve to that place when the server runs with GEO_MODE=mock.
   python -m tools.wokwi_aps --lat 12.9716 --lon 77.5946"""
import argparse
from cloud.simlib import build_routers
from cloud.kinematics import haversine_m
ap = argparse.ArgumentParser(); ap.add_argument("--lat", type=float, default=12.9716); ap.add_argument("--lon", type=float, default=77.5946)
a = ap.parse_args()
near = sorted(build_routers().items(), key=lambda kv: haversine_m(a.lat, a.lon, *kv[1]))[:3]
rssi = [-48, -61, -72]
rows = ", ".join("{{" + ",".join("0x" + b for b in mac.split(":")) + "}, %d}" % r for (mac, _), r in zip(near, rssi))
print(f"const AP FAKE[3] = {{ {rows} }};")
print("# nearest routers:", [(m, round(haversine_m(a.lat, a.lon, *p))) for m, p in near])
