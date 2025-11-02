"""Enhanced CLI orchestration for A/B testing with fairness validation."""

import json
import pathlib
import uuid
from typing import Any

import pandas as pd
import yaml
from rich.console import Console

from qx_cli.exp.entry_ab import deep_merge
from qx_data.gold_loader import load_bars
from qx_features.registry import apply_feature_packs

from ..utils.checksums import compute_input_checksums
from ..utils.validation import validate_config, validate_data_slice
from .fairness import ChecksumValidator, FairnessConfig

console = Console()


class ABOrchestrator:
    """Enhanced A/B test orchestrator with fairness validation."""

    def __init__(self, fairness_cfg: FairnessConfig):
        self.fairness_cfg = fairness_cfg
        self.validator = ChecksumValidator(fairness_cfg)

    def run_experiment(
        self,
        cfg_path: pathlib.Path,
        variant_paths: list[pathlib.Path],
        experiment_name: str,
        force: bool = False,
    ) -> dict[str, Any]:
        """Run A/B experiment with enhanced fairness validation."""
        console.print(f"Starting A/B experiment: {experiment_name}")

        # Load and validate base config
        with open(cfg_path) as f:
            base_config = yaml.safe_load(f)
        validate_config(base_config)

        # Validate data slice exists
        validate_data_slice(
            base_config["gold_root"],
            base_config["family"],
            base_config["symbols"],
            base_config["dates"],
        )

        # Load and normalize bars
        bars_df = load_bars(
            base_config["gold_root"],
            base_config["family"],
            base_config["symbols"],
            base_config["dates"],
        )

        # Apply features
        df_with_features = apply_feature_packs(bars_df, base_config["features"])

        # Compute base checksums
        base_checksums = compute_input_checksums(bars_df, df_with_features, base_config)

        # Run each variant
        run_results = []
        for variant_path in variant_paths:
            with open(variant_path) as f:
                overlay = yaml.safe_load(f)

            config = deep_merge(base_config, overlay)
            result = self._run_variant(config, variant_path, base_checksums)
            run_results.append(result)

        # Validate fairness across variants
        if not force:
            fairness_result = self.validator.validate_fairness(run_results)
            if not fairness_result.is_fair:
                console.print(
                    f"⚠️  Fairness validation failed: {fairness_result.reason}",
                    style="red",
                )
                if not self.fairness_cfg.allow_unfair:
                    raise RuntimeError("Experiment blocked due to fairness violations")

        # Write experiment manifest
        manifest = self._create_manifest(
            experiment_name, cfg_path, variant_paths, run_results, base_checksums
        )
        self._write_manifest(experiment_name, manifest)

        return {
            "experiment_name": experiment_name,
            "manifest": manifest,
            "run_results": run_results,
            "fairness_result": fairness_result if not force else None,
        }

    def _run_variant(
        self,
        config: dict[str, Any],
        variant_path: pathlib.Path,
        base_checksums: dict[str, str],
    ) -> dict[str, Any]:
        """Run a single variant."""
        run_id = str(uuid.uuid4())
        run_dir = pathlib.Path("runs") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Load data
        bars_df = load_bars(
            config["gold_root"],
            config["family"],
            config["symbols"],
            config["dates"],
        )
        df_with_features = apply_feature_packs(bars_df, config["features"])

        # Compute variant-specific checksums
        variant_checksums = compute_input_checksums(bars_df, df_with_features, config)

        # Validate base checksums match
        mismatches = []
        for key in ["bars_norm_hash", "features_hash"]:
            if base_checksums[key] != variant_checksums[key]:
                mismatches.append(
                    f"{key}: base={base_checksums[key]}, variant={variant_checksums[key]}"
                )

        if mismatches:
            raise ValueError(f"Checksum mismatch for {variant_path}: {mismatches}")

        # Run backtest using existing engine
        from qx_backtest.engine import BacktestConfig, BacktestEngine
        from qx_backtest.fill import DefaultFiller
        from qx_backtest.policies.vwap_revert import VwapRevertPolicy

        # Setup backtest
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

        engine = BacktestEngine(backtest_cfg, {"sip_method": "none"})

        policy_params = config.get("policy_params", {})
        policy = VwapRevertPolicy(**policy_params)
        policy.engine = engine
        engine.policy = policy
        policy.on_start()

        def strategy_fn(engine_ref: BacktestEngine, bar: dict[str, Any]) -> None:
            policy.process_bar(bar)

        # Execute backtest
        bars_for_engine = df_with_features.sort_values(["ts", "symbol"]).reset_index(
            drop=True
        )
        result = engine.run(bars_for_engine, strategy_fn)
        policy.on_end()

        # Persist artifacts
        self._persist_artifacts(run_dir, result, df_with_features, policy_params)

        return {
            "run_id": run_id,
            "variant_path": str(variant_path),
            "checksums": variant_checksums,
            "metrics": result.to_dict(),
            "run_dir": str(run_dir),
        }

    def _persist_artifacts(
        self,
        run_dir: pathlib.Path,
        result,
        df_with_features: pd.DataFrame,
        policy_params: dict[str, Any],
    ) -> None:
        """Persist run artifacts."""
        # Generate signals using policy
        from qx_backtest.policies.vwap_revert import generate_signals

        signals_df = generate_signals(df_with_features, policy_params)

        # Extract results
        equity_df = (
            result.equity_curve
            if isinstance(result.equity_curve, pd.DataFrame)
            else pd.DataFrame(result.equity_curve)
        )
        trades_df = pd.DataFrame(result.trades_history)
        orders_df = pd.DataFrame(result.orders_history)

        # Write artifacts
        signals_df.to_parquet(run_dir / "signals.parquet")
        orders_df.to_parquet(run_dir / "orders.parquet")
        equity_df.to_parquet(run_dir / "equity.parquet")
        trades_df.to_parquet(run_dir / "trades.parquet")

        # Write metrics and checksums
        result_dict = result.to_dict()
        with open(run_dir / "metrics.json", "w") as f:
            json.dump(result_dict, f, indent=2)

        checksums = compute_input_checksums(df_with_features, df_with_features, {})
        with open(run_dir / "inputs_checksum.json", "w") as f:
            json.dump(checksums, f, indent=2)

    def _create_manifest(
        self,
        experiment_name: str,
        cfg_path: pathlib.Path,
        variant_paths: list[pathlib.Path],
        run_results: list[dict[str, Any]],
        base_checksums: dict[str, str],
    ) -> dict[str, Any]:
        """Create experiment manifest."""
        return {
            "exp_id": experiment_name,
            "type": "entry-ab-enhanced",
            "base_config": str(cfg_path),
            "variants": [str(p) for p in variant_paths],
            "run_ids": [r["run_id"] for r in run_results],
            "base_checksums": base_checksums,
            "run_checksums": {r["run_id"]: r["checksums"] for r in run_results},
            "git_commit": "dirty",  # TODO: implement proper git integration
        }

    def _write_manifest(self, experiment_name: str, manifest: dict[str, Any]) -> None:
        """Write experiment manifest."""
        exp_dir = pathlib.Path("experiments") / experiment_name
        exp_dir.mkdir(parents=True, exist_ok=True)
        with open(exp_dir / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)
