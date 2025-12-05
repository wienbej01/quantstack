"""Analyze Stage 1 model performance and feature importance."""
import json
import joblib
from pathlib import Path
import pandas as pd
import numpy as np


def analyze_stage1_model(model_path: Path, output_path: Path):
    """Extract feature importance and model diagnostics from Stage 1."""
    model = joblib.load(model_path)
    
    # Feature importance
    importance = pd.DataFrame({
        "feature": model.feature_name_,
        "importance": model.feature_importances_,
    }).sort_values("importance", ascending=False)
    
    # Top features by family
    families = {}
    for feat in importance["feature"]:
        family = feat.split("__")[1] if "__" in feat else "other"
        families.setdefault(family, []).append(feat)
    
    report = {
        "model_type": type(model).__name__,
        "n_features": len(model.feature_name_),
        "n_estimators": model.n_estimators,
        "top_20_features": importance.head(20).to_dict("records"),
        "feature_families": {k: len(v) for k, v in families.items()},
        "top_features_by_family": {
            family: importance[importance["feature"].isin(feats)].head(5)["feature"].tolist()
            for family, feats in families.items()
        },
        "importance_concentration": {
            "top_10_pct": importance.head(10)["importance"].sum() / importance["importance"].sum(),
            "top_20_pct": importance.head(20)["importance"].sum() / importance["importance"].sum(),
        }
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    
    # Save full importance table
    importance.to_csv(output_path.with_suffix(".csv"), index=False)
    
    print(f"✓ Stage 1 analysis saved to {output_path}")
    print(f"  Top feature: {importance.iloc[0]['feature']} ({importance.iloc[0]['importance']:.4f})")
    print(f"  Top 10 features account for {report['importance_concentration']['top_10_pct']:.1%} of importance")


if __name__ == "__main__":
    model_path = Path("artefacts/extensions/intraday_ml/bigmove_stage1/model.pkl")
    output_path = Path("reports/diagnostics/stage1_analysis.json")
    analyze_stage1_model(model_path, output_path)
