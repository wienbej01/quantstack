"""L2 data storage with partitioning and optimization."""

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path


import pandas as pd

logger = logging.getLogger(__name__)


class L2Storage:
    """L2 data storage with partitioning and export."""

    def __init__(self, config: dict):
        storage_cfg = config.get("storage", {})
        self.base_dir = Path(storage_cfg.get("base_dir", "./data/l2"))
        self.format = storage_cfg.get("format", "parquet")
        self.compression = storage_cfg.get("compression", "snappy")
        self.flush_rows = storage_cfg.get("flush_rows", 300)
        self.retention_days = storage_cfg.get("retention_days", 90)

        # Ensure directories exist
        (self.base_dir / "raw").mkdir(parents=True, exist_ok=True)
        (self.base_dir / "features").mkdir(parents=True, exist_ok=True)
        (self.base_dir / "exports").mkdir(parents=True, exist_ok=True)

    def get_partition_path(self, data_type: str, date_str: str, symbol: str) -> Path:
        """Get partitioned path for data."""
        return self.base_dir / data_type / f"date={date_str}" / f"symbol={symbol}"

    def write_batch(self, records: list[dict], data_type: str = "raw") -> str:
        """Write batch of records with partitioning."""
        if not records:
            return ""

        df = pd.DataFrame(records)

        # Extract partition keys
        date_str = records[0].get("date_et", datetime.now().strftime("%Y-%m-%d"))
        symbol = records[0].get("symbol", "UNKNOWN")

        # Create partition directory
        partition_dir = self.get_partition_path(data_type, date_str, symbol)
        partition_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        ts = datetime.now().strftime("%H%M%S")
        filename = f"part_{ts}.parquet"
        filepath = partition_dir / filename

        # Write with compression
        df.to_parquet(filepath, index=False, compression=self.compression)

        logger.debug(f"Wrote {len(records)} records to {filepath}")
        return str(filepath)

    def consolidate_daily(self, date_str: str = None) -> dict:
        """Consolidate small files into daily files per symbol."""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        consolidated = {"raw": 0, "features": 0}

        for data_type in ["raw", "features"]:
            date_dir = self.base_dir / data_type / f"date={date_str}"
            if not date_dir.exists():
                continue

            for symbol_dir in date_dir.glob("symbol=*"):
                files = list(symbol_dir.glob("part_*.parquet"))
                if len(files) <= 1:
                    continue

                # Read and combine
                dfs = []
                for f in files:
                    try:
                        dfs.append(pd.read_parquet(f))
                    except Exception as e:
                        logger.warning(f"Failed to read {f}: {e}")

                if not dfs:
                    continue

                combined = pd.concat(dfs, ignore_index=True)
                combined = combined.drop_duplicates(subset=["ts_epoch", "symbol"])
                combined = combined.sort_values("ts_epoch")

                # Write consolidated file
                out_file = symbol_dir / f"consolidated_{date_str}.parquet"
                combined.to_parquet(out_file, index=False, compression=self.compression)

                # Remove original files
                for f in files:
                    f.unlink()

                consolidated[data_type] += 1
                logger.info(f"Consolidated {len(files)} files for {symbol_dir.name}")

        return consolidated

    def cleanup_old_data(self) -> dict:
        """Remove data older than retention period."""
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        removed = []

        for data_type in ["raw", "features"]:
            type_dir = self.base_dir / data_type
            if not type_dir.exists():
                continue

            for date_dir in type_dir.glob("date=*"):
                date_str = date_dir.name.replace("date=", "")
                try:
                    dir_date = datetime.strptime(date_str, "%Y-%m-%d")
                    if dir_date < cutoff:
                        shutil.rmtree(date_dir)
                        removed.append(f"{data_type}/{date_str}")
                except ValueError:
                    pass

        logger.info(f"Cleaned up {len(removed)} old directories")
        return {"removed": removed}

    def export_training_dataset(
        self,
        output_path: str,
        start_date: str = None,
        end_date: str = None,
        symbols: list[str] = None,
        features_only: bool = True,
    ) -> dict:
        """Export consolidated dataset for ML training."""
        data_type = "features" if features_only else "raw"
        type_dir = self.base_dir / data_type

        if not type_dir.exists():
            return {"error": f"No {data_type} data found"}

        # Find matching files
        files = []
        for date_dir in sorted(type_dir.glob("date=*")):
            date_str = date_dir.name.replace("date=", "")

            # Date filter
            if start_date and date_str < start_date:
                continue
            if end_date and date_str > end_date:
                continue

            for symbol_dir in date_dir.glob("symbol=*"):
                symbol = symbol_dir.name.replace("symbol=", "")

                # Symbol filter
                if symbols and symbol not in symbols:
                    continue

                files.extend(symbol_dir.glob("*.parquet"))

        if not files:
            return {"error": "No matching files found"}

        # Read and combine
        dfs = []
        for f in files:
            try:
                dfs.append(pd.read_parquet(f))
            except Exception as e:
                logger.warning(f"Failed to read {f}: {e}")

        if not dfs:
            return {"error": "Failed to read any files"}

        combined = pd.concat(dfs, ignore_index=True)
        combined = combined.drop_duplicates(subset=["ts_epoch", "symbol"])
        combined = combined.sort_values(["symbol", "ts_epoch"])

        # Save
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(output, index=False, compression=self.compression)

        return {
            "output_path": str(output),
            "records": len(combined),
            "symbols": combined["symbol"].nunique(),
            "date_range": f"{combined['date_et'].min()} to {combined['date_et'].max()}",
            "size_mb": output.stat().st_size / 1024 / 1024,
        }

    def get_stats(self) -> dict:
        """Get storage statistics."""
        raw_files = list((self.base_dir / "raw").rglob("*.parquet"))
        feat_files = list((self.base_dir / "features").rglob("*.parquet"))

        raw_size = sum(f.stat().st_size for f in raw_files)
        feat_size = sum(f.stat().st_size for f in feat_files)

        # Sample record count
        total_records = 0
        symbols = set()
        for f in raw_files[:10]:
            try:
                df = pd.read_parquet(f)
                total_records += len(df)
                symbols.update(df["symbol"].unique())
            except Exception:
                pass

        est_total = (
            int(total_records * len(raw_files) / min(10, len(raw_files)))
            if raw_files
            else 0
        )

        return {
            "raw_files": len(raw_files),
            "feature_files": len(feat_files),
            "raw_size_mb": raw_size / 1024 / 1024,
            "feature_size_mb": feat_size / 1024 / 1024,
            "total_size_mb": (raw_size + feat_size) / 1024 / 1024,
            "est_records": est_total,
            "symbols": len(symbols),
        }
