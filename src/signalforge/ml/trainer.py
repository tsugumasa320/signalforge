from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from signalforge.interpret.calibration import ProbabilityCalibrator
from signalforge.interpret.shap_explainer import SHAPExplainer


def _try_lightgbm():
    try:
        import lightgbm as lgb

        return lgb
    except OSError:
        return None


class WalkForwardTrainer:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        interp = cfg.get("interpretability", {})
        self.baseline_model_type = interp.get("baseline_model", "logistic_regression")
        self.primary_model_type = interp.get("primary_model", "lightgbm")
        self.shap_top_k = interp.get("shap_top_k", 3)
        self.calibration_method = interp.get("calibration", "platt")
        self.max_ece = interp.get("max_ece", 0.10)
        wf = cfg.get("walk_forward", {})
        self.train_days = wf.get("train_days", 252)
        self.test_days = wf.get("test_days", 63)
        self.model = None
        self.baseline = None
        self.calibrator = ProbabilityCalibrator(self.calibration_method)
        self.feature_names: list[str] = []
        self.calibration_ok = True
        self._uses_lightgbm = False

    def _make_primary(self):
        lgb = _try_lightgbm()
        if lgb is not None and self.primary_model_type == "lightgbm":
            self._uses_lightgbm = True
            return lgb.LGBMClassifier(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.05,
                verbosity=-1,
            )
        self._uses_lightgbm = False
        return GradientBoostingClassifier(n_estimators=100, max_depth=4)

    def _make_baseline(self):
        return LogisticRegression(max_iter=1000)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> dict[str, Any]:
        self.feature_names = list(X.columns)
        self.baseline = self._make_baseline()
        self.baseline.fit(X, y)

        self.model = self._make_primary()
        self.model.fit(X, y)

        raw_prob = self.model.predict_proba(X)[:, 1]
        self.calibrator.fit(raw_prob, y.values)
        ece = self.calibrator.ece(y.values, raw_prob)
        self.calibration_ok = ece <= self.max_ece

        importance = {}
        if hasattr(self.model, "feature_importances_"):
            importance = dict(zip(self.feature_names, self.model.feature_importances_, strict=False))

        return {
            "baseline_coef": dict(zip(self.feature_names, self.baseline.coef_[0], strict=False)),
            "feature_importance": importance,
            "ece": ece,
            "calibration_ok": self.calibration_ok,
            "model_type": "lightgbm" if self._uses_lightgbm else "gradient_boosting",
        }

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("Model not trained")
        raw = self.model.predict_proba(X)[:, 1]
        if self.calibration_ok:
            return self.calibrator.transform(raw)
        return raw

    def explain(self, X: pd.DataFrame, row_idx: int = 0) -> list[dict[str, Any]]:
        if self.model is None:
            return []
        if not self._uses_lightgbm:
            return self._explain_linear(row_idx)
        try:
            explainer = SHAPExplainer(self.model, self.feature_names, self.shap_top_k)
            return explainer.explain_row(X, row_idx)
        except Exception:
            return self._explain_linear(row_idx)

    def _explain_linear(self, row_idx: int) -> list[dict[str, Any]]:
        from signalforge.interpret.features_registry import get_feature_descriptions

        desc_map = get_feature_descriptions()
        if self.baseline is None:
            return []
        coefs = self.baseline.coef_[0]
        pairs = sorted(
            zip(self.feature_names, coefs, strict=False),
            key=lambda x: abs(x[1]),
            reverse=True,
        )[: self.shap_top_k]
        return [
            {"name": n, "value": 0.0, "shap": float(c), "desc": desc_map.get(n, n)}
            for n, c in pairs
        ]

    def walk_forward_eval(
        self,
        X: pd.DataFrame,
        y: pd.Series,
    ) -> list[dict[str, Any]]:
        results = []
        n = len(X)
        train_size = self.train_days
        test_size = self.test_days
        start = 0
        fold = 0
        while start + train_size + test_size <= n:
            train_end = start + train_size
            test_end = train_end + test_size
            X_train = X.iloc[start:train_end]
            y_train = y.iloc[start:train_end]
            X_test = X.iloc[train_end:test_end]
            y_test = y.iloc[train_end:test_end]

            trainer = WalkForwardTrainer(self.cfg)
            info = trainer.fit(X_train, y_train)
            prob = trainer.predict_proba(X_test)
            pred = (prob >= 0.5).astype(int)
            acc = (pred == y_test.values).mean()
            results.append({"fold": fold, "accuracy": float(acc), **info})
            fold += 1
            start += test_size
        return results
