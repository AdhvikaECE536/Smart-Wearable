"""Offline simulation helpers (router lattice + device scans). Used by demo/tests/simulate_device."""
import math, random
from .kinematics import offset_m, haversine_m

ORIGIN = (12.9716, 77.5946)  # Bengaluru

def build_routers(n_east=120, n_north=12, spacing_m=30.0, seed=7):
    rnd, routers = random.Random(seed), {}
    for i in range(n_east):
        for j in range(n_north):
            lat, lon = offset_m(ORIGIN[0], ORIGIN[1], (j - n_north / 2) * spacing_m + rnd.uniform(-8, 8),
                                i * spacing_m + rnd.uniform(-8, 8))
            mac = "02:00:%02x:%02x:%02x:%02x" % (i >> 8, i & 255, j, rnd.randrange(256))
            routers[mac] = [lat, lon]
    return routers

def trajectory(kind, steps=14, dt=10.0, seed=3):
    """Returns [(lat, lon)] every dt seconds. kind: stationary | foot | vehicle"""
    rnd = random.Random(seed)
    speed = {"stationary": 0.0, "foot": 2.2, "vehicle": 11.0}[kind]
    out, e = [], 100.0
    for _ in range(steps):
        out.append(offset_m(ORIGIN[0], ORIGIN[1], rnd.uniform(-2, 2) if kind == "stationary" else 0.0, e))
        e += speed * dt
    return out

def scan(routers, pos, rnd, noise_db=1.5):
    """Top-3 strongest routers under a log-distance path-loss model."""
    res = []
    for mac, (la, lo) in routers.items():
        d = haversine_m(pos[0], pos[1], la, lo)
        if d < 120:
            res.append({"bssid": mac, "rssi": int(round(-40 - 20 * math.log10(max(d, 1)) + rnd.gauss(0, noise_db)))})
    return sorted(res, key=lambda a: -a["rssi"])[:3]
