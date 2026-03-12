#!/usr/bin/env bash
# Wrapper that auto-restarts dashboard on reload (exit code 42).
# Reload trigger: touch .reload  (dashboard checks every 1s)
cd "$(dirname "$0")"
rm -f .reload

while true; do
    .venv/bin/python dashboard.py
    rc=$?
    if [ "$rc" -eq 42 ]; then
        sleep 0.3
        continue
    fi
    break
done
