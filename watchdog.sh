#!/bin/sh
# Watchdog for the arxiv-grader web service (see docs/runs/2026-08-26.md).
# If /health fails: capture py-spy stack dump of the gunicorn worker, then restart.
curl -sf -m 5 http://127.0.0.1:5000/health > /dev/null && exit 0
date >> /var/log/arxiv-grader/watchdog.log
/opt/arxiv-grader/venv/bin/py-spy dump --pid "$(pgrep -f gunicorn | tail -1)" >> /var/log/arxiv-grader/watchdog.log 2>&1
systemctl restart arxiv-grader
echo "restarted arxiv-grader" >> /var/log/arxiv-grader/watchdog.log
