# Automatic install on a new SD card

Makes a freshly imaged card install kiln-controller by itself on first boot.

1. In Raspberry Pi Imager, choose **Raspberry Pi OS (Legacy, 64-bit) Lite**
   (Bookworm, Python 3.11). In **Edit settings**, set the hostname, user,
   wifi and ssh, then write the card.
2. Leave the card in the PC. Imager may eject it; if so, re-insert it so the
   `bootfs` drive appears.
3. In PowerShell, from this folder:

   ```powershell
   .\prepare-sd.ps1                       # finds the bootfs drive and ..\..\config-v2-for-pi.py
   .\prepare-sd.ps1 -BootDrive E: -ConfigPath C:\path\to\config.py
   ```

   If PowerShell blocks the script, run
   `powershell -ExecutionPolicy Bypass -File .\prepare-sd.ps1` instead.

4. Eject the card and boot the Pi. Imager's first-run script reboots once.
   The install then runs (10-20 minutes on slower Pis): packages, a clone of
   the repo into `~/kiln-controller`, the venv, your `config.py`, and the
   `kiln-controller` service, which it starts.

Follow the progress with `ssh <user>@<pi> tail -f /var/log/kiln-setup.log`.
The install runs once. To re-run it, `sudo rm /var/lib/kiln-setup.done`
and `sudo bash /boot/firmware/kiln-setup/install.sh`.

`config.py` is deleted from the boot partition once installed, because
that partition can be read by anyone holding the card and the file holds
the MQTT password.

Imager on Raspberry Pi OS Trixie (and later) configures the card with
cloud-init instead of `firstrun.sh`. On those images `prepare-sd.ps1` still
copies the files but cannot hook the first boot, and warns you. After the
first boot, run `sudo bash /boot/firmware/kiln-setup/install.sh` over ssh.

## Touchscreen kiosk

To show the controller full screen on a display attached to the Pi (for
example the official 7" touchscreen), use the Raspberry Pi OS image *with
desktop*, with desktop autologin on, and run as the desktop user:

```bash
bash ~/kiln-controller/pi-setup/kiosk.sh
```

then reboot. Chromium opens the controller page once the service answers,
and is restarted if it exits. Its output goes to `~/.cache/kiln-kiosk.log`.
On a Pi 3 it takes a minute or two to appear after boot. Undo with
`bash ~/kiln-controller/pi-setup/kiosk.sh --remove`.
