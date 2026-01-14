#!/bin/bash
# L2 Scalping System Launcher
cd /home/jacobw/quantstack/l2_scalping

export TZ="America/New_York"
export PATH="/home/jacobw/quantstack/.venv/bin:$PATH"
export PYTHONPATH="/home/jacobw/quantstack:/home/jacobw/quantstack/l2_scalping/src"

exec /home/jacobw/quantstack/.venv/bin/python -u src/main.py --config config
