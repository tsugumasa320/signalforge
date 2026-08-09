from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from signalforge.ml.features import build_features
from signalforge.ml.labeler import triple_barrier_labels
from signalforge.ml.sampler import cusum_filter
from signalforge.ml.trainer import WalkForwardTrainer


@dataclass
class FoldModel:
    fold: int
    test_start_idx: int
    test_end_idx: int
    trainer: WalkForwardTrainer
    train_info: dict[str, Any] = field(default_factory=dict)


class MetaLabelFilter:
    """
    Meta-labeling filter with strict walk-forward OOS.

    ML is applied ONLY inside each fold's test window. Bars outside OOS windows
    pass through as TA-only (no ML gate) so the equity curve stays continuous,
    but those trades are tagged is_oos=False for separate metrics.
    """

    def __init__(self, cfg: dict[str, Any], intraday: bool = False) -> None:
        self.cfg = cfg
        self.enabled = cfg.get("enabled", False)
        self.min_prob = cfg.get("min_probability", 0.55)
        self.max_hold = cfg.get("max_holding_period", 10)
        self.cusum_threshold = cfg.get("cusum_threshold", 0.02)
        self.intraday = intraday
        self._features: pd.DataFrame | None = None
        self._folds: list[FoldModel] = []
        self.prepare_report: dict[str, Any] = {}

    def prepare(
        self,
        df: pd.DataFrame,
        signals: pd.Series,
        qqq_df: pd.DataFrame | None = None,
        soxx_df: pd.DataFrame | None = None,
        exit_rules: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"trained": False, "reason": "disabled"}

        exit_rules = exit_rules or {}
        tp = exit_rules.get("atr_tp_multiple", 2.0)
        sl = exit_rules.get("atr_sl_multiple", 1.0)

        # Meta-labeling: label each primary (TA) signal event
        event_index = signals.index[signals != 0]
        min_events = int(self.cfg.get("min_signal_events", 15))
        if len(event_index) < min_events:
            return {"trained": False, "reason": "insufficient signal events", "events": len(event_index)}

        event_signals = signals.loc[event_index]
        labels = triple_barrier_labels(
            df,
            event_index,
            event_signals,
            tp_mult=tp,
            sl_mult=sl,
            max_hold=self.max_hold,
        )
        if labels.empty:
            return {"trained": False, "reason": "no labels"}

        # Optional CUSUM subsampling for very high-frequency signals
        use_cusum = self.cfg.get("use_cusum_subsample", False)
        if use_cusum:
            returns = df["close"].pct_change()
            cusum_events = cusum_filter(returns, self.cusum_threshold)
            labels = labels.loc[labels.index.intersection(cusum_events)]
            if labels.empty:
                return {"trained": False, "reason": "cusum removed all labels"}

        self._features = build_features(df, qqq_df, soxx_df, self.intraday)
        common = labels.index.intersection(self._features.index)
        labels = labels.loc[common]
        X_all = self._features.loc[common]

        wf = self.cfg.get("walk_forward", {})
        train_size = wf.get("train_days", 252)
        test_size = wf.get("test_days", 63)
        train_label_count = wf.get("train_labels", max(20, train_size // 6))
        test_label_count = wf.get("test_labels", max(8, test_size // 6))
        min_train_labels = self.cfg.get("min_train_labels", 10)

        self._folds = []
        fold_reports = []
        sorted_label_idx = labels.index.sort_values()
        n_labels = len(sorted_label_idx)
        start = 0

        while start + train_label_count + test_label_count <= n_labels:
            train_labels = sorted_label_idx[start : start + train_label_count]
            test_labels = sorted_label_idx[
                start + train_label_count : start + train_label_count + test_label_count
            ]

            X_train = X_all.loc[train_labels.intersection(X_all.index)]
            y_train = labels.loc[X_train.index, "meta_label"]

            if len(X_train) < min_train_labels or y_train.nunique() < 2:
                start += test_label_count
                continue

            trainer = WalkForwardTrainer(self.cfg)
            try:
                info = trainer.fit(X_train, y_train)
            except ValueError:
                start += test_label_count
                continue

            test_start_bar = df.index.get_loc(test_labels[0])
            test_end_bar = df.index.get_loc(test_labels[-1]) + 1

            X_test = X_all.loc[test_labels.intersection(X_all.index)]
            y_test = labels.loc[X_test.index, "meta_label"]
            oos_acc = None
            if len(X_test) > 0 and y_test.nunique() >= 1:
                prob = trainer.predict_proba(X_test)
                pred = (prob >= 0.5).astype(int)
                oos_acc = float((pred == y_test.values).mean())

            fold = FoldModel(
                fold=len(self._folds),
                test_start_idx=int(test_start_bar),
                test_end_idx=int(test_end_bar),
                trainer=trainer,
                train_info=info,
            )
            self._folds.append(fold)
            fold_reports.append(
                {
                    "fold": fold.fold,
                    "train_labels": len(X_train),
                    "test_labels": len(X_test),
                    "oos_accuracy": oos_acc,
                    "ece": info.get("ece"),
                    "calibration_ok": info.get("calibration_ok"),
                    "model_type": info.get("model_type"),
                    "test_range": [str(test_labels[0]), str(test_labels[-1])],
                }
            )
            start += test_label_count

        if not self._folds:
            return {"trained": False, "reason": "insufficient folds"}

        avg_acc = _avg([r["oos_accuracy"] for r in fold_reports if r["oos_accuracy"] is not None])
        self.prepare_report = {
            "trained": True,
            "folds": len(self._folds),
            "fold_reports": fold_reports,
            "avg_oos_accuracy": avg_acc,
            "oos_bar_ranges": [
                {"fold": f.fold, "start": f.test_start_idx, "end": f.test_end_idx}
                for f in self._folds
            ],
        }
        return self.prepare_report

    def _active_fold(self, bar_idx: int) -> FoldModel | None:
        for fold in self._folds:
            if fold.test_start_idx <= bar_idx < fold.test_end_idx:
                return fold
        return None

    def is_oos_bar(self, bar_idx: int) -> bool:
        return self._active_fold(bar_idx) is not None

    def should_trade(
        self, df: pd.DataFrame, bar_idx: int
    ) -> tuple[bool, float, dict[str, Any] | None, bool]:
        """
        Returns: (allow_trade, probability, explanation, is_oos)
        """
        if not self.enabled:
            return True, 1.0, None, False

        fold = self._active_fold(bar_idx)
        if fold is None:
            return True, 1.0, {"mode": "ta_only", "reason": "outside_oos_window"}, False

        if self._features is None:
            return True, 1.0, {"mode": "ta_only", "reason": "features_unavailable"}, False

        ts = df.index[bar_idx]
        if ts not in self._features.index:
            return False, 0.0, {"mode": "oos", "reason": "missing_features", "fold": fold.fold}, True

        trainer = fold.trainer
        X = self._features.loc[[ts]]
        prob = float(trainer.predict_proba(X)[0])

        if not trainer.calibration_ok:
            expl = {
                "mode": "oos",
                "fold": fold.fold,
                "probability": prob,
                "threshold": self.min_prob,
                "calibration_disabled": True,
                "top_features": trainer.explain(X, 0),
            }
            return True, prob, expl, True

        expl = {
            "mode": "oos",
            "fold": fold.fold,
            "probability": prob,
            "threshold": self.min_prob,
            "top_features": trainer.explain(X, 0),
        }
        ok = prob >= self.min_prob
        return ok, prob, expl, True


def _avg(values: list[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    return sum(nums) / len(nums) if nums else None
