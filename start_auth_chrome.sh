#!/bin/bash
# Launch Chrome with remote debugging so Browser-Use can connect to it.
# You log into your marketplaces in this Chrome window, then agents use your sessions.
echo ""
echo "=== Launching Chrome with Remote Debugging ==="
echo "1. Chrome will open with a fresh window"
echo "2. Log into: eBay, Facebook, Mercari, Depop"
echo "3. Come back here and tell Claude you're ready"
echo ""
echo "Port: 9222"
echo ""

/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --user-data-dir="$HOME/Library/Application Support/Google/Chrome" \
    --profile-directory="Default" \
    2>/dev/null &

echo "Chrome launched (PID: $!)"
echo "Waiting for debugging port..."
sleep 3

# Verify the port is active
if curl -s http://localhost:9222/json/version > /dev/null 2>&1; then
    echo "✅ Remote debugging active on port 9222"
else
    echo "⚠️  Port not ready yet — give Chrome a few more seconds to start"
fi
