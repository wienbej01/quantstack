"""Fairness validation for A/B experiments."""

import json
import pathlib
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class FairnessConfig:
    """Configuration for fairness validation."""

    allow_unfair: bool = False
    require_identical_base_checksums: bool = True
    require_identical_data_hashes: bool = True
    max_config_drift: int = 5  # Maximum allowed differing config parameters


@dataclass
class FairnessResult:
    """Result of fairness validation."""

    is_fair: bool
    reason: str
    violations: List[str]
    warnings: List[str]


class ChecksumValidator:
    """Validates fairness across experiment variants."""

    def __init__(self, config: FairnessConfig):
        self.config = config

    def validate_fairness(self, run_results: List[Dict[str, Any]]) -> FairnessResult:
        """Validate fairness across all run results."""
        violations = []
        warnings = []

        if len(run_results) < 2:
            return FairnessResult(
                is_fair=False,
                reason="Need at least 2 variants for fairness validation",
                violations=["insufficient_variants"],
                warnings=warnings,
            )

        # Check base checksums are identical
        base_checksums = run_results[0]["checksums"]
        for i, result in enumerate(run_results[1:], 1):
            for key in ["bars_norm_hash", "features_hash"]:
                if base_checksums[key] != result["checksums"][key]:
                    violations.append(f"variant_{i}_base_hash_mismatch_{key}")

        # Check for identical data hashes if required
        if self.config.require_identical_data_hashes:
            for i, result in enumerate(run_results[1:], 1):
                if base_checksums != result["checksums"]:
                    violations.append(f"variant_{i}_data_hash_mismatch")

        # Validate reasonable differences in metrics
        self._validate_metric_differences(run_results, violations, warnings)

        is_fair = len(violations) == 0
        reason = (
            "All fairness checks passed"
            if is_fair
            else f"Violations: {', '.join(violations)}"
        )

        return FairnessResult(
            is_fair=is_fair,
            reason=reason,
            violations=violations,
            warnings=warnings,
        )

    def _validate_metric_differences(
        self,
        run_results: List[Dict[str, Any]],
        violations: List[str],
        warnings: List[str],
    ) -> None:
        """Validate that metric differences are reasonable."""
        if len(run_results) < 2:
            return

        trade_counts = [r["metrics"]["trading"]["total_trades"] for r in run_results]
        max_trades = max(trade_counts)
        min_trades = min(trade_counts)

        # Check for suspiciously identical results
        if len(set(trade_counts)) == 1 and max_trades > 0:
            warnings.append("identical_trade_counts_across_variants")

        # Check for extreme differences
        if max_trades > 0:
            ratio = max_trades / min_trades if min_trades > 0 else float("inf")
            if ratio > 10:  # More than 10x difference
                warnings.append("extreme_trade_count_difference")


def validate_fairness(exp_dir: pathlib.Path) -> Dict[str, Any]:
    """Validate fairness of an experiment directory."""
    manifest_file = exp_dir / "manifest.json"

    if not manifest_file.exists():
        return {"valid": False, "message": "No manifest.json found"}

    try:
        with open(manifest_file) as f:
            manifest = json.load(f)

        # Basic validation
        required_keys = ["exp_id", "type", "base_checksums", "run_checksums"]
        for key in required_keys:
            if key not in manifest:
                return {"valid": False, "message": f"Missing required key: {key}"}

        # Check if we have multiple runs
        run_ids = manifest.get("run_ids", [])
        if len(run_ids) < 2:
            return {
                "valid": False,
                "message": "Need at least 2 variants for fairness validation",
            }

        # Simple fairness check
        base_checksums = manifest["base_checksums"]
        run_checksums = manifest["run_checksums"]

        violations = []
        for run_id in run_ids:
            if run_id not in run_checksums:
                violations.append(f"Missing checksums for run: {run_id}")
                continue

            checksums = run_checksums[run_id]
            for key in ["bars_norm_hash", "features_hash"]:
                if base_checksums.get(key) != checksums.get(key):
                    violations.append(f"Base hash mismatch in {key} for run {run_id}")

        if violations:
            return {
                "valid": False,
                "message": f"Fairness violations: {', '.join(violations)}",
            }

        return {"valid": True, "message": "Fairness validation passed"}

    except Exception as e:
        return {"valid": False, "message": f"Error during validation: {e}"}
