#!/usr/bin/env python3
"""Debug and fix position sizing calculation errors."""

import logging
from pathlib import Path

import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# Parameters from rolling_train_fixed.py
EQUITY = 10_000.0
RISK_FRACTION = 0.01
ATR_STOP_MULTIPLE = 1.5


def analyze_position_sizing_bug():
    """Analyze the position sizing calculation bug."""
    logging.info("=" * 80)
    logging.info("DEBUGGING POSITION SIZING CALCULATION")
    logging.info("=" * 80)

    # Load fixed features to examine ATR values
    features_path = Path("run/intraday_features_fixed/features.parquet")
    if not features_path.exists():
        logging.error(
            "Fixed features not found. Run build_intraday_features_fixed.py first"
        )
        return

    df = pl.read_parquet(features_path)
    pdf = df.to_pandas()

    # Examine ATR percentage values
    if "atr_pct" in pdf.columns:
        atr_stats = pdf["atr_pct"].describe()
        logging.info(f"ATR percentage statistics:\n{atr_stats}")

        # Sample some values
        sample_atr = pdf["atr_pct"].head(10)
        logging.info(f"Sample ATR values: {sample_atr.tolist()}")

        # Test position sizing calculation
        logging.info("\n" + "=" * 50)
        logging.info("TESTING POSITION SIZING CALCULATIONS")
        logging.info("=" * 50)

        for i, atr_pct in enumerate(sample_atr[:5]):
            logging.info(f"\nTest {i+1}:")
            logging.info(f"  ATR percentage: {atr_pct:.6f}")

            # Current (buggy) calculation
            stop_distance = atr_pct * ATR_STOP_MULTIPLE
            risk_amount = EQUITY * RISK_FRACTION
            shares_buggy = int(risk_amount / (100 * stop_distance))

            logging.info(f"  Stop distance: {stop_distance:.6f}")
            logging.info(f"  Risk amount: ${risk_amount:.2f}")
            logging.info(f"  BUGGY shares: {shares_buggy:,}")

            # Fixed calculation (assuming ATR is already in percentage)
            # Risk per share = entry_price * stop_distance_pct
            entry_price = 100.0  # Assumed price
            risk_per_share = entry_price * stop_distance
            shares_fixed = (
                int(risk_amount / risk_per_share) if risk_per_share > 0 else 100
            )

            logging.info(f"  Risk per share: ${risk_per_share:.4f}")
            logging.info(f"  FIXED shares: {shares_fixed:,}")

            # Calculate position values
            position_value_buggy = shares_buggy * entry_price
            position_value_fixed = shares_fixed * entry_price

            logging.info(f"  Buggy position value: ${position_value_buggy:,.2f}")
            logging.info(f"  Fixed position value: ${position_value_fixed:,.2f}")

            # Check if position is reasonable (should be ~1% of equity)
            target_position = (
                EQUITY * RISK_FRACTION / stop_distance
                if stop_distance > 0
                else EQUITY * 0.01
            )
            logging.info(f"  Target position value: ${target_position:,.2f}")

    else:
        logging.error("ATR percentage column not found in features")


def create_fixed_position_sizing_function():
    """Create a corrected position sizing function."""

    function_code = '''
def calculate_position_size_fixed(atr_pct, current_equity, entry_price, risk_fraction=0.01, atr_multiplier=1.5):
    """
    Calculate position size with proper risk management.
    
    Args:
        atr_pct: ATR as percentage (e.g., 0.02 for 2%)
        current_equity: Current account equity
        entry_price: Entry price per share
        risk_fraction: Fraction of equity to risk (default 1%)
        atr_multiplier: ATR multiplier for stop distance
    
    Returns:
        shares: Number of shares to trade
    """
    # Calculate stop distance in percentage terms
    stop_distance_pct = atr_pct * atr_multiplier
    
    # Risk amount in dollars
    risk_amount = current_equity * risk_fraction
    
    # Risk per share in dollars
    risk_per_share = entry_price * stop_distance_pct
    
    # Calculate shares
    if risk_per_share <= 0:
        return 100  # Minimum position
    
    shares = int(risk_amount / risk_per_share)
    
    # Apply reasonable limits
    max_shares = int(current_equity * 0.1 / entry_price)  # Max 10% of equity
    min_shares = 100  # Minimum position
    
    shares = max(min_shares, min(shares, max_shares))
    
    return shares


def validate_position_size(shares, entry_price, current_equity, atr_pct, atr_multiplier=1.5):
    """Validate that position size is reasonable."""
    position_value = shares * entry_price
    position_pct = position_value / current_equity
    
    # Calculate actual risk
    stop_distance_pct = atr_pct * atr_multiplier
    risk_amount = shares * entry_price * stop_distance_pct
    risk_pct = risk_amount / current_equity
    
    # Validation checks
    checks = {
        "position_under_50pct": position_pct < 0.5,
        "risk_under_5pct": risk_pct < 0.05,
        "shares_reasonable": 100 <= shares <= 10000,
        "position_value_reasonable": 1000 <= position_value <= current_equity * 0.5
    }
    
    return all(checks.values()), checks, {
        "position_value": position_value,
        "position_pct": position_pct,
        "risk_amount": risk_amount,
        "risk_pct": risk_pct
    }
'''

    # Write the fixed function to a file
    with open("scripts/position_sizing_fixed.py", "w") as f:
        f.write("#!/usr/bin/env python3\n")
        f.write('"""Fixed position sizing functions."""\n\n')
        f.write(function_code)

    logging.info(
        "Created fixed position sizing function in scripts/position_sizing_fixed.py"
    )


def test_fixed_calculation():
    """Test the fixed position sizing calculation."""
    logging.info("\n" + "=" * 50)
    logging.info("TESTING FIXED POSITION SIZING")
    logging.info("=" * 50)

    # Test cases
    test_cases = [
        {"atr_pct": 0.02, "equity": 10000, "price": 100},  # 2% ATR
        {"atr_pct": 0.01, "equity": 10000, "price": 50},  # 1% ATR, lower price
        {"atr_pct": 0.05, "equity": 10000, "price": 200},  # 5% ATR, higher price
        {"atr_pct": 0.001, "equity": 10000, "price": 100},  # Very low ATR
        {"atr_pct": 0.10, "equity": 10000, "price": 100},  # Very high ATR
    ]

    for i, case in enumerate(test_cases):
        logging.info(f"\nTest case {i+1}:")
        logging.info(f"  ATR: {case['atr_pct']:.3f} ({case['atr_pct']*100:.1f}%)")
        logging.info(f"  Equity: ${case['equity']:,}")
        logging.info(f"  Price: ${case['price']}")

        # Fixed calculation
        atr_pct = case["atr_pct"]
        equity = case["equity"]
        price = case["price"]

        stop_distance_pct = atr_pct * 1.5
        risk_amount = equity * 0.01  # 1% risk
        risk_per_share = price * stop_distance_pct

        if risk_per_share > 0:
            shares = int(risk_amount / risk_per_share)
            shares = max(100, min(shares, int(equity * 0.1 / price)))
        else:
            shares = 100

        position_value = shares * price
        actual_risk = shares * price * stop_distance_pct

        logging.info(
            f"  Stop distance: {stop_distance_pct:.4f} ({stop_distance_pct*100:.2f}%)"
        )
        logging.info(f"  Risk per share: ${risk_per_share:.4f}")
        logging.info(f"  Shares: {shares:,}")
        logging.info(
            f"  Position value: ${position_value:,.2f} ({position_value/equity*100:.1f}% of equity)"
        )
        logging.info(
            f"  Actual risk: ${actual_risk:.2f} ({actual_risk/equity*100:.2f}% of equity)"
        )

        # Validation
        reasonable = (
            100 <= shares <= 10000
            and position_value <= equity * 0.5
            and actual_risk <= equity * 0.05
        )
        logging.info(f"  Reasonable: {'✅' if reasonable else '❌'}")


if __name__ == "__main__":
    analyze_position_sizing_bug()
    create_fixed_position_sizing_function()
    test_fixed_calculation()
