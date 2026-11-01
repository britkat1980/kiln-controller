#!/bin/bash
# one-shot kiln-controller install for a freshly imaged raspberry pi.
#
# prepare-sd.ps1 copies this script (and optionally config.py) to
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
apt-get install -y git python3-venv python3-dev

# lgpio only ships wheels for python 3.11/3.12; newer pythons build it
# from source, which needs swig and the lgpio headers
if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 13) else 1)'; then
    apt-get install -y swig liblgpio-dev
fi

if [ -d "$REPO_DIR/.git" ]; then
    sudo -u "$USER_NAME" git -C "$REPO_DIR" pull --ff-only || true
else
    sudo -u "$USER_NAME" git clone "$REPO_URL" "$REPO_DIR"
fi

sudo -u "$USER_NAME" python3 -m venv "$REPO_DIR/venv"
sudo -u "$USER_NAME" "$REPO_DIR/venv/bin/pip" install -e "$REPO_DIR"

# install the user's config, then take it off the boot partition: that
# partition is FAT, readable by anyone holding the card, and config.py
# holds the mqtt password
if [ -n "$SETUP_DIR" ] && [ -f "$SETUP_DIR/config.py" ]; then
    install -o "$USER_NAME" -g "$USER_NAME" -m 600 "$SETUP_DIR/config.py" "$REPO_DIR/config.py"
    rm -f "$SETUP_DIR/config.py"
    echo "installed config.py"
else
    echo "no config.py on the boot partition, using the repo default (simulate = True)"
fi

bash "$REPO_DIR/start-on-boot"
systemctl restart kiln-controller

# run once only
systemctl disable kiln-setup.service || true
touch /var/lib/kiln-setup.done

echo "=== kiln-setup finished $(date) ==="
