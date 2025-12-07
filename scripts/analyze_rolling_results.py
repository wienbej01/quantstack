#!/usr/bin/env python3
"""Analyze rolling training results."""

import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def main():
    logging.info("=" * 80)
    logging.info("ANALYZING ROLLING RESULTS")
    logging.info("=" * 80)
    
    # Load metrics
    metrics_file = Path("run/rolling_results/metrics.csv")
    df = pd.read_csv(metrics_file)
    
    logging.info(f"Loaded {len(df)} iterations")
    
    # Summary statistics
    logging.info("")
    logging.info("=" * 80)
    logging.info("SUMMARY STATISTICS")
    logging.info("=" * 80)
    
    logging.info(f"Total iterations: {len(df)}")
    logging.info(f"Total signals: {df['total_signals'].sum():,}")
    logging.info(f"Avg signals/month: {df['total_signals'].mean():.1f}")
    logging.info(f"")
    logging.info(f"Combined Win Rate:")
    logging.info(f"  Mean: {df['combined_win_rate'].mean():.2%}")
    logging.info(f"  Std: {df['combined_win_rate'].std():.2%}")
    logging.info(f"  Min: {df['combined_win_rate'].min():.2%}")
    logging.info(f"  Max: {df['combined_win_rate'].max():.2%}")
    logging.info(f"")
    logging.info(f"Total P&L: {df['total_pnl'].sum():.2%}")
    logging.info(f"Avg P&L/month: {df['total_pnl'].mean():.2%}")
    logging.info(f"")
    logging.info(f"Model Quality:")
    logging.info(f"  Avg LONG AUC: {df['auc_long'].mean():.4f}")
    logging.info(f"  Avg SHORT AUC: {df['auc_short'].mean():.4f}")
    
    # Monthly breakdown
    logging.info("")
    logging.info("=" * 80)
    logging.info("MONTHLY BREAKDOWN")
    logging.info("=" * 80)
    
    for _, row in df.iterrows():
        logging.info(f"{row['oos_month']}: {row['total_signals']:3d} signals, "
                    f"{row['combined_win_rate']:5.1%} win rate, "
                    f"{row['total_pnl']:6.2%} P&L")
    
    # Save report
    output_dir = Path("run/rolling_results")
    report_file = output_dir / "analysis_report.txt"
    
    with open(report_file, "w") as f:
        f.write("ROLLING TRAINING ANALYSIS REPORT\n")
        f.write("=" * 80 + "\n\n")
        
        f.write("SUMMARY STATISTICS\n")
        f.write("-" * 80 + "\n")
        f.write(f"Total iterations: {len(df)}\n")
        f.write(f"Total signals: {df['total_signals'].sum():,}\n")
        f.write(f"Avg signals/month: {df['total_signals'].mean():.1f}\n\n")
        
        f.write(f"Combined Win Rate:\n")
        f.write(f"  Mean: {df['combined_win_rate'].mean():.2%}\n")
        f.write(f"  Std: {df['combined_win_rate'].std():.2%}\n")
        f.write(f"  Min: {df['combined_win_rate'].min():.2%}\n")
        f.write(f"  Max: {df['combined_win_rate'].max():.2%}\n\n")
        
        f.write(f"Total P&L: {df['total_pnl'].sum():.2%}\n")
        f.write(f"Avg P&L/month: {df['total_pnl'].mean():.2%}\n\n")
        
        f.write(f"Model Quality:\n")
        f.write(f"  Avg LONG AUC: {df['auc_long'].mean():.4f}\n")
        f.write(f"  Avg SHORT AUC: {df['auc_short'].mean():.4f}\n\n")
        
        f.write("\nMONTHLY BREAKDOWN\n")
        f.write("-" * 80 + "\n")
        for _, row in df.iterrows():
            f.write(f"{row['oos_month']}: {row['total_signals']:3d} signals, "
                   f"{row['combined_win_rate']:5.1%} win rate, "
                   f"{row['total_pnl']:6.2%} P&L\n")
    
    logging.info(f"\nReport saved to: {report_file}")
    
    logging.info("")
    logging.info("=" * 80)
    logging.info("ANALYSIS COMPLETE")
    logging.info("=" * 80)


if __name__ == "__main__":
    main()
