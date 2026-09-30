"""Separate demo O3 response component; smoke is intentionally not a direct input."""
import numpy as np


class OzoneForecaster:
    FEATURES = ("previous_o3", "nox", "temperature", "radiation", "pblh", "humidity", "wind", "hour", "season")

    def predict(self, row):
        x = {k: float(v) for k, v in row.items()}
        photolysis = max(0, np.sin((x["hour"]-6) / 24 * 2*np.pi))
        mixing = max(0, (x["pblh"]-350)/1200)
        return float(np.clip(x["previous_o3"] + 5.2*photolysis + .11*(x["temperature"]-20) - .018*x["nox"] - .8*mixing - 1.2, 0, 150))
