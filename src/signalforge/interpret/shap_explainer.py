from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import shap

from signalforge.interpret.features_registry import get_feature_descriptions


class SHAPExplainer:
    """Explain individual predictions with SHAP values."""

    def __init__(self, model, feature_names: list[str], top_k: int = 3) -> None:
        self.model = model
        self.feature_names = feature_names
        self.top_k = top_k
        self._explainer = None

    def _get_explainer(self, X: pd.DataFrame):
        if self._explainer is None:
            self._explainer = shap.TreeExplainer(self.model)
        return self._explainer

    def explain_row(self, X: pd.DataFrame, row_idx: int = 0) -> list[dict[str, Any]]:
        row = X.iloc[[row_idx]]
        try:
            explainer = self._get_explainer(X)
            shap_vals = explainer.shap_values(row)
            if isinstance(shap_vals, list):
                shap_vals = shap_vals[1] if len(shap_vals) > 1 else shap_vals[0]
            vals = shap_vals[0]
        except Exception:
            vals = np.zeros(len(self.feature_names))

        desc_map = get_feature_descriptions()
        pairs = sorted(
            zip(self.feature_names, vals, row.iloc[0].values, strict=False),
            key=lambda x: abs(x[1]),
            reverse=True,
        )[: self.top_k]
        return [
            {
                "name": name,
                "value": float(val),
                "shap": float(shap_val),
                "desc": desc_map.get(name, name),
            }
            for name, shap_val, val in pairs
        ]
