# qx-l2 Architecture

Technical architecture and design decisions for the standalone L2 data collector.

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    qx-l2 Architecture                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Scheduler  │  │    Symbols   │  │   Journal    │      │
│  │ (Time Windows│  │  (Selection) │  │  (SQLite)    │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                 │               │
│         ▼                 ▼                 ▼               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                  Collector                          │   │
│  │  • IBKR Connection (Tagged)                         │   │
│  │  • L2 Subscription Management                       │   │
│  │  • Snapshot Generation                              │   │
│  └─────────────────────────────────────────────────────┘   │
│         │                 │                 │               │
│         ▼                 ▼                 ▼               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Features   │  │   Storage    │  │     CLI      │      │
│  │ (L2 Compute) │  │ (Partitioned)│  │ (Interface)  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Collector (`collector.py`)
**Purpose**: Main orchestrator and IBKR interface

**Key Responsibilities:**
- IBKR connection management with system tagging
- L2 market depth subscription
- Snapshot generation from ticker data
- Buffer management and flushing
- Session lifecycle management

**Design Patterns:**
- **State Machine**: Manages symbol subscription states
- **Observer**: Reacts to IBKR ticker updates
- **Buffer**: Batches data before storage

```python
class L2Collector:
    def __init__(self, config: dict):
        self.system_tag = f"{SYSTEM_NAME}_{client_id}"  # System identification
        self._states: dict[str, CollectorState] = {}    # Symbol states
        self._raw_buffer: list[dict] = []               # Data buffer
        
    def poll_once(self):
        """Core collection loop - non-blocking"""
        # Process IBKR messages
        # Generate snapshots
        # Buffer data
        # Flush if needed
```

### 2. Symbol Selector (`symbols.py`)
**Purpose**: Independent symbol selection with multiple strategies

**Selection Modes:**
- **Static**: Fixed list from configuration
- **Rotating**: Round-robin through symbol pool
- **Hybrid**: Core symbols + daily rotation (recommended)
- **External**: Accept symbols from external source

**Design Patterns:**
- **Strategy**: Different selection algorithms
- **Factory**: Mode-based selector creation

```python
class L2SymbolSelector:
    def get_symbols(self, date_str: str = None) -> list[str]:
        if self.mode == "hybrid":
            return self._get_hybrid(date_str)
        # ... other modes
    
    def _get_hybrid(self, date_str: str) -> list[str]:
        symbols = list(self.core_symbols)  # Always include core
        # Add rotating symbols based on date hash
        return symbols[:self.max_symbols]
```

### 3. Scheduler (`scheduler.py`)
**Purpose**: Time window management and daemon orchestration

**Features:**
- Timezone-aware window parsing
- Market hours detection
- Daemon mode with callbacks
- Next window calculation

**Design Patterns:**
- **Observer**: Callback-based window transitions
- **State Machine**: Window active/inactive states

```python
class L2Scheduler:
    def run_daemon(self, on_window_start: Callable, on_window_end: Callable):
        """Daemon loop with window detection"""
        while True:
            in_window = self.is_collection_time()
            if in_window and not was_in_window:
                on_window_start()  # Start collection
            elif not in_window and was_in_window:
                on_window_end()    # Stop collection
```

### 4. Storage (`storage.py`)
**Purpose**: Partitioned data storage with optimization

**Storage Strategy:**
- **Partitioning**: By date and symbol for efficient queries
- **Compression**: Snappy compression for space efficiency
- **Consolidation**: Daily file merging for performance
- **Retention**: Automatic cleanup of old data

**Design Patterns:**
- **Repository**: Abstract storage operations
- **Partition**: Hierarchical data organization

```
data/l2/
├── raw/date=2025-12-18/symbol=HAL/part_*.parquet
├── features/date=2025-12-18/symbol=HAL/part_*.parquet
└── exports/training_*.parquet
```

### 5. Features (`features.py`)
**Purpose**: Real-time L2 microstructure feature computation

**Feature Categories:**
- **Basic**: Mid price, spread, microprice
- **Depth**: Total depth, imbalance, pressure
- **OBI**: Order book imbalance at multiple levels
- **Time Deltas**: 5s and 30s momentum features

**Design Patterns:**
- **Pipeline**: Sequential feature computation
- **Sliding Window**: Time-based feature history

```python
class L2FeatureEngineer:
    def __init__(self, config: dict):
        self.history = deque(maxlen=100)  # Sliding window
    
    def compute(self, snapshot: dict, levels: int) -> dict:
        features = self._compute_basic(snapshot)
        features.update(self._compute_depth(snapshot, levels))
        features.update(self._compute_obi(snapshot, levels))
        features.update(self._compute_deltas(snapshot))
        return features
```

### 6. Journal (`journal.py`)
**Purpose**: Event logging and audit trail (from PAPER_TRADING_GUIDE)

**Event Types:**
- **Sessions**: Collection session start/end
- **Errors**: Connection and data quality issues
- **Daily Stats**: Aggregated daily metrics

**Design Patterns:**
- **Event Sourcing**: Complete audit trail
- **Repository**: SQLite data access

```sql
-- Schema Design
sessions: session_id, start_time, symbols, records_collected, depth_rate
errors: error_id, timestamp, error_type, message, symbol
daily_stats: date, total_records, avg_depth_rate, avg_spread
```

## Data Flow

### Collection Pipeline
```
1. Scheduler → Determines collection windows
2. Symbols → Selects symbols for today
3. Collector → Connects to IBKR, subscribes to symbols
4. IBKR → Streams L2 market depth data
5. Collector → Generates snapshots from ticker data
6. Features → Computes microstructure features
7. Storage → Writes to partitioned parquet files
8. Journal → Logs session events and stats
```

### Data Transformation
```
IBKR Ticker → Raw Snapshot → Features → Storage
     ↓              ↓           ↓         ↓
   DOM Bids      76 columns  28 columns  Parquet
   DOM Asks      L1 + L2     OBI, etc.   Compressed
   Market Data   Timestamps  Deltas      Partitioned
```

## System Integration

### IBKR Integration
**Connection Strategy:**
- **System Tagging**: `L2COLLECT_500` for clean separation
- **Client ID**: Unique per system (500 default)
- **Reconnection**: Automatic retry with exponential backoff
- **Error Handling**: Graceful degradation on connection loss

**Market Data:**
- **Smart Depth**: IBKR's aggregated order book
- **10 Levels**: Configurable depth (1-20 levels)
- **Market Makers**: Exchange attribution per level
- **Real-time**: 1-second snapshot frequency

### Configuration System
**Hierarchy:**
1. Default configuration (hardcoded)
2. YAML file configuration
3. Environment variable overrides

**Design Patterns:**
- **Builder**: Configuration assembly
- **Validation**: Type checking and constraints

```python
def load_config(config_path: str = None) -> dict:
    config = DEFAULT_CONFIG.copy()
    if config_path:
        user_config = yaml.safe_load(open(config_path))
        config = _deep_merge(config, user_config)
    config = _apply_env_overrides(config)
    return config
```

## Performance Characteristics

### Throughput
- **Symbols**: 6 concurrent (IBKR limit)
- **Frequency**: 1 snapshot/second per symbol
- **Daily Volume**: ~21,600 snapshots (4 hours × 6 symbols)
- **Storage**: ~20MB/day compressed

### Resource Usage
- **Memory**: <100MB for 6 symbols
- **CPU**: <5% on modern hardware
- **Network**: <1Mbps (IBKR connection)
- **Disk I/O**: Batched writes every 300 records

### Scalability Limits
- **IBKR Limit**: 6 concurrent L2 subscriptions
- **Symbol Rotation**: 5-minute rotation to cover more symbols
- **Storage Growth**: ~600MB/month with default settings
- **Processing Latency**: <100ms per snapshot

## Error Handling

### Connection Resilience
```python
def connect(self) -> bool:
    try:
        self.ib.connect(self.host, self.port, clientId=self.client_id)
        return True
    except Exception as e:
        self.journal.log_error("CONNECTION", str(e))
        return False

def reconnect_if_needed(self):
    if not self.ib.isConnected():
        self.journal.log_error("DISCONNECTION", "Connection lost")
        return self.connect()
```

### Data Quality Monitoring
- **Depth Rate**: % of snapshots with order book data
- **Spread Validation**: Reject unrealistic spreads
- **Timestamp Validation**: Ensure proper sequencing
- **Symbol Validation**: Verify subscription success

### Graceful Degradation
- **Partial Failures**: Continue with available symbols
- **Buffer Overflow**: Flush immediately if memory pressure
- **Storage Errors**: Log and continue (don't crash)
- **Feature Errors**: Skip features, keep raw data

## Security Considerations

### IBKR Security
- **Read-Only**: No trading permissions required
- **Client ID Isolation**: Unique ID prevents conflicts
- **Connection Limits**: Respects IBKR rate limits
- **Data Privacy**: No sensitive account data stored

### Data Security
- **Local Storage**: All data stored locally
- **No Network Exposure**: No external API endpoints
- **File Permissions**: Restrictive file permissions
- **Audit Trail**: Complete event logging

## Deployment Patterns

### Development
```bash
# Local development
l2-collect --once --symbols HAL --log-level DEBUG
```

### Testing
```bash
# Automated testing
l2-collect --once --config test_config.yaml
python scripts/analyze_data.py --date $(date +%Y-%m-%d)
```

### Production
```bash
# Daemon mode with systemd
systemctl start l2-collect
systemctl enable l2-collect
```

### Monitoring
```bash
# Health checks
curl -f http://localhost:8080/health || systemctl restart l2-collect
```

## Extension Points

### Custom Symbol Selection
```python
class CustomSymbolSelector(L2SymbolSelector):
    def get_symbols(self, date_str: str = None) -> list[str]:
        # Custom logic here
        return custom_symbols
```

### Custom Features
```python
class CustomFeatureEngineer(L2FeatureEngineer):
    def compute(self, snapshot: dict, levels: int) -> dict:
        features = super().compute(snapshot, levels)
        features.update(self._compute_custom_features(snapshot))
        return features
```

### External Integration
```python
# SIP integration example
collector = L2Collector(config)
collector.symbol_selector.set_external_symbols(sip_universe[:6])
```

## Design Decisions

### Why SQLite for Journaling?
- **Simplicity**: No external database required
- **ACID**: Reliable event logging
- **Performance**: Fast for append-only workload
- **Portability**: Single file, easy backup

### Why Parquet for Storage?
- **Compression**: 10x better than CSV
- **Schema**: Typed columns with metadata
- **Analytics**: Direct pandas/ML integration
- **Partitioning**: Efficient date/symbol queries

### Why Hybrid Symbol Selection?
- **Continuity**: Core symbols ensure time-series consistency
- **Diversity**: Rotation provides broader market coverage
- **Flexibility**: Can adapt to changing market conditions
- **Deterministic**: Date-based rotation is reproducible

### Why Independent Scheduling?
- **Decoupling**: No dependency on external systems
- **Reliability**: Self-contained time management
- **Flexibility**: Easy to adjust collection windows
- **Testing**: Can run outside market hours for testing
