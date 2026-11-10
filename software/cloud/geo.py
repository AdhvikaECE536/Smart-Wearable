import json, math, os, sqlite3
from dataclasses import dataclass
import requests

@dataclass
class Fix:
    t: float
    lat: float
    lon: float
    src: str
    acc: float = 0.0

def _weighted_fix(pts, t, src):
    """pts: [((lat, lon), weight)]. RSSI-weighted centroid; accuracy = weighted spread, never below the floor."""
    floor = float(os.environ.get("WIFI_ACC_FLOOR_M", "20"))
    w = sum(p[1] for p in pts)
    lat = sum(p[0][0] * p[1] for p in pts) / w
    lon = sum(p[0][1] * p[1] for p in pts) / w
    kx = 111320.0 * math.cos(math.radians(lat))
    spread = math.sqrt(sum(p[1] * (((p[0][0] - lat) * 111320.0) ** 2 + ((p[0][1] - lon) * kx) ** 2) for p in pts) / w)
    return Fix(t, lat, lon, src, max(floor, spread))

class UnwiredLocator:
    """Wi-Fi BSSID -> lat/lon. Needs >=2 APs. Caches by BSSID set to save the tiny free quota."""
    def __init__(self, token, url, timeout=6.0, ttl=3600.0):
        self.token, self.url, self.timeout, self.ttl = token, url, timeout, ttl
        self.cache = {}

    def locate(self, aps, t):
        if len(aps) < 2:
            return None
        key = tuple(sorted(a["bssid"] for a in aps))
        hit = self.cache.get(key)
        if hit and t - hit[0] < self.ttl:
            return Fix(t, hit[1], hit[2], "wifi-cache", hit[3])
        body = {"token": self.token, "address": 0,
                "wifi": [{"bssid": a["bssid"], "signal": a["rssi"]} for a in aps]}
        try:
            j = requests.post(self.url, json=body, timeout=self.timeout).json()
        except Exception as e:
            print("[geo] request failed:", e)
            return None
        if str(j.get("status", "")).lower() != "ok":
            print("[geo] no fix:", j.get("message") or j)
            return None
        self.cache[key] = (t, j["lat"], j["lon"], j.get("accuracy", 0.0))
        return Fix(t, j["lat"], j["lon"], "wifi", j.get("accuracy", 0.0))

class MockLocator:
    """Offline stand-in: RSSI-weighted centroid of known router positions."""
    def __init__(self, routers):
        self.routers = routers  # {bssid: [lat, lon]}

    @classmethod
    def from_file(cls, path):
        with open(path) as f:
            return cls(json.load(f))

    def locate(self, aps, t):
        pts = [(self.routers[a["bssid"]], 10 ** (a["rssi"] / 20)) for a in aps if a["bssid"] in self.routers]
        if len(pts) < 2:
            return None
        return _weighted_fix(pts, t, "mock")

class LocalDbLocator:
    """Our own Wi-Fi database (SQLite, built by tools/wifi_db.py from wardriving or synthetic data)."""
    def __init__(self, path, min_aps=2):
        if not os.path.exists(path):
            raise SystemExit(f"Wi-Fi database not found: {path}  (build it: python -m tools.wifi_db synthetic)")
        self.db, self.min_aps = sqlite3.connect(path, check_same_thread=False), min_aps

    def locate(self, aps, t):
        ids = [a["bssid"].lower() for a in aps]
        if not ids:
            return None
        rows = self.db.execute(f"SELECT bssid, lat, lon FROM ap WHERE bssid IN ({','.join('?' * len(ids))})", ids).fetchall()
        pos = {b: (la, lo) for b, la, lo in rows}
        pts = [(pos[a["bssid"].lower()], 10 ** (a["rssi"] / 20)) for a in aps if a["bssid"].lower() in pos]
        if len(pts) < self.min_aps:
            return None
        return _weighted_fix(pts, t, "local")

class ChainLocator:
    """Try each locator in turn; the first that returns a fix wins."""
    def __init__(self, *locators):
        self.locators = locators

    def locate(self, aps, t):
        for loc in self.locators:
            fix = loc.locate(aps, t)
            if fix is not None:
                return fix
        return None