#!/bin/bash
# L2 Trading Investigation Script
# Automated checks for Jan 30, 2026 trading anomaly

DATE="2026-01-30"
REPORT="/home/jacobw/quantstack/reports/l2_investigation_${DATE}.txt"

echo "Starting L2 investigation for $DATE..."
echo "Report will be saved to: $REPORT"
echo ""

{
echo "================================================================================"
echo "L2 TRADING SYSTEMS INVESTIGATION - $DATE"
echo "================================================================================"
echo "Generated: $(date)"
echo ""

echo "================================================================================"
echo "1. TRADE VOLUME ANALYSIS"
echo "================================================================================"
echo ""
echo "--- Historical Baseline (Last 10 Days) ---"
psql trading -c "SELECT entry_time::date as date, system, COUNT(*) as trades, ROUND(SUM(net_pnl)::numeric, 2) as total_pnl FROM trades WHERE entry_time >= '2026-01-20' AND system IN ('l2-scalping', 'l2-vwap-reversion') GROUP BY 1,2 ORDER BY 1 DESC, 2;"
echo ""

echo "--- Jan 30 Trade Details ---"
psql trading -c "SELECT system, symbol, TO_CHAR(entry_time, 'HH24:MI:SS') as entry, TO_CHAR(exit_time, 'HH24:MI:SS') as exit, entry_price, exit_price, net_pnl, exit_reason FROM trades WHERE entry_time::date = '$DATE' AND system IN ('l2-scalping', 'l2-vwap-reversion') ORDER BY entry_time;"
echo ""

echo "================================================================================"
echo "2. SERVICE STATUS"
echo "================================================================================"
echo ""
echo "--- Current Status ---"
systemctl status l2-scalping.service --no-pager | head -20
echo ""
systemctl status l2-vwap-reversion.service --no-pager | head -20
echo ""
systemctl status l2-collector.service --no-pager | head -20
echo ""

echo "--- Service Restarts/Failures on $DATE ---"
journalctl -u l2-scalping.service --since "$DATE 09:00" --until "$DATE 17:00" | grep -i "started\|stopped\|failed\|killed" | head -20
journalctl -u l2-vwap-reversion.service --since "$DATE 09:00" --until "$DATE 17:00" | grep -i "started\|stopped\|failed\|killed" | head -20
echo ""

echo "================================================================================"
echo "3. ERROR ANALYSIS"
echo "================================================================================"
echo ""
echo "--- L2 Scalping Errors ---"
journalctl -u l2-scalping.service --since "$DATE" | grep -i "error\|exception\|fail" | head -30
echo ""

echo "--- L2 VWAP Errors ---"
journalctl -u l2-vwap-reversion.service --since "$DATE" | grep -i "error\|exception\|fail" | head -30
echo ""

echo "================================================================================"
echo "4. SIGNAL GENERATION CHECK"
echo "================================================================================"
echo ""
echo "--- L2 Scalping Signal Count ---"
SCALP_SIGNALS=$(journalctl -u l2-scalping.service --since "$DATE 09:30" --until "$DATE 16:00" | grep -i "signal\|opportunity\|candidate" | wc -l)
echo "Signals/Opportunities: $SCALP_SIGNALS"
echo ""

echo "--- L2 VWAP Signal Count ---"
VWAP_SIGNALS=$(journalctl -u l2-vwap-reversion.service --since "$DATE 09:30" --until "$DATE 16:00" | grep -i "signal\|opportunity\|candidate" | wc -l)
echo "Signals/Opportunities: $VWAP_SIGNALS"
echo ""

echo "================================================================================"
echo "5. RISK LIMIT ANALYSIS"
echo "================================================================================"
echo ""
echo "--- Risk Limit Messages ---"
journalctl -u l2-scalping.service --since "$DATE 09:30" --until "$DATE 16:00" | grep -i "risk\|limit\|max.*position\|daily.*loss" | head -20
echo ""

echo "================================================================================"
echo "6. MARKET DATA CHECK"
echo "================================================================================"
echo ""
echo "--- L2 Data Files for $DATE ---"
if [ -d ~/l2_data/date=$DATE ]; then
    ls -lh ~/l2_data/date=$DATE/ | head -20
    echo ""
    echo "Total size:"
    du -sh ~/l2_data/date=$DATE/
else
    echo "ERROR: No L2 data directory found for $DATE"
fi
echo ""

echo "--- L2 Collector Logs ---"
journalctl -u l2-collector.service --since "$DATE 09:30" --until "$DATE 10:00" | grep -i "collected\|snapshot\|symbol" | head -20
echo ""

echo "================================================================================"
echo "7. CONNECTIVITY CHECK"
echo "================================================================================"
echo ""
echo "--- IBKR Disconnections ---"
grep -i "disconnect\|connection lost\|not connected" /home/jacobw/api-exported-logs.txt 2>/dev/null | grep "$DATE" | head -10
echo ""

echo "--- API Errors ---"
grep -i "error\|failed\|rejected" /home/jacobw/api-exported-logs.txt 2>/dev/null | grep "$DATE" | grep -i "L2_SCALP\|L2_VWAP" | head -20
echo ""

echo "================================================================================"
echo "8. CONFIGURATION CHECK"
echo "================================================================================"
echo ""
echo "--- Service File Modification Times ---"
stat /etc/systemd/system/l2-scalping.service 2>/dev/null | grep Modify
stat /etc/systemd/system/l2-vwap-reversion.service 2>/dev/null | grep Modify
echo ""

echo "--- Config File Modification Times ---"
if [ -d ~/l2_scalping/config ]; then
    ls -l ~/l2_scalping/config/ 2>/dev/null | grep -v "^total"
fi
if [ -d ~/l2_vwap_reversion/config ]; then
    ls -l ~/l2_vwap_reversion/config/ 2>/dev/null | grep -v "^total"
fi
echo ""

echo "================================================================================"
echo "9. FIRST 50 LOG LINES (L2 Scalping)"
echo "================================================================================"
echo ""
journalctl -u l2-scalping.service --since "$DATE 09:30" --until "$DATE 10:00" | head -50
echo ""

echo "================================================================================"
echo "10. FIRST 50 LOG LINES (L2 VWAP)"
echo "================================================================================"
echo ""
journalctl -u l2-vwap-reversion.service --since "$DATE 09:30" --until "$DATE 10:00" | head -50
echo ""

echo "================================================================================"
echo "INVESTIGATION COMPLETE"
echo "================================================================================"
echo ""
echo "Summary:"
echo "- L2 Scalping trades: $(psql trading -t -c "SELECT COUNT(*) FROM trades WHERE entry_time::date = '$DATE' AND system = 'l2-scalping';")"
echo "- L2 VWAP trades: $(psql trading -t -c "SELECT COUNT(*) FROM trades WHERE entry_time::date = '$DATE' AND system = 'l2-vwap-reversion';")"
echo "- L2 Scalping signals: $SCALP_SIGNALS"
echo "- L2 VWAP signals: $VWAP_SIGNALS"
echo ""

} > "$REPORT" 2>&1

echo ""
echo "Investigation complete!"
echo "Report saved to: $REPORT"
echo ""
echo "Quick summary:"
grep -A 5 "Summary:" "$REPORT"
