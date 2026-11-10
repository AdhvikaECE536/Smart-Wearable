import json, os
import numpy as np

class RuleModel:
    """Dev fallback ONLY (speed thresholds). Used when no trained model file is present."""
    n_features, window, name = 2, 5, "rule-fallback"
    def predict(self, x):
        v = float(np.mean(x[0, :, 0]))
        p = np.full(3, 0.05)
        p[0 if v < 0.7 else 1 if v < 4.0 else 2] = 0.90
        return p

class KerasModel:
    def __init__(self, path, scaler_path=""):
        import tensorflow as tf  # imported lazily so the rest runs without TF
        self.m = tf.keras.models.load_model(path)
        self.window, self.n_features = self.m.input_shape[1], self.m.input_shape[2]
        self.name = os.path.basename(path)
        self.scaler = None
        if scaler_path and os.path.exists(scaler_path):
            s = json.load(open(scaler_path))
            self.scaler = (np.array(s["mean"], dtype=np.float32), np.array(s["std"], dtype=np.float32))
    def predict(self, x):
        if self.scaler:
            x = (x - self.scaler[0]) / (self.scaler[1] + 1e-8)
        return self.m(x, training=False).numpy()[0]

def load_model(path, scaler_path=""):
    if path and os.path.exists(path):
        return KerasModel(path, scaler_path)
    print(f"[threat] {path!r} not found -> using RuleModel fallback (NOT the LSTM)")
    return RuleModel()
