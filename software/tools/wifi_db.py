"""Our own Wi-Fi location database (SQLite).  GEO_MODE=local reads it.

  python -m tools.wifi_db synthetic --n 50000          big demo database (clearly synthetic) + the simulator's routers
  python -m tools.wifi_db import-wigle  scan.csv       WiGLE app export (wardriving with a phone: real BSSIDs, real GPS)
  python -m tools.wifi_db import-csv    aps.csv        plain CSV with columns bssid,lat,lon
  python -m tools.wifi_db stats
  python -m tools.wifi_db sample --lat 12.97 --lon 77.59   print a FAKE[] table for the Wokwi sketch from DB entries

Each router's position is the RSSI-weighted centroid of everything we saw it from, and imports accumulate, so every
extra walk around the same place sharpens the estimate."""
import argparse, csv, io, math, os, random, sqlite3, sys

DB = os.environ.get("WIFI_DB", "wifi_db.sqlite")

def connect(path=None):
    db = sqlite3.connect(path or DB)
    db.execute("""CREATE TABLE IF NOT EXISTS ap (bssid TEXT PRIMARY KEY, lat REAL, lon REAL,
                  sw REAL, swlat REAL, swlon REAL, n INTEGER, ssid TEXT, src TEXT)""")
    return db

def norm(mac):
    m = mac.strip().lower().replace("-", ":")
    return m if len(m.split(":")) == 6 else None

def add(db, bssid, lat, lon, w=1.0, n=1, ssid="", src=""):
    """Accumulate one observation (or one pre-aggregated estimate) of a router."""
    b = norm(bssid)
    if b is None or not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return False
    row = db.execute("SELECT sw, swlat, swlon, n FROM ap WHERE bssid=?", (b,)).fetchone()
    sw, sla, slo, nn = (row if row else (0.0, 0.0, 0.0, 0))
    sw, sla, slo, nn = sw + w, sla + w * lat, slo + w * lon, nn + n
    db.execute("INSERT OR REPLACE INTO ap VALUES (?,?,?,?,?,?,?,?,?)", (b, sla / sw, slo / sw, sw, sla, slo, nn, ssid, src))
    return True

def import_wigle(db, text, max_acc=50.0):
    """WiGLE CSV: line 1 is a 'WigleWifi-1.4,...' banner, line 2 the column names. Only WIFI rows with a decent GPS fix."""
    lines = text.splitlines()
    start = 1 if lines and lines[0].startswith("WigleWifi") else 0
    rd = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    kept = skipped = 0
    for r in rd:
        try:
            if r.get("Type", "WIFI").upper() != "WIFI":
                skipped += 1; continue
            acc = float(r.get("AccuracyMeters") or 0)
            if acc > max_acc:
                skipped += 1; continue
            rssi = float(r.get("RSSI") or -80)
            ok = add(db, r["MAC"], float(r["CurrentLatitude"]), float(r["CurrentLongitude"]),
                     w=10 ** (rssi / 20), ssid=r.get("SSID", ""), src="wigle")
            kept += ok; skipped += (not ok)
        except (KeyError, ValueError):
            skipped += 1
    db.commit()
    return kept, skipped

def import_csv(db, text):
    kept = skipped = 0
    for r in csv.DictReader(io.StringIO(text)):
        try:
            kept += add(db, r["bssid"], float(r["lat"]), float(r["lon"]), src="csv")
        except (KeyError, ValueError):
            skipped += 1
    db.commit()
    return kept, skipped

def synthetic(db, n, seed=1, bbox=(12.85, 13.10, 77.45, 77.75)):
    """The simulator's own routers (so simulate_device resolves) plus n random ones across Bengaluru. NOT real data."""
    sys.path.insert(0, ".")
    from cloud.simlib import build_routers
    for mac, (la, lo) in build_routers().items():
        add(db, mac, la, lo, src="sim")
    rnd = random.Random(seed)
    for i in range(n):
        mac = "02:00:ff:%02x:%02x:%02x" % (i >> 16 & 255, i >> 8 & 255, i & 255)
        add(db, mac, rnd.uniform(bbox[0], bbox[1]), rnd.uniform(bbox[2], bbox[3]), src="synthetic")
        if i % 5000 == 0:
            db.commit()
    db.commit()

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("synthetic"); s.add_argument("--n", type=int, default=50000)
    for name in ("import-wigle", "import-csv"):
        s = sub.add_parser(name); s.add_argument("file")
    sub.add_parser("stats")
    s = sub.add_parser("sample"); s.add_argument("--lat", type=float, default=12.9716); s.add_argument("--lon", type=float, default=77.5946)
    a = ap.parse_args()
    db = connect(a.db)
    if a.cmd == "synthetic":
        synthetic(db, a.n); print("synthetic database built")
    elif a.cmd in ("import-wigle", "import-csv"):
        text = open(a.file, encoding="utf-8", errors="ignore").read()
        kept, skipped = (import_wigle if a.cmd == "import-wigle" else import_csv)(db, text)
        print(f"imported {kept} observations, skipped {skipped}")
    elif a.cmd == "sample":
        from cloud.kinematics import haversine_m
        rows = db.execute("SELECT bssid, lat, lon FROM ap WHERE abs(lat-?)<0.01 AND abs(lon-?)<0.01", (a.lat, a.lon)).fetchall()
        near = sorted(rows, key=lambda r: haversine_m(a.lat, a.lon, r[1], r[2]))[:3]
        if len(near) < 3:
            sys.exit("fewer than 3 routers within about 1 km of that point")
        rows_c = ", ".join("{{" + ",".join("0x" + b for b in m.split(":")) + "}, %d}" % r for (m, _, _), r in zip(near, (-48, -61, -72)))
        print(f"const AP FAKE[3] = {{ {rows_c} }};")
    n, = db.execute("SELECT COUNT(*) FROM ap").fetchone()
    by = db.execute("SELECT src, COUNT(*) FROM ap GROUP BY src").fetchall()
    print(f"{a.db}: {n} routers  {dict(by)}")

if __name__ == "__main__":
    main()
