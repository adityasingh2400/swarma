#!/bin/bash
# Launch Chrome with remote debugging so Playwright / agents can connect (CDP).
#
# Why a separate user-data-dir: if normal Chrome is already open, launching Chrome
# again with the *same* profile only opens a window in the existing process, which
# was NOT started with --remote-debugging-port — so port 9222 never opens ("Opening
# in existing browser session"). A dedicated profile starts a second Chrome instance
# with debugging enabled. Log into marketplaces once in this window; cookies are
# separate from your everyday Chrome profile.
#
# Optional: use a profile from your real Chrome data (Personal, Work, etc.). You must
# quit Chrome completely first (Cmd+Q), or the debug port will not open.
#   SWARMA_USE_DEFAULT_CHROME_PROFILE=1 bash start_auth_chrome.sh
#
# "Personal" is not always the folder name Default — Chrome uses Default, Profile 1,
# Profile 2, ... Open chrome://version in that profile and check "Profile Path"; the
# last path segment is what you pass below (e.g. Profile 1).
#   SWARMA_USE_DEFAULT_CHROME_PROFILE=1 SWARMA_CHROME_PROFILE_DIRECTORY="Profile 1" bash start_auth_chrome.sh

set -euo pipefail

PORT="${SWARMA_CHROME_DEBUG_PORT:-9222}"
# Only used with SWARMA_USE_DEFAULT_CHROME_PROFILE=1 (real Chrome user data).
PROFILE_DIR="${SWARMA_CHROME_PROFILE_DIRECTORY:-Default}"

if [[ "${SWARMA_USE_DEFAULT_CHROME_PROFILE:-}" == "1" ]]; then
  if pgrep -x "Google Chrome" >/dev/null 2>&1; then
    echo ""
    echo "❌ Google Chrome is already running."
    echo "   With your real Chrome profiles (Personal, etc.), remote debugging only"
    echo "   works if THIS script starts Chrome. Quit Chrome completely (Cmd+Q), then run:"
    echo "   SWARMA_USE_DEFAULT_CHROME_PROFILE=1 bash start_auth_chrome.sh"
    echo "   Add SWARMA_CHROME_PROFILE_DIRECTORY=\"Profile 1\" if Personal is not Default."
    echo ""
    exit 1
  fi
  USER_DATA_DIR="${HOME}/Library/Application Support/Google/Chrome"
else
  USER_DATA_DIR="${SWARMA_CHROME_USER_DATA_DIR:-${HOME}/.swarma/chrome-cdp}"
  mkdir -p "$USER_DATA_DIR"
fi

echo ""
echo "=== Launching Chrome with Remote Debugging ==="
if [[ "${SWARMA_USE_DEFAULT_CHROME_PROFILE:-}" == "1" ]]; then
  echo "Profile: your real Chrome data — folder \"${PROFILE_DIR}\" (same logins as that profile)"
else
  echo "Profile: ${USER_DATA_DIR}"
  echo "(Separate from daily Chrome — log into eBay, Facebook, etc. in this window if needed.)"
fi
echo "1. A Chrome window will open for Swarma / cookie export"
echo "2. Log into: eBay, Facebook, Mercari, Depop (in that window)"
echo "3. Run: source .venv/bin/activate && python3 scripts/save_auth.py"
echo ""
echo "Port: ${PORT}"
echo ""

# -n = new app instance even if Chrome is already running (macOS)
# (Two branches: macOS bash 3.2 + set -u errors on "${empty_array[@]}".)
if [[ "${SWARMA_USE_DEFAULT_CHROME_PROFILE:-}" == "1" ]]; then
  open -na "Google Chrome" --args \
    --remote-debugging-port="${PORT}" \
    --user-data-dir="${USER_DATA_DIR}" \
    --profile-directory="${PROFILE_DIR}" \
    --no-first-run \
    --no-default-browser-check
else
  open -na "Google Chrome" --args \
    --remote-debugging-port="${PORT}" \
    --user-data-dir="${USER_DATA_DIR}" \
    --no-first-run \
    --no-default-browser-check
fi

echo "Chrome launch requested."
echo "Waiting for debugging port..."
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sS "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
    echo "✅ Remote debugging active on http://127.0.0.1:${PORT}"
    exit 0
  fi
  sleep 1
done

echo "⚠️  Port ${PORT} not responding after ~10s."
echo "   Check that Google Chrome is installed, or try a free port:"
echo "   SWARMA_CHROME_DEBUG_PORT=9223 bash start_auth_chrome.sh"
echo "   (and point your tooling at that port if applicable)"
exit 1
