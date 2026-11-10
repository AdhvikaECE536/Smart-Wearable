"""21-byte uplink: 3 x [6-byte MAC][1 byte = -RSSI]. Unused slots are zero."""

def encode(aps):
    """aps: list of {'bssid': 'aa:bb:..', 'rssi': -63} (max 3). Returns hex string."""
    b = bytearray()
    for a in list(aps)[:3]:
        b += bytes.fromhex(a["bssid"].replace(":", "").replace("-", ""))
        b.append(min(255, int(-a["rssi"])))
    b += bytes(21 - len(b))
    return b.hex()

def decode(data):
    """data: hex str or 21 raw bytes. Returns list of {'bssid','rssi'}."""
    if isinstance(data, (bytes, bytearray)):
        raw = bytes(data) if len(data) == 21 else bytes.fromhex(data.decode().strip())
    else:
        raw = bytes.fromhex(data.strip())
    if len(raw) != 21:
        raise ValueError(f"payload must be 21 bytes, got {len(raw)}")
    aps = []
    for i in range(3):
        mac, r = raw[i * 7:i * 7 + 6], raw[i * 7 + 6]
        if any(mac):
            aps.append({"bssid": ":".join(f"{x:02x}" for x in mac), "rssi": -int(r)})
    return aps
