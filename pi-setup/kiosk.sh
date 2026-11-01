#!/bin/bash
# show the kiln-controller web page full screen on the pi's display.
#
# needs raspberry pi os with desktop (labwc, the default since bookworm)
# and desktop autologin (raspi-config > system > boot / auto login).
# run as the desktop user, not root:
#     bash pi-setup/kiosk.sh [url]
# undo with: bash pi-setup/kiosk.sh --remove
#
# the panel and desktop icons are not started, so the browser is all
# that shows. ssh in to get at the pi.

set -euo pipefail

AUTOSTART="$HOME/.config/labwc/autostart"
LAUNCHER="$HOME/.local/bin/kiln-kiosk"

if [ "${1:-}" = "--remove" ]; then
    rm -f "$AUTOSTART" "$LAUNCHER"
    echo "kiosk removed, the normal desktop starts after a reboot"
    exit 0
fi

# default to the port in config.py
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="$(sed -n 's/^listening_port *= *\([0-9]*\).*/\1/p' "$REPO_DIR/config.py" 2>/dev/null || true)"
URL="${1:-http://localhost:${PORT:-8081}/}"

if ! command -v chromium >/dev/null; then
    sudo apt-get install -y chromium
fi

mkdir -p "$(dirname "$AUTOSTART")" "$(dirname "$LAUNCHER")"

cat > "$LAUNCHER" <<EOF
#!/bin/sh
# wait for the controller, then show it full screen
until curl -sf -o /dev/null "$URL"; do sleep 2; done
exec >"\$HOME/.cache/kiln-kiosk.log" 2>&1
# --disable-gpu: the pi 3's gpu has no gles 3, and chromium spends
# cpu and memory retrying it. the page renders fine in software
exec chromium --kiosk --incognito --noerrdialogs --disable-infobars \\
    --no-first-run --password-store=basic \\
    --disable-session-crashed-bubble --disable-features=Translate \\
    --check-for-update-interval=31536000 \\
    --ozone-platform=wayland --touch-events=enabled \\
    --disable-gpu --renderer-process-limit=1 \\
    "$URL"
EOF
chmod +x "$LAUNCHER"

# replaces /etc/xdg/labwc/autostart: no panel or desktop, just the
# display layout and the browser (restarted by lwrespawn if it exits)
cat > "$AUTOSTART" <<EOF
/usr/bin/kanshi &
/usr/bin/lwrespawn $LAUNCHER &
EOF

echo "kiosk set up for $URL, reboot to start it"
