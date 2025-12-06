"""
This module handles the storage and retrieval of Stock-In-Play (SIP) membership data.

SIP membership is precomputed and stored in a partitioned Parquet dataset to be
consumed by the intraday ML pipeline for training and backtesting. This avoids
recomputing SIP on-the-fly and ensures consistency.

The core logic for *calculating* SIP is handled by `qx_screener.hmm_sip.HMMSIPUniverseSelector`
in `legacy` mode. This module is only responsible for the I/O layer.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

import pandas as pd

# Define a literal type for SIP filtering modes for type safety.
SIPMode = Literal["sip_only", "no_sip", "all"]

# Configure logging
logger = logging.getLogger(__name__)


def get_sip_membership_base_path(gold_root: str | Path) -> Path:
    """
    Returns the base path for SIP membership Parquet files.

    Args:
        gold_root: The root directory of the 'gold' data layer.

    Returns:
        The resolved path to the SIP membership directory.
    """
    root_path = Path(gold_root)

    # Allow callers to pass either the gold root or the SIP dataset path directly.
    if root_path.name == "sip_membership":
        return root_path
    if root_path.name == "intraday_ml":
        return root_path / "sip_membership"

    return root_path / "intraday_ml" / "sip_membership"


def save_sip_membership(
    df: pd.DataFrame,
    gold_root: str | Path,
    *,
    output_root: str | Path | None = None,
) -> None:
    """
    Persists SIP membership data as a partitioned Parquet dataset.

    The data is partitioned by `trade_date`. Existing partitions for the dates
    present in the DataFrame will be overwritten, making the operation idempotent.

    Args:
        df: DataFrame containing SIP membership. Must include columns:
            'trade_date', 'symbol', 'is_sip'.
        gold_root: The root directory of the 'gold' data layer.

    Raises:
        ValueError: If the DataFrame is missing required columns.
    """
    required_cols = {"trade_date", "symbol", "is_sip"}
    if not required_cols.issubset(df.columns):
        raise ValueError(
            f"Input DataFrame is missing one or more required columns: {required_cols}"
        )

    # Normalize data types for consistent storage
    df_to_save = df.copy()
    df_to_save["trade_date"] = pd.to_datetime(df_to_save["trade_date"]).dt.strftime("%Y-%m-%d")
    df_to_save["symbol"] = df_to_save["symbol"].astype(str)
    df_to_save["is_sip"] = df_to_save["is_sip"].astype(bool)

    base_path = Path(output_root) if output_root else get_sip_membership_base_path(gold_root)
    logger.info(f"Saving SIP membership to {base_path}")
    base_path.mkdir(parents=True, exist_ok=True)

    # Remove overlapping partitions to keep operation idempotent on older pyarrow versions.
    for partition in df_to_save["trade_date"].unique():
        partition_path = base_path / f"trade_date={partition}"
        if partition_path.exists():
            try:
                shutil.rmtree(partition_path)
            except PermissionError as exc:
                logger.warning(
                    "Unable to remove existing partition %s due to %s; attempting overwrite via pyarrow.",
                    partition_path,
                    exc,
                )

    try:
        df_to_save.to_parquet(
            base_path,
            partition_cols=["trade_date"],
            engine="pyarrow",
            existing_files_behavior="overwrite_partitions",
        )
    except TypeError:
        df_to_save.to_parquet(
            base_path,
            partition_cols=["trade_date"],
            engine="pyarrow",
        )


def load_sip_membership_for_dates(
    gold_root: str | Path,
    start_date: str,
    end_date: str,
    mode: SIPMode = "sip_only",
) -> pd.DataFrame:
    """
    Loads SIP membership for a date range, filtered by the specified mode.

    Args:
        gold_root: The root directory of the 'gold' data layer.
        start_date: The start of the date range (inclusive, YYYY-MM-DD).
        end_date: The end of the date range (inclusive, YYYY-MM-DD).
        mode: The filtering mode:
              - "sip_only": Return only tickers that are in play (is_sip=True).
              - "no_sip": Return only tickers that are not in play (is_sip=False).
              - "all": Return all tickers with their SIP status.

    Returns:
        A DataFrame containing the requested SIP membership data.

    Raises:
        ValueError: If the date range is invalid or the mode is incorrect.
        FileNotFoundError: If no SIP membership data is found for the given date range.
    """
    if pd.to_datetime(start_date) > pd.to_datetime(end_date):
        raise ValueError(f"Start date {start_date} cannot be after end date {end_date}.")

    if mode not in ("sip_only", "no_sip", "all"):
        raise ValueError(f"Invalid SIP mode: {mode}. Must be one of 'sip_only', 'no_sip', 'all'.")

    base_path = get_sip_membership_base_path(gold_root)
    logger.info(f"Loading SIP membership from {base_path} for dates {start_date} to {end_date}")

    try:
        filters = [("trade_date", ">=", start_date), ("trade_date", "<=", end_date)]
        if mode == "sip_only":
            filters.append(("is_sip", "==", True))
        elif mode == "no_sip":
            filters.append(("is_sip", "==", False))

        df = pd.read_parquet(base_path, filters=filters, engine="pyarrow")

        if mode == "sip_only":
            df = df[df["is_sip"]]
        elif mode == "no_sip":
            df = df[~df["is_sip"]]

        if df.empty:
            logger.warning(
                f"No SIP membership data found for mode '{mode}' in date range "
                f"[{start_date}, {end_date}]."
            )

        return df

    except Exception as e:
        # The underlying exception from pandas/pyarrow can be generic.
        # We raise a FileNotFoundError to signal that the data doesn't exist.
        logger.error(f"Failed to load SIP data from {base_path}: {e}")
        raise FileNotFoundError(
            f"No SIP membership data found at {base_path} for the date range "
            f"[{start_date}, {end_date}]. Please run the SIP precomputation CLI."
        ) from e


def get_phase_symbols_with_sip(
    splits_config: dict[str, Any],
    sip_config: dict[str, Any],
    candidate_symbols: Sequence[str],
    phase: str,
    *,
    verbose: bool = True,
    log_fn: Callable[[str], None] | None = None,
) -> list[str]:
    """
    Return the symbol universe for a pipeline phase, respecting SIP filters.

    Args:
        splits_config: Dictionary describing phase date ranges.
        sip_config: SIP filter configuration block from the master config.
        candidate_symbols: Original symbol universe for the phase.
        phase: Split name (e.g. \"train\", \"oos\").
        verbose: Whether to emit informational logs (defaults to True).
        log_fn: Optional callable for log messages (falls back to logger.info).

    Returns:
        Sorted list of symbols after applying the requested SIP filter.
    """

    def _emit(message: str) -> None:
        if not verbose:
            return
        if log_fn:
            log_fn(message)
        else:
            logger.info(message)

    if not sip_config.get("enabled", False):
        _emit(f"SIP filter disabled for phase '{phase}'. Using original symbol list.")
        return list(candidate_symbols)

    mode = sip_config.get("mode", "sip_only")
    raw_max_symbols = sip_config.get("max_symbols")
    membership_path = sip_config.get("membership_path")
    if not membership_path:
        raise ValueError("sip_filter.membership_path must be configured when SIP is enabled.")

    try:
        phase_dates = splits_config[phase]
        start_date = str(phase_dates["start"])
        end_date = str(phase_dates["end"])
    except KeyError as exc:
        raise ValueError(f"Phase '{phase}' not found in splits configuration.") from exc

    _emit(f"SIP filter enabled for phase '{phase}' with mode '{mode}'.")

    sip_df = load_sip_membership_for_dates(
        gold_root=membership_path,
        start_date=start_date,
        end_date=end_date,
        mode=mode,
    )

    if sip_df.empty:
        _emit(f"Warning: No SIP symbols found for phase '{phase}' in the given date range.")
        return []

    candidate_set = {str(symbol).upper() for symbol in candidate_symbols}
    sip_symbols = {str(symbol).upper() for symbol in sip_df["symbol"].unique().tolist()}
    sip_candidates = (
        sorted(candidate_set & sip_symbols) if candidate_set else sorted(sip_symbols)
    )
    candidate_count = len(sip_candidates)

    max_symbols: int | None = None
    if raw_max_symbols is not None:
        try:
            parsed_max = int(raw_max_symbols)
        except (TypeError, ValueError) as exc:
            raise ValueError("sip_filter.max_symbols must be an integer if provided.") from exc
        max_symbols = parsed_max if parsed_max > 0 else None

    if max_symbols is not None:
        symbol_counts = (
            sip_df["symbol"]
            .str.upper()
            .value_counts()
            .loc[lambda s: s.index.isin(sip_candidates)]
        )
        ranked_symbols = symbol_counts.index.tolist()
        filtered_symbols = ranked_symbols[:max_symbols]
        logger.info(
            "SIP membership: applying cap max_symbols=%d; kept %d of %d SIP symbols",
            max_symbols,
            len(filtered_symbols),
            len(symbol_counts),
        )
    else:
        filtered_symbols = sip_candidates
        logger.info(
            "SIP membership: no max_symbols cap applied; returning %d of %d SIP symbols",
            len(filtered_symbols),
            candidate_count,
        )

    _emit(
        "Filtered symbol list for phase "
        f"'{phase}': {len(filtered_symbols)} symbols from {len(candidate_symbols)} candidates."
    )

    return filtered_symbols
