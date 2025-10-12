#!/usr/bin/env python3
import argparse, sys, os, glob, json
from datetime import datetime
import pandas as pd

REQUIRED = ["ts","symbol","open","high","low","close","volume"]
OPTIONAL  = ["trades","vwap","session","date_et"]

def read_parquets(paths, n_files=3, symbol=None):
    picked = sorted(paths)[:n_files]
    if not picked:
        raise FileNotFoundError("No parquet files found for the requested month/symbol.")
    dfs = []
    for p in picked:
        try:
            df = pd.read_parquet(p)
            df["__source_file"] = p
            if symbol and "symbol" not in df.columns:
                df["symbol"] = symbol
            dfs.append(df)
        except Exception as e:
            print(f"[warn] failed to read {p}: {e}", file=sys.stderr)
    if not dfs:
        raise RuntimeError("All candidate parquet reads failed.")
    return pd.concat(dfs, ignore_index=True)

def normalize_in_memory(df: pd.DataFrame) -> pd.DataFrame:
    """Do NOT write back. This is only for hashing and schema assertions."""
    out = df.copy()
    # Column name standardization (Gold should already be canonical, but be defensive)
    rename = {"T":"symbol","t":"ts","o":"open","h":"high","l":"low","c":"close","v":"volume"}
    cols_lower = {c: c.lower() for c in out.columns}
    out = out.rename(columns=cols_lower).rename(columns=rename)
    # Types
    if "ts" in out.columns:
        # Ensure pandas tz-aware UTC
        if not pd.api.types.is_datetime64_any_dtype(out["ts"]):
            out["ts"] = pd.to_datetime(out["ts"], utc=True, errors="coerce")
        elif out["ts"].dt.tz is None:
            out["ts"] = out["ts"].dt.tz_localize("UTC")
        else:
            out["ts"] = out["ts"].dt.tz_convert("UTC")
    if "symbol" in out.columns:
        out["symbol"] = out["symbol"].astype(str)
    for col in ["open","high","low","close"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "volume" in out.columns:
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0).astype("int64")

    # Basic sanity
    missing = list(set(REQUIRED) - set(out.columns))
    if missing:
        raise AssertionError(f"Missing required cols in Gold: {missing}")
    bad_hilo = (out["high"] < out["low"]).sum()
    if bad_hilo:
        print(f"[warn] {bad_hilo} rows have high<low", file=sys.stderr)
    out = out.sort_values(["symbol","ts"]).reset_index(drop=True)
    return out

def summarize(df: pd.DataFrame):
    info = {
        "columns": list(df.columns),
        "dtypes": {c:str(df[c].dtype) for c in df.columns},
        "n_rows": int(len(df)),
        "n_symbols": int(df["symbol"].nunique()) if "symbol" in df.columns else None,
        "ts_min_utc": df["ts"].min().isoformat() if "ts" in df.columns and len(df)>0 else None,
        "ts_max_utc": df["ts"].max().isoformat() if "ts" in df.columns and len(df)>0 else None,
        "has_optional": {c: (c in df.columns) for c in OPTIONAL}
    }
    return info

def main():
    ap = argparse.ArgumentParser(description="Inspect Gold and build tiny normalized sample for smoke tests.")
    ap.add_argument("--gold-root", default="/home/jacobw/gcs-mount/gold", help="Path to gold root")
    ap.add_argument("--family", default="bars_1m", help="bars_1m or similar family dir")
    ap.add_argument("--symbol", default="AAPL", help="Symbol to inspect")
    ap.add_argument("--year", default="2024", help="Year, e.g. 2024")
    ap.add_argument("--month", default="01", help="Month, zero-padded, e.g. 01")
    ap.add_argument("--n-files", type=int, default=3, help="Number of parquet files to sample")
    ap.add_argument("--write-sample", action="store_true", help="Write a tiny sample parquet for smoke test")
    ap.add_argument("--out-dir", default="/tmp/e2e_smoke_from_gold", help="Where to write the sample if requested")
    args = ap.parse_args()

    # Handle different data structures
    if args.family == "bars_1m":
        # Actual structure: .../stocks/1m/symbol/year/year-month.parquet
        month_glob = os.path.join(args.gold_root, "stocks", "1m", args.symbol, args.year, f"{args.year}-{args.month}.parquet")
    else:
        # Expected partitions like .../family/symbol=AAPL/date=YYYY-MM-DD/*.parquet
        month_glob = os.path.join(
            args.gold_root, args.family, f"symbol={args.symbol}", f"date={args.year}-{args.month}-*", "*.parquet"
        )
    paths = glob.glob(month_glob)
    print(f"[info] probing glob: {month_glob}\n[info] files found: {len(paths)}")

    df_raw = read_parquets(paths, n_files=args.n_files, symbol=args.symbol)
    print("[info] RAW summary:")
    print(json.dumps(summarize(df_raw), indent=2, default=str))

    df_norm = normalize_in_memory(df_raw)
    print("[info] NORMALIZED summary:")
    print(json.dumps(summarize(df_norm), indent=2, default=str))

    print("[info] head(5) normalized:")
    with pd.option_context("display.max_columns", 50):
        print(df_norm.head(5).to_string(index=False))

    if args.write_sample:
        out_dir = os.path.join(args.out_dir, args.family, f"symbol={args.symbol}", "date=SMOKE")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "part-000.parquet")
        # Keep it tiny
        df_norm.iloc[:1000].to_parquet(out_path, index=False)
        print(f"[info] wrote smoke sample: {out_path}")

if __name__ == "__main__":
    main()
