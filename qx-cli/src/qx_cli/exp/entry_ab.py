"""Entry A/B testing command."""

import glob
import json
import pathlib
import uuid
from typing import Dict, Any

import yaml
import typer
import pandas as pd
import numpy as np
import random
from rich.console import Console

from qx_cli.exp import app
from qx_data.gold_loader import load_bars
from qx_features.registry import apply_feature_packs
from qx_screener.sip import screen
from qx_backtest.policies.vwap_revert import generate_signals
from qx_risk.atr_stop import size_order, set_stops
from qx_backtest.engine import run_backtest
from qx_core.hashers import hash_dataframe

console = Console()


@app.command("entry-ab")
def entry_ab(
    cfg: pathlib.Path = typer.Option(..., "--cfg", help="Base config file"),
    variants: str = typer.Option(..., "--variants", help="Variant overlay files pattern, e.g., test_config/variant_*.json"),
    name: str = typer.Option(..., "--name", help="Experiment ID"),
    force: bool = typer.Option(False, "--force", help="Force run even if checksums differ"),
) -> None:
    """Run entry A/B test with multiple policy variants."""
    console.print(f"Running entry-ab experiment: {name}")

    # Glob variant files
    variant_files = sorted(glob.glob(variants))  # Sort for determinism
    if not variant_files:
        console.print(f"No variant files found for pattern: {variants}", style="red")
        raise typer.Exit(1)

    # Create experiment directory
    exp_dir = pathlib.Path("experiments") / name
    exp_dir.mkdir(parents=True, exist_ok=True)

    # Load base config
    with open(cfg) as f:
        base_config = yaml.safe_load(f)

    # Set seed for determinism
    seed = base_config.get("seed", 42)
    random.seed(seed)
    np.random.seed(seed)

    # Load and normalize bars
    gold_root = base_config["gold_root"]
    family = base_config["family"]
    symbols = base_config["symbols"]
    dates = base_config["dates"]
    bars_df = load_bars(gold_root, family, symbols, dates)
    bars_norm_hash = hash_dataframe(bars_df, cols=["ts", "symbol", "open", "high", "low", "close", "volume"])

    # Apply features
    feature_packs = base_config["features"]
    df_with_features = apply_feature_packs(bars_df, feature_packs)
    warmup_mask = df_with_features["f__warmup_ok"]
    features_hash = hash_dataframe(df_with_features, cols=[c for c in df_with_features.columns if c.startswith("f__")])

    # SIP screen
    rvol_col = "f__vol__rel_volume_30"  # Hardcoded for now
    top_n = base_config.get("sip", {}).get("top_n", 5)
    whitelist = base_config.get("sip", {}).get("whitelist")
    if base_config.get('sip_filter', True):
        universe_map = screen(df_with_features, rvol_col, top_n, whitelist)
    else:
        universe_map = None
    # Hash the universe_map deterministically
    if universe_map is not None:
        sorted_universe = {int(k): sorted(list(v)) for k, v in universe_map.items()}
        sip_hash = hash_dataframe(pd.DataFrame([(k, json.dumps(v, sort_keys=True)) for k, v in sorted_universe.items()], columns=["ts", "symbols"]), cols=["ts", "symbols"])
    else:
        sip_hash = hash_dataframe(pd.DataFrame([json.dumps({}, sort_keys=True)], columns=["sip"]), cols=["sip"])

    # For each variant, run backtest
    run_ids = []
    for variant_path in variant_files:
        variant = pathlib.Path(variant_path)
        with open(variant) as f:
            overlay = yaml.safe_load(f)

        # Merge configs (deep merge)
        config = deep_merge(base_config, overlay)

        # Config hash (of merged config, excluding seed?)
        config_str = json.dumps(config, sort_keys=True)
        config_hash = hash_dataframe(pd.DataFrame([config_str], columns=["config"]), cols=["config"])

        # Generate run ID
        run_id = str(uuid.uuid4())
        run_ids.append(run_id)
        run_dir = pathlib.Path("runs") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Generate signals
        policy_params = config["policy_params"]
        policy_params["sip_universe"] = universe_map
        signals_df = generate_signals(df_with_features, policy_params)

        # Size and stops (integrate into signals or separate)
        # For simplicity, assume signals have entry_hint = close, stop_hint = close - atr
        # But need to add qty and stop_dist_ps to signals

        # Actually, the document says risk.size_and_stops() → orders with qty, stop_dist_ps
        # So, need to create orders from signals

        orders_df = create_orders_from_signals(signals_df, df_with_features, config)

        # Run backtest
        backtest_params = config["backtest"]
        artifacts = run_backtest(df_with_features, orders_df, signals_df, backtest_params)

        # Write artifacts
        artifacts["signals"].to_parquet(run_dir / "signals.parquet")
        artifacts["orders"].to_parquet(run_dir / "orders.parquet")
        artifacts["fills"].to_parquet(run_dir / "fills.parquet")
        artifacts["positions"].to_parquet(run_dir / "positions.parquet")
        artifacts["equity"].to_parquet(run_dir / "equity.parquet")
        artifacts["trades"].to_parquet(run_dir / "trades.parquet")
        artifacts["risk_rejects"].to_parquet(run_dir / "risk_rejects.parquet")
        artifacts["allocation_log"].to_parquet(run_dir / "allocation_log.parquet")
        with open(run_dir / "metrics.json", "w") as f:
            json.dump(artifacts["metrics"], f, indent=2)

        # Write checksum for this run
        variant_checksum = {
            "bars_norm_hash": bars_norm_hash,
            "features_hash": features_hash,
            "sip_hash": sip_hash,
            "config_hash": config_hash,
            "seed": seed
        }
        with open(run_dir / "inputs_checksum.json", "w") as f:
            json.dump(variant_checksum, f, indent=2)

    # Write experiment manifest
    manifest = {
        "exp_id": name,
        "type": "entry-ab",
        "base_config": str(cfg),
        "variants": variant_files,
        "run_ids": run_ids,
        "resolved_config": base_config,  # Actually, should be the merged, but since variants differ, maybe base
        "feature_packs": feature_packs,
        "policy_params": base_config["policy"],  # Base policy
        "sip_params": base_config.get("sip", {}),
        "data_slice": {
            "symbols": symbols,
            "dates": dates,
            "gold_root": gold_root
        },
        "git_commit": "dirty",  # Stub
        "seed": seed
    }
    with open(exp_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    

    # Run compare
    from qx_cli.exp.compare import compare_experiments
    compare_result = compare_experiments(exp_dir)

    # Print run summary
    print_run_summary(compare_result, run_ids)

    console.print(f"Experiment {name} completed. Artifacts in {exp_dir}")


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge overlay into base."""
    result = base.copy()
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def create_orders_from_signals(signals_df: pd.DataFrame, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
    """Create orders DataFrame from signals with sizing and stops."""
    orders = []
    equity = config["backtest"]["initial_equity"]
    risk_params = config["risk_params"]

    # Merge signals with bars for ATR and warmup
    merged = signals_df.merge(df[["ts", "symbol", "close", "f__vol__atr_14", "f__warmup_ok"]], on=["ts", "symbol"], how="left", suffixes=('_sig', '_bar'))

    prev_signals = {}  # symbol -> prev_signal

    for _, row in merged.iterrows():
        symbol = row["symbol"]
        prev_signal = prev_signals.get(symbol, 0)
        if row["signal"] == 1 and prev_signal == 0 and row["f__warmup_ok"]:
            # Entry signal
            atr_mult = risk_params.get('atr_mult', 1.0)
            signal_dict = {
                "entry_hint": row["close_bar"],
                "stop_hint": row["close_bar"] - row["f__vol__atr_14"] * atr_mult
            }
            qty = size_order(signal_dict, equity, row["f__vol__atr_14"], risk_params)
            if qty:
                stop_price, target_price = set_stops(signal_dict, qty, row["f__vol__atr_14"], risk_params)
                stop_dist_ps = row["f__vol__atr_14"] * atr_mult
                orders.append({
                    "ts": row["ts"],
                    "symbol": row["symbol"],
                    "side": "BUY",
                    "qty": qty,
                    "stop_dist_ps": stop_dist_ps,
                    "type": "MKT",
                    "tif": "DAY"
                })
        prev_signals[symbol] = row["signal"]

    return pd.DataFrame(orders)


def print_run_summary(compare_result: Dict, run_ids: list) -> None:
    """Print concise run summary."""
    # Load trades for each run
    summaries = []
    for run_id in run_ids:
        run_dir = pathlib.Path("runs") / run_id
        trades_df = pd.read_parquet(run_dir / "trades.parquet")
        if not trades_df.empty:
            mean_pnl = trades_df["pnl"].mean()
            median_r = trades_df["r_multiple"].median()
        else:
            mean_pnl = 0.0
            median_r = 0.0
        summaries.append({
            "run_id": run_id,
            "trades": len(trades_df),
            "mean_pnl": mean_pnl,
            "median_r": median_r
        })

    console.print("Run Summary:")
    for summary in summaries:
        console.print(f"  {summary['run_id']}: trades={summary['trades']}, mean_pnl={summary['mean_pnl']:.2f}, median_R={summary['median_r']:.4f}")

    # If counts equal, show first differences in signals
    if len(set(s["trades"] for s in summaries)) == 1:
        # Load signals and compare
        signals_dfs = []
        for run_id in run_ids:
            run_dir = pathlib.Path("runs") / run_id
            signals_dfs.append(pd.read_parquet(run_dir / "signals.parquet"))
        # Simple diff: first differing row
        for i in range(len(signals_dfs[0])):
            row0 = signals_dfs[0].iloc[i]
            for j, df in enumerate(signals_dfs[1:], 1):
                rowj = df.iloc[i]
                if not row0.equals(rowj):
                    console.print(f"First signal difference at row {i}: variant 0 vs {j}")
                    break
            else:
                continue
            break