#!/usr/bin/env python3
"""
Intraday ML Decision Policy for generating execution orders from model predictions.
"""

from __future__ import annotations

from numbers import Integral

import pandas as pd

from .calibration import SymbolThresholdCalibrator
from .strategy_checks import StrategyCheckRegistry


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
        self.min_time = pd.to_datetime(config.get("min_time", "09:45:00")).time()
        self.max_time = pd.to_datetime(config.get("max_time", "15:45:00")).time()
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
        self.max_entries_per_day = config.get("max_entries_per_day")
        cooldown_half = max(self.cooldown_minutes / 2.0, 1.0)
        self.gap_exit_delay_minutes = float(
            config.get("gap_exit_delay_minutes", max(5.0, cooldown_half))
        )
        self.force_flat_time = pd.to_datetime(config.get("force_flat_time", "15:59:59")).time()
        self.session_timezone = config.get("session_timezone", "America/New_York")

        # Order parameters
        self.stop_loss_pct = float(config.get("stop_loss_pct", 0.01))
        self.take_profit_pct = float(config.get("take_profit_pct", 0.015))
        self.order_qty = config.get("order_qty", 100)

        # State tracking
        self.last_trade_ts: dict[str, pd.Timestamp] = {}  # (symbol -> last trade ts) for cooldown
        self.position_state: dict[
            str, dict[str, object]
        ] = {}  # symbol -> {"side": str, "entry_ts": ts}
        self.entries_per_day: dict[tuple[str, pd.Timestamp], int] = {}
        self.symbol_thresholds: dict[str, dict[str, float]] = {}
        self.strategy_checks = StrategyCheckRegistry(config.get("enabled_strategies", []))
        self.required_feature_columns = set(self.strategy_checks.required_columns)

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
        }

        calibration_config = config.get("calibration")
        self.calibrator = SymbolThresholdCalibrator(calibration_config, self.base_thresholds)

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
        prepared = self._prepare_signals(signals)
        orders: list[dict[str, object]] = []
        rejections: list[dict[str, object]] = []

        for _, row in prepared.iterrows():
            dt_utc: pd.Timestamp = row["ts"]
            symbol = row["symbol"]
            dt_et = dt_utc.tz_convert(self.session_timezone)
            day_key = (symbol, pd.Timestamp(dt_et.date()))

            if self._force_flat_if_needed(symbol, dt_utc, dt_et, orders):
                self.last_trade_ts[symbol] = dt_utc
                continue

            thresholds = self._get_thresholds(symbol)
            prob_threshold_long = thresholds["prob_threshold_long"]
            prob_threshold_short = thresholds["prob_threshold_short"]
            exit_threshold_long = thresholds["exit_threshold_long"]
            exit_threshold_short = thresholds["exit_threshold_short"]
            max_hold_minutes = thresholds["max_hold_minutes"]
            score_margin = thresholds["score_margin"]
            min_directional_gap = thresholds["min_directional_gap"]
            min_conviction_score = thresholds["min_conviction_score"]
            max_entries_per_day = thresholds.get("max_entries_per_day")
            gap_exit_delay = thresholds.get("gap_exit_delay_minutes", self.gap_exit_delay_minutes)

            # 1. Time filter (entry + exit decisions respect trading window)
            current_time = dt_et.time()
            if not (self.min_time <= current_time <= self.max_time):
                rejections.append(self._rejection_record(dt_utc, symbol, "time_filter"))
                continue

            # 2. Cooldown
            cooldown_duration = pd.Timedelta(minutes=self.cooldown_minutes)
            last_trade = self.last_trade_ts.get(symbol)
            if last_trade is not None and (dt_utc - last_trade) < cooldown_duration:
                rejections.append(self._rejection_record(dt_utc, symbol, "cooldown"))
                continue

            prob_long = float(row.get("prob_long", 0.0))
            prob_short = float(row.get("prob_short", 0.0))
            prob_neutral = float(row.get("prob_neutral", 0.0))
            directional_gap = abs(prob_long - prob_short)
            conviction_score = directional_gap * max(prob_long, prob_short)

            side: str | None = None
            exit_reason: str | None = None
            entry_strategy: tuple[str, str] | None = None
            position = self.position_state.get(symbol)
            hold_duration = None
            if position:
                hold_duration = (dt_utc - position["entry_ts"]).total_seconds() / 60.0

            shrinkage_trigger = directional_gap < (min_directional_gap / 2.0)
            if min_conviction_score > 0.0:
                shrinkage_trigger = shrinkage_trigger or (
                    conviction_score < (min_conviction_score / 2.0)
                )

            if (
                position
                and hold_duration is not None
                and gap_exit_delay is not None
                and hold_duration >= gap_exit_delay
                and shrinkage_trigger
            ):
                side = "long" if position["side"] == "short" else "short"
                exit_reason = "conviction_decay"
            elif position and position["side"] == "short":
                exit_signal = prob_long >= exit_threshold_long or (
                    hold_duration is not None and hold_duration >= max_hold_minutes
                )
                if exit_signal:
                    side = "long"
                    exit_reason = "flatten_short"
                else:
                    rejections.append(self._rejection_record(dt_utc, symbol, "holding_short"))
                    continue
            elif position and position["side"] == "long":
                exit_signal = prob_short >= exit_threshold_short or (
                    hold_duration is not None and hold_duration >= max_hold_minutes
                )
                if exit_signal:
                    side = "short"
                    exit_reason = "flatten_long"
                else:
                    rejections.append(self._rejection_record(dt_utc, symbol, "holding_long"))
                    continue
            else:
                if max_entries_per_day and self.entries_per_day.get(day_key, 0) >= int(
                    max_entries_per_day
                ):
                    rejections.append(self._rejection_record(dt_utc, symbol, "max_entries_reached"))
                    continue

                if directional_gap < min_directional_gap:
                    rejections.append(self._rejection_record(dt_utc, symbol, "gap_insufficient"))
                    continue

                if min_conviction_score and conviction_score < min_conviction_score:
                    rejections.append(self._rejection_record(dt_utc, symbol, "conviction_low"))
                    continue

                long_score = prob_long - max(prob_short, prob_neutral)
                short_score = prob_short - max(prob_long, prob_neutral)

                if (
                    prob_long >= prob_threshold_long
                    and long_score >= score_margin
                    and prob_long > prob_short
                ):
                    side = "long"
                    exit_reason = "trade"
                elif (
                    prob_short >= prob_threshold_short
                    and short_score >= score_margin
                    and prob_short > prob_long
                ):
                    side = "short"
                    exit_reason = "trade"
                else:
                    rejections.append(self._rejection_record(dt_utc, symbol, "below_threshold"))
                    continue

                valid_strategy, strategy_name, detail = self.strategy_checks.validate(row, side)
                if not valid_strategy:
                    rejections.append(
                        self._rejection_record(dt_utc, symbol, f"strategy_check:{detail}")
                    )
                    side = None
                    continue
                entry_strategy = (strategy_name, detail)
            if side is None:
                continue

            if position:
                qty = int(position.get("qty", self.order_qty))
                strategy_name = "exit"
                strategy_detail = exit_reason or "exit"
                self.position_state.pop(symbol, None)
            else:
                qty = int(self.order_qty)
                if entry_strategy is None:
                    valid_strategy, strategy_name, strategy_detail = self.strategy_checks.validate(
                        row, side
                    )
                    if not valid_strategy:
                        rejections.append(
                            self._rejection_record(
                                dt_utc, symbol, f"strategy_check:{strategy_detail}"
                            )
                        )
                        continue
                else:
                    strategy_name, strategy_detail = entry_strategy
                self.position_state[symbol] = {
                    "side": side,
                    "entry_ts": dt_utc,
                    "qty": qty,
                }
                self.entries_per_day[day_key] = self.entries_per_day.get(day_key, 0) + 1

            order = self._build_order(
                symbol=symbol,
                dt_utc=dt_utc,
                side=side,
                qty=qty,
                reason=exit_reason or "trade",
                strategy=strategy_name,
                strategy_detail=strategy_detail if position is None else exit_reason,
            )
            orders.append(order)

            self.last_trade_ts[symbol] = dt_utc

        orders_df = pd.DataFrame(orders)
        if not orders_df.empty:
            orders_df["timestamp"] = pd.to_datetime(orders_df["timestamp"], utc=True)
            orders_df["ts"] = orders_df["timestamp"].astype("int64")
        else:
            orders_df = pd.DataFrame(
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

        rejections_df = pd.DataFrame(rejections)
        if not rejections_df.empty:
            rejections_df["timestamp"] = pd.to_datetime(rejections_df["timestamp"], utc=True)
            rejections_df["ts"] = rejections_df["timestamp"].astype("int64")
        else:
            rejections_df = pd.DataFrame(columns=["ts", "timestamp", "symbol", "reason"])

        return orders_df, rejections_df

    def get_required_feature_columns(self) -> set[str]:
        """Return the set of feature columns required by enabled strategy checks."""
        return set(self.required_feature_columns)

    def _prepare_signals(self, signals: pd.DataFrame) -> pd.DataFrame:
        """Standardise signal DataFrame and ensure UTC nanosecond timestamps."""
        if "ts" not in signals.columns:
            if "timestamp" in signals.columns:
                signals = signals.rename(columns={"timestamp": "ts"})
            else:
                raise KeyError("Signals DataFrame must contain either 'ts' or 'timestamp'")

        prepared = signals.copy()

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
        )
        orders.append(order)
        self.position_state.pop(symbol, None)
        return True

    @staticmethod
    def _rejection_record(dt_utc: pd.Timestamp, symbol: str, reason: str) -> dict[str, object]:
        """Create a rejection record."""
        return {
            "timestamp": dt_utc,
            "ts": dt_utc.value,
            "symbol": symbol,
            "reason": reason,
        }

    def _build_order(
        self,
        symbol: str,
        dt_utc: pd.Timestamp,
        side: str,
        qty: int,
        reason: str,
        strategy: str,
        strategy_detail: str | None = None,
    ) -> dict[str, object]:
        """Construct a deterministic order dictionary."""
        return {
            "ts": dt_utc.value,
            "timestamp": dt_utc,
            "symbol": symbol,
            "side": side,
            "qty": int(qty),
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "reason": reason,
            "strategy": strategy,
            "strategy_detail": strategy_detail or reason,
        }

    def _get_thresholds(self, symbol: str) -> dict[str, float]:
        """Retrieve (or cache) thresholds for the given symbol."""
        if symbol not in self.symbol_thresholds:
            self.symbol_thresholds[symbol] = self.calibrator.get_thresholds(symbol)
        return self.symbol_thresholds[symbol]
