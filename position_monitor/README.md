# Position Monitor

Real-time IBKR position and P&L tracking with Conky display.

## Overview

The Position Monitor queries the IBKR Gateway every 60 seconds for open positions and daily
P&L, then writes the data to `/tmp/positions.json` for consumption by Conky desktop widgets.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    IBKR Gateway (TWS API)                   │
│  Host: 127.0.0.1  Port: 7497                                │
└────────────────────────┬────────────────────────────────────┘
                         │ socket (ib_insync)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│            Position Monitor (position_monitor/)              │
│  - Queries positions & P&L every 60s                        │
│  - Writes to /tmp/positions.json                            │
│  - Color-coded display (green/red/yellow)                   │
└────────────────────────┬────────────────────────────────────┘
                         │ JSON file
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Conky Display (~/.config/conky/)                │
│  - Reads /tmp/positions.json via jq                         │
│  - Ultra-minimalist single-line output                      │
└─────────────────────────────────────────────────────────────┘
```

## Installation

### Prerequisites

1. **IBKR Gateway** must be running and accepting API connections:
   ```bash
   systemctl status ibkr-gateway.service
   nc -zv 127.0.0.1 7497
   ```

2. **Conky** installed on your system:
   ```bash
   sudo apt install conky-all  # Debian/Ubuntu
   ```

### Systemd Service Installation

Run the installation script (requires sudo):
```bash
cd /home/jacobw/quantstack
./systemd/install_position_monitor.sh
```

Or manually:
```bash
sudo cp systemd/position-monitor.service /etc/systemd/system/
sudo cp systemd/conky-position.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable position-monitor.service conky-position.service
sudo systemctl start position-monitor.service conky-position.service
```

### Verify Installation

```bash
# Check service status
systemctl status position-monitor.service
systemctl status conky-position.service

# Check JSON output
cat /tmp/positions.json | jq .

# View logs
tail -f /home/jacobw/quantstack/logs/position_monitor.log
```

## Configuration

### Position Monitor

Configure via environment variables (read in `position_monitor/main.py`):
```bash
export IBKR_GATEWAY_HOST="127.0.0.1"
export IBKR_GATEWAY_PORT="7497"
export IBKR_POSITION_CLIENT_ID="900"
export IBKR_ACCOUNT_ID="DU123456"  # Optional
```

### Conky Display

Edit `~/.config/conky/positions.conf`:
- `gap_x`, `gap_y`: Position on screen (pixels from edge)
- `font`: Text font and size
- `update_interval`: Conky refresh rate (default: 5 seconds)

## Output Format

### `/tmp/positions.json`

```json
{
  "positions": [
    {"symbol": "AAPL", "pnl": "+500.00", "color": "#00FF00"},
    {"symbol": "TSLA", "pnl": "-200.00", "color": "#FF3333"}
  ],
  "daily_pnl": "+$300.00",
  "daily_color": "#00FF00",
  "market_hours": true
}
```

### Color Codes

- `#00FF00` (Green): Positive P&L
- `#FF3333` (Red): Negative P&L
- `#FFFF00` (Yellow): Zero/flat

### Conky Display

Single-line format: `SYMBOL:+$PnL SYMBOL:+$PnL ... D:+$DAILY`

Example: `AAPL:+$500.00 TSLA:-$200.00 D:+$300.00`

## Usage

### Manual Testing

Run the monitor manually:
```bash
cd /home/jacobw/quantstack
python -m position_monitor.main
```

### Unit Tests

Run tests directly:
```bash
python tests/position_monitor/run_tests.py
```

## Troubleshooting

### Service not starting

```bash
# Check service logs
journalctl -u position-monitor.service -n 50

# Check IBKR Gateway connectivity
systemctl status ibkr-gateway.service
nc -zv 127.0.0.1 7497
```

### No positions displayed

1. Verify IBKR Gateway is authenticated (check the Gateway UI or logs):
   ```bash
   journalctl -u ibkr-gateway.service -n 50
   ```

2. Confirm account selection (optional):
   ```bash
   export IBKR_ACCOUNT_ID="DU123456"
   ```

3. Monitor logs for errors:
   ```bash
   tail -f /home/jacobw/quantstack/logs/position_monitor.log
   ```

### Conky not updating

1. Restart Conky service:
   ```bash
   systemctl restart conky-position.service
   ```

2. Verify JSON file exists and is readable:
   ```bash
   cat /tmp/positions.json | jq .
   ```

3. Check Conky logs:
   ```bash
   journalctl -u conky-position.service -n 50
   ```

### Market hours detection

The monitor only shows positions during US market hours (09:30-16:30 ET). Outside these hours, the output will show:
```json
{"positions": [], "daily_pnl": "+$0.00", "daily_color": "#FFFF00", "market_hours": false}
```

To override this, edit `position_monitor/monitor.py` and modify the `is_market_hours()` method.

## Module Reference

### `position_monitor.models`

```python
@dataclass
class Position:
    symbol: str
    quantity: int
    avg_price: float
    current_price: float
    unrealized_pnl: float
    market_value: float

    @property
    def pnl_display(self) -> str     # "+$500.00" or "-$500.00"

    @property
    def color(self) -> str           # "#00FF00" (green/red/yellow)


@dataclass
class PnLData:
    daily_pnl: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    @property
    def daily_display(self) -> str   # "+$1234.56"


@dataclass
class PositionsOutput:
    positions: List[dict]
    daily_pnl: str
    daily_color: str
    market_hours: bool
```

### `position_monitor.monitor`

```python
class PositionMonitor:
    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        output_file: str,
        account_id: str | None = None,
    )
    def connect(self) -> bool
    def is_market_hours(self) -> bool
    def get_open_positions(self) -> list[Position]
    def get_daily_pnl(self) -> PnLData
    def write_positions_json(self, positions=None, pnl=None) -> bool
    def update(self) -> bool
    def disconnect(self)
```

## Files

| File | Purpose |
|------|---------|
| `position_monitor/__init__.py` | Package exports |
| `position_monitor/models.py` | Dataclasses (Position, PnLData, PositionsOutput) |
| `position_monitor/monitor.py` | PositionMonitor class with IBKR Gateway integration |
| `position_monitor/main.py` | Application entry point (async, signal handling) |
| `systemd/position-monitor.service` | Systemd service for monitor |
| `systemd/conky-position.service` | Systemd service for Conky display |
| `~/.config/conky/positions.conf` | Conky display configuration |

## License

Part of the quantstack trading system.
