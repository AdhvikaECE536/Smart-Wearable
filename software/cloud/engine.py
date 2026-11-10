"""Per-device logic: decode -> locate -> (dead-reckon on gaps) -> kinematics -> LSTM -> 2-window latch."""
import numpy as np
from . import config as C
from .geo import Fix
from .kinematics import smooth, features, to_local_m, offset_m, haversine_m
from .payload import decode

class DeviceTracker:
    def __init__(self, device, locator, model):
        self.device, self.locator, self.model = device, locator, model
        self.window = getattr(model, "window", C.WINDOW)
        self.nfeat = getattr(model, "n_features", 2)
        self.reset()

    def reset(self):
        self.fixes, self.consec, self.latched = [], 0, False
        self.active, self.last_rx, self.dr_count = False, 0.0, 0
        self.last = None  # last classification: (idx, prob)

    # ---------- inputs ----------
    def on_uplink(self, data, now):
        if self.active and now - self.last_rx > C.SESSION_TIMEOUT_S:
            self.reset()
        if self.fixes and now - self.fixes[-1].t < C.MIN_DT_S:
            return None  # duplicate / bounce
        aps = decode(data)
        fix = self.locator.locate(aps, now)
        if fix is None:
            fix = self._dead_reckon(now)
        else:
            self.dr_count = 0
        self.active, self.last_rx = True, now
        return self._advance(fix, now, aps)

    def tick(self, now):
        """Call every few seconds: fills gaps when the device went silent (cellular dead zone)."""
        if not self.active:
            return None
        if now - self.last_rx > C.SESSION_TIMEOUT_S:
            self.reset()
            return None
        last_t = self.fixes[-1].t if self.fixes else 0
        if now - last_t >= 1.5 * C.FIX_INTERVAL_S and self.dr_count < C.MAX_DEADRECKON:
            fix = self._dead_reckon(last_t + C.FIX_INTERVAL_S)
            return self._advance(fix, fix.t, []) if fix else None
        return None

    # ---------- internals ----------
    def _dead_reckon(self, t):
        if not self.fixes or self.dr_count >= C.MAX_DEADRECKON:
            return None
        last = self.fixes[-1]
        vn = ve = 0.0
        if len(self.fixes) >= 2:
            p = self.fixes[-2]
            n, e = to_local_m(p.lat, p.lon, last.lat, last.lon)
            dt = max(last.t - p.t, 1e-3)
            vn, ve = n / dt, e / dt
        lat, lon = offset_m(last.lat, last.lon, vn * (t - last.t), ve * (t - last.t))
        self.dr_count += 1
        return Fix(t, lat, lon, "dead-reckoning" if (vn or ve) else "hold")

    def _advance(self, fix, now, aps):
        if fix is not None:
            self.fixes = (self.fixes + [fix])[-(self.window + C.SMOOTH + 2):]
        res = {"device": self.device, "t": now, "n_aps": len(aps), "sos": 1,
               "lat": None, "lon": None, "src": None, "accuracy": None,
               "speed": None, "accel": None, "class": None, "prob": None,
               "gated": False, "consec": self.consec, "alert_level": 2 if self.latched else 1}
        if fix is None:
            res["src"] = "no-fix"
            return res
        res.update(lat=fix.lat, lon=fix.lon, src=fix.src, accuracy=fix.acc)
        if len(self.fixes) >= self.window + 1 and fix.src != "no-fix":
            sm = smooth([(f.t, f.lat, f.lon) for f in self.fixes], C.SMOOTH)
            feats = features(sm)[-self.window:]
            res["speed"], res["accel"] = float(feats[-1, 0]), float(feats[-1, 1])
            x = feats[:, :self.nfeat][None].astype(np.float32)
            probs = self.model.predict(x)
            k = int(np.argmax(probs))
            win = sm[-(self.window + 1):]
            span = haversine_m(win[0][1], win[0][2], win[-1][1], win[-1][2])
            accs = [f.acc for f in self.fixes[-(self.window + 1):] if f.acc]
            res["gated"] = bool(C.ACC_GATE and accs and span < C.ACC_GATE * max(accs))
            if res["gated"]:
                k = C.CLASS_NAMES.index("stationary")   # movement within position error is not evidence
            res["class"], res["prob"] = C.CLASS_NAMES[k], float(probs[k])
            if k in C.THREAT_CLASSES and probs[k] >= C.THREAT_MIN_PROB:
                self.consec += 1
            else:
                self.consec = 0
            if self.consec >= C.LATCH:
                self.latched = True   # sticky until the session ends
            res["consec"] = self.consec
            res["alert_level"] = 2 if self.latched else 1
        return res
