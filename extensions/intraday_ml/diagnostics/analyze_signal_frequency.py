"""Analyze signal frequency at different probability thresholds."""
import json
from pathlib import Path
import pandas as pd
import numpy as np


def analyze_signal_frequency(predictions_path: Path, output_path: Path):
    """Count signals per day at different thresholds."""
    df = pd.read_parquet(predictions_path)
    
    # Ensure timestamp is datetime
    ts_col = "ts" if "ts" in df.columns else "timestamp"
    df["timestamp"] = pd.to_datetime(df[ts_col])
    df["date"] = df["timestamp"].dt.date
    
    # Test thresholds
    thresholds = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
    
    results = []
    for thresh in thresholds:
        # Count signals above threshold
        if "prob_bigmove" in df.columns:
            signals = df[df["prob_bigmove"] >= thresh]
        else:
            # Fallback to any probability column
            prob_cols = [c for c in df.columns if c.startswith("prob_")]
            if prob_cols:
                signals = df[df[prob_cols[0]] >= thresh]
            else:
                print(f"Warning: No probability columns found in {predictions_path}")
                continue
        
        signals_per_day = signals.groupby("date").size()
        
        results.append({
            "threshold": thresh,
            "total_signals": len(signals),
            "avg_signals_per_day": float(signals_per_day.mean()),
            "median_signals_per_day": float(signals_per_day.median()),
            "max_signals_per_day": int(signals_per_day.max()),
            "min_signals_per_day": int(signals_per_day.min()),
            "days_with_signals": len(signals_per_day),
            "days_with_5plus": int((signals_per_day >= 5).sum()),
            "days_with_10plus": int((signals_per_day >= 10).sum()),
        })
    
    report = {
        "total_samples": len(df),
        "date_range": {
            "start": str(df["date"].min()),
            "end": str(df["date"].max()),
            "trading_days": df["date"].nunique(),
        },
        "threshold_analysis": results,
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    
    # Save as CSV for easy viewing
    pd.DataFrame(results).to_csv(output_path.with_suffix(".csv"), index=False)
    
    print(f"✓ Signal frequency analysis saved to {output_path}")
    print(f"  Date range: {report['date_range']['start']} to {report['date_range']['end']}")
    print(f"\n  Signals per day by threshold:")
    for r in results:
        print(f"    {r['threshold']:.2f}: {r['avg_signals_per_day']:.1f} avg, {r['median_signals_per_day']:.0f} median")


if __name__ == "__main__":
    predictions_path = Path("artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet")
    output_path = Path("reports/diagnostics/signal_frequency.json")
    
    if not predictions_path.exists():
        print(f"Predictions file not found: {predictions_path}")
        print("This will be available after Step 3 completes.")
    else:
        analyze_signal_frequency(predictions_path, output_path)
