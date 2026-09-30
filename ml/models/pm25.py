"""PM2.5 quantile model interface with optional LightGBM and an honest demo fallback."""
from __future__ import annotations
import numpy as np


FEATURES = ("previous_pm25", "temperature", "humidity", "wind_speed", "wind_direction", "pblh", "isi", "vc", "smoke", "hour", "day", "month", "previous_o3", "previous_no2")


class PM25Forecaster:
    def __init__(self, demo_mode: bool = True):
        self.demo_mode = demo_mode
        self.models = {}
        self.fitted = False

    def fit(self, X, y):
        X = np.asarray(X, dtype=float); y = np.asarray(y, dtype=float)
        if X.ndim != 2 or X.shape[1] != len(FEATURES):
            raise ValueError(f"Expected {len(FEATURES)} ordered features")
        try:
            from lightgbm import LGBMRegressor
            for q in (.1, .5, .9):
                model = LGBMRegressor(objective="quantile", alpha=q, n_estimators=80, max_depth=3, learning_rate=.04, verbosity=-1, random_state=26082)
                model.fit(X, y); self.models[q] = model
        except ImportError:
            # Demo fixture fallback: quantiles around a bounded, process-inspired median.
            self.models = {q: None for q in (.1, .5, .9)}
        self.fitted = True
        return self

    def fit_demo_fixture(self, seed: int = 26082):
        from ml.demo.training_fixture import make_pm25_training_fixture
        X, y = make_pm25_training_fixture(seed=seed)
        return self.fit(X, y)

    def predict_quantiles(self, X):
        if not self.fitted: raise RuntimeError("Call fit() before predict_quantiles()")
        X = np.asarray(X, dtype=float)
        if X.ndim == 1: X = X.reshape(1, -1)
        if all(model is not None for model in self.models.values()):
            return {q: self.models[q].predict(X) for q in (.1, .5, .9)}
        median = np.clip(X[:, 0] + .45*np.maximum(X[:, 6]-2, 0) + .002*np.maximum(650-X[:, 7], 0) + .4*X[:, 8] + .006*np.maximum(700-X[:, 5], 0), 0, 500)
        return {.1: np.maximum(0, median*.82), .5: median, .9: np.minimum(500, median*1.2+5)}

    def predict(self, X):
        return self.predict_quantiles(X)[.5]
