import os
import math
import numpy as np

R = 6371000.0

def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360

def wrap180(d):
    return (d + 180) % 360 - 180

def offset_m(lat, lon, north_m, east_m):
    dlat = math.degrees(north_m / R)
    dlon = math.degrees(east_m / (R * math.cos(math.radians(lat))))
    return lat + dlat, lon + dlon

def to_local_m(lat0, lon0, lat, lon):
    n = math.radians(lat - lat0) * R
    e = math.radians(lon - lon0) * R * math.cos(math.radians(lat0))
    return n, e

def smooth(track, k):
    """Trailing mean over the last k positions (partial window at the start). track: [(t,lat,lon)]"""
    out = []
    for i, (t, _, _) in enumerate(track):
        seg = track[max(0, i - k + 1):i + 1]
        out.append((t, sum(s[1] for s in seg) / len(seg), sum(s[2] for s in seg) / len(seg)))
    return out

ACC_PER_STEP = os.environ.get("ACC_PER_STEP", "1") == "1"   # 1 = acceleration as speed change per step (matches the Colab np.diff); 0 = m/s^2

def features(track):
    """track: [(t,lat,lon)], n>=2 -> array (n-1, 3) of [speed m/s, accel m/s^2, heading delta deg]."""
    rows, prev_v, prev_b = [], 0.0, None
    for (t0, la0, lo0), (t1, la1, lo1) in zip(track[:-1], track[1:]):
        dt = max(t1 - t0, 1e-3)
        d = haversine_m(la0, lo0, la1, lo1)
        v = d / dt
        a = ((v - prev_v) if ACC_PER_STEP else (v - prev_v) / dt) if rows else 0.0
        b = bearing_deg(la0, lo0, la1, lo1) if d > 1.0 else prev_b
        dh = wrap180(b - prev_b) if (b is not None and prev_b is not None) else 0.0
        rows.append([v, a, dh])
        prev_v, prev_b = v, (b if b is not None else prev_b)
    return np.array(rows, dtype=np.float32)
