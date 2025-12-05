#!/usr/bin/env python3
"""Analyze prediction distribution and quality."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def analyze_predictions(predictions_path: Path) -> None:
    """Analyze prediction distribution and correlations."""
    
    print(f"\nLoading predictions from: {predictions_path}")
    preds = pd.read_parquet(predictions_path)
    
    print(f"Total predictions: {len(preds):,}")
    print(f"Columns: {list(preds.columns)}")
    
    # Determine predicted class
    prob_cols = [c for c in preds.columns if c.startswith("prob_")]
    if prob_cols:
        preds["predicted_class"] = preds[prob_cols].idxmax(axis=1)
        
        print("\n" + "=" * 60)
        print("Prediction Distribution:")
        print("=" * 60)
        dist = preds["predicted_class"].value_counts(normalize=True) * 100
        for cls, pct in dist.items():
            count = (preds["predicted_class"] == cls).sum()
            print(f"  {cls:15s}: {count:6,} ({pct:5.2f}%)")
        
        # Target distribution
        print("\n" + "=" * 60)
        print("Target: Neutral 60-70%, Long 15-20%, Short 15-20%")
        print("=" * 60)
        
        # Check if we have actual labels
        if "label_bigmove" in preds.columns and "label_bigmove_direction" in preds.columns:
            print("\nActual Label Distribution:")
            bigmove = preds["label_bigmove"]
            direction = preds["label_bigmove_direction"]
            
            neutral_count = (bigmove == 0).sum()
            long_count = ((bigmove == 1) & (direction == 1)).sum()
            short_count = ((bigmove == 1) & (direction == -1)).sum()
            total = len(preds)
            
            print(f"  Neutral: {neutral_count:6,} ({100*neutral_count/total:5.2f}%)")
            print(f"  Long:    {long_count:6,} ({100*long_count/total:5.2f}%)")
            print(f"  Short:   {short_count:6,} ({100*short_count/total:5.2f}%)")
            
            # Compute accuracy
            print("\n" + "=" * 60)
            print("Prediction Accuracy:")
            print("=" * 60)
            
            # Map predicted class to actual format
            pred_map = {"prob_0": 0, "prob_1": 1, "prob_-1": -1}
            preds["pred_direction"] = preds["predicted_class"].map(pred_map)
            
            # Create actual direction
            preds["actual_direction"] = 0
            preds.loc[(bigmove == 1) & (direction == 1), "actual_direction"] = 1
            preds.loc[(bigmove == 1) & (direction == -1), "actual_direction"] = -1
            
            accuracy = (preds["pred_direction"] == preds["actual_direction"]).mean()
            print(f"  Overall Accuracy: {accuracy:.4f}")
            
            # Per-class accuracy
            for cls in [0, 1, -1]:
                mask = preds["actual_direction"] == cls
                if mask.sum() > 0:
                    cls_acc = (preds.loc[mask, "pred_direction"] == cls).mean()
                    cls_name = {0: "Neutral", 1: "Long", -1: "Short"}[cls]
                    print(f"  {cls_name} Accuracy: {cls_acc:.4f}")
        
        # Probability statistics
        print("\n" + "=" * 60)
        print("Probability Statistics:")
        print("=" * 60)
        for col in prob_cols:
            mean_prob = preds[col].mean()
            std_prob = preds[col].std()
            max_prob = preds[col].max()
            print(f"  {col:15s}: mean={mean_prob:.4f} std={std_prob:.4f} max={max_prob:.4f}")
        
        # Confidence analysis
        preds["max_prob"] = preds[prob_cols].max(axis=1)
        print(f"\n  Prediction Confidence:")
        print(f"    Mean max probability: {preds['max_prob'].mean():.4f}")
        print(f"    High confidence (>0.7): {(preds['max_prob'] > 0.7).sum():,} ({100*(preds['max_prob'] > 0.7).mean():.2f}%)")
        print(f"    Low confidence (<0.5):  {(preds['max_prob'] < 0.5).sum():,} ({100*(preds['max_prob'] < 0.5).mean():.2f}%)")


def main():
    parser = argparse.ArgumentParser(description="Analyze prediction distribution")
    parser.add_argument(
        "--predictions",
        type=Path,
        default=Path("artefacts/extensions/intraday_ml/phaseA_full_sip_v2/oos_predictions_bigmove.parquet"),
        help="Path to predictions parquet file",
    )
    args = parser.parse_args()
    
    if not args.predictions.exists():
        print(f"Error: Predictions file not found: {args.predictions}")
        print("\nGenerate predictions first using:")
        print("  python -m extensions.intraday_ml.experiments.score_bigmove_oos")
        return
    
    analyze_predictions(args.predictions)


if __name__ == "__main__":
    main()
