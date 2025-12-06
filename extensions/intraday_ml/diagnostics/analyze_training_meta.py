"""Analyze training metadata and cross-validation results."""
import json
from pathlib import Path


def analyze_training_meta(meta_path: Path, output_path: Path):
    """Extract key insights from training metadata."""
    with open(meta_path) as f:
        meta = json.load(f)
    
    # Extract key metrics
    metrics = meta.get("metrics", {})
    cv_summary = meta.get("cv_metrics", {}).get("summary", {})
    
    # Class imbalance
    class_dist = meta.get("class_distribution", {})
    total = sum(class_dist.values())
    imbalance_ratio = class_dist.get("0", 0) / class_dist.get("1", 1) if class_dist.get("1") else 0
    
    # Model performance summary
    report = {
        "stage": meta.get("stage"),
        "training_samples": meta.get("training_samples"),
        "feature_count": meta.get("feature_count"),
        "class_imbalance": {
            "negative_samples": class_dist.get("0"),
            "positive_samples": class_dist.get("1"),
            "imbalance_ratio": round(imbalance_ratio, 2),
            "positive_rate": meta.get("metrics", {}).get("positive_rate"),
        },
        "performance": {
            "roc_auc": metrics.get("roc_auc"),
            "precision": metrics.get("precision"),
            "recall": metrics.get("recall"),
            "f1": metrics.get("f1"),
            "accuracy": metrics.get("accuracy"),
        },
        "cv_performance": {
            "roc_auc_mean": cv_summary.get("roc_auc", {}).get("mean"),
            "roc_auc_std": cv_summary.get("roc_auc", {}).get("std"),
            "precision_mean": cv_summary.get("precision", {}).get("mean"),
            "recall_mean": cv_summary.get("recall", {}).get("mean"),
            "f1_mean": cv_summary.get("f1", {}).get("mean"),
        },
        "confusion_matrix": metrics.get("confusion_matrix", {}),
        "dataset_info": meta.get("dataset", {}),
    }
    
    # Calculate derived metrics
    cm = metrics.get("confusion_matrix", {})
    if cm:
        tn, fp, fn, tp = cm.get("tn", 0), cm.get("fp", 0), cm.get("fn", 0), cm.get("tp", 0)
        report["derived_metrics"] = {
            "false_positive_rate": fp / (fp + tn) if (fp + tn) > 0 else 0,
            "false_negative_rate": fn / (fn + tp) if (fn + tp) > 0 else 0,
            "true_negative_rate": tn / (tn + fp) if (tn + fp) > 0 else 0,
        }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    
    print(f"✓ Training meta analysis saved to {output_path}")
    print(f"\n  Model: {report['stage']}")
    print(f"  Samples: {report['training_samples']:,} ({report['class_imbalance']['positive_rate']:.2%} positive)")
    print(f"  Imbalance ratio: {report['class_imbalance']['imbalance_ratio']:.1f}:1")
    print("\n  Performance:")
    print(f"    ROC-AUC: {report['performance']['roc_auc']:.4f}")
    print(f"    Precision: {report['performance']['precision']:.4f}")
    print(f"    Recall: {report['performance']['recall']:.4f}")
    print(f"    F1: {report['performance']['f1']:.4f}")
    print("\n  CV Performance (5-fold):")
    print(f"    ROC-AUC: {report['cv_performance']['roc_auc_mean']:.4f} ± {report['cv_performance']['roc_auc_std']:.4f}")


if __name__ == "__main__":
    meta_path = Path("artefacts/extensions/intraday_ml/bigmove_stage1/train_meta.json")
    output_path = Path("reports/diagnostics/training_meta_analysis.json")
    analyze_training_meta(meta_path, output_path)
