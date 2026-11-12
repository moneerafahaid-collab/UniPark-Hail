#!/bin/bash
cd /workspaces/UniPark-Hail
python3 -m pip install -q -r requirements.txt
if ! curl -sf -o /dev/null --max-time 3 http://127.0.0.1:5050/login; then
  setsid python3 app.py > /tmp/unipark.log 2>&1 < /dev/null &
fi
