# IBKR Gateway Programmatic Startup Methods

## Overview

Multiple methods exist for programmatically starting the IBKR Gateway without Docker interference. This document covers all available options with implementation details.

## 1. IBC (Interactive Brokers Controller) - Recommended

**Primary non-Docker solution** for programmatic Gateway control.

### Installation
```bash
# Download latest IBC release
wget https://github.com/IbcAlpha/IBC/releases/download/latest/IBC-linux.zip
unzip IBC-linux.zip -d ./ibc
chmod +x ./ibc/*.sh ./ibc/*/*.sh
```

### Configuration
Create `IBController.ini`:
```ini
LogToConsole=no
IbLoginId=<USERNAME>
IbPassword=<PASSWORD>
PasswordEncrypted=no
TradingMode=paper
AcceptIncomingConnectionAction=accept
AllowBlindTrading=yes
IbControllerPort=7462
```

### Command Line Start
```bash
# Set display for headless operation
export DISPLAY=:1
Xvfb :1 -ac -screen 0 1024x768x24 &

# Start Gateway via IBC
./ibc/IBControllerGatewayStart.sh
```

### Systemd Integration
```bash
# Add to existing service
ExecStart=/home/jacobw/quantstack/scripts/start_ibkr_gateway.sh
```

Where script contains:
```bash
#!/bin/bash
export DISPLAY=:1
cd /path/to/ibc
./IBControllerGatewayStart.sh
```

## 2. Client Portal Gateway (REST API)

**Web-based gateway** with REST interface - no GUI dependencies.

### Installation
```bash
wget https://download2.interactivebrokers.com/portal/clientportal.gw.zip
unzip clientportal.gw.zip
cd clientportal.gw
```

### Start
```bash
./bin/run.sh root/conf.yaml
```

**Advantages:**
- No X11/display requirements
- REST API interface
- Simpler authentication

## 3. Native Gateway Installation

**Direct installation method** using official installer.

### Install
```bash
wget https://download2.interactivebrokers.com/installers/ibgateway/latest-standalone/ibgateway-latest-standalone-linux-x64.sh
chmod +x ibgateway-latest-standalone-linux-x64.sh
./ibgateway-latest-standalone-linux-x64.sh -c
```

### Manual Start
```bash
cd ~/Jts
DISPLAY=:1 java -cp jts.jar:total.jar -Xmx768M jclient.LoginFrame ~/Jts
```

## Current Implementation

The production system uses systemd service with automatic restart capability:
- Service: `ibkr-gateway.service`
- Script: `/home/jacobw/quantstack/scripts/start_ibkr_gateway.sh`
- Integration: Works with existing trading orchestrator

## Dependencies

Required packages for headless operation:
```bash
sudo apt install xvfb x11vnc unzip
```

## Recommendation

**Use IBC** for production because:
- No Docker conflicts with SSH/services
- Proven reliability
- Integrates with existing systemd setup
- Handles authentication automatically
- Active community support

## References

- [IBC GitHub Repository](https://github.com/IbcAlpha/IBC)
- [Headless Installation Guide](https://github.com/roblav96/headless-ib-gateway-installation-ubuntu-server)
- [IBKR Client Portal API](https://easyib.readthedocs.io/en/latest/)
