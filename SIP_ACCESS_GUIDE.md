# SIP Data Access Guide

**For use in other trading repos (e.g., ~/transalpha/)**

---

## What is SIP?

SIP (Stocks In Play) is a daily-filtered list of catalyst-driven stocks selected using SMB Capital methodology:
- Gap ≥ 2%
- ATR ≥ $2
- ADV ≥ 10M
- Top 20 stocks per day by score

---

## Data Location

### Current SIP Data (1 month - May 2024)
```
/home/jacobw/quantstack/run/sip_membership_smb_1month/sip_membership.parquet
```

### 3-Month SIP Data (Mar-May 2024) - In Progress
```
/home/jacobw/quantstack/run/sip_membership_smb_3months/sip_membership.parquet
```
*Available after feature store build completes (~20:30 SGT)*

---

## Data Schema

```python
import pandas as pd

sip = pd.read_parquet('/home/jacobw/quantstack/run/sip_membership_smb_1month/sip_membership.parquet')

# Columns:
# - date: datetime.date - Trading date
# - symbol: str - Ticker symbol (uppercase)
# - open, high, low, close: float - Daily OHLC
# - volume: int - Daily volume
# - prior_close: float - Previous day's close
# - gap_pct: float - Gap percentage (open - prior_close) / prior_close
# - adv20: float - 20-day average daily volume
# - atr14: float - 14-day ATR
# - score: float - Catalyst score (gap_pct × atr14 × adv20/1M)
```

---

## Usage Examples

### 1. Get Today's SIP List

```python
import pandas as pd
from datetime import date

sip = pd.read_parquet('/home/jacobw/quantstack/run/sip_membership_smb_1month/sip_membership.parquet')

# Get today's stocks
today = date.today()
today_sip = sip[sip['date'] == today]

# Get just the symbols
symbols = today_sip['symbol'].tolist()
print(f"Today's SIP: {symbols}")
```

### 2. Get SIP for Specific Date

```python
import pandas as pd

sip = pd.read_parquet('/home/jacobw/quantstack/run/sip_membership_smb_1month/sip_membership.parquet')

# Get specific date
target_date = pd.to_datetime('2024-05-23').date()
day_sip = sip[sip['date'] == target_date]

print(f"SIP for {target_date}:")
print(day_sip[['symbol', 'gap_pct', 'atr14', 'score']])
```

### 3. Get Historical SIP Membership

```python
import pandas as pd

sip = pd.read_parquet('/home/jacobw/quantstack/run/sip_membership_smb_1month/sip_membership.parquet')

# Get all dates a symbol was in SIP
symbol = 'NVDA'
symbol_sip = sip[sip['symbol'] == symbol]

print(f"{symbol} was in SIP on {len(symbol_sip)} days:")
print(symbol_sip[['date', 'gap_pct', 'score']].to_string())
```

### 4. Filter by Criteria

```python
import pandas as pd

sip = pd.read_parquet('/home/jacobw/quantstack/run/sip_membership_smb_1month/sip_membership.parquet')

# Get only high-gap stocks (>5%)
high_gap = sip[sip['gap_pct'].abs() >= 0.05]

print(f"High-gap stocks: {len(high_gap)} entries")
print(high_gap[['date', 'symbol', 'gap_pct', 'atr14']].head(10))
```

### 5. Integration with Trading Strategy

```python
import pandas as pd
from datetime import date

def get_todays_sip_universe():
    """Get today's SIP-filtered universe for trading."""
    sip_file = '/home/jacobw/quantstack/run/sip_membership_smb_1month/sip_membership.parquet'
    sip = pd.read_parquet(sip_file)
    
    today = date.today()
    today_sip = sip[sip['date'] == today]
    
    # Return as list of symbols
    return today_sip['symbol'].tolist()

# Use in your strategy
universe = get_todays_sip_universe()
print(f"Trading universe: {universe}")

# Or get full data for additional filtering
def get_todays_sip_data():
    """Get today's SIP data with metrics."""
    sip_file = '/home/jacobw/quantstack/run/sip_membership_smb_1month/sip_membership.parquet'
    sip = pd.read_parquet(sip_file)
    
    today = date.today()
    return sip[sip['date'] == today]

# Use for additional filtering
sip_data = get_todays_sip_data()
# Filter to only stocks with ATR > $3
high_atr = sip_data[sip_data['atr14'] > 3.0]
universe = high_atr['symbol'].tolist()
```

---

## Symlink for Easy Access

Create a symlink in your transalpha repo:

```bash
cd ~/transalpha
mkdir -p data/sip
ln -s /home/jacobw/quantstack/run/sip_membership_smb_1month/sip_membership.parquet data/sip/current.parquet

# Then access as:
# pd.read_parquet('data/sip/current.parquet')
```

---

## Update Frequency

- **Current**: Static historical data (May 2024)
- **Future**: Can be regenerated daily by running:
  ```bash
  cd /home/jacobw/quantstack
  python scripts/generate_smb_sip_from_features_no_pm.py
  ```

---

## Notes

1. **Symbol Case**: All symbols are UPPERCASE
2. **Date Format**: Python `datetime.date` objects (not strings)
3. **Missing Dates**: Weekends and holidays not included
4. **Dynamic Universe**: Different stocks each day based on catalysts
5. **Typical Size**: 15-25 stocks per day (can be 1-30 depending on market conditions)

---

## Validation

```python
import pandas as pd

sip = pd.read_parquet('/home/jacobw/quantstack/run/sip_membership_smb_1month/sip_membership.parquet')

print("SIP Data Summary:")
print(f"  Total entries: {len(sip)}")
print(f"  Unique symbols: {sip['symbol'].nunique()}")
print(f"  Date range: {sip['date'].min()} to {sip['date'].max()}")
print(f"  Avg stocks/day: {len(sip) / sip['date'].nunique():.1f}")
print()
print("Top 5 most frequent symbols:")
print(sip['symbol'].value_counts().head())
```

---

## Questions?

See `/home/jacobw/quantstack/SYSTEM_OVERVIEW.md` for full system documentation.
