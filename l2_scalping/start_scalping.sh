#!/bin/bash
# L2 Scalping System Launcher
cd /home/jacobw/quantstack/l2_scalping
export TZ="America/New_York"
exec /usr/bin/python3 -u src/main.py --config config
