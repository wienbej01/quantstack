# System Technical Documentation

## Overview
This document describes the QuantStack trading system's technical architecture, data flows, and operational procedures.

## Version History
- 2025-10-12: Added JSON schema validators in qx-core/schemas.py, gold_loader.py in qx-data for read-only normalized bar loading, and hashers.py in qx-core for stable dataframe hashing. Sprint 1.9 and 1.10 implementation.
- 2025-10-11: Initial creation. Updated check_gold_and_make_smoke_sample.py to handle actual gold data structure for bars_1m family.

## Architecture

### Data Ingestion
- **Gold Data**: Reference market data stored in GCS-mounted directories
  - Path: `/home/jacobw/gcs-mount/gold/`
  - Structure:
    - Stocks 1m bars: `stocks/1m/{symbol}/{year}/{year}-{month}.parquet`
    - Features: `features/`
    - Metadata: `metadata/`

### Data Processing Scripts
- `tools/check_gold_and_make_smoke_sample.py`: Validates gold data integrity and creates smoke test samples
  - Supports family "bars_1m" with actual structure `stocks/1m/{symbol}/{year}/{year}-{month}.parquet`
  - Adds missing "symbol" column if not present in parquet files
  - Outputs normalized data summaries and optional parquet samples

### Features
- TBD

### Risk Management
- TBD

### Testing
- Smoke samples created under `/tmp/e2e_smoke_from_gold/` for testing pipelines

### Operations
- Data validation: Run `check_gold_and_make_smoke_sample.py` with appropriate parameters
- Environment: Requires Python 3, pandas, GCS mount access

## Assumptions
- Gold data is mounted at `/home/jacobw/gcs-mount/gold/`
- Virtual environment activated for dependencies
- Timezones handled as UTC in data processing

## CFS Score
- Current: 9/10 (Stable data validation, needs expansion for full system coverage)