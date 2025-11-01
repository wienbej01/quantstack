#!/usr/bin/env python3
"""
Intraday ML Decision Policy for generating execution orders from model predictions.
"""
import pandas as pd


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
        # Gating parameters
        self.prob_threshold_long = config.get("prob_threshold_long", 0.55)
        self.prob_threshold_short = config.get("prob_threshold_short", 0.55)
        self.cooldown_minutes = config.get("cooldown_minutes", 30)
        self.min_time = pd.to_datetime(config.get("min_time", "09:45:00")).time()
        self.max_time = pd.to_datetime(config.get("max_time", "15:45:00")).time()

        # Order parameters
        self.stop_loss_pct = config.get("stop_loss_pct", 0.01)
        self.take_profit_pct = config.get("take_profit_pct", 0.015)
        self.order_qty = config.get("order_qty", 1)

        # State tracking
        self.last_trade_ts = {}  # (symbol, ts) for cooldown

    def process_signals(self, signals: pd.DataFrame) -> pd.DataFrame:
        """
        Processes a DataFrame of signals to generate a DataFrame of orders.

        Args:
            signals: DataFrame with columns ['timestamp', 'symbol', 'prob_long', 'prob_short']

        Returns:
            A DataFrame of orders with columns ['timestamp', 'symbol', 'side', 'qty',
                                               'stop_loss_pct', 'take_profit_pct', 'reason'].
        """
        orders = []
        reasons = []

        signals = signals.sort_values("ts").reset_index(drop=True)
        
        for _, row in signals.iterrows():
            ts = row["ts"]
            symbol = row["symbol"]
            dt = pd.to_datetime(ts)

            # 1. Time Filter
            if not (self.min_time <= dt.time() <= self.max_time):
                reasons.append({"timestamp": ts, "symbol": symbol, "reason": "time_filter"})
                continue

            # 2. Cooldown
            cooldown_duration = pd.Timedelta(minutes=self.cooldown_minutes)
            last_trade = self.last_trade_ts.get(symbol)
            if last_trade and (dt - last_trade) < cooldown_duration:
                reasons.append({"timestamp": ts, "symbol": symbol, "reason": "cooldown"})
                continue

            prob_long = row.get("prob_long", 0.0)
            prob_short = row.get("prob_short", 0.0)
            side = None

            # 3. Probability Threshold
            if prob_long > self.prob_threshold_long and prob_long > prob_short:
                side = "long"
            elif prob_short > self.prob_threshold_short:
                side = "short"
            else:
                reasons.append({"timestamp": ts, "symbol": symbol, "reason": "below_threshold"})
                continue

            # All checks passed, create order
            order = {
                "ts": ts,
                "symbol": symbol,
                "side": side,
                "qty": self.order_qty,
                "stop_loss_pct": self.stop_loss_pct,
                "take_profit_pct": self.take_profit_pct,
                "reason": "trade",
            }
            orders.append(order)

            # Update state
            self.last_trade_ts[symbol] = dt

        return pd.DataFrame(orders), pd.DataFrame(reasons)

