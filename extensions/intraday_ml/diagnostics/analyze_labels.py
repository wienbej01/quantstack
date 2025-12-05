"""Analyze label distribution from training metadata."""
import json
from pathlib import Path


def analyze_labels_from_meta(meta_path: Path, output_path: Path):
    """Analyze big move label distribution from training metadata."""
    with open(meta_path) as f:
        meta = json.load(f)
    
    # Extract class distribution
    class_dist = meta.get("class_distribution", {})
    total_samples = sum(class_dist.values())
    positive_samples = class_dist.get("1", 0)
    negative_samples = class_dist.get("0", 0)
    bigmove_rate = positive_samples / total_samples if total_samples > 0 else 0
    
    # Confusion matrix analysis
    cm = meta.get("metrics", {}).get("confusion_matrix", {})
    tn, fp, fn, tp = cm.get("tn", 0), cm.get("fp", 0), cm.get("fn", 0), cm.get("tp", 0)
    
    report = {
        "total_samples": total_samples,
        "bigmove_count": positive_samples,
        "no_bigmove_count": negative_samples,
        "bigmove_rate": round(bigmove_rate, 4),
        "imbalance_ratio": round(negative_samples / positive_samples, 2) if positive_samples > 0 else 0,
        "dataset_info": meta.get("dataset", {}),
        "model_predictions": {
            "true_negatives": tn,
            "false_positives": fp,
            "false_negatives": fn,
            "true_positives": tp,
            "predicted_positive_rate": (tp + fp) / (tn + fp + fn + tp) if (tn + fp + fn + tp) > 0 else 0,
        },
        "key_insights": {
            "samples_per_day": total_samples / meta.get("dataset", {}).get("symbols", 1),
            "bigmoves_per_day": positive_samples / meta.get("dataset", {}).get("symbols", 1),
            "model_recall": tp / (tp + fn) if (tp + fn) > 0 else 0,
            "model_precision": tp / (tp + fp) if (tp + fp) > 0 else 0,
        }
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    
    print(f"✓ Label analysis saved to {output_path}")
    print(f"  Big move rate: {bigmove_rate:.2%} ({positive_samples:,}/{total_samples:,})")
    print(f"  Imbalance ratio: {report['imbalance_ratio']:.1f}:1 (negative:positive)")
    print(f"  Date range: {report['dataset_info'].get('start_date')} to {report['dataset_info'].get('end_date')}")
    print(f"  Symbols: {report['dataset_info'].get('symbols')}")


if __name__ == "__main__":
    meta_path = Path("artefacts/extensions/intraday_ml/bigmove_stage1/train_meta.json")
    output_path = Path("reports/diagnostics/label_analysis.json")
    analyze_labels_from_meta(meta_path, output_path)
