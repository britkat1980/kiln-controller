<#
.SYNOPSIS
  Make a freshly imaged Raspberry Pi OS SD card install kiln-controller on first boot.

.DESCRIPTION
  Run after Raspberry Pi Imager has written the card WITH custom settings
  (hostname, user, wifi, ssh). Imager puts a one-time firstrun.sh on the boot
  partition; this script adds a few lines to it that install a systemd service,
  which runs pi-setup/install.sh once the network is up on the next boot.

  Copies install.sh and (optionally) your config.py to <boot>\kiln-setup\.
  install.sh moves config.py into place and deletes it from the card.

.EXAMPLE
  .\prepare-sd.ps1
  .\prepare-sd.ps1 -BootDrive E: -ConfigPath C:\path\to\config.py
#>
param(
    [string]$BootDrive,
    [string]$ConfigPath = (Join-Path $PSScriptRoot '..\..\config-v2-for-pi.py')
)

$ErrorActionPreference = 'Stop'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$marker = '# --- kiln-controller auto install'

function Write-LfFile($path, $text) {
    [IO.File]::WriteAllText($path, ($text -replace "`r`n", "`n"), $utf8NoBom)
}

if (-not $BootDrive) {
    $vol = Get-Volume | Where-Object { $_.FileSystemLabel -eq 'bootfs' -and $_.DriveLetter }
    if (@($vol).Count -ne 1) {
        throw "Could not find exactly one drive labelled 'bootfs'. Pass -BootDrive E: (the SD card's boot partition)."
    }
    $BootDrive = "$($vol.DriveLetter):"
}
$boot = $BootDrive.TrimEnd('\') + '\'
$firstrun = Join-Path $boot 'firstrun.sh'

if (-not (Test-Path (Join-Path $boot 'cmdline.txt'))) {
    throw "$boot does not look like a Raspberry Pi boot partition (no cmdline.txt)."
}
# copy the installer and config
$setupDir = Join-Path $boot 'kiln-setup'
New-Item -ItemType Directory -Force $setupDir | Out-Null
Write-LfFile (Join-Path $setupDir 'install.sh') ([IO.File]::ReadAllText((Join-Path $PSScriptRoot 'install.sh')))
Write-Host "Copied install.sh"

if ($ConfigPath -and (Test-Path $ConfigPath)) {
    Write-LfFile (Join-Path $setupDir 'config.py') ([IO.File]::ReadAllText((Resolve-Path $ConfigPath)))
    Write-Host "Copied config: $(Resolve-Path $ConfigPath)"
} else {
    Write-Warning "No config found at '$ConfigPath'. The Pi will use the repo default config (simulate = True)."
}

# hook into firstrun.sh
if (-not (Test-Path $firstrun)) {
    Write-Warning ("No firstrun.sh on $boot, so the install will NOT start by itself. " +
        "Either re-image with Raspberry Pi OS (Legacy, 64-bit) Lite using Imager's 'Edit settings', " +
        "or after first boot run: sudo bash /boot/firmware/kiln-setup/install.sh")
    exit 1
}
$script = [IO.File]::ReadAllText($firstrun) -replace "`r`n", "`n"
if ($script.Contains($marker)) {
    Write-Host "firstrun.sh already hooked, leaving it alone"
} else {
    $hook = @'
# --- kiln-controller auto install (added by prepare-sd.ps1) ---
cat > /etc/systemd/system/kiln-setup.service <<'KILNEOF'
[Unit]
Description=kiln-controller first boot install
Wants=network-online.target
After=network-online.target
ConditionPathExists=!/var/lib/kiln-setup.done

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'for d in /boot/firmware/kiln-setup /boot/kiln-setup; do [ -f "$$d/install.sh" ] && exec /bin/bash "$$d/install.sh"; done; echo "kiln-setup: install.sh not found"; exit 1'
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
KILNEOF
mkdir -p /etc/systemd/system/multi-user.target.wants
ln -sf /etc/systemd/system/kiln-setup.service /etc/systemd/system/multi-user.target.wants/kiln-setup.service
# --- end kiln-controller auto install ---

'@ -replace "`r`n", "`n"

    # firstrun.sh deletes itself at the end; add the hook just before that
    $lines = $script -split "`n"
    $at = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*rm -f .*firstrun\.sh') { $at = $i; break }
    }
    if ($at -lt 0) {
        for ($i = $lines.Count - 1; $i -ge 0; $i--) {
            if ($lines[$i] -match '^\s*exit 0') { $at = $i; break }
        }
    }
    if ($at -lt 0) { throw "Could not find where to hook into firstrun.sh; it has an unexpected layout." }

    Copy-Item $firstrun "$firstrun.orig" -Force
    $before = ($lines[0..($at - 1)] -join "`n") + "`n"
    $after = $lines[$at..($lines.Count - 1)] -join "`n"
    Write-LfFile $firstrun ($before + $hook + $after)
    Write-Host "Hooked kiln-setup into firstrun.sh (original saved as firstrun.sh.orig)"
}

Write-Host ""
Write-Host "Done. Eject the card, boot the Pi, and give it 10-20 minutes."
Write-Host "Progress: ssh in and run  tail -f /var/log/kiln-setup.log"
