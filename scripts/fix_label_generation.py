#!/usr/bin/env python3
"""Fix label generation - simplified approach using existing forward_return."""

import logging
from pathlib import Path

import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def create_net_labels_simple(df):
    """Create net labels using existing forward_return and realistic costs."""

    # Transaction costs (realistic for $10k account)
    fee_per_trade = 0.70  # $0.35 * 2 sides
    spread_bps = 5  # 5 basis points

    results = []

    for i, row in df.iterrows():
        if i % 10000 == 0:
            logging.info(f"Processing: {i:,}/{len(df):,}")

        # Use existing forward_return
        gross_return = row["forward_return"]
        entry_price = 100.0  # Normalized
        atr_pct = row["atr_pct"]

        # Calculate position size
        risk_amount = 100.0  # 1% of $10k
        stop_distance = atr_pct * 1.5
        shares = max(100, min(1000, int(risk_amount / (entry_price * stop_distance))))

        # Calculate costs
        position_value = shares * entry_price
        spread_cost = position_value * (spread_bps / 10000)
        total_costs = fee_per_trade + spread_cost

        # Net P&L
        gross_pnl = gross_return * position_value
        net_pnl = gross_pnl - total_costs
        net_return = net_pnl / position_value

        # Simple labels based on net profitability
        label_long_net = 1 if net_return > 0.002 else 0  # >0.2% net
        label_short_net = 1 if net_return < -0.002 else 0  # <-0.2% net

        results.append(
            {
                "net_return": net_return,
                "gross_return": gross_return,
                "total_costs_pct": total_costs / position_value,
                "label_long_net": label_long_net,
                "label_short_net": label_short_net,
                "shares": shares,
                "position_value": position_value,
            }
        )

    return pd.DataFrame(results)


def main():
    """Fix label generation."""
    logging.info("FIXING LABEL GENERATION")

    # Load enhanced features
    features_path = Path("run/enhanced_features_v2/features.parquet")
    if not features_path.exists():
        logging.error("Enhanced features not found")
        return False

    df = pl.read_parquet(features_path)
    pdf = df.to_pandas()

    logging.info(f"Loaded {len(pdf):,} rows")

    # Create simplified net labels
    logging.info("Creating net labels...")
    label_results = create_net_labels_simple(pdf)

    # Replace the problematic columns
    pdf = pdf.drop(
        columns=["net_return", "label_long_net", "label_short_net"], errors="ignore"
    )
    pdf = pd.concat([pdf, label_results], axis=1)

    # Validation
    logging.info("\n=== FIXED LABELS VALIDATION ===")
    logging.info(f"Net label rate (long): {pdf['label_long_net'].mean()*100:.2f}%")
    logging.info(f"Net label rate (short): {pdf['label_short_net'].mean()*100:.2f}%")
    logging.info(f"Average net return: {pdf['net_return'].mean()*100:.3f}%")
    logging.info(f"Average costs: {pdf['total_costs_pct'].mean()*100:.3f}%")

    # Save fixed features
    df_fixed = pl.from_pandas(pdf)
    df_fixed.write_parquet(features_path)

    logging.info(f"✅ Fixed and saved features")
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
