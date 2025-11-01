"""Entry A/B testing command."""

import glob
import json
import pathlib
import random
import uuid
from typing import Any

import numpy as np
import pandas as pd
import typer
import yaml
from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_backtest.fill import DefaultFiller
from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy
from qx_backtest.policies.vwap_momentum import (
    generate_signals as generate_vwap_momentum_signals,
)
from qx_backtest.policies.vwap_revert import VwapRevertPolicy
from qx_backtest.policies.vwap_revert import (
    generate_signals as generate_vwap_revert_signals,
)
from qx_core.hashers import hash_dataframe, hash_sip_map
from qx_data.gold_loader import load_bars
from qx_features.registry import apply_feature_packs
from qx_screener.hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector
from qx_screener.sip import screen
from rich.console import Console

from qx_cli.exp import app

console = Console()


@app.command("entry-ab")
def entry_ab(
    cfg: pathlib.Path = typer.Option(..., "--cfg", help="Base config file"),
    variants: str = typer.Option(
        ...,
        "--variants",
        help="Variant overlay files pattern, e.g., test_config/variant_*.json",
    ),
    name: str = typer.Option(..., "--name", help="Experiment ID"),
    force: bool = typer.Option(
        False, "--force", help="Force run even if checksums differ"
    ),
) -> None:
    """Run entry A/B test with multiple policy variants."""
    console.print(f"Running entry-ab experiment: {name}")

    # Handle comma-separated list or glob pattern
    if "," in variants:
        # Comma-separated list of files
        variant_files = [f.strip() for f in variants.split(",") if f.strip()]
    else:
        # Glob pattern
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
    bars_norm_hash = hash_dataframe(
        bars_df, cols=["ts", "symbol", "open", "high", "low", "close", "volume"]
    )

    # Apply features
    feature_packs = base_config["features"]
    df_with_features = apply_feature_packs(bars_df, feature_packs)
    features_hash = hash_dataframe(
        df_with_features,
        cols=[c for c in df_with_features.columns if c.startswith("f__")],
    )

    # For each variant, run backtest
    run_ids = []
    actual_metrics: list[dict[str, Any]] = []
    for variant_path in variant_files:
        variant = pathlib.Path(variant_path)
        with open(variant) as f:
            overlay = yaml.safe_load(f)

        # Merge configs (deep merge)
        config = deep_merge(base_config, overlay)

        # SIP screening / hashing
        universe_map = None
        sip_hash = None
        sip_selector = None
        sip_method = "none"

        if config.get("sip_filter", True):
            sip_selector, sip_method = _setup_sip_selector(config)

            if sip_method == "hmm":
                # Use HMM SIP selector
                target_dates = config.get("dates") or dates
                target_date = target_dates[0] if target_dates else None
                if target_date:
                    ref = {"target_date": target_date}
                    universe_map = sip_selector.select(df_with_features, ref)

                sip_hash = (
                    hash_sip_map(universe_map)
                    if universe_map
                    else hash_dataframe(
                        pd.DataFrame([json.dumps({}, sort_keys=True)], columns=["sip"]),
                        cols=["sip"],
                    )
                )
            else:
                # Original SIP screener (legacy top-N)
                sip_config = config.get("sip", {})
                rvol_col = "f__vol__rel_volume_30"
                top_n = sip_config.get("top_n", 5)
                whitelist = sip_config.get("whitelist")
                universe_map = screen(df_with_features, rvol_col, top_n, whitelist)

                if universe_map:
                    sorted_universe = {
                        int(k): sorted(v) for k, v in universe_map.items()
                    }
                    sip_hash = hash_dataframe(
                        pd.DataFrame(
                            [
                                (k, json.dumps(v, sort_keys=True))
                                for k, v in sorted_universe.items()
                            ],
                            columns=["ts", "symbols"],
                        ),
                        cols=["ts", "symbols"],
                    )
                else:
                    sip_hash = hash_dataframe(
                        pd.DataFrame([json.dumps({}, sort_keys=True)], columns=["sip"]),
                        cols=["sip"],
                    )
        else:
            sip_hash = hash_dataframe(
                pd.DataFrame([json.dumps({}, sort_keys=True)], columns=["sip"]),
                cols=["sip"],
            )

        # Config hash (of merged config, excluding seed?)
        config_copy = json.loads(json.dumps(config, sort_keys=True, default=str))
        config_str = json.dumps(config_copy, sort_keys=True)
        config_hash = hash_dataframe(
            pd.DataFrame([config_str], columns=["config"]), cols=["config"]
        )

        # Generate run ID / directory
        run_id = str(uuid.uuid4())
        run_ids.append(run_id)
        run_dir = pathlib.Path("runs") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Log SIP selector info
        sip_info_method = config.get("sip", {}).get("method", "original")
        sip_top_k = config.get("sip", {}).get("top_k", "default")
        sip_preview = f"{sip_hash[:8]}..." if sip_hash else "none"
        console.print(
            f"[{variant_path}] SIP: {sip_info_method}, top_k: {sip_top_k}, sip_hash: {sip_preview}"
        )

        # Prepare bars for engine
        bars_for_engine = df_with_features.sort_values(["ts", "symbol"]).reset_index(
            drop=True
        )

        backtest_params = config["backtest"]
        filler = DefaultFiller(
            commission_per_share=backtest_params.get("cost_per_share", 0.0),
            commission_min=backtest_params.get("commission_min", 0.0),
            slippage_bps=backtest_params.get("cost_bps", 0),
        )
        backtest_cfg = BacktestConfig(
            initial_cash=backtest_params.get("initial_equity", 100_000.0),
            filler=filler,
        )

        engine_sip_cfg: dict[str, Any]
        if sip_method == "hmm":
            engine_sip_cfg = {
                "sip_method": "hmm",
                "sip_config": config.get("sip", {}).get("config", {}),
            }
        else:
            engine_sip_cfg = {"sip_method": "none"}

        engine = BacktestEngine(backtest_cfg, engine_sip_cfg)
        if sip_method == "hmm" and sip_selector:
            engine._sip_selector = sip_selector

        policy_type = str(config.get("policy", "vwap_revert")).lower()
        policy_params = config.get("policy_params", {}).copy()

        if "rvol_min" in policy_params:
            if "min_rvol" not in policy_params:
                policy_params["min_rvol"] = policy_params["rvol_min"]
            policy_params.pop("rvol_min", None)

        def ensure_risk_params() -> None:
            if "risk_params" not in policy_params and config.get("risk_params"):
                policy_params["risk_params"] = config["risk_params"]

        if policy_type in {"vwap_momentum", "momentum"}:
            if (
                "timeout_bars" in policy_params
                and "max_position_bars" not in policy_params
            ):
                policy_params["max_position_bars"] = policy_params.pop("timeout_bars")
            ensure_risk_params()
            policy = VwapMomentumPolicy(**policy_params)
            generate_signals_fn = generate_vwap_momentum_signals
        else:
            if (
                "timeout_bars" in policy_params
                and "max_position_bars" not in policy_params
            ):
                policy_params["max_position_bars"] = policy_params.pop("timeout_bars")
            ensure_risk_params()
            policy = VwapRevertPolicy(**policy_params)
            generate_signals_fn = generate_vwap_revert_signals
        policy.engine = engine
        engine.policy = policy
        policy.on_start()

        def strategy_fn(engine_ref: BacktestEngine, bar: dict[str, Any]) -> None:
            policy.process_bar(bar)

        result = engine.run(bars_for_engine, strategy_fn)
        policy.on_end()

        # Diagnostics signals (optional, for parity with legacy outputs)
        signal_params = {
            **policy_params,
            "sip_universe": universe_map,
            "timeout_bars": policy_params.get("max_position_bars", 10),
        }
        signal_params.setdefault(
            "rvol_min",
            policy_params.get("min_rvol", policy_params.get("rvol_min", 1.0)),
        )
        signals_df = generate_signals_fn(bars_for_engine, signal_params)

        # Extract artifacts
        equity_df = (
            result.equity_curve
            if isinstance(result.equity_curve, pd.DataFrame)
            else pd.DataFrame(result.equity_curve)
        )
        trades_df = pd.DataFrame(result.trades_history)
        if trades_df.empty:
            trades_df = pd.DataFrame(
                columns=[
                    "timestamp",
                    "symbol",
                    "side",
                    "quantity",
                    "price",
                    "commission",
                    "total_cost",
                    "order_id",
                ]
            )
        orders_history_df = pd.DataFrame(result.orders_history)
        if orders_history_df.empty:
            orders_history_df = pd.DataFrame(
                columns=[
                    "order_id",
                    "symbol",
                    "side",
                    "order_type",
                    "quantity",
                    "price",
                    "stop_price",
                    "time_in_force",
                    "timestamp",
                    "status",
                    "filled_quantity",
                    "remaining_quantity",
                    "avg_fill_price",
                    "is_fully_filled",
                    "is_active",
                    "strategy_id",
                    "parent_order_id",
                    "tags",
                    "fill_count",
                ]
            )

        result_dict = result.to_dict()
        result_dict["trading"]["total_trades"] = result.total_trades
        result_dict["trading"]["winning_trades"] = result.winning_trades
        result_dict["trading"]["losing_trades"] = result.losing_trades
        result_dict["trading"]["avg_trade_pnl"] = result.avg_trade_pnl
        result_dict["trading"]["avg_win"] = result.avg_win
        result_dict["trading"]["avg_loss"] = result.avg_loss
        result_dict["trading"]["largest_win"] = result.largest_win
        result_dict["trading"]["largest_loss"] = result.largest_loss
        result_dict["performance"]["win_rate"] = result.win_rate
        result_dict["performance"]["total_trades"] = result.total_trades

        # Persist artifacts
        signals_df.to_parquet(run_dir / "signals.parquet")
        orders_history_df.to_parquet(run_dir / "orders.parquet")
        equity_df.to_parquet(run_dir / "equity.parquet")
        trades_df.to_parquet(run_dir / "trades.parquet")
        orders_history_df.to_parquet(run_dir / "filled_orders.parquet")
        with open(run_dir / "metrics.json", "w") as f:
            json.dump(result_dict, f, indent=2)

        actual_metrics.append(
            {
                "run_id": run_id,
                "performance": result_dict.get("performance", {}),
                "trading": result_dict.get("trading", {}),
            }
        )

        # Write checksum for this run
        variant_checksum = {
            "bars_norm_hash": bars_norm_hash,
            "features_hash": features_hash,
            "sip_hash": sip_hash,
            "config_hash": config_hash,
            "seed": seed,
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
        "sip_params": {
            **base_config.get("sip", {}),
            "method": base_config.get("sip", {}).get("method", "original"),
            "hash_function": (
                "hash_sip_map"
                if base_config.get("sip", {}).get("method") == "hmm"
                else "hash_dataframe"
            ),
        },
        "data_slice": {"symbols": symbols, "dates": dates, "gold_root": gold_root},
        "git_commit": "dirty",  # Stub
        "seed": seed,
    }
    with open(exp_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    # Run compare
    from qx_cli.exp.compare import compare_experiments

    compare_result = compare_experiments(exp_dir)

    # Print run summary
    print_run_summary(compare_result, run_ids)

    console.print("\nActual Performance:")
    for metrics in actual_metrics:
        run_id = metrics["run_id"]
        performance = metrics.get("performance", {})
        trading = metrics.get("trading", {})
        console.print(f"  {run_id}:")
        console.print(
            f"    Total Return: {performance.get('total_return', 0):.3%} | "
            f"Sharpe: {performance.get('sharpe_ratio', 0):.2f} | "
            f"Win Rate: {performance.get('win_rate', 0):.2%}"
        )
        console.print(
            f"    Trades: {trading.get('total_trades', 0)} | "
            f"Wins: {trading.get('winning_trades', 0)} | "
            f"Losses: {trading.get('losing_trades', 0)} | "
            f"Avg Trade PnL: {trading.get('avg_trade_pnl', 0):.2f}"
        )

    console.print(f"Experiment {name} completed. Artifacts in {exp_dir}")


def _setup_sip_selector(config):
    """Setup SIP selector with support for daily mode"""
    sip_method = config.get("sip", {}).get("method", "original")

    if sip_method == "hmm":
        sip_config_dict = config.get("sip", {}).get("config", {})

        # Handle both legacy and daily configs
        if "mode" not in sip_config_dict:
            sip_config_dict["mode"] = "legacy"  # Default for backward compatibility

        sip_config = HMMSIPConfig(**sip_config_dict)

        if sip_config.mode == "daily":
            # Log daily mode setup
            print(f"Setting up Daily HMM_SIP with top_k={sip_config.top_k}")

        selector = HMMSIPUniverseSelector(sip_config)
        return selector, "hmm"
    else:
        # Original SIP setup
        return None, sip_method


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep merge overlay into base."""
    result = base.copy()
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def print_run_summary(compare_result: dict, run_ids: list) -> None:
    """Print concise run summary."""
    # Load trades for each run
    summaries = []
    for run_id in run_ids:
        run_dir = pathlib.Path("runs") / run_id
        trades_df = pd.read_parquet(run_dir / "trades.parquet")
        mean_pnl = (
            trades_df["pnl"].mean()
            if not trades_df.empty and "pnl" in trades_df.columns
            else 0.0
        )
        median_r = (
            trades_df["r_multiple"].median()
            if not trades_df.empty and "r_multiple" in trades_df.columns
            else 0.0
        )
        summaries.append(
            {
                "run_id": run_id,
                "trades": len(trades_df),
                "mean_pnl": mean_pnl,
                "median_r": median_r,
            }
        )

    console.print("Run Summary:")
    for summary in summaries:
        console.print(
            f"  {summary['run_id']}: trades={summary['trades']}, mean_pnl={summary['mean_pnl']:.2f}, median_R={summary['median_r']:.4f}"
        )

    # If counts equal, show first differences in signals
    if len({s["trades"] for s in summaries}) == 1:
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
                    console.print(
                        f"First signal difference at row {i}: variant 0 vs {j}"
                    )
                    break
            else:
                continue
            break
