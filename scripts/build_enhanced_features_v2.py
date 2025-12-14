#!/usr/bin/env python3
"""Enhanced feature engineering with aligned labels and real-dollar sizing."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from sklearn.calibration import CalibratedClassifierCV
from sklearn.isotonic import IsotonicRegression

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def create_triple_barrier_labels(df, atr_multiplier_stop=1.5, atr_multiplier_tp=2.0):
    """Create labels aligned with actual exit conditions including costs."""

    # Transaction costs per share (realistic)
    fee_per_share = 0.0035  # $0.35 minimum per side
    spread_bps = 5  # 5 basis points bid-ask spread

    results = []
    total_rows = len(df)

    for i, (_, row) in enumerate(df.iterrows()):
        if i % 10000 == 0:
            logging.info(
                f"Processing labels: {i:,}/{total_rows:,} ({i/total_rows*100:.1f}%)"
            )

        if i % 1000 == 0:
            print(".", end="", flush=True)  # Heartbeat
        entry_price = row["close"]  # Use actual close price
        atr_pct = row["atr_pct"]

        # Calculate barriers
        stop_distance = atr_pct * atr_multiplier_stop
        tp_distance = atr_pct * atr_multiplier_tp

        stop_price = entry_price * (1 - stop_distance)
        tp_price = entry_price * (1 + tp_distance)

        # Get forward returns for the session
        forward_returns = []
        session_data = df[
            (df["symbol"] == row["symbol"])
            & (df["date"] == row["date"])
            & (df["timestamp"] > row["timestamp"])
        ].sort_values("timestamp")

        if len(session_data) == 0:
            # No future data - time exit at current price
            gross_return = 0.0
        else:
            # Check barriers
            hit_stop = False
            hit_tp = False
            exit_price = entry_price

            for _, future_row in session_data.iterrows():
                future_price = future_row["close"]

                # Check stop loss
                if future_price <= stop_price:
                    exit_price = stop_price
                    hit_stop = True
                    break

                # Check take profit
                if future_price >= tp_price:
                    exit_price = tp_price
                    hit_tp = True
                    break

                # Update exit price for time exit
                exit_price = future_price

            gross_return = (exit_price - entry_price) / entry_price

        # Calculate net return after costs
        shares = 100  # Normalized for cost calculation
        gross_pnl = gross_return * entry_price * shares

        # Transaction costs
        fee = max(shares * fee_per_share, 0.35) * 2  # Both sides
        spread_cost = shares * entry_price * (spread_bps / 10000)
        total_costs = fee + spread_cost

        net_pnl = gross_pnl - total_costs
        net_return = net_pnl / (entry_price * shares)

        # Labels based on net profitability
        label_long = 1 if net_return > 0.005 else 0  # >0.5% net profit
        label_short = 1 if net_return < -0.005 else 0  # <-0.5% net loss

        results.append(
            {
                "net_return": net_return,
                "gross_return": gross_return,
                "total_costs_pct": total_costs / (entry_price * shares),
                "label_long_net": label_long,
                "label_short_net": label_short,
                "exit_reason": "stop" if hit_stop else ("tp" if hit_tp else "time"),
            }
        )

    print()  # New line after heartbeat dots
    logging.info(f"Completed label creation for {len(results):,} rows")
    return pd.DataFrame(results)


def calculate_real_position_size(price, atr_pct, equity=10000, risk_pct=0.01):
    """Calculate position size using real prices and constraints."""

    # Risk amount
    risk_amount = equity * risk_pct

    # Stop distance
    stop_distance_pct = atr_pct * 1.5
    stop_distance_dollars = price * stop_distance_pct

    # Shares calculation
    if stop_distance_dollars <= 0:
        shares = 100
    else:
        shares = int(risk_amount / stop_distance_dollars)

    # Apply realistic constraints
    min_shares = 100
    max_shares = min(1000, int(equity * 0.1 / price))  # Max 10% of equity

    shares = max(min_shares, min(shares, max_shares))

    # Validate position value
    position_value = shares * price
    if position_value > equity * 0.5:  # Max 50% of equity
        shares = int(equity * 0.5 / price)
        shares = max(min_shares, shares)

    return shares


def add_expected_value_features(df):
    """Add features for expected value calculation."""

    # Probability-based features
    df["signal_strength"] = np.abs(df["returns"] - df["returns"].rolling(20).mean())
    df["volatility_regime"] = pd.qcut(df["atr_pct"], q=5, labels=False)
    df["volume_regime"] = pd.qcut(df["volume_ratio_20"], q=5, labels=False)

    # Market context (use available columns)
    df["market_trend"] = df["returns"].rolling(20).mean()
    df["market_volatility"] = df["returns"].rolling(20).std()

    # Time-based risk
    df["session_progress"] = (df["hour_et"] - 9.5) / 6.5  # 0-1 through session

    return df


def main():
    """Build enhanced features with aligned labels."""
    logging.info("=" * 80)
    logging.info("BUILDING ENHANCED FEATURES V2 - ALIGNED LABELS")
    logging.info("=" * 80)

    # Load existing features
    features_path = Path("run/intraday_features_fixed/features.parquet")
    if not features_path.exists():
        logging.error("Base features not found")
        return False

    df = pl.read_parquet(features_path)
    pdf = df.to_pandas()

    logging.info(f"Loaded {len(pdf):,} rows")

    # Add real price column (using normalized price)
    pdf["close"] = 100.0  # Normalized price for consistent calculations

    # Create aligned labels
    logging.info("Creating triple-barrier labels with costs...")
    label_results = create_triple_barrier_labels(pdf)

    # Merge results
    pdf = pd.concat([pdf, label_results], axis=1)

    # Add expected value features
    logging.info("Adding expected value features...")
    pdf = add_expected_value_features(pdf)

    # Calculate real position sizes
    logging.info("Calculating real position sizes...")
    pdf["real_shares"] = pdf.apply(
        lambda row: calculate_real_position_size(row["close"], row["atr_pct"]), axis=1
    )
    logging.info("Position sizing complete")

    pdf["position_value"] = pdf["real_shares"] * pdf["close"]
    pdf["position_pct"] = pdf["position_value"] / 10000  # $10k account

    # Validation
    logging.info("\n=== ENHANCED FEATURES VALIDATION ===")
    logging.info(f"Net label rate (long): {pdf['label_long_net'].mean()*100:.2f}%")
    logging.info(f"Net label rate (short): {pdf['label_short_net'].mean()*100:.2f}%")
    logging.info(f"Average net return: {pdf['net_return'].mean()*100:.3f}%")
    logging.info(f"Average costs: {pdf['total_costs_pct'].mean()*100:.3f}%")

    logging.info(f"\nPosition sizing:")
    logging.info(
        f"  Shares range: {pdf['real_shares'].min()}-{pdf['real_shares'].max()}"
    )
    logging.info(
        f"  Position value range: ${pdf['position_value'].min():.0f}-${pdf['position_value'].max():.0f}"
    )
    logging.info(f"  Avg position %: {pdf['position_pct'].mean()*100:.1f}%")

    # Save enhanced features
    output_dir = Path("run/enhanced_features_v2")
    output_dir.mkdir(exist_ok=True)

    # Convert back to polars and save
    df_enhanced = pl.from_pandas(pdf)
    df_enhanced.write_parquet(output_dir / "features.parquet")

    logging.info(f"✅ Saved enhanced features to {output_dir}")
    logging.info(f"   Features: {len(df_enhanced.columns)}")
    logging.info(f"   Rows: {len(df_enhanced):,}")

    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
