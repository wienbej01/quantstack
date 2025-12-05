#!/usr/bin/env python3
"""Enhanced backtest with separate LONG/SHORT models and dynamic position sizing."""

import json
import logging
from pathlib import Path

import joblib
import pandas as pd

from extensions.intraday_ml.risk_manager import DynamicPositionSizer, RiskLimits

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


def load_models(output_root: Path):
    """Load separate LONG and SHORT models."""
    
    # Load LONG model
    long_model_path = output_root / "model_long" / "model.pkl"
    long_features_path = output_root / "model_long" / "features.json"
    
    long_model = joblib.load(long_model_path)
    with open(long_features_path) as f:
        long_features = json.load(f)
    
    # Load SHORT model
    short_model_path = output_root / "model_short" / "model.pkl"
    short_features_path = output_root / "model_short" / "features.json"
    
    short_model = joblib.load(short_model_path)
    with open(short_features_path) as f:
        short_features = json.load(f)
    
    return {
        "long_model": long_model,
        "long_features": long_features,
        "short_model": short_model,
        "short_features": short_features,
    }


def generate_predictions_separate(oos_data: pd.DataFrame, models: dict) -> pd.DataFrame:
    """Generate predictions using separate LONG and SHORT models."""
    
    # LONG predictions
    X_long = oos_data[models["long_features"]].fillna(0)
    prob_long = models["long_model"].predict_proba(X_long)[:, 1]
    
    # SHORT predictions
    X_short = oos_data[models["short_features"]].fillna(0)
    prob_short = models["short_model"].predict_proba(X_short)[:, 1]
    
    # Neutral probability
    prob_neutral = 1 - prob_long - prob_short
    prob_neutral = prob_neutral.clip(0, 1)  # Ensure non-negative
    
    # Normalize to sum to 1
    total = prob_long + prob_short + prob_neutral
    prob_long = prob_long / total
    prob_short = prob_short / total
    prob_neutral = prob_neutral / total
    
    predictions = pd.DataFrame({
        "symbol": oos_data["symbol"],
        "ts": oos_data["ts"],
        "prob_long": prob_long,
        "prob_short": prob_short,
        "prob_neutral": prob_neutral,
    })
    
    return predictions


def generate_signals(
    predictions: pd.DataFrame,
    prob_threshold_long: float = 0.40,
    prob_threshold_short: float = 0.40,
) -> pd.DataFrame:
    """Generate trading signals from predictions."""
    
    signals = predictions.copy()
    
    # Determine signal
    signals["signal"] = 0  # Neutral
    signals.loc[signals["prob_long"] > prob_threshold_long, "signal"] = 1  # LONG
    signals.loc[signals["prob_short"] > prob_threshold_short, "signal"] = -1  # SHORT
    
    # If both exceed threshold, take the stronger one
    both_mask = (signals["prob_long"] > prob_threshold_long) & (signals["prob_short"] > prob_threshold_short)
    signals.loc[both_mask & (signals["prob_long"] > signals["prob_short"]), "signal"] = 1
    signals.loc[both_mask & (signals["prob_short"] > signals["prob_long"]), "signal"] = -1
    
    return signals


def simulate_trades_with_dynamic_sizing(
    signals: pd.DataFrame,
    oos_data: pd.DataFrame,
    initial_equity: float = 1000000.0,
    risk_per_trade_pct: float = 0.02,
    max_daily_loss_pct: float = 0.05,
) -> tuple[pd.DataFrame, dict]:
    """Simulate trades with dynamic position sizing."""
    
    # Merge signals with OOS data
    merged = signals.merge(oos_data, on=["symbol", "ts"], how="left")
    
    # Initialize risk manager
    risk_limits = RiskLimits(
        equity=initial_equity,
        max_risk_per_trade_pct=risk_per_trade_pct,
        max_daily_loss_pct=max_daily_loss_pct,
    )
    position_sizer = DynamicPositionSizer(risk_limits)
    
    trades = []
    equity = initial_equity
    
    for idx, row in merged.iterrows():
        if row["signal"] == 0:
            continue
        
        # Reset daily P&L if new day
        position_sizer.reset_daily_pnl(row["ts"])
        
        # Check if we can trade
        if not position_sizer.can_trade():
            continue
        
        # Get entry price and stop
        entry_price = row["close"]
        
        # Calculate stop based on ATR (simplified)
        atr = row.get("f__vol__atr_6", entry_price * 0.01)
        if row["signal"] == 1:  # LONG
            stop_price = entry_price - (atr * 1.0)
            target_price = entry_price + (atr * 1.6)
        else:  # SHORT
            stop_price = entry_price + (atr * 1.0)
            target_price = entry_price - (atr * 1.6)
        
        # Calculate position size
        position_size = position_sizer.calculate_position_size(entry_price, stop_price)
        
        if position_size == 0:
            continue
        
        # Simulate exit (simplified - assume stop or target hit)
        # In reality, would need to check 1-minute bars
        # For now, use random outcome based on historical win rate
        import random
        if row["signal"] == 1:  # LONG
            win_rate = 0.44  # Historical LONG win rate
        else:  # SHORT
            win_rate = 0.29  # Historical SHORT win rate
        
        if random.random() < win_rate:
            # Hit target
            exit_price = target_price
            exit_reason = "TARGET"
        else:
            # Hit stop
            exit_price = stop_price
            exit_reason = "STOP"
        
        # Calculate P&L
        if row["signal"] == 1:  # LONG
            pnl_gross = (exit_price - entry_price) * position_size
        else:  # SHORT
            pnl_gross = (entry_price - exit_price) * position_size
        
        commission = 0.007 * position_size
        pnl_net = pnl_gross - commission
        
        # Update equity and daily P&L
        equity += pnl_net
        position_sizer.update_daily_pnl(pnl_net)
        
        trades.append({
            "symbol": row["symbol"],
            "ts": row["ts"],
            "side": "LONG" if row["signal"] == 1 else "SHORT",
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "position_size": position_size,
            "pnl_gross": pnl_gross,
            "pnl_net": pnl_net,
            "commission": commission,
            "prob_long": row["prob_long"],
            "prob_short": row["prob_short"],
        })
    
    trades_df = pd.DataFrame(trades)
    
    summary = {
        "initial_equity": initial_equity,
        "final_equity": equity,
        "total_pnl": equity - initial_equity,
        "return_pct": (equity - initial_equity) / initial_equity * 100,
        "total_trades": len(trades_df),
        "win_rate": (trades_df["pnl_net"] > 0).mean() if len(trades_df) > 0 else 0,
    }
    
    return trades_df, summary


def main():
    output_root = Path("artefacts/extensions/intraday_ml/phaseA_full_sip_v2")
    
    LOGGER.info("Loading separate LONG/SHORT models...")
    models = load_models(output_root)
    
    LOGGER.info("Loading OOS features...")
    oos_data = pd.read_parquet(output_root / "oos_features.parquet")
    LOGGER.info("Loaded %d OOS samples", len(oos_data))
    
    LOGGER.info("Generating predictions with separate models...")
    predictions = generate_predictions_separate(oos_data, models)
    
    # Save predictions
    pred_path = output_root / "oos_predictions_separate.parquet"
    predictions.to_parquet(pred_path, index=False)
    LOGGER.info("Saved predictions to: %s", pred_path)
    
    # Analyze prediction distribution
    LOGGER.info("\nPrediction Distribution:")
    LOGGER.info("  Mean prob_long:    %.4f", predictions["prob_long"].mean())
    LOGGER.info("  Mean prob_short:   %.4f", predictions["prob_short"].mean())
    LOGGER.info("  Mean prob_neutral: %.4f", predictions["prob_neutral"].mean())
    
    # Test different thresholds
    thresholds = [
        (0.30, 0.30),
        (0.35, 0.35),
        (0.40, 0.40),
        (0.45, 0.45),
        (0.50, 0.50),
    ]
    
    LOGGER.info("\n" + "=" * 80)
    LOGGER.info("Testing Different Probability Thresholds")
    LOGGER.info("=" * 80)
    
    for long_thresh, short_thresh in thresholds:
        signals = generate_signals(predictions, long_thresh, short_thresh)
        
        n_long = (signals["signal"] == 1).sum()
        n_short = (signals["signal"] == -1).sum()
        n_neutral = (signals["signal"] == 0).sum()
        total = len(signals)
        
        LOGGER.info(f"\nThreshold: LONG={long_thresh:.2f}, SHORT={short_thresh:.2f}")
        LOGGER.info(f"  LONG:    {n_long:5d} ({100*n_long/total:5.1f}%)")
        LOGGER.info(f"  SHORT:   {n_short:5d} ({100*n_short/total:5.1f}%)")
        LOGGER.info(f"  NEUTRAL: {n_neutral:5d} ({100*n_neutral/total:5.1f}%)")
        
        # Quick simulation
        trades_df, summary = simulate_trades_with_dynamic_sizing(
            signals, oos_data,
            initial_equity=1000000.0,
            risk_per_trade_pct=0.02,
            max_daily_loss_pct=0.05,
        )
        
        if len(trades_df) > 0:
            LOGGER.info(f"  Trades:  {summary['total_trades']}")
            LOGGER.info(f"  PnL:     ${summary['total_pnl']:,.2f}")
            LOGGER.info(f"  Return:  {summary['return_pct']:.2f}%")
            LOGGER.info(f"  Win Rate: {summary['win_rate']*100:.1f}%")
    
    LOGGER.info("\n" + "=" * 80)
    LOGGER.info("Analysis Complete")
    LOGGER.info("=" * 80)


if __name__ == "__main__":
    main()
