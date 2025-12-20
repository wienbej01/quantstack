#!/usr/bin/env python3
"""L2 data storage management and optimization."""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


class L2StorageManager:
    """Manage L2 data storage with optimization and cleanup."""

    def __init__(self, base_dir: str = "data/live_l2"):
        self.base_dir = Path(base_dir)

    def get_storage_stats(self) -> dict:
        """Get storage statistics."""
        raw_files = list(self.base_dir.rglob("**/raw/**/*.parquet"))
        feat_files = list(self.base_dir.rglob("**/feat/**/*.parquet"))

        raw_size = sum(f.stat().st_size for f in raw_files)
        feat_size = sum(f.stat().st_size for f in feat_files)

        # Count records
        total_records = 0
        symbols = set()
        dates = set()

        for f in raw_files[:20]:  # Sample
            try:
                df = pd.read_parquet(f)
                total_records += len(df)
                symbols.update(df["symbol"].unique())
            except:
                pass

        # Extrapolate
        if raw_files:
            est_total = int(total_records * len(raw_files) / min(20, len(raw_files)))
        else:
            est_total = 0

        return {
            "raw_files": len(raw_files),
            "feat_files": len(feat_files),
            "raw_size_mb": raw_size / 1024 / 1024,
            "feat_size_mb": feat_size / 1024 / 1024,
            "total_size_mb": (raw_size + feat_size) / 1024 / 1024,
            "est_records": est_total,
            "bytes_per_record": raw_size / est_total if est_total else 0,
            "symbols": len(symbols),
        }

    def consolidate_daily(self, date_str: str = None) -> dict:
        """
        Consolidate small parquet files into daily files per symbol.
        Reduces file count and improves read performance.
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        consolidated = {"raw": 0, "feat": 0}

        for data_type in ["raw", "feat"]:
            # Find all files for this date
            pattern = f"**/date={date_str}/**/*.parquet"
            files = list(self.base_dir.rglob(pattern))

            if not files:
                continue

            # Group by symbol
            by_symbol = {}
            for f in files:
                if data_type not in str(f):
                    continue
                parts = f.parts
                symbol_part = [p for p in parts if p.startswith("symbol=")]
                if symbol_part:
                    symbol = symbol_part[0].replace("symbol=", "")
                    if symbol not in by_symbol:
                        by_symbol[symbol] = []
                    by_symbol[symbol].append(f)

            # Consolidate each symbol
            for symbol, symbol_files in by_symbol.items():
                if len(symbol_files) <= 1:
                    continue

                # Read all files
                dfs = []
                for f in symbol_files:
                    try:
                        dfs.append(pd.read_parquet(f))
                    except:
                        pass

                if not dfs:
                    continue

                # Combine and deduplicate
                combined = pd.concat(dfs, ignore_index=True)
                combined = combined.drop_duplicates(subset=["ts_epoch", "symbol"])
                combined = combined.sort_values("ts_epoch")

                # Write consolidated file
                out_dir = symbol_files[0].parent
                out_file = out_dir / f"consolidated_{date_str}.parquet"
                combined.to_parquet(out_file, index=False)

                # Remove original files
                for f in symbol_files:
                    if f != out_file:
                        f.unlink()

                consolidated[data_type] += 1

        return consolidated

    def cleanup_old_runs(self, keep_days: int = 30) -> dict:
        """Remove run directories older than keep_days."""
        cutoff = datetime.now() - timedelta(days=keep_days)
        removed = []

        for run_dir in self.base_dir.glob("run_id=*"):
            # Extract date from run_id
            run_id = run_dir.name.replace("run_id=", "")
            try:
                # Format: live_YYYYMMDD
                date_str = run_id.split("_")[-1]
                run_date = datetime.strptime(date_str, "%Y%m%d")

                if run_date < cutoff:
                    shutil.rmtree(run_dir)
                    removed.append(run_id)
            except:
                pass

        return {"removed_runs": removed, "count": len(removed)}

    def export_training_dataset(
        self, output_path: str = "data/l2_training.parquet"
    ) -> dict:
        """Export consolidated training dataset."""
        feat_files = list(self.base_dir.rglob("**/feat/**/*.parquet"))

        dfs = []
        for f in feat_files:
            try:
                df = pd.read_parquet(f)
                dfs.append(df)
            except:
                pass

        if not dfs:
            return {"error": "No feature files found"}

        # Combine all features
        combined = pd.concat(dfs, ignore_index=True)
        combined = combined.drop_duplicates(subset=["ts_epoch", "symbol"])
        combined = combined.sort_values(["symbol", "ts_epoch"])

        # Save
        combined.to_parquet(output_path, index=False)

        return {
            "output_path": output_path,
            "records": len(combined),
            "symbols": combined["symbol"].nunique(),
            "size_mb": Path(output_path).stat().st_size / 1024 / 1024,
        }


def print_storage_report():
    """Print storage report."""
    mgr = L2StorageManager()
    stats = mgr.get_storage_stats()

    print("=== L2 STORAGE REPORT ===")
    print(f"Raw files: {stats['raw_files']}")
    print(f"Feature files: {stats['feat_files']}")
    print(f"Total size: {stats['total_size_mb']:.2f}MB")
    print(f"Est. records: {stats['est_records']:,}")
    print(f"Bytes/record: {stats['bytes_per_record']:.0f}")
    print(f"Symbols: {stats['symbols']}")

    # Projection
    target_records = 200000
    current = stats["est_records"]
    if current > 0:
        days_needed = (target_records - current) / (
            current / 3
        )  # Assume 3 days of data
        print(f"\nML Training Target: {target_records:,} records")
        print(f"Current: {current:,} ({current/target_records*100:.1f}%)")
        print(f"Est. days to target: {days_needed:.0f}")


if __name__ == "__main__":
    print_storage_report()
