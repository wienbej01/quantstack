
import logging
import pandas as pd
from pathlib import Path
from extensions.intraday_ml_models.bigmove_training_utils import (
    load_master_and_includes,
    load_yaml,
    build_split_dataset,
    attach_bigmove_labels,
)

def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    dataset_config_path = Path("configs/extensions/intraday_ml/phaseA_sip_full.yaml")
    targets_config_path = Path("configs/extensions/intraday_ml/targets_bigmove.yaml")

    logger.info("Loading configs...")
    master_config, includes = load_master_and_includes(dataset_config_path)
    targets_cfg = load_yaml(targets_config_path)

    # FORCE DISABLE SIP FILTER FOR SPEED
    master_config["sip_filter"] = {"enabled": False}
    logger.info("Disabled SIP filter for debugging.")

    # Manually override splits to be very small for speed
    # We'll just look at one month of data
    includes["splits"]["train"] = {
        "start": "2024-01-08",
        "end": "2024-01-12"
    }
    logger.info("Overrode train split to 2024-01-08 -> 2024-01-12")

    logger.info("Building dataset (train split)...")
    # We use 'train' split as it's what the model learns from
    dataset, _ = build_split_dataset(
        master_config=master_config,
        includes=includes,
        targets_config=targets_cfg,
        split="train",
    )
    
    logger.info(f"Dataset shape: {dataset.shape}")

    logger.info("Attaching big-move labels...")
    dataset, label_config = attach_bigmove_labels(dataset, targets_cfg)
    
    label_col = label_config.label_name
    threshold_col = "big_move_threshold" # This is added by compute_big_move_labels but not formally in config returned?
    # Actually compute_big_move_labels returns a result object with it, 
    # but attach_bigmove_labels might not attach the threshold column to the dataframe returned.
    # Let's check the implementation of attach_bigmove_labels again...
    # It attaches label_name, direction_label_name, forward_return_column.
    # It does NOT attach the threshold.
    
    # We can re-compute the threshold locally for inspection or trust the labels.
    # Let's just look at the labels first.
    
    counts = dataset[label_col].value_counts()
    logger.info(f"Label counts:\n{counts}")
    
    pos_rate = counts.get(1, 0) / len(dataset)
    logger.info(f"Positive rate: {pos_rate:.6f}")

    if pos_rate == 0:
        logger.error("NO POSITIVE LABELS FOUND!")
    
    # Let's inspect some rows where we EXPECTED a move or where the return was high
    fwd_col = label_config.forward_return_column
    dataset['abs_fwd_return'] = dataset[fwd_col].abs()
    
    logger.info("Top 10 absolute forward returns:")
    print(dataset.sort_values('abs_fwd_return', ascending=False)[['symbol', 'ts', 'close', fwd_col, label_col]].head(10))

    # Check the ATR column values
    atr_col = label_config.atr_column
    logger.info(f"ATR column ({atr_col}) stats:")
    print(dataset[atr_col].describe())

    # Verify Hypothesis: Is ATR absolute or percentage?
    # Calculate implied % volatility if we assume it is absolute
    dataset['implied_atr_pct'] = dataset[atr_col] / dataset['close']
    logger.info("Implied ATR % (assuming raw col is absolute $):")
    print(dataset['implied_atr_pct'].describe())

    # If the raw column was ALREADY percentage, these numbers would be tiny (e.g. 0.01 / 100 = 0.0001)
    # If the raw column is absolute, these numbers should look like normal vol (e.g. 0.002 to 0.01)
    
if __name__ == "__main__":
    main()
