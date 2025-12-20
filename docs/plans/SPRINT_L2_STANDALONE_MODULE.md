# Sprint Plan: Standalone L2 Data Collection Module

**Sprint Duration:** 5 days  
**Goal:** Extract L2 functionality into a truly independent, production-ready module  
**Priority:** High

---

## Executive Summary

Create `qx-l2` as a standalone package that:
- Operates independently of the ML trading system
- Has its own ticker selection, timing, and storage
- Incorporates PAPER_TRADING_GUIDE best practices
- Can run as a daemon or scheduled service
- Produces ML-ready datasets for downstream consumption

---

## Current State

### Dependencies to Remove
```
quantstack/
├── qx-data/src/qx_data/live/l2_collector.py  # Wrapper, depends on transalpha
├── scripts/l2_symbol_selector.py              # Coupled to SIP
├── scripts/l2_storage_manager.py              # Utility, not integrated

transalpha/l2/                                  # Source code to migrate
├── multi_l2_collector.py                      # Core collector
├── l2_features.py                             # Feature engineering
├── time_windows.py                            # Time utilities
├── ib_l2_adapter.py                           # IBKR adapter
└── logging_setup.py                           # Logging
```

### Target State
```
quantstack/
├── qx-l2/                                     # NEW: Standalone package
│   ├── pyproject.toml
│   ├── src/qx_l2/
│   │   ├── __init__.py
│   │   ├── collector.py                       # Main collector
│   │   ├── features.py                        # Feature engineering
│   │   ├── storage.py                         # Storage management
│   │   ├── symbols.py                         # Independent ticker selection
│   │   ├── scheduler.py                       # Time windows & scheduling
│   │   ├── ibkr_client.py                     # IBKR connection (tagged)
│   │   ├── journal.py                         # Event logging (from PAPER_TRADING_GUIDE)
│   │   └── config.py                          # Configuration management
│   ├── configs/
│   │   └── default.yaml
│   ├── scripts/
│   │   ├── run_collector.py                   # Main entry point
│   │   ├── export_dataset.py                  # Export for ML
│   │   └── analyze_data.py                    # Data quality analysis
│   └── tests/
│       └── test_collector.py
```

---

## Sprint Tasks

### Day 1: Package Structure & Core Migration

#### Task 1.1: Create qx-l2 Package Structure
```bash
# Create package
mkdir -p qx-l2/src/qx_l2
mkdir -p qx-l2/configs
mkdir -p qx-l2/scripts
mkdir -p qx-l2/tests
```

**Deliverables:**
- [ ] `qx-l2/pyproject.toml`
- [ ] `qx-l2/src/qx_l2/__init__.py`
- [ ] Package installable via `pip install -e ./qx-l2`

#### Task 1.2: Migrate Core Collector
Migrate from `transalpha/l2/multi_l2_collector.py` with modifications:

**Changes Required:**
- Remove external dependencies on transalpha paths
- Add system tagging (from PAPER_TRADING_GUIDE)
- Add event journaling hooks
- Improve error handling

**Deliverables:**
- [ ] `qx-l2/src/qx_l2/collector.py`
- [ ] `qx-l2/src/qx_l2/features.py`

---

### Day 2: Independent Ticker Selection & IBKR Client

#### Task 2.1: Independent Symbol Selection
Create standalone ticker selection that does NOT depend on SIP/Polygon:

```python
# qx-l2/src/qx_l2/symbols.py

class L2SymbolSelector:
    """Independent L2 symbol selection."""
    
    def __init__(self, config: dict):
        self.core_symbols = config.get('core_symbols', [])
        self.rotating_pool = config.get('rotating_pool', [])
        self.max_symbols = config.get('max_symbols', 6)
    
    def get_daily_symbols(self, date_str: str = None) -> list[str]:
        """Get symbols for today's collection."""
        # Core symbols always included
        symbols = list(self.core_symbols)
        
        # Add rotating symbols (round-robin by date)
        if self.rotating_pool:
            day_offset = hash(date_str or datetime.now().strftime('%Y-%m-%d')) % len(self.rotating_pool)
            rotating = self.rotating_pool[day_offset:] + self.rotating_pool[:day_offset]
            symbols.extend(rotating[:self.max_symbols - len(symbols)])
        
        return symbols[:self.max_symbols]
```

**Symbol Selection Modes:**
1. **Static**: Fixed list from config
2. **Rotating**: Round-robin from pool
3. **External**: Accept symbols from external source (optional SIP integration)

**Deliverables:**
- [ ] `qx-l2/src/qx_l2/symbols.py`
- [ ] Unit tests for symbol selection

#### Task 2.2: Tagged IBKR Client
Create IBKR client with system tagging (from PAPER_TRADING_GUIDE):

```python
# qx-l2/src/qx_l2/ibkr_client.py

class L2IBKRClient:
    """IBKR client for L2 data with system tagging."""
    
    SYSTEM_NAME = "L2COLLECT"
    DEFAULT_CLIENT_ID = 500
    
    def __init__(self, config: dict):
        self.host = config.get('host', '127.0.0.1')
        self.port = config.get('port', 7497)
        self.client_id = config.get('client_id', self.DEFAULT_CLIENT_ID)
        self.system_tag = f"{self.SYSTEM_NAME}_{self.client_id}"
```

**Deliverables:**
- [ ] `qx-l2/src/qx_l2/ibkr_client.py`
- [ ] Connection health checks
- [ ] Reconnection logic

---

### Day 3: Storage & Scheduling

#### Task 3.1: Storage Management
Create comprehensive storage system:

```python
# qx-l2/src/qx_l2/storage.py

class L2Storage:
    """L2 data storage with partitioning and optimization."""
    
    def __init__(self, base_dir: str, config: dict):
        self.base_dir = Path(base_dir)
        self.partition_by = config.get('partition_by', ['date', 'symbol'])
        self.format = config.get('format', 'parquet')
        self.compression = config.get('compression', 'snappy')
        self.max_file_size_mb = config.get('max_file_size_mb', 50)
    
    def write_batch(self, records: list[dict], data_type: str = 'raw'):
        """Write batch of records with partitioning."""
        ...
    
    def consolidate_daily(self, date_str: str):
        """Consolidate small files into daily files."""
        ...
    
    def export_training_dataset(self, output_path: str, 
                                 start_date: str = None,
                                 end_date: str = None) -> dict:
        """Export consolidated dataset for ML training."""
        ...
```

**Storage Structure:**
```
data/l2/
├── raw/
│   └── date=2025-12-18/
│       └── symbol=HAL/
│           └── part_0000.parquet
├── features/
│   └── date=2025-12-18/
│       └── symbol=HAL/
│           └── part_0000.parquet
├── exports/
│   └── training_2025-12-18.parquet
└── metadata/
    └── collection_log.json
```

**Deliverables:**
- [ ] `qx-l2/src/qx_l2/storage.py`
- [ ] Partitioned writes
- [ ] Daily consolidation
- [ ] Export functionality

#### Task 3.2: Scheduling System
Create independent scheduling (not dependent on ML system):

```python
# qx-l2/src/qx_l2/scheduler.py

class L2Scheduler:
    """Independent L2 collection scheduler."""
    
    DEFAULT_WINDOWS = [
        "09:30-10:30",  # Opening
        "11:30-12:30",  # Pre-lunch
        "14:00-15:00",  # Afternoon
        "15:00-16:00",  # Power hour
    ]
    
    def __init__(self, config: dict):
        self.windows = self._parse_windows(config.get('windows', self.DEFAULT_WINDOWS))
        self.timezone = pytz.timezone(config.get('timezone', 'America/New_York'))
    
    def is_collection_time(self) -> bool:
        """Check if current time is within collection windows."""
        ...
    
    def next_window_start(self) -> datetime:
        """Get next collection window start time."""
        ...
    
    def run_daemon(self, collector, poll_interval: int = 5):
        """Run as daemon, collecting during windows."""
        ...
```

**Deliverables:**
- [ ] `qx-l2/src/qx_l2/scheduler.py`
- [ ] Time window parsing
- [ ] Daemon mode support

---

### Day 4: Event Journaling & Configuration

#### Task 4.1: Event Journaling (from PAPER_TRADING_GUIDE)
Create comprehensive event logging:

```python
# qx-l2/src/qx_l2/journal.py

class L2Journal:
    """Event journaling for L2 collection (SQLite)."""
    
    def __init__(self, db_path: str = "data/l2/journal.db"):
        self.db_path = Path(db_path)
        self._init_db()
    
    def log_collection_start(self, symbols: list[str], window: str):
        """Log collection session start."""
        ...
    
    def log_snapshot(self, symbol: str, has_depth: bool, spread: float):
        """Log individual snapshot (sampled)."""
        ...
    
    def log_collection_end(self, stats: dict):
        """Log collection session end with stats."""
        ...
    
    def log_error(self, error_type: str, message: str, symbol: str = None):
        """Log errors for debugging."""
        ...
    
    def get_daily_summary(self, date_str: str) -> dict:
        """Get collection summary for a date."""
        ...
```

**Journal Schema:**
```sql
-- Collection sessions
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    start_time TEXT,
    end_time TEXT,
    symbols TEXT,  -- JSON
    window TEXT,
    records_collected INTEGER,
    depth_rate REAL,
    status TEXT
);

-- Errors
CREATE TABLE errors (
    error_id TEXT PRIMARY KEY,
    timestamp TEXT,
    session_id TEXT,
    error_type TEXT,
    message TEXT,
    symbol TEXT
);

-- Daily stats
CREATE TABLE daily_stats (
    date TEXT PRIMARY KEY,
    total_records INTEGER,
    total_symbols INTEGER,
    avg_depth_rate REAL,
    avg_spread REAL,
    storage_mb REAL
);
```

**Deliverables:**
- [ ] `qx-l2/src/qx_l2/journal.py`
- [ ] Session tracking
- [ ] Error logging
- [ ] Daily summaries

#### Task 4.2: Configuration Management
Create flexible configuration system:

```yaml
# qx-l2/configs/default.yaml

# System identification
system:
  name: "L2COLLECT"
  client_id: 500
  version: "1.0.0"

# IBKR connection
ibkr:
  host: "127.0.0.1"
  port: 7497
  timeout: 30
  reconnect_interval: 60

# Symbol selection
symbols:
  mode: "hybrid"  # static, rotating, hybrid, external
  core:
    - HAL
    - PFE
    - LUV
  rotating_pool:
    - MOS
    - ACHR
    - CRGY
    - FCX
    - AA
    - T
    - VZ
  max_symbols: 6

# Collection parameters
collection:
  levels: 10
  snapshot_interval_ms: 1000
  smart_depth: true
  rotate_seconds: 300

# Scheduling
schedule:
  timezone: "America/New_York"
  windows:
    - "09:30-10:30"
    - "11:30-12:30"
    - "14:00-15:00"
    - "15:00-16:00"
  skip_weekends: true
  skip_holidays: true

# Storage
storage:
  base_dir: "./data/l2"
  format: "parquet"
  compression: "snappy"
  partition_by:
    - date
    - symbol
  flush_rows: 300
  consolidate_daily: true
  retention_days: 90

# Feature engineering
features:
  enabled: true
  obi_levels: [1, 3, 5, 10]
  delta_windows_sec: [5, 30]

# Journaling
journal:
  enabled: true
  db_path: "./data/l2/journal.db"
  sample_rate: 0.1  # Log 10% of snapshots

# Quality thresholds
quality:
  min_depth_rate: 0.85
  max_spread: 0.03
  alert_on_degradation: true
```

**Deliverables:**
- [ ] `qx-l2/src/qx_l2/config.py`
- [ ] `qx-l2/configs/default.yaml`
- [ ] Config validation
- [ ] Environment variable overrides

---

### Day 5: Scripts, Testing & Documentation

#### Task 5.1: Entry Point Scripts

```python
# qx-l2/scripts/run_collector.py
#!/usr/bin/env python3
"""Main L2 collector entry point."""

import argparse
from qx_l2 import L2Collector, load_config

def main():
    parser = argparse.ArgumentParser(description='L2 Data Collector')
    parser.add_argument('--config', default='configs/default.yaml')
    parser.add_argument('--daemon', action='store_true', help='Run as daemon')
    parser.add_argument('--once', action='store_true', help='Run one collection cycle')
    parser.add_argument('--symbols', nargs='+', help='Override symbols')
    args = parser.parse_args()
    
    config = load_config(args.config)
    if args.symbols:
        config['symbols']['mode'] = 'static'
        config['symbols']['core'] = args.symbols
    
    collector = L2Collector(config)
    
    if args.daemon:
        collector.run_daemon()
    elif args.once:
        collector.run_once()
    else:
        collector.run_interactive()

if __name__ == '__main__':
    main()
```

```python
# qx-l2/scripts/export_dataset.py
#!/usr/bin/env python3
"""Export L2 data for ML training."""

import argparse
from qx_l2 import L2Storage, load_config

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, help='Output path')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--symbols', nargs='+', help='Filter symbols')
    parser.add_argument('--features-only', action='store_true')
    args = parser.parse_args()
    
    storage = L2Storage(load_config())
    result = storage.export_training_dataset(
        output_path=args.output,
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=args.symbols,
        features_only=args.features_only,
    )
    print(f"Exported: {result}")

if __name__ == '__main__':
    main()
```

**Deliverables:**
- [ ] `qx-l2/scripts/run_collector.py`
- [ ] `qx-l2/scripts/export_dataset.py`
- [ ] `qx-l2/scripts/analyze_data.py`
- [ ] `qx-l2/scripts/preflight_check.py`

#### Task 5.2: Testing

```python
# qx-l2/tests/test_collector.py

def test_symbol_selector_static():
    """Test static symbol selection."""
    ...

def test_symbol_selector_rotating():
    """Test rotating symbol selection."""
    ...

def test_scheduler_windows():
    """Test time window parsing."""
    ...

def test_storage_partitioning():
    """Test partitioned writes."""
    ...

def test_feature_computation():
    """Test L2 feature computation."""
    ...
```

**Deliverables:**
- [ ] Unit tests for all components
- [ ] Integration test with mock IBKR

#### Task 5.3: Documentation

**Deliverables:**
- [ ] `qx-l2/README.md` - Quick start guide
- [ ] `qx-l2/docs/CONFIGURATION.md` - Config reference
- [ ] `qx-l2/docs/ARCHITECTURE.md` - System design
- [ ] Update main `quantstack/README.md`

---

## Integration Points (Optional, Post-Sprint)

### ML System Integration
```python
# In quantstack ML system (optional consumer)
from qx_l2 import L2Storage

# Load latest L2 features for live trading
storage = L2Storage("./data/l2")
l2_features = storage.get_latest_features(symbol="HAL")
```

### SIP Integration (Optional)
```python
# External symbol injection
from qx_l2 import L2Collector

collector = L2Collector(config)
collector.set_symbols(sip_universe[:6])  # Override from SIP
```

---

## Acceptance Criteria

### Must Have
- [ ] `qx-l2` installable as standalone package
- [ ] No imports from `transalpha/l2` or `qx-data`
- [ ] Independent symbol selection (not dependent on Polygon/SIP)
- [ ] Independent scheduling (not dependent on ML system)
- [ ] System tagging for IBKR (client_id + order_ref pattern)
- [ ] Event journaling (SQLite)
- [ ] Configurable via YAML
- [ ] Can run as daemon or one-shot
- [ ] Exports ML-ready datasets

### Should Have
- [ ] Daily consolidation
- [ ] Data quality monitoring
- [ ] Preflight checks
- [ ] Graceful shutdown

### Nice to Have
- [ ] Systemd service file
- [ ] Docker container
- [ ] Prometheus metrics
- [ ] Slack/email alerts

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| IBKR connection instability | Reconnection logic, health checks |
| Data loss on crash | Frequent flushes, WAL journaling |
| Storage growth | Retention policy, compression |
| Symbol selection drift | Core symbols always included |

---

## Post-Sprint Tasks

1. **Week 2**: Run parallel with existing system, validate data quality
2. **Week 3**: Deprecate `transalpha/l2` dependency
3. **Week 4**: ML integration testing
4. **Week 5**: Production deployment

---

## Commands Reference

```bash
# Install package
cd qx-l2 && pip install -e .

# Run collector (daemon mode)
python scripts/run_collector.py --daemon

# Run single collection cycle
python scripts/run_collector.py --once

# Export training dataset
python scripts/export_dataset.py --output data/training.parquet --start-date 2025-12-01

# Analyze data quality
python scripts/analyze_data.py --date 2025-12-18

# Preflight check
python scripts/preflight_check.py
```

---

**Sprint Owner:** [TBD]  
**Review Date:** End of Day 5  
**Dependencies:** IBKR Gateway running, Python 3.11+
