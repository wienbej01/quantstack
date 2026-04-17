"""Learned action-ranking models for trade-budget research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier


@dataclass(frozen=True)
class ActionSpec:
    """Discrete action candidate."""

    side: str
    hold_minutes: int

    @property
    def key(self) -> str:
        return f"{self.side}_{self.hold_minutes}m"


ACTION_QUALITY_BASE_COLUMNS = (
    "rank_score",
    "pressure_k",
    "spread",
    "depth_imb_k",
    "micro_off",
    "spread_mean_10s",
    "depth_imb_k_mean_10s",
    "depth_imb_k_mean_60s",
)

ACTION_QUALITY_PRICE_COLUMNS = (
    "dist_vwap_bps",
    "hl_range_pct",
    "oc_change_pct",
    "volume_rel_20",
    "atr_pct",
    "position_in_range",
    "rsi",
    "bb_position",
    "ret_3",
    "ret_10",
)


class _ConstantBinaryModel:
    """Predict a fixed positive class probability when a training target is degenerate."""

    def __init__(self, positive_rate: float) -> None:
        self.positive_rate = float(np.clip(positive_rate, 1e-4, 1.0 - 1e-4))

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        n = len(np.asarray(X))
        positive = np.full(n, self.positive_rate, dtype=np.float32)
        return np.column_stack([1.0 - positive, positive])

_ACTION_RANKER_STABLE_FEATURES = {
    "mid",
    "spread",
    "microprice",
    "micro_off",
    "depth_bid_k",
    "depth_ask_k",
    "depth_imb_k",
    "pressure_k",
    "obi_1",
    "obi_2",
    "obi_3",
    "obi_5",
    "obi_10",
    "d_mid_5s",
    "d_spread_5s",
    "d_obi_1_5s",
    "d_micro_off_5s",
    "d_mid_30s",
    "d_spread_30s",
    "d_obi_1_30s",
    "d_micro_off_30s",
    "d_mid_60s",
    "d_spread_60s",
    "d_obi_1_60s",
    "d_micro_off_60s",
    "session_bucket",
    "seconds_since_open",
    "session_progress",
    "source_is_features",
    "source_is_raw",
    "session_is_open",
    "session_is_morning",
    "session_is_midday",
    "session_is_close",
    "spread_mean_10s",
    "spread_std_10s",
    "pressure_k_mean_10s",
    "pressure_k_std_10s",
    "depth_imb_k_mean_10s",
    "depth_imb_k_std_10s",
    "micro_off_mean_10s",
    "micro_off_std_10s",
    "spread_mean_60s",
    "spread_std_60s",
    "pressure_k_mean_60s",
    "pressure_k_std_60s",
    "depth_imb_k_mean_60s",
    "depth_imb_k_std_60s",
    "micro_off_mean_60s",
    "micro_off_std_60s",
    "depth_imb_positive_10s",
    "depth_imb_negative_10s",
    "depth_imb_positive_60s",
    "depth_imb_negative_60s",
    "micro_off_positive_30s",
    "micro_off_negative_30s",
    "micro_off_positive_60s",
    "micro_off_negative_60s",
}

_ACTION_RANKER_CAUSAL_FEATURES = {
    "dist_vwap_bps",
    "hl_range_pct",
    "oc_change_pct",
    "volume_rel_20",
    "atr_pct",
    "position_in_range",
    "rsi",
    "bb_position",
    "ret_1",
    "ret_3",
    "ret_5",
    "ret_10",
    "log_log_ret_1",
    "log_log_ret_3",
    "log_log_ret_5",
    "log_log_ret_10",
}


def build_action_specs(hold_minutes: Iterable[int]) -> list[ActionSpec]:
    """Build ordered discrete actions over side x hold."""
    specs: list[ActionSpec] = []
    for hold in hold_minutes:
        specs.append(ActionSpec(side="long", hold_minutes=int(hold)))
    for hold in hold_minutes:
        specs.append(ActionSpec(side="short", hold_minutes=int(hold)))
    return specs


def _dynamic_edge_floor_bps(
    df: pd.DataFrame,
    *,
    spread_weight: float,
    open_penalty_bps: float,
    raw_penalty_bps: float,
    base_edge_bps: float,
) -> pd.Series:
    spread = pd.to_numeric(
        df["spread"] if "spread" in df.columns else pd.Series(np.nan, index=df.index),
        errors="coerce",
    )
    mid = pd.to_numeric(
        df["mid"] if "mid" in df.columns else pd.Series(np.nan, index=df.index),
        errors="coerce",
    )
    spread_bps = (
        (spread / mid.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        * 10000.0
    ).clip(lower=0.0)
    session_bucket = pd.to_numeric(df.get("session_bucket"), errors="coerce").fillna(
        1.0
    )
    source_type = (
        df.get("source_type", pd.Series("unknown", index=df.index))
        .fillna("unknown")
        .astype(str)
    )
    return (
        float(base_edge_bps)
        + spread_bps * float(spread_weight)
        + np.where(session_bucket == 0.0, float(open_penalty_bps), 0.0)
        + np.where(source_type == "raw", float(raw_penalty_bps), 0.0)
    ).astype(np.float32)


def derive_action_targets(
    df: pd.DataFrame,
    *,
    hold_minutes: Iterable[int],
    base_edge_bps: float,
    spread_weight: float,
    open_penalty_bps: float,
    raw_penalty_bps: float,
    positive_edge_buffer_bps: float = 0.0,
) -> tuple[pd.DataFrame, list[ActionSpec]]:
    """Attach per-action post-cost edge targets to a training frame."""
    derived = df.copy()
    specs = build_action_specs(hold_minutes)
    edge_columns: list[str] = []

    for spec in specs:
        horizon = spec.hold_minutes * 60
        ret_col = f"ret_fwd_{horizon}s"
        if ret_col not in derived.columns:
            raise RuntimeError(
                f"Required return column missing for action ranker: {ret_col}"
            )

        floor_bps = _dynamic_edge_floor_bps(
            derived,
            spread_weight=spread_weight,
            open_penalty_bps=open_penalty_bps,
            raw_penalty_bps=raw_penalty_bps,
            base_edge_bps=base_edge_bps,
        )
        ret_bps = pd.to_numeric(derived[ret_col], errors="coerce") * 10000.0
        if spec.side == "short":
            net_edge_bps = -ret_bps - floor_bps
        else:
            net_edge_bps = ret_bps - floor_bps

        edge_col = f"edge_{spec.key}_bps"
        edge_columns.append(edge_col)
        derived[edge_col] = net_edge_bps.astype(np.float32)
        derived[f"target_{spec.key}"] = (
            net_edge_bps > float(positive_edge_buffer_bps)
        ).astype(np.float32)

    edge_frame = derived[edge_columns].astype(np.float32)
    best_idx = edge_frame.to_numpy().argmax(axis=1)
    best_edges = edge_frame.to_numpy()[np.arange(len(derived)), best_idx]
    action_keys = [spec.key for spec in specs]
    derived["best_action_key"] = pd.Series(
        [action_keys[idx] for idx in best_idx], index=derived.index
    )
    derived["best_action_edge_bps"] = best_edges.astype(np.float32)
    derived["best_action_positive"] = (
        derived["best_action_edge_bps"] > float(positive_edge_buffer_bps)
    ).astype(np.float32)

    return derived, specs


def build_action_quality_features(
    df: pd.DataFrame,
    *,
    hold_minutes: Iterable[int],
) -> tuple[pd.DataFrame, list[str]]:
    """Build deterministic features for a lightweight accept/reject quality layer."""
    out = df.copy()
    hold_values = sorted({int(value) for value in hold_minutes})

    for column in ACTION_QUALITY_BASE_COLUMNS:
        source = (
            out[column] if column in out.columns else pd.Series(np.nan, index=out.index)
        )
        out[column] = pd.to_numeric(source, errors="coerce")
    for column in ACTION_QUALITY_PRICE_COLUMNS:
        source = (
            out[column] if column in out.columns else pd.Series(np.nan, index=out.index)
        )
        out[column] = pd.to_numeric(source, errors="coerce")

    side = (
        (out["side"] if "side" in out.columns else pd.Series("", index=out.index))
        .fillna("")
        .astype(str)
        .str.lower()
    )
    out["side_is_long"] = (side == "long").astype(np.float32)
    out["side_is_short"] = (side == "short").astype(np.float32)

    session_bucket = pd.to_numeric(
        (
            out["session_bucket"]
            if "session_bucket" in out.columns
            else pd.Series(np.nan, index=out.index)
        ),
        errors="coerce",
    )
    for bucket in range(4):
        out[f"session_is_{bucket}"] = (session_bucket == float(bucket)).astype(
            np.float32
        )

    hold_series = pd.to_numeric(
        (
            out["hold_minutes"]
            if "hold_minutes" in out.columns
            else pd.Series(np.nan, index=out.index)
        ),
        errors="coerce",
    )
    for hold in hold_values:
        out[f"hold_is_{hold}m"] = (hold_series == float(hold)).astype(np.float32)

    feature_columns = [
        *ACTION_QUALITY_BASE_COLUMNS,
        *ACTION_QUALITY_PRICE_COLUMNS,
        "side_is_long",
        "side_is_short",
        *(f"session_is_{bucket}" for bucket in range(4)),
        *(f"hold_is_{hold}m" for hold in hold_values),
    ]
    out[feature_columns] = (
        out[feature_columns]
        .astype(np.float32)
        .fillna(0.0)
        .replace([float("inf"), float("-inf")], 0.0)
    )
    return out, feature_columns


class ActionRankerLogistic:
    """One-vs-rest profitable-after-cost action scorer."""

    def __init__(
        self,
        *,
        feature_columns: list[str],
        action_specs: list[ActionSpec],
        c: float = 1.0,
        max_iter: int = 1000,
        class_weight: str | dict | None = "balanced",
        random_state: int = 42,
    ) -> None:
        if not feature_columns:
            raise ValueError("feature_columns must not be empty")
        if not action_specs:
            raise ValueError("action_specs must not be empty")
        self.feature_columns = feature_columns
        self.action_specs = action_specs
        self.scaler = StandardScaler()
        self.models = {
            spec.key: LogisticRegression(
                C=c,
                max_iter=max_iter,
                class_weight=class_weight,
                random_state=random_state,
                solver="lbfgs",
            )
            for spec in action_specs
        }

    def fit(
        self, df: pd.DataFrame, sample_weight: np.ndarray | None = None
    ) -> "ActionRankerLogistic":
        X = np.nan_to_num(
            df[self.feature_columns].to_numpy(dtype=np.float32, copy=True)
        )
        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)
        weights = (
            None
            if sample_weight is None
            else np.asarray(sample_weight, dtype=np.float64)
        )

        for spec in self.action_specs:
            target_col = f"target_{spec.key}"
            if target_col not in df.columns:
                raise RuntimeError(f"Missing action target column: {target_col}")
            y = df[target_col].to_numpy(dtype=int, copy=False)
            if np.unique(y).size < 2:
                self.models[spec.key] = _ConstantBinaryModel(float(y.mean()))
                continue
            self.models[spec.key].fit(X_scaled, y, sample_weight=weights)
        return self

    def predict_action_scores(self, X: np.ndarray) -> np.ndarray:
        X_scaled = self.scaler.transform(np.asarray(X, dtype=np.float32))
        scores = []
        for spec in self.action_specs:
            scores.append(self.models[spec.key].predict_proba(X_scaled)[:, 1])
        return np.column_stack(scores)

    def feature_importance(self) -> dict[str, float]:
        combined = np.zeros(len(self.feature_columns), dtype=np.float64)
        for model in self.models.values():
            if hasattr(model, "coef_"):
                combined += np.abs(model.coef_[0])
        total = float(combined.sum())
        if total <= 0:
            return {name: 0.0 for name in self.feature_columns}
        return {
            name: float(value / total)
            for name, value in zip(self.feature_columns, combined)
        }


class ActionQualityLogisticModel:
    """Small calibrated accept/reject layer on top of ranked action candidates."""

    def __init__(
        self,
        *,
        feature_columns: list[str],
        c: float = 1.0,
        max_iter: int = 1000,
        class_weight: str | dict | None = "balanced",
        random_state: int = 42,
    ) -> None:
        if not feature_columns:
            raise ValueError("feature_columns must not be empty")
        self.feature_columns = feature_columns
        self.scaler = StandardScaler()
        self.model = LogisticRegression(
            C=c,
            max_iter=max_iter,
            class_weight=class_weight,
            random_state=random_state,
            solver="lbfgs",
        )

    def fit(
        self,
        df: pd.DataFrame,
        *,
        target_column: str = "quality_target",
        sample_weight: np.ndarray | None = None,
    ) -> "ActionQualityLogisticModel":
        if target_column not in df.columns:
            raise RuntimeError(f"Missing quality target column: {target_column}")
        X = np.nan_to_num(
            df[self.feature_columns].to_numpy(dtype=np.float32, copy=True)
        )
        y = (
            pd.to_numeric(df[target_column], errors="coerce")
            .fillna(0.0)
            .to_numpy(dtype=np.int32)
        )
        if np.unique(y).size < 2:
            raise RuntimeError(
                "Quality model requires both positive and negative examples"
            )
        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)
        weights = (
            None
            if sample_weight is None
            else np.asarray(sample_weight, dtype=np.float64)
        )
        self.model.fit(X_scaled, y, sample_weight=weights)
        return self

    def predict_acceptance_proba(self, X: np.ndarray) -> np.ndarray:
        X_scaled = self.scaler.transform(np.asarray(X, dtype=np.float32))
        return self.model.predict_proba(X_scaled)[:, 1]

    def feature_importance(self) -> dict[str, float]:
        weights = np.abs(self.model.coef_[0]).astype(np.float64)
        total = float(weights.sum())
        if total <= 0:
            return {name: 0.0 for name in self.feature_columns}
        return {
            name: float(value / total)
            for name, value in zip(self.feature_columns, weights)
        }


class ActionEdgeRegressor:
    """One-regressor-per-action scorer for post-cost edge ranking."""

    def __init__(
        self,
        *,
        feature_columns: list[str],
        action_specs: list[ActionSpec],
        alpha: float = 1.0,
        random_state: int = 42,
    ) -> None:
        if not feature_columns:
            raise ValueError("feature_columns must not be empty")
        if not action_specs:
            raise ValueError("action_specs must not be empty")
        self.feature_columns = feature_columns
        self.action_specs = action_specs
        self.scaler = StandardScaler()
        self.models = {
            spec.key: Ridge(alpha=alpha, random_state=random_state)
            for spec in action_specs
        }

    def fit(
        self, df: pd.DataFrame, sample_weight: np.ndarray | None = None
    ) -> "ActionEdgeRegressor":
        X = np.nan_to_num(
            df[self.feature_columns].to_numpy(dtype=np.float32, copy=True)
        )
        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)
        weights = (
            None
            if sample_weight is None
            else np.asarray(sample_weight, dtype=np.float64)
        )

        for spec in self.action_specs:
            edge_col = f"edge_{spec.key}_bps"
            if edge_col not in df.columns:
                raise RuntimeError(f"Missing action edge column: {edge_col}")
            y = (
                pd.to_numeric(df[edge_col], errors="coerce")
                .fillna(0.0)
                .to_numpy(dtype=np.float32)
            )
            self.models[spec.key].fit(X_scaled, y, sample_weight=weights)
        return self

    def predict_action_scores(self, X: np.ndarray) -> np.ndarray:
        X_scaled = self.scaler.transform(np.asarray(X, dtype=np.float32))
        scores = []
        for spec in self.action_specs:
            scores.append(self.models[spec.key].predict(X_scaled))
        return np.column_stack(scores)

    def feature_importance(self) -> dict[str, float]:
        combined = np.zeros(len(self.feature_columns), dtype=np.float64)
        for model in self.models.values():
            combined += np.abs(np.asarray(model.coef_, dtype=np.float64))
        total = float(combined.sum())
        if total <= 0:
            return {name: 0.0 for name in self.feature_columns}
        return {
            name: float(value / total)
            for name, value in zip(self.feature_columns, combined)
        }


class ActionRankerXGBoost:
    """One-vs-rest tree-based profitable-after-cost action scorer."""

    def __init__(
        self,
        *,
        feature_columns: list[str],
        action_specs: list[ActionSpec],
        max_depth: int = 4,
        n_estimators: int = 200,
        learning_rate: float = 0.05,
        subsample: float = 0.8,
        colsample_bytree: float = 0.7,
        min_child_weight: float = 25.0,
        reg_alpha: float = 0.1,
        reg_lambda: float = 1.0,
        random_state: int = 42,
        n_jobs: int = 1,
    ) -> None:
        if not feature_columns:
            raise ValueError("feature_columns must not be empty")
        if not action_specs:
            raise ValueError("action_specs must not be empty")
        self.feature_columns = feature_columns
        self.action_specs = action_specs
        self.models = {
            spec.key: XGBClassifier(
                objective="binary:logistic",
                eval_metric="logloss",
                max_depth=max_depth,
                n_estimators=n_estimators,
                learning_rate=learning_rate,
                subsample=subsample,
                colsample_bytree=colsample_bytree,
                min_child_weight=min_child_weight,
                reg_alpha=reg_alpha,
                reg_lambda=reg_lambda,
                random_state=random_state,
                n_jobs=n_jobs,
            )
            for spec in action_specs
        }

    def fit(
        self, df: pd.DataFrame, sample_weight: np.ndarray | None = None
    ) -> "ActionRankerXGBoost":
        X = np.nan_to_num(
            df[self.feature_columns].to_numpy(dtype=np.float32, copy=True)
        )
        weights = (
            None
            if sample_weight is None
            else np.asarray(sample_weight, dtype=np.float64)
        )

        for spec in self.action_specs:
            target_col = f"target_{spec.key}"
            if target_col not in df.columns:
                raise RuntimeError(f"Missing action target column: {target_col}")
            y = df[target_col].to_numpy(dtype=np.int32, copy=False)
            if np.unique(y).size < 2:
                self.models[spec.key] = _ConstantBinaryModel(float(y.mean()))
                continue
            self.models[spec.key].fit(X, y, sample_weight=weights)
        return self

    def predict_action_scores(self, X: np.ndarray) -> np.ndarray:
        features = np.nan_to_num(np.asarray(X, dtype=np.float32))
        scores = []
        for spec in self.action_specs:
            scores.append(self.models[spec.key].predict_proba(features)[:, 1])
        return np.column_stack(scores)

    def feature_importance(self) -> dict[str, float]:
        combined = np.zeros(len(self.feature_columns), dtype=np.float64)
        for model in self.models.values():
            if hasattr(model, "feature_importances_"):
                combined += np.asarray(model.feature_importances_, dtype=np.float64)
        total = float(combined.sum())
        if total <= 0:
            return {name: 0.0 for name in self.feature_columns}
        return {
            name: float(value / total)
            for name, value in zip(self.feature_columns, combined)
        }


def get_action_ranker_feature_columns(
    df: pd.DataFrame,
    *,
    profile: str = "full",
) -> list[str]:
    """Return numeric ML features safe for action-ranker training.

    Excludes forward-return targets and any derived action-label columns to avoid leakage.
    """

    disallowed_prefixes = ("ret_fwd_", "label_", "target_", "edge_", "best_action_")
    disallowed_exact = {
        "ts_epoch",
        "smart_depth",
        "has_depth",
        "l1_bid",
        "l1_ask",
        "l1_bid_size",
        "l1_ask_size",
    }
    cols = []
    for column in df.columns:
        if column.startswith(disallowed_prefixes):
            continue
        if column in disallowed_exact:
            continue
        if df[column].dtype in (np.float64, np.float32, float, int):
            cols.append(column)
    if profile == "full":
        return cols

    allowed = set(_ACTION_RANKER_STABLE_FEATURES)
    if profile == "stable_causal":
        allowed |= _ACTION_RANKER_CAUSAL_FEATURES
    elif profile != "stable":
        raise ValueError(
            f"Unsupported action-ranker feature profile '{profile}'. "
            "Expected one of: full, stable, stable_causal."
        )
    return [column for column in cols if column in allowed]


def action_edge_sample_weights(
    df: pd.DataFrame,
    *,
    edge_column: str = "best_action_edge_bps",
    scale_bps: float = 12.0,
    max_multiplier: float = 3.0,
) -> np.ndarray:
    """Weight rows by action clarity so marginal edges count less than decisive edges."""
    if df.empty:
        return np.array([], dtype=np.float64)
    if edge_column not in df.columns:
        raise RuntimeError(f"Missing edge column for action weights: {edge_column}")
    scale = max(float(scale_bps), 1e-6)
    magnitudes = np.abs(
        pd.to_numeric(df[edge_column], errors="coerce")
        .fillna(0.0)
        .to_numpy(dtype=np.float64)
    )
    multipliers = 0.5 + np.clip(magnitudes / scale, 0.0, float(max_multiplier) - 0.5)
    return multipliers.astype(np.float64)
