#!/bin/bash
# Restart Pokemon Showdown server and clear all battles

echo "Stopping Pokemon Showdown server..."
pkill -f "node pokemon-showdown" || echo "Server not running"

# Wait a moment for clean shutdown
sleep 2

echo "Starting Pokemon Showdown server..."
cd "$(dirname "$0")/../pokemon-showdown" || exit 1
node pokemon-showdown start --no-security &

echo "Server restarted! All battles cleared."
echo "Server PID: $!"
