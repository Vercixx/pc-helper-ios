#!/usr/bin/env bash
# Enable Wake-on-LAN so the machine can actually be woken. Needs root.
#
# Three things must all be true, and only the first is under this script's
# control:
#   1. the NIC has magic-packet wake armed          <- this script
#   2. the kernel is allowed to wake on that device <- this script
#   3. the firmware permits it                      <- your BIOS/UEFI setup
#
# Ethernet (r8169 and friends) is reliable. Wake-on-WLAN depends heavily on the
# driver; the script reports what your chip claims to support and arms it, but
# whether it wakes from S3 can only be settled by testing.
set -euo pipefail

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root: sudo $0"

UDEV_RULE=/etc/udev/rules.d/70-wol-unlock.rules
: >"$UDEV_RULE.tmp"

bold "Wired interfaces"
found_wired=0
for path in /sys/class/net/*; do
    iface="$(basename "$path")"
    [[ "$iface" == "lo" ]] && continue
    [[ -e "$path/device" ]] || continue
    [[ -d "$path/wireless" || -e "$path/phy80211" ]] && continue
    found_wired=1

    mac="$(cat "$path/address")"
    if ! command -v ethtool >/dev/null; then
        warn "ethtool is not installed; cannot arm $iface (pacman -S ethtool)"
        continue
    fi

    supported="$(ethtool "$iface" 2>/dev/null | awk '/Supports Wake-on/{print $3}')"
    current="$(ethtool "$iface" 2>/dev/null | awk '/Wake-on:/{print $2}')"
    echo "  $iface ($mac): supports=${supported:-?} current=${current:-?}"

    if [[ "$supported" != *g* ]]; then
        warn "  $iface does not support magic-packet wake"
        continue
    fi

    ethtool -s "$iface" wol g && ok "  armed $iface for magic packet"
    # ethtool settings do not survive a reboot or a driver reload.
    echo "ACTION==\"add\", SUBSYSTEM==\"net\", NAME==\"$iface\", RUN+=\"/usr/bin/ethtool -s $iface wol g\"" >>"$UDEV_RULE.tmp"

    if [[ -w "$path/device/power/wakeup" ]]; then
        echo enabled >"$path/device/power/wakeup" && ok "  PCI wakeup enabled for $iface"
    fi
done
[[ $found_wired -eq 1 ]] || warn "no wired interfaces found"

echo
bold "Wireless interfaces"
for path in /sys/class/net/*; do
    iface="$(basename "$path")"
    [[ -d "$path/wireless" || -e "$path/phy80211" ]] || continue
    mac="$(cat "$path/address")"
    echo "  $iface ($mac)"

    if ! command -v iw >/dev/null; then
        warn "  iw is not installed (pacman -S iw)"
        continue
    fi
    phy="$(basename "$(readlink -f "$path/phy80211")" 2>/dev/null || echo phy0)"
    if iw phy "$phy" info 2>/dev/null | grep -q "wake up on magic packet"; then
        ok "  $phy advertises magic-packet WoWLAN"
        if iw phy "$phy" wowlan enable magic-packet 2>/dev/null; then
            ok "  armed $phy"
        else
            warn "  the driver refused to arm WoWLAN"
        fi
    else
        warn "  $phy does not advertise magic-packet WoWLAN"
    fi
    [[ -w "$path/device/power/wakeup" ]] && echo enabled >"$path/device/power/wakeup" || true
done

if [[ -s "$UDEV_RULE.tmp" ]]; then
    mv "$UDEV_RULE.tmp" "$UDEV_RULE"
    udevadm control --reload-rules
    ok "wrote $UDEV_RULE so the setting survives reboots"
else
    rm -f "$UDEV_RULE.tmp"
fi

cat <<'EOF'

Remaining manual step
---------------------
Enable Wake-on-LAN in your BIOS/UEFI. It is usually under Power Management and
called "Wake on LAN", "Power On by PCI-E", or "Resume by PCI-E Device". Without
it, the NIC is armed but the board will ignore the packet.

Testing it
----------
  1. From another machine on the LAN:  tcpdump -i any -n udp port 9
  2. systemctl suspend
  3. Tap "Wake up" in the app, or:  wakeonlan <MAC>

If the packet is visible on the wire but the machine stays asleep, the problem
is step 2 or 3 above (firmware or driver), not this service.
EOF
