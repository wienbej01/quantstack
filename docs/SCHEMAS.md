# SCHEMAS

## Bars (canonical)
```json
{
  "type":"object",
  "required":["ts","symbol","open","high","low","close","volume"],
  "properties":{
    "ts":{"type":"string","format":"date-time","x-tz":"UTC","x-unit":"ns"},
    "symbol":{"type":"string"},
    "open":{"type":"number"}, "high":{"type":"number"},
    "low":{"type":"number"},  "close":{"type":"number"},
    "volume":{"type":"integer"},
    "trades":{"type":"integer"},
    "vwap":{"type":"number"}, "session":{"type":"string"}, "date_et":{"type":"string"}
  }
}
```

## Trades (per-run)
```json
{
  "type":"object",
  "required":["entry_ts","exit_ts","symbol","side","qty","entry_px","exit_px","pnl"],
  "properties":{
    "entry_ts":{"type":"string","format":"date-time","x-tz":"UTC","x-unit":"ns"},
    "exit_ts":{"type":"string","format":"date-time","x-tz":"UTC","x-unit":"ns"},
    "symbol":{"type":"string"},
    "side":{"type":"string","enum":["BUY","SELL"]},
    "qty":{"type":"integer"},
    "entry_px":{"type":"number"}, "exit_px":{"type":"number"},
    "fees":{"type":"number"}, "slippage_est":{"type":"number"},
    "pnl":{"type":"number"}, "r_multiple":{"type":"number"},
    "mfe":{"type":"number"}, "mae":{"type":"number"},
    "duration_s":{"type":"integer"},
    "policy_tag":{"type":"string"}, "risk_tag":{"type":"string"}
  }
}
```

## Inputs checksum
```json
{
  "type":"object",
  "required":["bars_norm_hash","features_hash","config_hash","seed"],
  "properties":{
    "bars_norm_hash":{"type":"string"},
    "features_hash":{"type":"string"},
    "sip_hash":{"type":"string"},
    "config_hash":{"type":"string"},
    "seed":{"type":"integer"}
  }
}
```
