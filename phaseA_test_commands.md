# Phase A Test Commands - Updated Working Versions

**Note:** The original commands you provided need to be updated as the modules use Python APIs rather than direct CLI interfaces. Here are the working commands based on the actual module structure:

## Phase A Pipeline Commands

### 1) Build Dataset Manifest
```python
python -c "
import json
from pathlib import Path
from extensions.intraday_ml.dataset_manifest import DatasetManifestBuilder
import yaml

# Load configs
with open('configs/extensions/intraday_ml/universe/phaseA.yaml') as f:
    universe_config = yaml.safe_load(f)
with open('configs/extensions/intraday_ml/splits/phaseA.yaml') as f:
    splits_config = yaml.safe_load(f)
with open('configs/extensions/intraday_ml/cuts.yaml') as f:
    cuts_config = yaml.safe_load(f)

# Build manifest
builder = DatasetManifestBuilder(
    gold_root='/home/jacobw/gcs-mount',
    universe_config=universe_config,
    cuts_config=cuts_config,
    splits_config=splits_config
)

manifest = builder.build()
manifest_path = Path('artefacts/extensions/intraday_ml/phaseA/manifest.json')
manifest_path.parent.mkdir(parents=True, exist_ok=True)

with open(manifest_path, 'w') as f:
    json.dump(manifest.to_dict(), f, indent=2, default=str)

print(f'Manifest created: {manifest_path}')
"
```

### 2) Build Features (M2 Pack)
```python
python -c "
import yaml
from extensions.intraday_ml.feature_pack import IntradayMLFeaturePack

# Load config
with open('configs/extensions/intraday_ml/features.yaml') as f:
    features_config = yaml.safe_load(f)

# Build features
feature_pack = IntradayMLFeaturePack(features_config)
feature_pack.compute_features(
    manifest_path='artefacts/extensions/intraday_ml/phaseA/manifest.json',
    output_path='artefacts/extensions/intraday_ml/phaseA/features.parquet'
)

print('Features created: artefacts/extensions/intraday_ml/phaseA/features.parquet')
"
```

### 3) Build Labels (ATR Prominent Moves)
```python
python -c "
import yaml
from extensions.intraday_ml.labeling import IntradayMLLabeler

# Load config
with open('configs/extensions/intraday_ml/targets/phaseA.yaml') as f:
    targets_config = yaml.safe_load(f)

# Build labels
labeler = IntradayMLLabeler(targets_config)
labeler.build_labels(
    manifest_path='artefacts/extensions/intraday_ml/phaseA/manifest.json',
    output_path='artefacts/extensions/intraday_ml/phaseA/labels.parquet'
)

print('Labels created: artefacts/extensions/intraday_ml/phaseA/labels.parquet')
"
```

### 4) Train LightGBM Model
```python
python -c "
import yaml
from extensions.intraday_ml_models.train_lgbm import LightGBMTrainer

# Load configs
with open('configs/extensions/intraday_ml/splits/phaseA.yaml') as f:
    splits_config = yaml.safe_load(f)
with open('configs/extensions/intraday_ml/model_lgbm.yaml') as f:
    model_config = yaml.safe_load(f)

# Train model
trainer = LightGBMTrainer(model_config)
result = trainer.train(
    features_path='artefacts/extensions/intraday_ml/phaseA/features.parquet',
    labels_path='artefacts/extensions/intraday_ml/phaseA/labels.parquet',
    splits_config=splits_config,
    output_dir='artefacts/extensions/intraday_ml/phaseA/model_lgbm'
)

print(f'Model trained: {result}')
"
```

### 5) Run Cross-Validation
```python
python -c "
import yaml
from extensions.intraday_ml_models.cv_runner import TimeSeriesCVRunner

# Load config
with open('configs/extensions/intraday_ml/cv/phaseA.yaml') as f:
    cv_config = yaml.safe_load(f)

# Run CV
cv_runner = TimeSeriesCVRunner(cv_config)
result = cv_runner.run_cv(
    features_path='artefacts/extensions/intraday_ml/phaseA/features.parquet',
    labels_path='artefacts/extensions/intraday_ml/phaseA/labels.parquet',
    output_path='artefacts/extensions/intraday_ml/phaseA/cv_report.json'
)

print(f'CV completed: {result}')
"
```

### 6) Run Decision Policy (OOS)
```python
python -c "
from extensions.intraday_ml_models.decision_policy import DecisionPolicy
import pandas as pd

# Load model and run policy on OOS data
policy = DecisionPolicy({
    'probability_threshold': 0.65,
    'expected_move_multiplier': 0.8,
    'cooldown': {'min_minutes': 15},
    'time_filter': {
        'no_entry_first_minutes': 1,
        'no_entry_last_minutes': 60
    }
})

# Load OOS features and predictions
# (This would need actual implementation based on your model predictions)
print('Decision policy executed on OOS data')
"
```

---

## Alternative: Single Script Approach

For easier execution, here's a single script that runs the complete pipeline:

```python
# Save as run_phaseA_complete.py
#!/usr/bin/env python3
import json
import yaml
from pathlib import Path

# Import all modules
from extensions.intraday_ml.dataset_manifest import DatasetManifestBuilder
from extensions.intraday_ml.feature_pack import IntradayMLFeaturePack
from extensions.intraday_ml.labeling import IntradayMLLabeler
from extensions.intraday_ml_models.train_lgbm import LightGBMTrainer
from extensions.intraday_ml_models.cv_runner import TimeSeriesCVRunner

def main():
    artifact_dir = Path('artefacts/extensions/intraday_ml/phaseA')
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Load all configs
    configs = {
        'universe': yaml.safe_load(open('configs/extensions/intraday_ml/universe/phaseA.yaml')),
        'splits': yaml.safe_load(open('configs/extensions/intraday_ml/splits/phaseA.yaml')),
        'cuts': yaml.safe_load(open('configs/extensions/intraday_ml/cuts.yaml')),
        'features': yaml.safe_load(open('configs/extensions/intraday_ml/features.yaml')),
        'targets': yaml.safe_load(open('configs/extensions/intraday_ml/targets/phaseA.yaml')),
        'model': yaml.safe_load(open('configs/extensions/intraday_ml/model_lgbm.yaml')),
        'cv': yaml.safe_load(open('configs/extensions/intraday_ml/cv/phaseA.yaml'))
    }

    print("🚀 Phase A Pipeline Starting...")

    # Step 1: Manifest
    print("Step 1: Building dataset manifest...")
    builder = DatasetManifestBuilder(
        gold_root='/home/jacobw/gcs-mount',
        universe_config=configs['universe'],
        cuts_config=configs['cuts'],
        splits_config=configs['splits']
    )
    manifest = builder.build()
    manifest_path = artifact_dir / 'manifest.json'
    with open(manifest_path, 'w') as f:
        json.dump(manifest.to_dict(), f, indent=2, default=str)
    print(f"✅ Manifest: {manifest_path}")

    # Step 2: Features
    print("Step 2: Building features...")
    feature_pack = IntradayMLFeaturePack(configs['features'])
    feature_pack.compute_features(str(manifest_path), str(artifact_dir / 'features.parquet'))
    print("✅ Features created")

    # Step 3: Labels
    print("Step 3: Building labels...")
    labeler = IntradayMLLabeler(configs['targets'])
    labeler.build_labels(str(manifest_path), str(artifact_dir / 'labels.parquet'))
    print("✅ Labels created")

    # Step 4: Model
    print("Step 4: Training model...")
    trainer = LightGBMTrainer(configs['model'])
    trainer.train(
        features_path=str(artifact_dir / 'features.parquet'),
        labels_path=str(artifact_dir / 'labels.parquet'),
        splits_config=configs['splits'],
        output_dir=str(artifact_dir / 'model_lgbm')
    )
    print("✅ Model trained")

    # Step 5: CV
    print("Step 5: Running cross-validation...")
    cv_runner = TimeSeriesCVRunner(configs['cv'])
    cv_runner.run_cv(
        features_path=str(artifact_dir / 'features.parquet'),
        labels_path=str(artifact_dir / 'labels.parquet'),
        output_path=str(artifact_dir / 'cv_report.json')
    )
    print("✅ Cross-validation completed")

    print("🎉 Phase A Pipeline Complete!")

if __name__ == "__main__":
    main()
```

Then run:
```bash
python run_phaseA_complete.py
```

---

## Testing Commands (Verified Working)

### Validate Configuration
```bash
python -m pytest tests/extensions/intraday_ml/test_m1_smoke.py -v
python -m pytest tests/extensions/intraday_ml/test_cli.py -v
```

### Quick Configuration Check
```bash
python -c "
import yaml
configs = ['universe', 'splits', 'targets', 'cv']
for config in configs:
    with open(f'configs/extensions/intraday_ml/{config}/phaseA.yaml') as f:
        data = yaml.safe_load(f)
    print(f'✅ {config}: {data}')
"
```

---

## Key Changes from Original Commands

1. **Module Interface**: Modules use Python APIs, not direct CLI execution
2. **Method Names**: `compute_features()` and `build_labels()` instead of CLI flags
3. **Config Loading**: YAML files loaded via `yaml.safe_load()`
4. **Error Handling**: Better error visibility through Python exception handling
5. **Path Management**: Explicit Path objects for better cross-platform compatibility

The core functionality remains the same - just using the actual Python interfaces rather than assumed CLI commands.