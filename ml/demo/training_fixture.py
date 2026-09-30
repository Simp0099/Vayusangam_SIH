"""Fixed-seed synthetic fixture for exercising the PM2.5 model interface only."""
import numpy as np

from ml.models.pm25 import FEATURES


def make_pm25_training_fixture(seed: int = 26082, rows: int = 512):
    rng = np.random.default_rng(seed)
    pm = rng.uniform(25, 260, rows)
    temperature = rng.uniform(3, 32, rows)
    humidity = rng.uniform(25, 95, rows)
    wind = rng.uniform(.2, 6, rows)
    direction = rng.uniform(0, 360, rows)
    pblh = rng.uniform(120, 1800, rows)
    isi = rng.uniform(-2, 8, rows)
    vc = pblh * wind
    smoke = rng.uniform(0, 2.5, rows)
    hour = rng.integers(0, 24, rows)
    day = rng.integers(1, 29, rows)
    month = rng.integers(1, 13, rows)
    o3 = rng.uniform(8, 90, rows)
    no2 = rng.uniform(8, 75, rows)
    X = np.column_stack([pm, temperature, humidity, wind, direction, pblh, isi, vc, smoke, hour, day, month, o3, no2])
    y = np.clip(pm + .45*np.maximum(isi-2, 0) + .002*np.maximum(650-vc, 0) + .4*smoke + .006*np.maximum(700-pblh, 0) + rng.normal(0, 5, rows), 0, 500)
    assert X.shape[1] == len(FEATURES)
    return X, y
