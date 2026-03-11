#!/bin/bash
set -e

echo "Running database migrations..."
cd /app

# Retry migrations — Fly Postgres can be slow after deploy
for attempt in $(seq 1 10); do
  if python3 -m alembic upgrade head; then
    echo "Migrations complete."
    break
  fi
  if [ "$attempt" -eq 10 ]; then
    echo "Migrations failed after 10 attempts"
    exit 1
  fi
  wait=$((attempt < 10 ? attempt * 2 : 10))
  echo "DB not ready, retrying in ${wait}s (attempt ${attempt}/10)"
  sleep "$wait"
done

echo "Starting services..."
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
