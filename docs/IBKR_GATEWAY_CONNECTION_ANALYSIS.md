# IBKR Gateway Connection Analysis Report

**Date:** 2026-01-13  
**System:** quantstack trading infrastructure  
**Issue:** Services failing to connect to IBKR Gateway API

---

## Executive Summary

The system uses **IB Gateway (TWS API)** on port 7497, NOT the Client Portal Gateway (REST API on port 5000). These are two completely different IBKR API products. The connection failures are caused by **stale TCP connections accumulating** and overwhelming the Gateway, not configuration issues.

---

## 1. API Product Clarification

| Feature | IB Gateway (TWS API) - **CURRENT** | Client Portal Gateway (REST API) |
|---------|-----------------------------------|----------------------------------|
| Port | 7497 (paper) / 4001 (live) | 5000 |
| Protocol | Socket/TCP binary | REST/HTTP + WebSocket |
| Library | `ib_insync`, `ibapi` | `requests`, HTTP clients |
| Auth | IBC automation + 2FA | Browser login + session cookies |
| Session | Persistent until disconnect | 24hr, needs /tickle every 5min |
| Use Case | Automated trading systems | Web-based applications |

**Your services use `ib_insync` which requires the TWS API (socket-based), not the REST API.**

---

## 2. Documentation Requirements vs Current Configuration

### TWS API Requirements (from [IBKR Documentation](https://interactivebrokers.github.io/tws-api/connection.html))

| Requirement | Documentation | Current System | Status |
|-------------|---------------|----------------|--------|
| Enable ActiveX and Socket Clients | Must be checked in API settings | `EnableApi=true` in jts.ini | ✅ OK |
| Socket Port | 7497 (paper) or 4001 (live) | `LocalServerPort=7497` | ✅ OK |
| Trusted IPs | 127.0.0.1 for local connections | `TrustedIPs=127.0.0.1` | ✅ OK |
| API Only Mode | Recommended for Gateway | `ApiOnly=true` | ✅ OK |
| Accept Incoming Connections | Auto-accept or configure trusted IPs | `AcceptIncomingConnectionAction=accept` | ✅ OK |
| Max 32 concurrent client connections | Per TWS API spec | Multiple services with unique client IDs | ⚠️ ISSUE |

### jts.ini Configuration (Current)
```ini
[IBGateway]
WriteDebug=true
EnableApi=true
MainWindow.Width=757
RemotePortOrderRouting=4001
RemoteHostOrderRouting=ndc1.ibllc.com
LocalServerPort=7497
TrustedIPs=127.0.0.1
ApiOnly=true
```

### IBC config.ini Key Settings (Current)
```ini
TradingMode=paper
AcceptNonBrokerageAccountWarning=yes
AcceptIncomingConnectionAction=accept
ExistingSessionDetectedAction=primaryoverride
```

**Configuration is CORRECT per documentation.**

---

## 3. Root Cause Analysis

### Problem: Zombie TCP Connections

The Gateway becomes unresponsive due to accumulated stale TCP connections in CLOSE-WAIT and FIN-WAIT-2 states:

```
CLOSE-WAIT 1      0   127.0.0.1:7497   127.0.0.1:45094
CLOSE-WAIT 18     0   127.0.0.1:7497   127.0.0.1:38406
CLOSE-WAIT 1      0   127.0.0.1:7497   127.0.0.1:34342
... (30+ stale connections observed)
```

### Why This Happens

1. **Services crash or timeout** without properly closing connections
2. **Gateway holds CLOSE-WAIT** waiting for client to finish closing
3. **Connections accumulate** over time
4. **Gateway becomes overwhelmed** and stops accepting new connections
5. **New connection attempts timeout** even though port is listening

### Evidence
- Port 7497 is LISTENING (socket opens successfully)
- Raw `nc` connection succeeds
- API handshake fails (timeout)
- Multiple CLOSE-WAIT connections visible in `ss -tnp`

---

## 4. Connection Plan Based on Documentation

### Immediate Fix (When Connections Fail)

```bash
# 1. Kill zombie connections
sudo ss -K state close-wait '( dport = 7497 or sport = 7497 )'
sudo ss -K state fin-wait-2 '( dport = 7497 or sport = 7497 )'

# 2. If still failing, restart Gateway
sudo systemctl restart ibkr-gateway

# 3. Wait for login to complete (check logs)
journalctl -u ibkr-gateway -f
# Look for: "IBC: Login has completed"

# 4. Test connection
cd /home/jacobw/quantstack && source .venv/bin/activate
python3 -c "
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 7497, clientId=999, timeout=10)
print(f'Connected: {ib.managedAccounts()}')
ib.disconnect()
"
```

### Permanent Fix: Proper Connection Handling in Services

Per TWS API documentation, services MUST:

1. **Use unique client IDs** (0-32 range, 0 receives GUI orders)
2. **Properly disconnect** on exit/error
3. **Handle connection drops** gracefully
4. **Implement reconnection logic** with backoff

Current client ID assignments:
- `intraday-paper`: clientId=1
- `l2-scalping`: clientId=10,11
- `l2-collector`: clientId=521
- `preflight-check`: clientId=998
- `test connections`: clientId=999

---

## 5. Service-Specific Issues

### intraday-paper.service (FAILED)
```bash
systemctl status intraday-paper
# Check logs for connection errors
journalctl -u intraday-paper --since "1 hour ago" | grep -i "error\|timeout\|connect"
```

### l2-scalping.service (FAILED)
```bash
systemctl status l2-scalping
journalctl -u l2-scalping --since "1 hour ago" | grep -i "error\|timeout\|connect"
```

### Recommended Service Modifications

Add connection wrapper with cleanup:

```python
import atexit
from ib_insync import IB

class IBConnection:
    def __init__(self, client_id):
        self.ib = IB()
        self.client_id = client_id
        atexit.register(self.cleanup)
    
    def connect(self, host='127.0.0.1', port=7497, timeout=10):
        try:
            self.ib.connect(host, port, clientId=self.client_id, timeout=timeout)
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False
    
    def cleanup(self):
        if self.ib.isConnected():
            self.ib.disconnect()
```

---

## 6. Monitoring & Prevention

### Add Connection Health Check Script

Create `/home/jacobw/quantstack/scripts/check_gateway_connections.sh`:

```bash
#!/bin/bash
# Check for zombie connections and alert

ZOMBIE_COUNT=$(ss -tnp state close-wait '( dport = 7497 or sport = 7497 )' 2>/dev/null | wc -l)

if [ "$ZOMBIE_COUNT" -gt 10 ]; then
    echo "WARNING: $ZOMBIE_COUNT zombie connections on port 7497"
    # Kill them
    sudo ss -K state close-wait '( dport = 7497 or sport = 7497 )' 2>/dev/null
    sudo ss -K state fin-wait-2 '( dport = 7497 or sport = 7497 )' 2>/dev/null
fi
```

### Add to Cron (every 5 minutes)
```bash
*/5 * * * * /home/jacobw/quantstack/scripts/check_gateway_connections.sh
```

---

## 7. Summary of Required Actions

| Priority | Action | Status |
|----------|--------|--------|
| 1 | Clean zombie connections | TODO |
| 2 | Restart Gateway if needed | TODO |
| 3 | Test API connection | TODO |
| 4 | Restart failed services | TODO |
| 5 | Add connection cleanup script | TODO |
| 6 | Update services with proper disconnect handling | FUTURE |

---

## References

- [TWS API Connection Documentation](https://interactivebrokers.github.io/tws-api/connection.html)
- [IBKR API Settings Guide](https://ibkrguides.com/traderworkstation/api.htm)
- [IBC Configuration](https://github.com/IbcAlpha/IBC/blob/master/userguide.md)

Content was rephrased for compliance with licensing restrictions.
