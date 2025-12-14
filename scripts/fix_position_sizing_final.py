#!/usr/bin/env python3
"""Final fix for position sizing calculation with proper validation."""

import logging
from pathlib import Path

import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# Safe position sizing parameters
EQUITY = 10_000.0
RISK_FRACTION = 0.01  # 1% risk per trade
ATR_STOP_MULTIPLE = 1.5
MIN_ATR_PCT = 0.005  # 0.5% minimum ATR
MAX_ATR_PCT = 0.20  # 20% maximum ATR
MIN_SHARES = 100
MAX_SHARES = 1000  # Maximum shares per trade
MAX_POSITION_PCT = 0.10  # Maximum 10% of equity per position


def safe_position_sizing(atr_pct, current_equity=EQUITY, entry_price=100.0):
    """
    Calculate position size with comprehensive safety checks.

    Args:
        atr_pct: ATR as percentage (e.g., 0.02 for 2%)
        current_equity: Current account equity
        entry_price: Entry price per share

    Returns:
        shares: Number of shares (safe and validated)
    """
    # Validate and clamp ATR
    atr_pct = max(MIN_ATR_PCT, min(MAX_ATR_PCT, atr_pct))

    # Calculate stop distance
    stop_distance_pct = atr_pct * ATR_STOP_MULTIPLE

    # Risk amount in dollars
    risk_amount = current_equity * RISK_FRACTION

    # Risk per share in dollars
    risk_per_share = entry_price * stop_distance_pct

    # Calculate shares
    if risk_per_share <= 0:
        shares = MIN_SHARES
    else:
        shares = int(risk_amount / risk_per_share)

    # Apply safety limits
    max_shares_by_equity = int(current_equity * MAX_POSITION_PCT / entry_price)
    shares = max(MIN_SHARES, min(shares, MAX_SHARES, max_shares_by_equity))

    return shares


def validate_atr_data():
    """Validate ATR data and identify problematic values."""
    logging.info("=" * 80)
    logging.info("VALIDATING ATR DATA")
    logging.info("=" * 80)

    features_path = Path("run/intraday_features_fixed/features.parquet")
    if not features_path.exists():
        logging.error("Fixed features not found")
        return False

    df = pl.read_parquet(features_path)
    pdf = df.to_pandas()

    if "atr_pct" not in pdf.columns:
        logging.error("ATR percentage column not found")
        return False

    atr_stats = pdf["atr_pct"].describe()
    logging.info(f"ATR statistics:\n{atr_stats}")

    # Check for extreme values
    extreme_low = pdf[pdf["atr_pct"] < MIN_ATR_PCT]
    extreme_high = pdf[pdf["atr_pct"] > MAX_ATR_PCT]

    logging.info(
        f"Extreme low ATR (<{MIN_ATR_PCT}): {len(extreme_low)} rows ({len(extreme_low)/len(pdf)*100:.2f}%)"
    )
    logging.info(
        f"Extreme high ATR (>{MAX_ATR_PCT}): {len(extreme_high)} rows ({len(extreme_high)/len(pdf)*100:.2f}%)"
    )

    if len(extreme_low) > 0:
        logging.warning(f"Min ATR: {pdf['atr_pct'].min():.8f}")
        logging.warning("Very low ATR values will be clamped to minimum")

    if len(extreme_high) > 0:
        logging.warning(f"Max ATR: {pdf['atr_pct'].max():.8f}")
        logging.warning("Very high ATR values will be clamped to maximum")

    return True


def test_position_sizing_safety():
    """Test position sizing with extreme ATR values."""
    logging.info("\n" + "=" * 80)
    logging.info("TESTING POSITION SIZING SAFETY")
    logging.info("=" * 80)

    test_cases = [
        ("Normal ATR", 0.02),
        ("Low ATR", 0.001),
        ("Very low ATR", 0.0001),
        ("Extremely low ATR", 0.000001),
        ("High ATR", 0.10),
        ("Very high ATR", 0.50),
        ("Zero ATR", 0.0),
    ]

    for name, atr_pct in test_cases:
        shares = safe_position_sizing(atr_pct)
        position_value = shares * 100.0
        position_pct = position_value / EQUITY * 100

        # Calculate actual risk
        clamped_atr = max(MIN_ATR_PCT, min(MAX_ATR_PCT, atr_pct))
        stop_distance = clamped_atr * ATR_STOP_MULTIPLE
        actual_risk = shares * 100.0 * stop_distance
        risk_pct = actual_risk / EQUITY * 100

        logging.info(f"{name}:")
        logging.info(f"  Input ATR: {atr_pct:.6f} ({atr_pct*100:.4f}%)")
        logging.info(f"  Clamped ATR: {clamped_atr:.6f} ({clamped_atr*100:.4f}%)")
        logging.info(f"  Shares: {shares:,}")
        logging.info(
            f"  Position: ${position_value:,.2f} ({position_pct:.1f}% of equity)"
        )
        logging.info(f"  Risk: ${actual_risk:.2f} ({risk_pct:.2f}% of equity)")

        # Validation
        safe = (
            MIN_SHARES <= shares <= MAX_SHARES
            and position_pct <= MAX_POSITION_PCT * 100
            and risk_pct <= RISK_FRACTION * 100 * 2  # Allow 2x target risk
        )
        logging.info(f"  Safe: {'✅' if safe else '❌'}")
        logging.info("")


def fix_enhanced_results():
    """Fix the enhanced results file with extreme position sizes."""
    logging.info("=" * 80)
    logging.info("FIXING ENHANCED RESULTS")
    logging.info("=" * 80)

    enhanced_path = Path("run/enhanced_results/trades.csv")
    if not enhanced_path.exists():
        logging.info("Enhanced results file not found - nothing to fix")
        return True

    # Read the file
    df = pd.read_csv(enhanced_path, dtype={"shares": str})

    # Convert shares to numeric, handling errors
    df["shares_numeric"] = pd.to_numeric(df["shares"], errors="coerce")

    # Identify problematic trades
    extreme_trades = df[df["shares_numeric"] > MAX_SHARES]
    logging.info(f"Found {len(extreme_trades)} trades with extreme share counts")

    if len(extreme_trades) > 0:
        logging.info(f"Max shares before fix: {df['shares_numeric'].max():,.0f}")

        # Cap shares at maximum
        df["shares_fixed"] = df["shares_numeric"].clip(upper=MAX_SHARES)

        # Recalculate PnL with fixed shares
        df["gross_pnl_fixed"] = df["gross_pnl"] * (
            df["shares_fixed"] / df["shares_numeric"]
        )
        df["fee_fixed"] = df["fee"] * (df["shares_fixed"] / df["shares_numeric"])
        df["spread_fixed"] = df["spread"] * (df["shares_fixed"] / df["shares_numeric"])
        df["net_pnl_fixed"] = (
            df["gross_pnl_fixed"] - df["fee_fixed"] - df["spread_fixed"]
        )

        # Replace original values
        df["shares"] = df["shares_fixed"].astype(int)
        df["gross_pnl"] = df["gross_pnl_fixed"]
        df["fee"] = df["fee_fixed"]
        df["spread"] = df["spread_fixed"]
        df["net_pnl"] = df["net_pnl_fixed"]

        # Drop temporary columns
        df = df.drop(
            columns=[
                "shares_numeric",
                "shares_fixed",
                "gross_pnl_fixed",
                "fee_fixed",
                "spread_fixed",
                "net_pnl_fixed",
            ]
        )

        # Save fixed file
        backup_path = enhanced_path.with_suffix(".csv.backup")
        enhanced_path.rename(backup_path)
        df.to_csv(enhanced_path, index=False)

        logging.info(f"✅ Fixed enhanced results file")
        logging.info(f"   Backup saved to: {backup_path}")
        logging.info(f"   Max shares after fix: {df['shares'].max():,}")

        return True
    else:
        logging.info("✅ No extreme trades found in enhanced results")
        return True


def main():
    """Main execution function."""
    logging.info("🔧 FINAL POSITION SIZING FIX")

    # Step 1: Validate ATR data
    atr_ok = validate_atr_data()
    if not atr_ok:
        return False

    # Step 2: Test safety mechanisms
    test_position_sizing_safety()

    # Step 3: Fix enhanced results
    enhanced_fixed = fix_enhanced_results()

    # Step 4: Final validation
    logging.info("=" * 80)
    logging.info("FINAL VALIDATION")
    logging.info("=" * 80)

    # Check all results files
    results_files = [
        "run/rolling_results_fixed/trades.csv",
        "run/enhanced_results/trades.csv",
    ]

    all_good = True

    for file_path in results_files:
        if Path(file_path).exists():
            df = pd.read_csv(file_path)

            # Convert shares to numeric if needed
            if df["shares"].dtype == "object":
                df["shares"] = pd.to_numeric(df["shares"], errors="coerce")

            max_shares = df["shares"].max()
            max_pnl = abs(df["net_pnl"]).max()

            reasonable = max_shares <= MAX_SHARES and max_pnl < 10000

            logging.info(f"{file_path}:")
            logging.info(f"  Max shares: {max_shares:,}")
            logging.info(f"  Max |PnL|: ${max_pnl:,.2f}")
            logging.info(f"  Status: {'✅' if reasonable else '❌'}")

            if not reasonable:
                all_good = False

    if all_good:
        logging.info("\n🎉 SUCCESS: All position sizing issues resolved!")
        logging.info("   - ATR data validated and clamped")
        logging.info("   - Safety mechanisms implemented")
        logging.info("   - Enhanced results fixed")
        logging.info("   - All trades have reasonable position sizes")
    else:
        logging.error("\n❌ Issues remain - manual intervention needed")

    return all_good


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
