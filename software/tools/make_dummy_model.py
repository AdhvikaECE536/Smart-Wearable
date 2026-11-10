"""Builds a small LSTM on synthetic motion so you can test the Keras path end-to-end.
NOT your GeoLife model. Replace model.keras with the one saved from your Colab notebook.
   python -m tools.make_dummy_model [--features 2]"""
import argparse, numpy as np

ap = argparse.ArgumentParser(); ap.add_argument("--features", type=int, default=2); ap.add_argument("--out", default="model.keras")
a = ap.parse_args()
import tensorflow as tf
rng = np.random.default_rng(0)

def windows(mean_v, sd_v, n, label):
    v = np.abs(rng.normal(mean_v, sd_v, (n, 5)))
    acc = np.diff(v, axis=1, prepend=v[:, :1]) # per step, matches the Colab np.diff
    dh = rng.normal(0, 20, (n, 5))
    x = np.stack([v, acc, dh], axis=-1)[:, :, :a.features]
    return x.astype("float32"), np.full(n, label)

xs, ys = zip(windows(0.3, 0.3, 800, 0), windows(2.2, 1.0, 800, 1), windows(10, 3, 800, 2))
X, y = np.concatenate(xs), np.concatenate(ys)
m = tf.keras.Sequential([tf.keras.Input((5, a.features)), tf.keras.layers.LSTM(32), tf.keras.layers.Dropout(0.2),
                         tf.keras.layers.Dense(16, activation="relu"), tf.keras.layers.Dense(3, activation="softmax")])
m.compile("adam", "sparse_categorical_crossentropy", metrics=["accuracy"])
m.fit(X, y, epochs=8, batch_size=64, verbose=0, validation_split=0.2)
m.save(a.out); print("saved", a.out, "val_acc", round(m.evaluate(X, y, verbose=0)[1], 3))
