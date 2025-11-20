#!/usr/bin/env python3
"""
Intraday ML Decision Policy for generating execution orders from model predictions.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from numbers import Integral
import math

import pandas as pd

from extensions.intraday_ml.policy.bigmove_policy_adapter import BigMovePolicyAdapter
from extensions.intraday_ml.policy.rejection_reasons import (
    REJECT_REASON_BAR_CAP,
    REJECT_REASON_BIGMOVE_PROB,
    REJECT_REASON_MIN_EXPECTED_R,
    REJECT_REASON_OTHER,
    REJECT_REASON_PROB_LONG,
    REJECT_REASON_RISK_BUDGET,
    REJECT_REASON_SCORE_MARGIN,
    REJECT_REASON_TOD_PROFILE,
    REJECTION_REASON_TO_COLUMN,
    categorize_rejection_reason,
)
from extensions.intraday_ml.policy.tod_utils import build_tod_profiles, get_active_profile
from extensions.intraday_ml.risk_levels import compute_risk_levels

from .calibration import SymbolThresholdCalibrator
from .strategy_checks import StrategyCheckRegistry


@dataclass(frozen=True)
class EntryCandidate:
    symbol: str
    dt_utc: pd.Timestamp
    day_key: tuple[str, pd.Timestamp]
    side: str
    prob_long: float
    prob_short: float
    prob_neutral: float
    directional_gap: float
    conviction_score: float
    expected_r: float
    stop_loss_pct: float
    take_profit_pct: float
    risk_metadata: dict[str, object]
    entry_price: float
    entry_expected_r: float
    score: float
    strategy_name: str
    strategy_detail: str | None
    profile_name: str | None
    prob_bigmove: float | None = None


class IntradayMLDecisionPolicy:
    """
    Translates raw model probabilities into concrete trading decisions with risk controls.

    Gating logic:
    1.  **Position Guard:** Only one open position per symbol at a time.
    2.  **Time Filter:** Trades only allowed within a specified time window.
    3.  **Probability Threshold:** Signal must exceed a configured confidence level.
    4.  **Cooldown:** Minimum time between trades for the same symbol.
    """

    def __init__(self, config: dict):
        # Gating parameters (base fallbacks before calibration overrides)
        self.prob_threshold_long = float(config.get("prob_threshold_long", 0.55))
        self.prob_threshold_short = float(config.get("prob_threshold_short", 0.55))
        self.cooldown_minutes = float(config.get("cooldown_minutes", 30))
        time_filter_cfg = config.get("time_filter", {})
        min_time_str = time_filter_cfg.get("min_time", config.get("min_time", "09:45:00"))
        max_time_str = time_filter_cfg.get("max_time", config.get("max_time", "15:45:00"))
        tz_name = time_filter_cfg.get("timezone", config.get("session_timezone", "America/New_York"))
        self.tod_filter_enabled = bool(config.get("tod_filter_enabled", True))
        self.min_time = pd.to_datetime(min_time_str).time()
        self.max_time = pd.to_datetime(max_time_str).time()
        self.max_hold_minutes = float(config.get("max_hold_minutes", 60))
        self.exit_threshold_long = float(
            config.get("exit_threshold_long", self.prob_threshold_long)
        )
        self.exit_threshold_short = float(
            config.get("exit_threshold_short", self.prob_threshold_short)
        )
        self.score_margin = float(config.get("score_margin", 0.05))
        self.min_directional_gap = float(config.get("min_directional_gap", 0.05))
        self.min_conviction_score = float(config.get("min_conviction_score", 0.0))
        self.max_entries_per_day = self._as_int(config.get("max_entries_per_day"))
        self.max_open_positions_global = self._as_int(config.get("max_open_positions_global"))
        self.max_trades_per_symbol_per_day = self._as_int(
            config.get("max_trades_per_symbol_per_day")
        )
        self.max_trades_per_bar_global = self._as_int(config.get("max_trades_per_bar_global"))
        lifecycle_cfg = config.get("lifecycle", {})
        self.early_loss_cut_r = self._maybe_float(lifecycle_cfg.get("early_loss_cut_r"))
        self.early_loss_cut_minutes = self._as_int(lifecycle_cfg.get("early_loss_cut_minutes"))
        self.dead_trade_exit_minutes = self._as_int(lifecycle_cfg.get("dead_trade_exit_minutes"))
        self.dead_trade_pnl_band_r = self._maybe_float(lifecycle_cfg.get("dead_trade_pnl_band_r"))
        self.max_hold_minutes_flat_or_loser = float(
            lifecycle_cfg.get("max_hold_minutes_flat_or_loser", self.max_hold_minutes)
        )
        self.max_hold_minutes_in_the_money = float(
            lifecycle_cfg.get("max_hold_minutes_in_the_money", self.max_hold_minutes)
        )
        self.trail_activation_r = self._maybe_float(lifecycle_cfg.get("trail_activation_r"))
        self.trail_stop_r = self._maybe_float(lifecycle_cfg.get("trail_stop_r"))
        cooldown_half = max(self.cooldown_minutes / 2.0, 1.0)
        self.gap_exit_delay_minutes = float(
            config.get("gap_exit_delay_minutes", max(5.0, cooldown_half))
        )
        self.force_flat_time = pd.to_datetime(config.get("force_flat_time", "15:59:59")).time()
        self.session_timezone = tz_name
        self.conviction_decay_min_hold_minutes = float(
            config.get(
                "conviction_decay_min_hold_minutes",
                max(self.cooldown_minutes, 15.0),
            )
        )
        self.conviction_decay_gap_multiplier = float(
            config.get("conviction_decay_gap_multiplier", 0.5)
        )
        self.conviction_decay_conv_multiplier = float(
            config.get("conviction_decay_conv_multiplier", 0.5)
        )

        self.global_entries_today = 0
        self.current_trading_day: date | None = None
        self.tod_profiles = build_tod_profiles(config)

        # Order parameters
        self.stop_loss_pct = float(config.get("stop_loss_pct", 0.01))
        self.take_profit_pct = float(config.get("take_profit_pct", 0.015))
        self.order_qty = config.get("order_qty", 100)

        # Dynamic risk management configuration
        risk_cfg = config.get("risk", {})
        self.use_dynamic_risk = True
        self.risk_atr_feature = risk_cfg.get("atr_feature", "f__vol__atr_6")
        self.risk_support_long_feature = risk_cfg.get("support_feature_long", "low")
        self.risk_resistance_short_feature = risk_cfg.get("resistance_feature_short", "high")
        self.risk_stop_atr_multiple = float(
            risk_cfg.get(
                "stop_atr_multiple",
                risk_cfg.get("max_atr_multiple", 1.0),
            )
        )
        self.risk_max_atr_multiple = float(risk_cfg.get("max_atr_multiple", self.risk_stop_atr_multiple))
        self.risk_buffer_atr = float(risk_cfg.get("support_buffer_atr", 0.1))
        self.risk_target_r_multiple = float(
            risk_cfg.get(
                "tp_r_multiple",
                risk_cfg.get("target_r_multiple", 1.5),
            )
        )
        self.risk_target_r_multiple = max(self.risk_target_r_multiple, 1.0)
        self.risk_min_stop_pct = float(risk_cfg.get("min_stop_pct", 0.0005))
        self.risk_max_stop_pct = float(risk_cfg.get("max_stop_pct", 0.05))
        self.risk_allow_missing_support = bool(risk_cfg.get("allow_missing_support", True))
        self.min_expected_r = float(risk_cfg.get("min_expected_r", self.risk_target_r_multiple))
        self._risk_helper_config = {
            "price_column": "close",
            "atr_feature": self.risk_atr_feature,
            "support_feature_long": self.risk_support_long_feature,
            "resistance_feature_short": self.risk_resistance_short_feature,
            "max_atr_multiple": self.risk_max_atr_multiple,
             "stop_atr_multiple": self.risk_stop_atr_multiple,
            "support_buffer_atr": self.risk_buffer_atr,
            "target_r_multiple": self.risk_target_r_multiple,
             "tp_r_multiple": self.risk_target_r_multiple,
            "min_stop_pct": self.risk_min_stop_pct,
            "max_stop_pct": self.risk_max_stop_pct,
            "allow_missing_support": self.risk_allow_missing_support,
        }
        self.max_daily_loss_r = self._maybe_float(config.get("max_daily_loss_R"))
        self.trade_risk_unit = float(config.get("trade_risk_R", 1.0))
        self.daily_realized_r = 0.0

        # State tracking
        self.last_trade_ts: dict[str, pd.Timestamp] = {}  # (symbol -> last trade ts) for cooldown
        self.position_state: dict[
            str, dict[str, object]
        ] = {}  # symbol -> {"side": str, "entry_ts": ts, "entry_gap": float, "entry_conviction": float}
        self.entries_per_day: dict[tuple[str, pd.Timestamp], int] = {}
        self.symbol_thresholds: dict[str, dict[str, float]] = {}
        self.strategy_checks = StrategyCheckRegistry(config.get("enabled_strategies", []))
        self.required_feature_columns = set(self.strategy_checks.required_columns)
        self.required_feature_columns.update(
            {
                "close",
                self.risk_atr_feature,
                self.risk_support_long_feature,
                self.risk_resistance_short_feature,
            }
        )
        self.required_feature_columns.discard(None)
        self._order_seq = 0

        self.base_thresholds = {
            "prob_threshold_long": self.prob_threshold_long,
            "prob_threshold_short": self.prob_threshold_short,
            "exit_threshold_long": self.exit_threshold_long,
            "exit_threshold_short": self.exit_threshold_short,
            "max_hold_minutes": self.max_hold_minutes,
            "score_margin": self.score_margin,
            "min_directional_gap": self.min_directional_gap,
            "min_conviction_score": self.min_conviction_score,
            "max_entries_per_day": self.max_entries_per_day,
            "gap_exit_delay_minutes": self.gap_exit_delay_minutes,
            "min_expected_r": self.min_expected_r,
        }

        calibration_config = config.get("calibration")
        self.calibrator = SymbolThresholdCalibrator(calibration_config, self.base_thresholds)

        self.policy_mode = str(config.get("policy_mode", "baseline")).lower()
        self.bigmove_adapter: BigMovePolicyAdapter | None = None
        if self.policy_mode == "bigmove":
            self.bigmove_adapter = BigMovePolicyAdapter(config.get("bigmove_policy"))
        self._rejection_reason_counts: Counter[str] = Counter()

    def process_signals(self, signals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Processes a DataFrame of signals to generate orders and rejection logs.

        Args:
            signals: DataFrame containing at minimum ['ts' or 'timestamp', 'symbol',
                'prob_long', 'prob_short', 'prob_neutral'] along with any feature
                columns required by enabled strategy checks.

        Returns:
            Tuple of (orders_df, rejections_df).
        """
        self._reset_rejection_reason_counts()
        prepared = self._prepare_signals(signals)
        orders: list[dict[str, object]] = []
        rejections: list[dict[str, object]] = []

        if prepared.empty:
            return self._finalize_orders(orders), self._finalize_rejections(rejections)

        grouped = prepared.groupby("ts", sort=True)
        for _, group in grouped:
            entry_candidates: list[EntryCandidate] = []
            entries_this_bar = 0
            for _, row in group.iterrows():
                dt_utc: pd.Timestamp = row["ts"]
                symbol = row["symbol"]
                dt_et = dt_utc.tz_convert(self.session_timezone)
                self._sync_trading_day(dt_et.date())
                day_key = (symbol, pd.Timestamp(dt_et.date()))
                stop_loss_pct_dynamic: float | None = None
                take_profit_pct_dynamic: float | None = None
                risk_metadata: dict[str, object] | None = None
                side: str | None = None
                exit_reason: str | None = None

                if self._force_flat_if_needed(symbol, dt_utc, dt_et, orders):
                    self.last_trade_ts[symbol] = dt_utc
                    continue

                prob_long = float(row.get("prob_long", 0.0))
                prob_short = float(row.get("prob_short", 0.0))
                prob_neutral = float(row.get("prob_neutral", 0.0))
                directional_gap = abs(prob_long - prob_short)
                conviction_score = directional_gap * max(prob_long, prob_short)

                thresholds = self._get_thresholds(symbol)
                exit_threshold_long = thresholds["exit_threshold_long"]
                exit_threshold_short = thresholds["exit_threshold_short"]
                max_hold_minutes = thresholds["max_hold_minutes"]
                score_margin = thresholds["score_margin"]
                min_directional_gap = thresholds["min_directional_gap"]
                min_conviction_score = thresholds["min_conviction_score"]
                gap_exit_delay = thresholds.get("gap_exit_delay_minutes", self.gap_exit_delay_minutes)
                gap_exit_delay = float(gap_exit_delay) if gap_exit_delay is not None else None

                current_time = dt_et.time()
                profile = get_active_profile(self.tod_profiles, current_time)

                if self.tod_filter_enabled and not (self.min_time <= current_time <= self.max_time):
                    self._append_rejection_record(
                        rejections,
                        dt_utc,
                        symbol,
                        "time_filter",
                        prob_long=prob_long,
                        prob_short=prob_short,
                        directional_gap=directional_gap,
                        reason_key=REJECT_REASON_TOD_PROFILE,
                    )
                    continue

                cooldown_duration = pd.Timedelta(minutes=self.cooldown_minutes)
                last_trade = self.last_trade_ts.get(symbol)
                if last_trade is not None and (dt_utc - last_trade) < cooldown_duration:
                    self._append_rejection_record(
                        rejections,
                        dt_utc,
                        symbol,
                        "cooldown",
                        prob_long=prob_long,
                        prob_short=prob_short,
                        directional_gap=directional_gap,
                        reason_key=REJECT_REASON_TOD_PROFILE,
                    )
                    continue

                position = self.position_state.get(symbol)
                hold_duration = None
                pnl_r: float | None = None
                current_price = self._clean_float(row.get("close"))
                if position:
                    hold_duration = (dt_utc - position["entry_ts"]).total_seconds() / 60.0
                    entry_gap = float(position.get("entry_gap", directional_gap))
                    entry_conviction = float(position.get("entry_conviction", conviction_score))
                    if current_price is not None:
                        pnl_r = self._compute_position_pnl_r(position, current_price)
                else:
                    entry_gap = directional_gap
                    entry_conviction = conviction_score

                    gap_threshold = max(
                        min_directional_gap,
                        entry_gap * self.conviction_decay_gap_multiplier,
                    )
                    if entry_gap <= 0:
                        gap_threshold = min_directional_gap
                    conviction_threshold = min_conviction_score
                    if entry_conviction > 0:
                        conviction_threshold = max(
                            min_conviction_score,
                            entry_conviction * self.conviction_decay_conv_multiplier,
                        )
                    shrinkage_trigger = directional_gap <= gap_threshold
                    if min_conviction_score > 0.0:
                        shrinkage_trigger = shrinkage_trigger or (
                            conviction_score <= conviction_threshold
                        )

                hold_threshold = self.conviction_decay_min_hold_minutes
                if gap_exit_delay is not None:
                    hold_threshold = max(hold_threshold, gap_exit_delay)

                hold_limit = max_hold_minutes
                if pnl_r is not None:
                    if pnl_r >= 1.0:
                        hold_limit = max(hold_limit, self.max_hold_minutes_in_the_money)
                    elif pnl_r <= 0.0:
                        hold_limit = min(hold_limit, self.max_hold_minutes_flat_or_loser)

                exit_decision = self._evaluate_position_exit(
                    position=position,
                    pnl_r=pnl_r,
                    hold_duration=hold_duration,
                    hold_threshold=hold_threshold,
                    hold_limit=hold_limit,
                    shrinkage_trigger=shrinkage_trigger,
                    prob_long=prob_long,
                    prob_short=prob_short,
                    exit_threshold_long=exit_threshold_long,
                    exit_threshold_short=exit_threshold_short,
                )

                if exit_decision is not None:
                    side, exit_reason = exit_decision
                elif position:
                    hold_reason = "holding_short" if position["side"] == "short" else "holding_long"
                    self._append_rejection_record(
                        rejections,
                        dt_utc,
                        symbol,
                        hold_reason,
                        prob_long=prob_long,
                        prob_short=prob_short,
                        directional_gap=directional_gap,
                        reason_key=REJECT_REASON_BAR_CAP,
                    )
                    continue
                else:
                    candidate = self._evaluate_entry_candidate(
                        row=row,
                        dt_utc=dt_utc,
                        symbol=symbol,
                        day_key=day_key,
                        thresholds=thresholds,
                        profile=profile,
                        prob_long=prob_long,
                        prob_short=prob_short,
                        prob_neutral=prob_neutral,
                        directional_gap=directional_gap,
                        conviction_score=conviction_score,
                        score_margin=score_margin,
                        rejections=rejections,
                    )
                    if candidate is not None:
                        entry_candidates.append(candidate)
                    continue

                if side is None:
                    continue

                qty = int(position.get("qty", self.order_qty))
                strategy_name = "exit"
                strategy_detail = exit_reason or "exit"
                self.position_state.pop(symbol, None)
                stop_loss_pct_dynamic = position.get("entry_stop_pct")
                take_profit_pct_dynamic = position.get("entry_take_profit_pct")

                order = self._build_order(
                    symbol=symbol,
                    dt_utc=dt_utc,
                    side=side,
                    qty=qty,
                    reason=exit_reason or "exit",
                    strategy=strategy_name,
                    strategy_detail=strategy_detail,
                    stop_loss_pct=stop_loss_pct_dynamic,
                    take_profit_pct=take_profit_pct_dynamic,
                    metadata=None,
                )
                orders.append(order)
                if pnl_r is not None:
                    self.daily_realized_r += pnl_r
                self.last_trade_ts[symbol] = dt_utc

            entries_this_bar = self._apply_entry_candidates(
                entry_candidates,
                entries_this_bar,
                orders,
                rejections,
            )

        return self._finalize_orders(orders), self._finalize_rejections(rejections)

    def get_required_feature_columns(self) -> set[str]:
        """Return the set of feature columns required by enabled strategy checks."""
        return set(self.required_feature_columns)

    def _finalize_orders(self, orders: list[dict[str, object]]) -> pd.DataFrame:
        orders_df = pd.DataFrame(orders)
        if not orders_df.empty:
            orders_df["timestamp"] = pd.to_datetime(orders_df["timestamp"], utc=True)
            orders_df["ts"] = orders_df["timestamp"].astype("int64")
            return orders_df
        return pd.DataFrame(
            columns=[
                "ts",
                "timestamp",
                "symbol",
                "side",
                "qty",
                "stop_loss_pct",
                "take_profit_pct",
                "reason",
                "strategy",
                "strategy_detail",
            ]
        )

    def _finalize_rejections(self, rejections: list[dict[str, object]]) -> pd.DataFrame:
        rejection_columns = [
            "ts",
            "timestamp",
            "symbol",
            "reason",
            "prob_long",
            "prob_short",
            "directional_gap",
            "atr_stop",
            "atr_target",
            "expected_R",
            "gap_reason",
        ]
        rejections_df = pd.DataFrame(rejections)
        if rejections_df.empty:
            return pd.DataFrame(columns=rejection_columns)

        rejections_df["timestamp"] = pd.to_datetime(rejections_df["timestamp"], utc=True)
        rejections_df["ts"] = rejections_df["timestamp"].astype("int64")
        for column in rejection_columns:
            if column not in rejections_df.columns:
                rejections_df[column] = pd.NA
        ordered_columns = rejection_columns + [
            col for col in rejections_df.columns if col not in rejection_columns
        ]
        return rejections_df[ordered_columns]

    def get_rejection_reason_counts(self) -> dict[str, int]:
        """Return aggregated rejection counters keyed by canonical reason."""
        return {
            key: int(self._rejection_reason_counts.get(key, 0))
            for key in REJECTION_REASON_TO_COLUMN
        }

    def _reset_rejection_reason_counts(self) -> None:
        self._rejection_reason_counts.clear()

    def _increment_rejection_reason(self, reason_key: str | None) -> None:
        key = reason_key or REJECT_REASON_OTHER
        if key not in REJECTION_REASON_TO_COLUMN:
            key = REJECT_REASON_OTHER
        self._rejection_reason_counts[key] += 1

    def _append_rejection_record(
        self,
        rejections: list[dict[str, object]],
        dt_utc: pd.Timestamp,
        symbol: str,
        reason: str,
        *,
        prob_long: float | None = None,
        prob_short: float | None = None,
        directional_gap: float | None = None,
        stop_pct: float | None = None,
        take_pct: float | None = None,
        expected_r: float | None = None,
        gap_reason: str | None = None,
        prob_bigmove: float | None = None,
        reason_key: str | None = None,
    ) -> None:
        resolved_key = reason_key or categorize_rejection_reason(reason)
        self._increment_rejection_reason(resolved_key)
        rejections.append(
            self._rejection_record(
                dt_utc,
                symbol,
                reason,
                context=self._build_rejection_context(
                    prob_long=prob_long,
                    prob_short=prob_short,
                    directional_gap=directional_gap,
                    stop_pct=stop_pct,
                    take_pct=take_pct,
                    expected_r=expected_r,
                    gap_reason=gap_reason,
                    prob_bigmove=prob_bigmove,
                ),
            )
        )

    def _append_candidate_rejection(
        self,
        rejections: list[dict[str, object]],
        candidate: EntryCandidate,
        reason: str,
        *,
        reason_key: str | None = None,
    ) -> None:
        self._append_rejection_record(
            rejections,
            candidate.dt_utc,
            candidate.symbol,
            reason,
            prob_long=candidate.prob_long,
            prob_short=candidate.prob_short,
            directional_gap=candidate.directional_gap,
            stop_pct=candidate.stop_loss_pct,
            take_pct=candidate.take_profit_pct,
            expected_r=candidate.expected_r,
            prob_bigmove=candidate.prob_bigmove,
            reason_key=reason_key,
        )

    def _entry_block_reason(self, entries_this_bar: int) -> str | None:
        if self.max_trades_per_bar_global and entries_this_bar >= self.max_trades_per_bar_global:
            return "max_trades_per_bar_reached"
        if self.max_open_positions_global and len(self.position_state) >= self.max_open_positions_global:
            return "max_open_positions_reached"
        if self.max_entries_per_day and self.global_entries_today >= self.max_entries_per_day:
            return "max_entries_reached_global"
        return None

    def _apply_entry_candidates(
        self,
        entry_candidates: list[EntryCandidate],
        entries_this_bar: int,
        orders: list[dict[str, object]],
        rejections: list[dict[str, object]],
    ) -> int:
        if not entry_candidates:
            return entries_this_bar

        entry_candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        for candidate in entry_candidates:
            block_reason = self._entry_block_reason(entries_this_bar)
            symbol_day_count = self.entries_per_day.get(candidate.day_key, 0)
            if block_reason:
                self._append_candidate_rejection(
                    rejections,
                    candidate,
                    block_reason,
                    reason_key=REJECT_REASON_BAR_CAP,
                )
                continue
            if (
                self.max_trades_per_symbol_per_day
                and symbol_day_count >= self.max_trades_per_symbol_per_day
            ):
                self._append_candidate_rejection(
                    rejections,
                    candidate,
                    "max_trades_per_symbol_reached",
                    reason_key=REJECT_REASON_BAR_CAP,
                )
                continue
            if candidate.symbol in self.position_state:
                self._append_candidate_rejection(
                    rejections,
                    candidate,
                    "position_exists",
                    reason_key=REJECT_REASON_BAR_CAP,
                )
                continue

            metadata = dict(candidate.risk_metadata)
            if candidate.profile_name:
                metadata.setdefault("tod_profile", candidate.profile_name)

            qty = int(self.order_qty)
            order = self._build_order(
                symbol=candidate.symbol,
                dt_utc=candidate.dt_utc,
                side=candidate.side,
                qty=qty,
                reason="trade",
                strategy=candidate.strategy_name,
                strategy_detail=candidate.strategy_detail or "trade",
                stop_loss_pct=candidate.stop_loss_pct,
                take_profit_pct=candidate.take_profit_pct,
                metadata=metadata,
            )
            orders.append(order)
            entries_this_bar += 1
            self.global_entries_today += 1
            self.entries_per_day[candidate.day_key] = symbol_day_count + 1
            self.position_state[candidate.symbol] = {
                "side": candidate.side,
                "entry_ts": candidate.dt_utc,
                "qty": qty,
                "entry_gap": candidate.directional_gap,
                "entry_conviction": candidate.conviction_score,
                "entry_stop_pct": candidate.stop_loss_pct,
                "entry_take_profit_pct": candidate.take_profit_pct,
                "entry_price": candidate.entry_price,
                "entry_expected_r": candidate.entry_expected_r,
            }
            self.last_trade_ts[candidate.symbol] = candidate.dt_utc
        return entries_this_bar

    def _sync_trading_day(self, trading_day: date) -> None:
        if self.current_trading_day == trading_day:
            return
        self.current_trading_day = trading_day
        self.global_entries_today = 0
        self.daily_realized_r = 0.0
        self.entries_per_day = {
            key: value
            for key, value in self.entries_per_day.items()
            if key[1].date() == trading_day
        }

    def _evaluate_position_exit(
        self,
        *,
        position: dict[str, object] | None,
        pnl_r: float | None,
        hold_duration: float | None,
        hold_threshold: float,
        hold_limit: float,
        shrinkage_trigger: bool,
        prob_long: float,
        prob_short: float,
        exit_threshold_long: float,
        exit_threshold_short: float,
    ) -> tuple[str, str] | None:
        if not position:
            return None

        flatten_side = "long" if position["side"] == "short" else "short"
        if (
            self.early_loss_cut_r is not None
            and self.early_loss_cut_minutes is not None
            and pnl_r is not None
            and hold_duration is not None
            and hold_duration <= self.early_loss_cut_minutes
            and pnl_r <= -self.early_loss_cut_r
        ):
            return flatten_side, "early_loss_cut"

        if (
            self.dead_trade_exit_minutes is not None
            and self.dead_trade_pnl_band_r is not None
            and pnl_r is not None
            and hold_duration is not None
            and hold_duration >= self.dead_trade_exit_minutes
            and abs(pnl_r) <= self.dead_trade_pnl_band_r
        ):
            return flatten_side, "dead_trade_exit"

        if (
            self.trail_activation_r is not None
            and self.trail_stop_r is not None
            and pnl_r is not None
            and pnl_r >= self.trail_activation_r
            and pnl_r <= self.trail_stop_r
        ):
            return flatten_side, "trail_stop"

        if (
            hold_duration is not None
            and hold_duration >= hold_threshold
            and shrinkage_trigger
        ):
            return flatten_side, "conviction_decay"

        time_stop_trigger = hold_duration is not None and hold_duration >= hold_limit
        if position["side"] == "short":
            exit_signal = prob_long >= exit_threshold_long or time_stop_trigger
            if exit_signal:
                reason = "flatten_short"
                if time_stop_trigger and (pnl_r is None or pnl_r <= 0.0):
                    reason = "time_stop"
                return "long", reason
        else:
            exit_signal = prob_short >= exit_threshold_short or time_stop_trigger
            if exit_signal:
                reason = "flatten_long"
                if time_stop_trigger and (pnl_r is None or pnl_r <= 0.0):
                    reason = "time_stop"
                return "short", reason

        return None

    def _evaluate_entry_candidate(
        self,
        *,
        row: pd.Series,
        dt_utc: pd.Timestamp,
        symbol: str,
        day_key: tuple[str, pd.Timestamp],
        thresholds: dict[str, float],
        profile,
        prob_long: float,
        prob_short: float,
        prob_neutral: float,
        directional_gap: float,
        conviction_score: float,
        score_margin: float,
        rejections: list[dict[str, object]],
    ) -> EntryCandidate | None:
        if self.max_entries_per_day and self.global_entries_today >= self.max_entries_per_day:
            self._append_rejection_record(
                rejections,
                dt_utc,
                symbol,
                "max_entries_reached_global",
                prob_long=prob_long,
                prob_short=prob_short,
                directional_gap=directional_gap,
                reason_key=REJECT_REASON_BAR_CAP,
            )
            return None

        if (
            self.max_trades_per_symbol_per_day
            and self.entries_per_day.get(day_key, 0) >= self.max_trades_per_symbol_per_day
        ):
            self._append_rejection_record(
                rejections,
                dt_utc,
                symbol,
                "max_trades_per_symbol_reached",
                prob_long=prob_long,
                prob_short=prob_short,
                directional_gap=directional_gap,
                reason_key=REJECT_REASON_BAR_CAP,
            )
            return None

        if self.max_daily_loss_r is not None:
            projected = self.daily_realized_r - self.trade_risk_unit
            if projected < self.max_daily_loss_r:
                self._append_rejection_record(
                    rejections,
                    dt_utc,
                    symbol,
                    "risk_budget_exhausted",
                    prob_long=prob_long,
                    prob_short=prob_short,
                    directional_gap=directional_gap,
                    reason_key=REJECT_REASON_RISK_BUDGET,
                )
                return None

        bigmove_prob = self._clean_float(row.get("prob_bigmove"))
        if self.bigmove_adapter is not None:
            bigmove_allowed = bool(row.get("_bigmove_allowed", False))
            if not bigmove_allowed:
                self._append_rejection_record(
                    rejections,
                    dt_utc,
                    symbol,
                    "bigmove_prob_below_threshold",
                    prob_long=prob_long,
                    prob_short=prob_short,
                    directional_gap=directional_gap,
                    expected_r=self._clean_float(row.get("_bigmove_expected_r")),
                    prob_bigmove=bigmove_prob,
                    reason_key=REJECT_REASON_BIGMOVE_PROB,
                )
                return None
            if bigmove_prob is None:
                self._append_rejection_record(
                    rejections,
                    dt_utc,
                    symbol,
                    "bigmove_signal_missing",
                    prob_long=prob_long,
                    prob_short=prob_short,
                    directional_gap=directional_gap,
                    reason_key=REJECT_REASON_BIGMOVE_PROB,
                )
                return None

        entry_price = self._clean_float(row.get("close"))
        if entry_price is None or entry_price <= 0.0:
            return None

        base_gap = thresholds.get("min_directional_gap", self.min_directional_gap)
        base_conv = thresholds.get("min_conviction_score", self.min_conviction_score)
        base_expected_r = thresholds.get("min_expected_r", self.min_expected_r)

        prob_threshold_long = self._apply_profile_override(
            thresholds.get("prob_threshold_long", self.prob_threshold_long),
            profile,
            "prob_threshold_long",
        )
        prob_threshold_short = self._apply_profile_override(
            thresholds.get("prob_threshold_short", self.prob_threshold_short),
            profile,
            "prob_threshold_short",
        )
        min_gap_long = self._apply_profile_override(base_gap, profile, "min_directional_gap_long")
        min_gap_short = self._apply_profile_override(base_gap, profile, "min_directional_gap_short")
        min_conv_long = self._apply_profile_override(base_conv, profile, "min_conviction_long")
        min_conv_short = self._apply_profile_override(base_conv, profile, "min_conviction_short")
        min_expected_r_long = self._apply_profile_override(base_expected_r, profile, "min_expected_r_long")
        min_expected_r_short = self._apply_profile_override(
            base_expected_r, profile, "min_expected_r_short"
        )

        long_score = prob_long - max(prob_short, prob_neutral)
        short_score = prob_short - max(prob_long, prob_neutral)
        long_allowed = (
            prob_long >= prob_threshold_long
            and long_score >= score_margin
            and prob_long > prob_short
            and directional_gap >= min_gap_long
            and (min_conv_long == 0.0 or conviction_score >= min_conv_long)
        )
        short_allowed = (
            prob_short >= prob_threshold_short
            and short_score >= score_margin
            and prob_short > prob_long
            and directional_gap >= min_gap_short
            and (min_conv_short == 0.0 or conviction_score >= min_conv_short)
        )

        side: str | None
        min_expected_r_required: float
        if long_allowed and short_allowed:
            side = "long" if prob_long >= prob_short else "short"
        elif long_allowed:
            side = "long"
        elif short_allowed:
            side = "short"
        else:
            if directional_gap < min(min_gap_long, min_gap_short):
                reason = "gap_insufficient"
                gap_reason = "directional_gap"
                reason_bucket = REJECT_REASON_SCORE_MARGIN
            elif (min_conv_long > 0 or min_conv_short > 0) and conviction_score < min(
                value for value in (min_conv_long, min_conv_short) if value > 0
            ):
                reason = "conviction_low"
                gap_reason = "conviction"
                reason_bucket = REJECT_REASON_SCORE_MARGIN
            else:
                reason = "below_threshold"
                gap_reason = "probability"
                reason_bucket = REJECT_REASON_PROB_LONG
            self._append_rejection_record(
                rejections,
                dt_utc,
                symbol,
                reason,
                prob_long=prob_long,
                prob_short=prob_short,
                directional_gap=directional_gap,
                gap_reason=gap_reason,
                reason_key=reason_bucket,
            )
            return None

        min_expected_r_required = (
            min_expected_r_long if side == "long" else min_expected_r_short
        )
        risk_calc = self._compute_risk_targets(row, side)
        if risk_calc is None:
            self._append_rejection_record(
                rejections,
                dt_utc,
                symbol,
                "risk_unavailable",
                prob_long=prob_long,
                prob_short=prob_short,
                directional_gap=directional_gap,
                gap_reason="risk",
                reason_key=REJECT_REASON_RISK_BUDGET,
            )
            return None
        stop_loss_pct, take_profit_pct, risk_metadata = risk_calc
        expected_r_value = risk_metadata.get("expected_r")
        if self.bigmove_adapter is not None:
            bigmove_expected_r = self._clean_float(row.get("_bigmove_expected_r"))
            if bigmove_expected_r is not None:
                base_value = expected_r_value if expected_r_value is not None else 0.0
                expected_r_value = max(base_value, bigmove_expected_r)
                risk_metadata["bigmove_expected_r"] = bigmove_expected_r
        if (
            expected_r_value is None
            or not math.isfinite(expected_r_value)
            or expected_r_value < min_expected_r_required
        ):
            self._append_rejection_record(
                rejections,
                dt_utc,
                symbol,
                "expected_r_low",
                prob_long=prob_long,
                prob_short=prob_short,
                directional_gap=directional_gap,
                stop_pct=stop_loss_pct,
                take_pct=take_profit_pct,
                expected_r=expected_r_value,
                gap_reason="expected_r",
                reason_key=REJECT_REASON_MIN_EXPECTED_R,
            )
            return None

        valid_strategy, strategy_name, strategy_detail = self.strategy_checks.validate(row, side)
        if not valid_strategy:
            self._append_rejection_record(
                rejections,
                dt_utc,
                symbol,
                f"strategy_check:{strategy_detail}",
                prob_long=prob_long,
                prob_short=prob_short,
                directional_gap=directional_gap,
                reason_key=REJECT_REASON_OTHER,
            )
            return None

        score = self._compute_candidate_score(
            prob_long=prob_long,
            prob_short=prob_short,
            prob_neutral=prob_neutral,
            directional_gap=directional_gap,
            conviction_score=conviction_score,
            expected_r=expected_r_value,
        )
        profile_name = profile.name if profile else None
        return EntryCandidate(
            symbol=symbol,
            dt_utc=dt_utc,
            day_key=day_key,
            side=side,
            prob_long=prob_long,
            prob_short=prob_short,
            prob_neutral=prob_neutral,
            directional_gap=directional_gap,
            conviction_score=conviction_score,
            expected_r=float(expected_r_value),
            stop_loss_pct=float(stop_loss_pct),
            take_profit_pct=float(take_profit_pct),
            risk_metadata=dict(risk_metadata),
            entry_price=float(entry_price),
            entry_expected_r=float(expected_r_value),
            score=score,
            strategy_name=strategy_name,
            strategy_detail=strategy_detail,
            profile_name=profile_name,
            prob_bigmove=bigmove_prob,
        )

    @staticmethod
    def _apply_profile_override(
        base_value: float,
        profile,
        key: str,
    ) -> float:
        if profile and key in profile.thresholds:
            return float(profile.thresholds[key])
        return float(base_value)

    @staticmethod
    def _compute_candidate_score(
        *,
        prob_long: float,
        prob_short: float,
        prob_neutral: float,
        directional_gap: float,
        conviction_score: float,
        expected_r: float,
    ) -> float:
        prob_max = max(prob_long, prob_short, prob_neutral)
        return (
            max(prob_max, 0.0)
            * max(directional_gap, 0.0)
            * max(conviction_score, 0.0)
            * max(expected_r, 0.0)
        )

    @staticmethod
    def _maybe_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric):
            return None
        return numeric

    @staticmethod
    def _as_int(value: object) -> int | None:
        if value is None:
            return None
        try:
            result = int(value)
        except (TypeError, ValueError):
            return None
        return result

    def _compute_position_pnl_r(
        self,
        position: dict[str, object],
        current_price: float,
    ) -> float | None:
        entry_price = self._clean_float(position.get("entry_price"))
        stop_pct = self._clean_float(position.get("entry_stop_pct"))
        if entry_price is None or stop_pct is None or stop_pct <= 0.0:
            return None
        direction = 1.0 if position.get("side") == "long" else -1.0
        price_diff = (current_price - entry_price) * direction
        return price_diff / (entry_price * stop_pct)

    def _prepare_signals(self, signals: pd.DataFrame) -> pd.DataFrame:
        """Standardise signal DataFrame and ensure UTC nanosecond timestamps."""
        if "ts" not in signals.columns:
            if "timestamp" in signals.columns:
                signals = signals.rename(columns={"timestamp": "ts"})
            else:
                raise KeyError("Signals DataFrame must contain either 'ts' or 'timestamp'")

        prepared = signals.copy()
        if self.bigmove_adapter is not None:
            prepared = self.bigmove_adapter.transform(prepared)

        def _normalize(value: object) -> pd.Timestamp:
            if isinstance(value, pd.Timestamp):
                ts = value
            elif isinstance(value, Integral):
                ts = pd.to_datetime(int(value), utc=True, unit="ns")
            else:
                ts = pd.to_datetime(value, errors="raise")

            if ts.tzinfo is None:
                ts = ts.tz_localize(self.session_timezone)
            return ts.tz_convert("UTC")

        prepared["ts"] = prepared["ts"].apply(_normalize)
        prepared = prepared.sort_values("ts").reset_index(drop=True)
        return prepared

    def _force_flat_if_needed(
        self,
        symbol: str,
        dt_utc: pd.Timestamp,
        dt_et: pd.Timestamp,
        orders: list[dict[str, object]],
    ) -> bool:
        """Force-close open positions beyond the configured flat time."""
        position = self.position_state.get(symbol)
        if not position:
            return False

        if dt_et.time() < self.force_flat_time:
            return False

        side = "long" if position["side"] == "short" else "short"
        qty = int(position.get("qty", self.order_qty))
        order = self._build_order(
            symbol=symbol,
            dt_utc=dt_utc,
            side=side,
            qty=qty,
            reason="force_flat",
            strategy="force_flat",
            strategy_detail="session_close",
            stop_loss_pct=position.get("entry_stop_pct"),
            take_profit_pct=position.get("entry_take_profit_pct"),
        )
        orders.append(order)
        self.position_state.pop(symbol, None)
        return True

    @staticmethod
    def _rejection_record(
        dt_utc: pd.Timestamp,
        symbol: str,
        reason: str,
        *,
        context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Create a rejection record."""
        record: dict[str, object] = {
            "timestamp": dt_utc,
            "ts": dt_utc.value,
            "symbol": symbol,
            "reason": reason,
        }
        if context:
            for key, value in context.items():
                record.setdefault(key, value)
        return record

    def _build_rejection_context(
        self,
        *,
        prob_long: float | None,
        prob_short: float | None,
        directional_gap: float | None,
        stop_pct: float | None = None,
        take_pct: float | None = None,
        expected_r: float | None = None,
        gap_reason: str | None = None,
        prob_bigmove: float | None = None,
    ) -> dict[str, object]:
        """Assemble diagnostic payload for a rejection record."""
        context = {
            "prob_long": self._clean_float(prob_long),
            "prob_short": self._clean_float(prob_short),
            "directional_gap": self._clean_float(directional_gap),
            "atr_stop": self._clean_float(stop_pct),
            "atr_target": self._clean_float(take_pct),
            "expected_R": self._clean_float(expected_r),
        }
        if gap_reason:
            context["gap_reason"] = gap_reason
        if prob_bigmove is not None:
            context["prob_bigmove"] = self._clean_float(prob_bigmove)
        return context

    @staticmethod
    def _clean_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric):
            return None
        return numeric

    def _get_numeric(self, row: pd.Series, column: str | None) -> float | None:
        if not column or column not in row:
            return None
        value = row[column]
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric):
            return None
        return numeric

    def _compute_risk_targets(
        self, row: pd.Series, side: str
    ) -> tuple[float, float, dict[str, object]] | None:
        risk_levels = compute_risk_levels(
            row=row,
            side=side,
            config=self._risk_helper_config,
        )
        if risk_levels is None:
            return None

        metadata = dict(risk_levels.metadata)
        if "expected_r" not in metadata:
            metadata["expected_r"] = risk_levels.expected_r
        metadata.setdefault("risk_r_multiple", self.risk_target_r_multiple)
        return risk_levels.stop_pct, risk_levels.take_profit_pct, metadata

    def _build_order(
        self,
        symbol: str,
        dt_utc: pd.Timestamp,
        side: str,
        qty: int,
        reason: str,
        strategy: str,
        strategy_detail: str | None = None,
        *,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Construct a deterministic order dictionary."""
        sl_pct = float(stop_loss_pct) if stop_loss_pct is not None else self.stop_loss_pct
        tp_pct = float(take_profit_pct) if take_profit_pct is not None else self.take_profit_pct

        order = {
            "ts": dt_utc.value,
            "timestamp": dt_utc,
            "symbol": symbol,
            "side": side,
            "qty": int(qty),
            "stop_loss_pct": sl_pct,
            "take_profit_pct": tp_pct,
            "reason": reason,
            "strategy": strategy,
            "strategy_detail": strategy_detail or reason,
        }

        order_id = f"ml_order_{int(dt_utc.value)}_{self._order_seq:04d}"
        self._order_seq += 1
        order["order_id"] = order_id
        order["signal_ts"] = dt_utc.value
        order["signal_timestamp"] = dt_utc

        if metadata:
            for key, value in metadata.items():
                if key not in order:
                    order[key] = value

        return order

    def _get_thresholds(self, symbol: str) -> dict[str, float]:
        """Retrieve (or cache) thresholds for the given symbol."""
        if symbol not in self.symbol_thresholds:
            self.symbol_thresholds[symbol] = self.calibrator.get_thresholds(symbol)
        return self.symbol_thresholds[symbol]
