#!/bin/bash
# Install passwordless sudo rules for IBKR gateway/service control.

set -euo pipefail

TARGET="/etc/sudoers.d/ibkr-gateway"

cat > "$TARGET" <<'EOF'
jacobw ALL=(root) NOPASSWD: /bin/systemctl start ibkr-gateway.service, /bin/systemctl stop ibkr-gateway.service, /bin/systemctl restart ibkr-gateway.service, /bin/systemctl status ibkr-gateway.service, /bin/systemctl start ibkr-gateway-ready.service, /bin/systemctl stop ibkr-gateway-ready.service, /bin/systemctl restart ibkr-gateway-ready.service, /bin/systemctl status ibkr-gateway-ready.service, /bin/systemctl start l2-scalping.service, /bin/systemctl stop l2-scalping.service, /bin/systemctl restart l2-scalping.service, /bin/systemctl status l2-scalping.service, /bin/systemctl start l2-collector.service, /bin/systemctl stop l2-collector.service, /bin/systemctl restart l2-collector.service, /bin/systemctl status l2-collector.service, /bin/systemctl start intraday-paper.service, /bin/systemctl stop intraday-paper.service, /bin/systemctl restart intraday-paper.service, /bin/systemctl status intraday-paper.service, /usr/bin/install, /usr/bin/tee, /bin/mkdir, /bin/systemctl daemon-reload, /bin/systemctl enable ibkr-gateway.service, /bin/systemctl enable ibkr-gateway-ready.service
EOF

chmod 440 "$TARGET"
visudo -cf "$TARGET"
echo "Installed sudoers entry at $TARGET"
