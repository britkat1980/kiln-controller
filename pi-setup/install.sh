#!/bin/bash
# one-shot kiln-controller install for a freshly imaged raspberry pi.
#
# prepare-sd.ps1 copies this script (and optionally config_local.py) to
# <boot partition>/kiln-setup/ and hooks it into imager's firstrun.sh,
# which installs kiln-setup.service to run it once the network is up.
# it can also be run by hand: sudo bash install.sh
#
# progress is logged to /var/log/kiln-setup.log

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/britkat1980/kiln-controller}"
LOG=/var/log/kiln-setup.log
exec > >(tee -a "$LOG") 2>&1

echo "=== kiln-setup started $(date) ==="

# the boot partition is /boot/firmware on bookworm, /boot before that
SETUP_DIR=""
for d in /boot/firmware/kiln-setup /boot/kiln-setup; do
    [ -d "$d" ] && SETUP_DIR="$d" && break
done

# the imager-created user (uid 1000), not root, owns the checkout
USER_NAME="$(getent passwd 1000 | cut -d: -f1)"
USER_HOME="$(getent passwd 1000 | cut -d: -f6)"
if [ -z "$USER_NAME" ]; then
    echo "no uid 1000 user found, aborting"
    exit 1
fi
REPO_DIR="$USER_HOME/kiln-controller"
echo "installing for $USER_NAME into $REPO_DIR"

# wait for the network (wifi can take a while on first boot)
for i in $(seq 1 60); do
    if getent hosts github.com >/dev/null; then
        break
    fi
    echo "waiting for network ($i)..."
    sleep 5
done

export DEBIAN_FRONTEND=noninteractive
apt-get update
# lgpio has no wheel for every python/arch combination (32-bit os,
# python 3.13+); pip then builds it from source, which needs swig and
# the lgpio headers
apt-get install -y git python3-venv python3-dev swig liblgpio-dev

if [ -d "$REPO_DIR/.git" ]; then
    sudo -u "$USER_NAME" git -C "$REPO_DIR" pull --ff-only || true
else
    sudo -u "$USER_NAME" git clone "$REPO_URL" "$REPO_DIR"
fi

sudo -u "$USER_NAME" python3 -m venv "$REPO_DIR/venv"
sudo -u "$USER_NAME" "$REPO_DIR/venv/bin/pip" install -e "$REPO_DIR"

# install the user's settings as config_local.py (read after the tracked
# config.py, see its end), then take them off the boot partition: that
# partition is FAT, readable by anyone holding the card, and the file
# holds the mqtt password. a full config.py from before config_local.py
# existed works as config_local.py too: it simply sets every value.
installed=""
for f in config_local.py config.py; do
    if [ -n "$SETUP_DIR" ] && [ -f "$SETUP_DIR/$f" ]; then
        if [ -z "$installed" ]; then
            install -o "$USER_NAME" -g "$USER_NAME" -m 600 "$SETUP_DIR/$f" "$REPO_DIR/config_local.py"
            installed="$f"
            echo "installed $f as config_local.py"
        fi
        rm -f "$SETUP_DIR/$f"
    fi
done
if [ -z "$installed" ]; then
    echo "no config_local.py on the boot partition, using the repo defaults (simulate = True)"
fi

bash "$REPO_DIR/start-on-boot"
systemctl restart kiln-controller

# run once only
systemctl disable kiln-setup.service || true
touch /var/lib/kiln-setup.done

echo "=== kiln-setup finished $(date) ==="
