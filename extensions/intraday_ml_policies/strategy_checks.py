"""Strategy-specific validation checks for intraday ML policies.

These checks ensure that trades produced by the ML decision policy align with
the desired AVWAP-centric playbooks (momentum, pullback, value rotation,
liquidity sweep) without depending on legacy non-ML policy implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

import pandas as pd

try:  # Import is optional during unit tests that stub regime enums
    from qx_core.schemas import RegimeType
except ModuleNotFoundError:  # pragma: no cover - fallback for isolated tests
    RegimeType = None  # type: ignore[assignment]


Validator = Callable[[pd.Series, str], tuple[bool, str]]


@dataclass(frozen=True)
class StrategyCheck:
    """Encapsulates feature requirements and validator behaviour for a strategy."""

    name: str
    required_columns: tuple[str, ...]
    validator: Validator

    def validate(self, row: pd.Series, side: str) -> tuple[bool, str]:
        """Validate a single prediction row for the desired trading side."""
        missing = [col for col in self.required_columns if col not in row.index]
        if missing:
            return False, f"missing_features:{','.join(sorted(missing))}"

        # Guard against NaNs in the required feature set
        null_cols = [col for col in self.required_columns if pd.isna(row[col])]
        if null_cols:
            return False, f"nan_features:{','.join(sorted(null_cols))}"

        return self.validator(row, side)


def _normalize_regime(value: object) -> str:
    """Normalize regime representation to an uppercase string label."""
    if value is None:
        return "OFF"
    if RegimeType is not None and isinstance(value, RegimeType):
        return value.name
    if isinstance(value, str):
        return value.upper()
    return str(value).upper()


def _momentum_validator(row: pd.Series, side: str) -> tuple[bool, str]:
    regime = _normalize_regime(row.get("f__regime__current"))
    var_ratio = row.get("f__regime__var_ratio_10_60")
    adx = row.get("f__regime__adx_proxy_14")
    avwap = row.get("f__anchor__session_avwap")
    close = row.get("close")

    if side == "long":
        if regime not in {"BULL", "SIDEWAYS"}:
            return False, f"regime_mismatch:{regime}"
        if var_ratio is not None and var_ratio < 1.05:
            return False, f"variance_ratio_low:{var_ratio:.3f}"
        if adx is not None and adx < 18:
            return False, f"adx_low:{adx:.2f}"
        if avwap is not None and close is not None and close <= avwap:
            return False, "price_not_above_session_avwap"
    else:
        if regime not in {"BEAR", "SIDEWAYS"}:
            return False, f"regime_mismatch:{regime}"
        if var_ratio is not None and var_ratio > 0.95:
            return False, f"variance_ratio_high:{var_ratio:.3f}"
        if adx is not None and adx < 18:
            return False, f"adx_low:{adx:.2f}"
        if avwap is not None and close is not None and close >= avwap:
            return False, "price_not_below_session_avwap"

    return True, "momentum_valid"


def _pullback_validator(row: pd.Series, side: str) -> tuple[bool, str]:
    avwap = row.get("f__anchor__session_avwap")
    atr = row.get("f__vol__atr_14")
    close = row.get("close")
    pullback_dev = row.get("f__profile__value_deviation", 0.0)

    if atr is not None and atr <= 0:
        return False, "atr_non_positive"

    if side == "long":
        if avwap is not None and close is not None and close < avwap - (atr or 0):
            return False, "pullback_too_deep"
        if pullback_dev and pullback_dev < -2:
            return False, f"value_deviation_excess:{pullback_dev}"
    else:
        if avwap is not None and close is not None and close > avwap + (atr or 0):
            return False, "rally_too_extended"
        if pullback_dev and pullback_dev > 2:
            return False, f"value_deviation_excess:{pullback_dev}"

    return True, "pullback_valid"


def _value_rotation_validator(row: pd.Series, side: str) -> tuple[bool, str]:
    poc = row.get("f__profile__poc")
    vah = row.get("f__profile__vah")
    val = row.get("f__profile__val")
    close = row.get("close")

    if None in (poc, vah, val, close):
        return False, "value_profile_unavailable"

    if side == "long" and close > poc:
        return False, "price_not_below_poc"
    if side == "short" and close < poc:
        return False, "price_not_above_poc"

    return True, "value_rotation_valid"


def _sweep_reversion_validator(row: pd.Series, side: str) -> tuple[bool, str]:
    sweep_high = bool(row.get("f__ict__liq_sweep_high"))
    sweep_low = bool(row.get("f__ict__liq_sweep_low"))
    ofi_trend = row.get("f__flow__ofi_trend")
    absorption = row.get("f__vpa__absorption")

    if side == "long":
        if not sweep_low:
            return False, "no_liquidity_sweep_low"
        if ofi_trend is not None and ofi_trend <= 0:
            return False, f"ofi_not_supportive:{ofi_trend}"
        if absorption is False:
            return False, "no_absorption"
    else:
        if not sweep_high:
            return False, "no_liquidity_sweep_high"
        if ofi_trend is not None and ofi_trend >= 0:
            return False, f"ofi_not_supportive:{ofi_trend}"
        if absorption is False:
            return False, "no_absorption"

    return True, "sweep_reversion_valid"


DEFAULT_STRATEGIES: dict[str, StrategyCheck] = {
    "momentum": StrategyCheck(
        name="momentum",
        required_columns=(
            "close",
            "f__anchor__session_avwap",
            "f__regime__current",
            "f__regime__var_ratio_10_60",
            "f__regime__adx_proxy_14",
        ),
        validator=_momentum_validator,
    ),
    "pullback": StrategyCheck(
        name="pullback",
        required_columns=(
            "close",
            "f__anchor__session_avwap",
            "f__vol__atr_14",
            "f__profile__value_deviation",
        ),
        validator=_pullback_validator,
    ),
    "value_rotation": StrategyCheck(
        name="value_rotation",
        required_columns=(
            "close",
            "f__profile__poc",
            "f__profile__vah",
            "f__profile__val",
        ),
        validator=_value_rotation_validator,
    ),
    "sweep_reversion": StrategyCheck(
        name="sweep_reversion",
        required_columns=(
            "f__ict__liq_sweep_high",
            "f__ict__liq_sweep_low",
            "f__flow__ofi_trend",
            "f__vpa__absorption",
        ),
        validator=_sweep_reversion_validator,
    ),
}


class StrategyCheckRegistry:
    """Manage enabled strategy checks and perform validation."""

    def __init__(self, enabled: Sequence[str] | None = None):
        enabled = enabled or []
        unknown = [name for name in enabled if name not in DEFAULT_STRATEGIES]
        if unknown:
            raise ValueError(f"Unknown strategy checks requested: {', '.join(unknown)}")

        self._checks: list[StrategyCheck] = [DEFAULT_STRATEGIES[name] for name in enabled]

    @property
    def required_columns(self) -> set[str]:
        """Return the set of all required columns for the enabled strategies."""
        columns: set[str] = set()
        for check in self._checks:
            columns.update(check.required_columns)
        return columns

    def validate(self, row: pd.Series, side: str) -> tuple[bool, str, str]:
        """
        Validate row against enabled strategies.

        Returns:
            tuple(valid, strategy_used, detail)
        """
        if not self._checks:
            return True, "none", "strategy_checks_disabled"

        failure_messages: list[str] = []
        for check in self._checks:
            valid, detail = check.validate(row, side)
            if valid:
                return True, check.name, detail
            failure_messages.append(f"{check.name}:{detail}")

        return False, "all_failed", ";".join(failure_messages)

    def __iter__(self) -> Iterable[StrategyCheck]:  # pragma: no cover - utility
        return iter(self._checks)
