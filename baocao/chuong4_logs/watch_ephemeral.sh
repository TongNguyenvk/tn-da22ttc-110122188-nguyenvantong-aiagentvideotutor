#!/bin/bash
SEEN=""
END=$(($(date +%s) + 480))
while [ $(date +%s) -lt $END ]; do
  for cname in $(docker ps --format '{{.Names}}' | grep -E '^(web-worker|presentation-worker|presentation-gg-worker|office-worker|os-worker)' || true); do
    if ! grep -q "^$cname$" /tmp/seen_workers.txt 2>/dev/null; then
      echo "$cname" >> /tmp/seen_workers.txt
      echo "[$(date '+%H:%M:%S')] DETECTED ephemeral worker: $cname"
      (docker logs -f "$cname" 2>&1 > "worker_${cname}.log") &
      echo "[$(date '+%H:%M:%S')] tailing -> worker_${cname}.log"
    fi
  done
  sleep 1.5
done
