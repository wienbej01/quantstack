#!/bin/bash
# Setup daily SIP selection cron job (runs at 6:00 AM ET)

echo "Setting up daily SIP selection cron job..."

# Create cron job entry
CRON_JOB="0 6 * * 1-5 cd /home/jacobw/quantstack && source ~/.bashrc && python3 scripts/daily_sip_scheduler.py >> logs/daily_sip_cron.log 2>&1"

# Add to crontab
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

echo "✅ Cron job added:"
echo "   - Runs Monday-Friday at 6:00 AM ET"
echo "   - Selects daily SIP universe (40 symbols)"
echo "   - Identifies L2 symbols (top 6 NYSE)"
echo "   - Logs to logs/daily_sip_cron.log"
echo ""
echo "To view current cron jobs: crontab -l"
echo "To remove cron job: crontab -e"
