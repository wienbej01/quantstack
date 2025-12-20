# qx-l2 Configuration Reference

Complete reference for all configuration options.

## Configuration Hierarchy

1. **Default Configuration** (hardcoded in `config.py`)
2. **YAML File** (specified with `--config`)
3. **Environment Variables** (highest priority)

## Configuration File Format

### Basic Structure
```yaml
# configs/default.yaml
system:          # System identification
ibkr:           # IBKR connection settings
symbols:        # Symbol selection strategy
collection:     # Data collection parameters
schedule:       # Time windows and scheduling
storage:        # Data storage settings
features:       # Feature engineering options
journal:        # Event logging configuration
quality:        # Data quality thresholds
```

## Section Reference

### System Configuration
```yaml
system:
  name: "L2COLLECT"        # System name for tagging
  client_id: 500           # IBKR client ID (must be unique)
  version: "1.0.0"         # Version for logging
```

**Options:**
- `name`: System identifier used in IBKR order references
- `client_id`: IBKR client ID (100-999, avoid conflicts)
- `version`: Version string for audit trail

**Environment Overrides:**
- `L2_CLIENT_ID`: Override client ID

### IBKR Connection
```yaml
ibkr:
  host: "127.0.0.1"        # IBKR host
  port: 7497               # IBKR port (7497=paper, 7496=live)
  timeout: 30              # Connection timeout (seconds)
  reconnect_interval: 60   # Reconnection retry interval
```

**Options:**
- `host`: IBKR TWS/Gateway host (usually localhost)
- `port`: Connection port
  - `7497`: Paper trading (TWS)
  - `7496`: Live trading (TWS)
  - `4002`: Paper trading (Gateway)
  - `4001`: Live trading (Gateway)
- `timeout`: Connection timeout in seconds
- `reconnect_interval`: Seconds between reconnection attempts

**Environment Overrides:**
- `L2_IBKR_HOST`: Override host
- `L2_IBKR_PORT`: Override port

### Symbol Selection
```yaml
symbols:
  mode: "hybrid"           # Selection mode
  nyse_only: true          # Enforce NYSE-only contracts
  exchange: "NYSE"         # Contract exchange for depth requests
  allowed_primary_exchanges: ["NYSE"]  # Optional primary exchange filter
  core: [HAL, PFE, LUV]   # Core symbols (always included)
  rotating_pool:           # Pool for rotation
    - MOS
    - ACHR
    - CRGY
  max_symbols: 6          # Maximum concurrent symbols
```

**Selection Modes:**

#### Static Mode
Fixed symbol list:
```yaml
symbols:
  mode: "static"
  core: [HAL, PFE, LUV, MOS, ACHR, CRGY]
  max_symbols: 6
```

#### Rotating Mode
Round-robin through pool:
```yaml
symbols:
  mode: "rotating"
  rotating_pool: [HAL, PFE, LUV, MOS, ACHR, CRGY, FCX, AA]
  max_symbols: 6
```

#### Hybrid Mode (Recommended)
Core symbols + daily rotation:
```yaml
symbols:
  mode: "hybrid"
  core: [HAL, PFE, LUV]                    # Always collected
  rotating_pool: [MOS, ACHR, CRGY, FCX]   # Rotated daily
  max_symbols: 6
```

#### External Mode
Accept symbols from external source:
```yaml
symbols:
  mode: "external"
  core: [HAL, PFE, LUV]  # Fallback if no external symbols
  max_symbols: 6
```

**Options:**
- `mode`: Selection strategy (`static`, `rotating`, `hybrid`, `external`)
- `nyse_only`: Enforce NYSE-only contracts and NYSE exchange routing
- `exchange`: Contract exchange used for L2 requests (`SMART`, `NYSE`, etc.)
- `allowed_primary_exchanges`: Optional allowlist for contract primary exchanges
- `core`: Symbols always included (for time-series continuity)
- `rotating_pool`: Pool of symbols for rotation
- `max_symbols`: Maximum concurrent L2 subscriptions (IBKR limit: ~6)

### Collection Parameters
```yaml
collection:
  levels: 10                    # Order book depth levels (1-20)
  snapshot_interval_ms: 1000    # Snapshot frequency (milliseconds)
  smart_depth: true             # Use IBKR smart depth aggregation
  rotate_seconds: 300           # Symbol rotation interval (seconds)
  poll_interval_sec: 0.1        # Daemon poll interval (seconds)
```

**Options:**
- `levels`: Order book depth levels to collect (1-20)
  - More levels = more data but higher bandwidth
  - Recommended: 10 levels for most use cases
- `snapshot_interval_ms`: Time between snapshots per symbol
  - 1000ms = 1 snapshot/second (recommended)
  - Lower values = higher frequency but more data
- `poll_interval_sec`: Main loop sleep interval while in-window
- `smart_depth`: Use IBKR's smart depth aggregation
  - `true`: Aggregated across exchanges (recommended)
  - `false`: Exchange-specific depth
- `rotate_seconds`: Symbol rotation interval
  - 300s = 5 minutes (recommended)
  - Only applies when `max_symbols < total_symbols`

### Schedule Configuration
```yaml
schedule:
  timezone: "America/New_York"  # Timezone for windows
  windows:                      # Collection time windows
    - "09:30-10:30"            # Opening hour
    - "11:30-12:30"            # Pre-lunch
    - "14:00-15:00"            # Afternoon
    - "15:00-16:00"            # Power hour
  skip_weekends: true          # Skip Saturday/Sunday
  skip_holidays: true          # Skip market holidays (requires list)
  holidays: ["2025-12-25"]     # Optional holiday date list
```

**Options:**
- `timezone`: Timezone for collection windows
  - Use IANA timezone names (e.g., "America/New_York")
- `windows`: List of collection time windows in HH:MM-HH:MM format
  - Times are in the specified timezone
  - Multiple windows supported
- `skip_weekends`: Skip collection on weekends
- `skip_holidays`: Skip market holidays defined in `holidays`
- `holidays`: List of YYYY-MM-DD dates to skip

**Common Timezones:**
- `"America/New_York"`: US Eastern (NYSE, NASDAQ)
- `"America/Chicago"`: US Central
- `"Europe/London"`: UK (LSE)
- `"Asia/Tokyo"`: Japan (TSE)

### Storage Configuration
```yaml
storage:
  base_dir: "./data/l2"        # Base storage directory
  format: "parquet"            # File format
  compression: "snappy"        # Compression algorithm
  partition_by:                # Partitioning strategy
    - date
    - symbol
  flush_rows: 300             # Rows before flush
  consolidate_daily: true     # Enable daily consolidation
  retention_days: 90          # Data retention period
```

**Options:**
- `base_dir`: Root directory for all L2 data
- `format`: File format (`parquet` only currently)
- `compression`: Compression algorithm
  - `snappy`: Fast compression (recommended)
  - `gzip`: Better compression, slower
  - `lz4`: Fastest, less compression
- `partition_by`: Partitioning columns (order matters)
  - `date`: Partition by collection date
  - `symbol`: Partition by symbol
- `flush_rows`: Buffer size before writing to disk
  - Higher = fewer files, more memory usage
  - Lower = more files, less memory usage
- `consolidate_daily`: Merge small files daily
- `retention_days`: Delete data older than N days

**Environment Overrides:**
- `L2_STORAGE_DIR`: Override base directory

### Feature Engineering
```yaml
features:
  enabled: true               # Enable feature computation
  obi_levels: [1, 3, 5, 10]  # Order book imbalance levels
  delta_windows_sec: [5, 30] # Time delta windows (seconds)
```

**Options:**
- `enabled`: Enable/disable feature computation
  - `true`: Compute features (recommended for ML)
  - `false`: Raw data only (faster, less storage)
- `obi_levels`: Order book imbalance calculation levels
  - List of levels to compute OBI (1-based)
  - More levels = more features but slower computation
- `delta_windows_sec`: Time windows for delta features
  - List of seconds for momentum calculations
  - Common: [5, 30] for short and medium-term momentum

**Generated Features:**
- Basic: `mid`, `spread`, `microprice`, `micro_off`
- Depth: `depth_bid_k`, `depth_ask_k`, `depth_imb_k`, `pressure_k`
- OBI: `obi_1`, `obi_3`, `obi_5`, `obi_10` (based on `obi_levels`)
- Deltas: `d_mid_5s`, `d_spread_5s`, etc. (based on `delta_windows_sec`)

### Journal Configuration
```yaml
journal:
  enabled: true                    # Enable event logging
  db_path: "./data/l2/journal.db" # SQLite database path
  sample_rate: 0.1                # Snapshot sampling rate
```

**Options:**
- `enabled`: Enable/disable event journaling
- `db_path`: Path to SQLite database file
- `sample_rate`: Fraction of snapshots to log (0.0-1.0)
  - 0.1 = log 10% of snapshots (recommended)
  - 1.0 = log all snapshots (high overhead)
  - 0.0 = log no snapshots (sessions/errors only)

### Quality Thresholds
```yaml
quality:
  min_depth_rate: 0.85          # Minimum depth availability
  max_spread: 0.03              # Maximum spread (dollars)
  alert_on_degradation: true    # Enable quality alerts
```

**Options:**
- `min_depth_rate`: Minimum fraction of snapshots with order book data
  - 0.85 = 85% of snapshots should have depth data
  - Lower values indicate data quality issues
- `max_spread`: Maximum acceptable bid-ask spread
  - 0.03 = 3 cents maximum spread
  - Higher spreads may indicate illiquid symbols
- `alert_on_degradation`: Enable quality degradation alerts
  - Currently logs warnings, future: email/Slack alerts

## Environment Variables

Override any configuration with environment variables:

```bash
# IBKR connection
export L2_IBKR_HOST=127.0.0.1
export L2_IBKR_PORT=7497
export L2_CLIENT_ID=500

# Storage
export L2_STORAGE_DIR=/data/l2

# System
export L2_LOG_LEVEL=INFO
```

**Variable Format:**
- Prefix: `L2_`
- Section: `IBKR_`, `STORAGE_`, etc.
- Setting: `HOST`, `PORT`, etc.
- Case: UPPER_CASE

## Configuration Examples

### High-Frequency Collection
```yaml
collection:
  snapshot_interval_ms: 500     # 2 snapshots/second
  levels: 5                     # Fewer levels for speed
storage:
  flush_rows: 500              # Larger batches
features:
  delta_windows_sec: [1, 5]    # Shorter time windows
```

### Low-Resource Mode
```yaml
symbols:
  max_symbols: 3               # Fewer symbols
collection:
  snapshot_interval_ms: 2000   # Lower frequency
  levels: 5                    # Fewer levels
features:
  enabled: false               # Disable features
storage:
  flush_rows: 100             # Smaller batches
```

### Extended Hours Collection
```yaml
schedule:
  windows:
    - "04:00-09:30"            # Pre-market
    - "09:30-16:00"            # Regular hours
    - "16:00-20:00"            # After-hours
```

### Multi-Exchange Setup
```yaml
symbols:
  mode: "static"
  core:
    - HAL      # NYSE
    - AAPL     # NASDAQ
    - GLD      # ARCA
collection:
  smart_depth: false           # Exchange-specific depth
```

## Validation Rules

### Symbol Validation
- Must be valid ticker symbols
- Maximum 10 characters
- Alphanumeric only
- Must have market data permissions

### Time Window Validation
- Format: "HH:MM-HH:MM"
- Start time < End time
- No overlapping windows
- Within 24-hour format

### Numeric Validation
- `client_id`: 1-999
- `levels`: 1-20
- `snapshot_interval_ms`: 100-10000
- `flush_rows`: 10-10000
- `retention_days`: 1-365

## Configuration Testing

### Validate Configuration
```python
from qx_l2 import load_config

try:
    config = load_config("configs/my_config.yaml")
    print("✅ Configuration valid")
except Exception as e:
    print(f"❌ Configuration error: {e}")
```

### Test Symbol Selection
```python
from qx_l2 import L2SymbolSelector, load_config

config = load_config()
selector = L2SymbolSelector(config)
symbols = selector.get_symbols()
print(f"Selected symbols: {symbols}")
```

### Test Schedule
```python
from qx_l2 import L2Scheduler, load_config

config = load_config()
scheduler = L2Scheduler(config)
print(f"In collection window: {scheduler.is_collection_time()}")
print(f"Next window: {scheduler.next_window_start()}")
```
