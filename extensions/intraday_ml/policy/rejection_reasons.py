"""Standard rejection reason constants for policy instrumentation."""

from __future__ import annotations

REJECT_REASON_BIGMOVE_PROB = "bigmove_prob"
REJECT_REASON_PROB_LONG = "probability"
REJECT_REASON_SCORE_MARGIN = "score_margin"
REJECT_REASON_TOD_PROFILE = "tod_profile"
REJECT_REASON_MIN_EXPECTED_R = "expected_r"
REJECT_REASON_RISK_BUDGET = "risk_budget"
REJECT_REASON_BAR_CAP = "capacity"
REJECT_REASON_OTHER = "other"

REJECTION_REASON_TO_COLUMN: dict[str, str] = {
    REJECT_REASON_BIGMOVE_PROB: "reject_bigmove_prob",
    REJECT_REASON_PROB_LONG: "reject_probability",
    REJECT_REASON_SCORE_MARGIN: "reject_score_margin",
    REJECT_REASON_TOD_PROFILE: "reject_tod_profile",
    REJECT_REASON_MIN_EXPECTED_R: "reject_expected_r",
    REJECT_REASON_RISK_BUDGET: "reject_risk_budget",
    REJECT_REASON_BAR_CAP: "reject_capacity",
    REJECT_REASON_OTHER: "reject_other",
}

_BIGMOVE_PREFIXES = ("bigmove_",)
_BAR_CAP_REASONS = {
    "max_trades_per_bar_reached",
    "max_open_positions_reached",
    "max_entries_reached_global",
    "max_trades_per_symbol_reached",
    "position_exists",
    "holding_long",
    "holding_short",
}
_PROBABILITY_REASONS = {"below_threshold"}
_SCORE_MARGIN_REASONS = {"gap_insufficient", "conviction_low"}
_TOD_REASONS = {"time_filter", "cooldown"}
_EXPECTED_R_REASONS = {"expected_r_low"}
_RISK_BUDGET_REASONS = {"risk_budget_exhausted", "risk_unavailable"}


def categorize_rejection_reason(reason: str | None) -> str:
    """Map a raw rejection reason to a stable bucket for reporting."""
    if not reason:
        return REJECT_REASON_OTHER
    normalized = str(reason).lower()
    if normalized.startswith(_BIGMOVE_PREFIXES):
        return REJECT_REASON_BIGMOVE_PROB
    if normalized in _BAR_CAP_REASONS:
        return REJECT_REASON_BAR_CAP
    if normalized in _RISK_BUDGET_REASONS:
        return REJECT_REASON_RISK_BUDGET
    if normalized in _EXPECTED_R_REASONS:
        return REJECT_REASON_MIN_EXPECTED_R
    if normalized in _TOD_REASONS:
        return REJECT_REASON_TOD_PROFILE
    if normalized in _SCORE_MARGIN_REASONS:
        return REJECT_REASON_SCORE_MARGIN
    if normalized in _PROBABILITY_REASONS or normalized.startswith("strategy_check:"):
        return REJECT_REASON_PROB_LONG
    return REJECT_REASON_OTHER


REJECTION_REASON_KEYS = list(REJECTION_REASON_TO_COLUMN.keys())

__all__ = [
    "REJECT_REASON_BAR_CAP",
    "REJECT_REASON_BIGMOVE_PROB",
    "REJECT_REASON_MIN_EXPECTED_R",
    "REJECT_REASON_OTHER",
    "REJECT_REASON_PROB_LONG",
    "REJECT_REASON_RISK_BUDGET",
    "REJECT_REASON_SCORE_MARGIN",
    "REJECT_REASON_TOD_PROFILE",
    "REJECTION_REASON_KEYS",
    "REJECTION_REASON_TO_COLUMN",
    "categorize_rejection_reason",
]
