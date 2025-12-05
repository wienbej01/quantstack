#!/usr/bin/env python3
"""Monitor training progress and display key metrics."""

import argparse
import json
import time
from pathlib import Path

BYTES_PER_KB = 1024


def format_size(size_bytes: float) -> str:
    """Format bytes to human readable."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < BYTES_PER_KB:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= BYTES_PER_KB
    return f"{size_bytes:.1f}TB"


def check_file_progress(output_root: Path) -> dict:
    """Check which files exist and their sizes."""
    files = {
        "training_data": output_root / "training_data.parquet",
        "oos_features": output_root / "oos_features.parquet",
        "stage1_model": output_root / "bigmove_stage1" / "model.pkl",
        "stage1_metadata": output_root / "bigmove_stage1" / "metadata.json",
        "stage1_feature_perf": output_root
        / "bigmove_stage1"
        / "feature_performance_summary.json",
        "stage2_model": output_root / "bigmove_stage2_dir" / "model.pkl",
        "stage2_metadata": output_root / "bigmove_stage2_dir" / "metadata.json",
        "stage2_feature_perf": output_root
        / "bigmove_stage2_dir"
        / "feature_performance_summary.json",
    }

    status = {}
    for name, path in files.items():
        if path.exists():
            size = path.stat().st_size
            status[name] = {
                "exists": True,
                "size": format_size(size),
                "path": str(path),
            }
        else:
            status[name] = {"exists": False, "size": None, "path": str(path)}

    return status


def display_feature_performance(perf_path: Path, stage: str) -> None:
    """Display feature performance summary."""
    if not perf_path.exists():
        return

    with open(perf_path) as f:
        perf = json.load(f)

    print(f"\n{stage} Feature Performance:")
    print("=" * 60)

    corr_stats = perf.get("correlation_stats", {})
    print(f"  Max Correlation:    {corr_stats.get('max_abs_correlation', 0):.4f}")
    print(f"  Mean Correlation:   {corr_stats.get('mean_abs_correlation', 0):.4f}")
    print(f"  Features > 0.10:    {corr_stats.get('features_above_0.10', 0)}")
    print(f"  Features > 0.05:    {corr_stats.get('features_above_0.05', 0)}")

    imp_stats = perf.get("importance_stats")
    if imp_stats:
        print(f"  Max Importance:     {imp_stats.get('max_importance', 0):.4f}")
        print(f"  Zero Importance:    {imp_stats.get('zero_importance_count', 0)}")

    print("\n  Top 5 Features by Correlation:")
    for i, feat in enumerate(perf.get("top_10_by_correlation", [])[:5], 1):
        print(f"    {i}. {feat['feature']}: {feat['pearson']:.4f}")


def display_model_metrics(metadata_path: Path, stage: str) -> None:
    """Display model training metrics."""
    if not metadata_path.exists():
        return

    with open(metadata_path) as f:
        meta = json.load(f)

    print(f"\n{stage} Model Metrics:")
    print("=" * 60)

    print(f"  Training Samples:   {meta.get('training_samples', 0):,}")
    print(f"  Feature Count:      {meta.get('feature_count', 0)}")

    class_dist = meta.get("class_distribution", {})
    total = sum(class_dist.values())
    print("  Class Distribution:")
    for cls, count in sorted(class_dist.items()):
        pct = 100 * count / total if total > 0 else 0
        print(f"    Class {cls}: {count:,} ({pct:.1f}%)")

    metrics = meta.get("metrics", {})
    print("\n  Training Metrics:")
    print(f"    Accuracy:  {metrics.get('accuracy', 0):.4f}")
    print(f"    Precision: {metrics.get('precision', 0):.4f}")
    print(f"    Recall:    {metrics.get('recall', 0):.4f}")
    print(f"    F1:        {metrics.get('f1', 0):.4f}")
    if "roc_auc" in metrics:
        print(f"    ROC AUC:   {metrics.get('roc_auc', 0):.4f}")

    cv_summary = meta.get("cv_metrics", {}).get("summary", {})
    if cv_summary:
        print("\n  Cross-Validation (mean ± std):")
        for metric, stats in cv_summary.items():
            mean = stats.get("mean", 0)
            std = stats.get("std", 0)
            if mean is not None:
                print(f"    {metric}: {mean:.4f} ± {std:.4f}")


def main():
    parser = argparse.ArgumentParser(description="Monitor training progress")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artefacts/extensions/intraday_ml/phaseA_full_sip_v2"),
        help="Training output directory",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch mode - refresh every 30 seconds",
    )
    args = parser.parse_args()

    while True:
        print("\n" + "=" * 80)
        print(f"Training Progress Monitor - {args.output_root}")
        print("=" * 80)

        status = check_file_progress(args.output_root)

        print("\nFile Status:")
        print("-" * 60)
        for name, info in status.items():
            status_str = "✓" if info["exists"] else "✗"
            size_str = f"({info['size']})" if info["size"] else ""
            print(f"  {status_str} {name:25s} {size_str}")

        # Display Stage 1 metrics if available
        if status["stage1_metadata"]["exists"]:
            display_model_metrics(
                Path(status["stage1_metadata"]["path"]), "Stage 1 (Probability)"
            )

        if status["stage1_feature_perf"]["exists"]:
            display_feature_performance(
                Path(status["stage1_feature_perf"]["path"]), "Stage 1"
            )

        # Display Stage 2 metrics if available
        if status["stage2_metadata"]["exists"]:
            display_model_metrics(
                Path(status["stage2_metadata"]["path"]), "Stage 2 (Direction)"
            )

        if status["stage2_feature_perf"]["exists"]:
            display_feature_performance(
                Path(status["stage2_feature_perf"]["path"]), "Stage 2"
            )

        if not args.watch:
            break

        print("\n" + "=" * 80)
        print("Refreshing in 30 seconds... (Ctrl+C to exit)")
        time.sleep(30)


if __name__ == "__main__":
    main()
