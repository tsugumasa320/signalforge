from __future__ import annotations

import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


def platt_calibrate(y_prob: np.ndarray, y_true: np.ndarray) -> LogisticRegression:
    lr = LogisticRegression()
    lr.fit(y_prob.reshape(-1, 1), y_true)
    return lr


def expected_calibration_error(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    if len(y_true) < n_bins:
        return 0.0
    prob_true, prob_pred = calibration_curve(y_true, y_prob, n_bins=n_bins, strategy="uniform")
    if len(prob_pred) == 0:
        return 1.0
    weights = np.histogram(y_prob, bins=np.linspace(0, 1, n_bins + 1))[0]
    weights = weights[: len(prob_pred)] / max(len(y_prob), 1)
    return float(np.sum(weights * np.abs(prob_true - prob_pred)))


class ProbabilityCalibrator:
    def __init__(self, method: str = "platt") -> None:
        self.method = method
        self._model = None

    def fit(self, y_prob: np.ndarray, y_true: np.ndarray) -> None:
        if self.method == "isotonic":
            self._model = IsotonicRegression(out_of_bounds="clip")
            self._model.fit(y_prob, y_true)
        else:
            self._model = platt_calibrate(y_prob, y_true)

    def transform(self, y_prob: np.ndarray) -> np.ndarray:
        if self._model is None:
            return y_prob
        if isinstance(self._model, IsotonicRegression):
            return self._model.predict(y_prob)
        return self._model.predict_proba(y_prob.reshape(-1, 1))[:, 1]

    def ece(self, y_true: np.ndarray, y_prob: np.ndarray) -> float:
        calibrated = self.transform(y_prob) if self._model else y_prob
        return expected_calibration_error(y_true, calibrated)
