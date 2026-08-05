#!/usr/bin/env bash
# Install wol-unlock as a systemd --user service.
#
# Runs entirely unprivileged. The only steps that want root are the firewall
# rules and Wake-on-LAN enablement, and both are optional and prompted for
# separately -- see scripts/enable-wol.sh.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/wol-unlock"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/wol-unlock"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
VENV="$DATA_DIR/venv"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] && die "do not run this as root; it installs a --user service"

bold "wol-unlock installer"
echo

# --- 1. Preconditions -------------------------------------------------------
command -v systemctl >/dev/null || die "systemd is required"
command -v loginctl  >/dev/null || die "loginctl is required"

if ! loginctl list-sessions --no-legend 2>/dev/null | awk '{print $2}' | grep -qx "$(id -u)"; then
    warn "no logind session found for uid $(id -u); unlock will not work until you log in graphically"
fi

DESKTOP="${XDG_CURRENT_DESKTOP:-unknown}"
case "$DESKTOP" in
    *KDE*|*GNOME*|*Cinnamon*|*MATE*) ok "desktop $DESKTOP honours logind's Unlock signal" ;;
    *) warn "desktop '$DESKTOP' is untested. Lockers that ignore logind (bare swaylock, i3lock) cannot be unlocked remotely." ;;
esac

# --- 2. Virtualenv ----------------------------------------------------------
mkdir -p "$DATA_DIR"
chmod 700 "$DATA_DIR"

if command -v uv >/dev/null; then
    bold "Creating virtualenv with uv"
    uv venv --quiet "$VENV"
    VENV_PY="$VENV/bin/python"
    uv pip install --quiet --python "$VENV_PY" "$REPO_DIR"
else
    bold "Creating virtualenv with python -m venv"
    python3 -m venv "$VENV"
    VENV_PY="$VENV/bin/python"
    "$VENV_PY" -m pip install --quiet --upgrade pip
    "$VENV_PY" -m pip install --quiet "$REPO_DIR"
fi
ok "installed into $VENV"

# --- 3. Configuration -------------------------------------------------------
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
if [[ -f "$CONFIG_DIR/config.toml" ]]; then
    ok "keeping existing $CONFIG_DIR/config.toml"
else
    "$VENV/bin/wol-unlock" --write-default-config >/dev/null
    ok "wrote $CONFIG_DIR/config.toml (detected this machine's interfaces)"
fi
"$VENV/bin/wol-unlock" --check || die "configuration did not validate"

# Keep the protocol spec next to the install for the unit's Documentation= line.
[[ -f "$REPO_DIR/../docs/PROTOCOL.md" ]] && cp "$REPO_DIR/../docs/PROTOCOL.md" "$DATA_DIR/" 2>/dev/null || true

# --- 4. systemd unit --------------------------------------------------------
mkdir -p "$UNIT_DIR"
install -m 644 "$REPO_DIR/systemd/wol-unlock.service" "$UNIT_DIR/wol-unlock.service"
systemctl --user daemon-reload
systemctl --user enable --now wol-unlock.service
sleep 1

if systemctl --user is-active --quiet wol-unlock.service; then
    ok "service is running"
else
    warn "service did not start; recent log:"
    journalctl --user -u wol-unlock.service -n 20 --no-pager || true
    exit 1
fi

# --- 5. Firewall ------------------------------------------------------------
PORT="$(awk -F'= *' '/^port *=/{print $2; exit}' "$CONFIG_DIR/config.toml" 2>/dev/null || echo 8765)"

echo
bold "Firewall"
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
    warn "ufw is active. Without these rules the app cannot reach the service:"
    echo "    sudo ufw allow in to any port $PORT proto tcp comment 'wol-unlock API'"
    echo "    sudo ufw allow in to any port 5353 proto udp comment 'mDNS'"
elif command -v firewall-cmd >/dev/null && systemctl is-active --quiet firewalld; then
    warn "firewalld is active. Run:"
    echo "    sudo firewall-cmd --permanent --add-port=$PORT/tcp"
    echo "    sudo firewall-cmd --permanent --add-service=mdns"
    echo "    sudo firewall-cmd --reload"
else
    ok "no active ufw/firewalld detected"
fi

# --- 6. Done ----------------------------------------------------------------
echo
bold "Installed."
echo
echo "  Pair a phone:      wol-unlockctl pair"
echo "  Check status:      wol-unlockctl status"
echo "  List devices:      wol-unlockctl devices"
echo "  Follow the log:    journalctl --user -u wol-unlock -f"
echo
echo "  Wake-on-LAN needs a one-time NIC/BIOS change:"
echo "                     sudo $REPO_DIR/scripts/enable-wol.sh"
echo
if ! grep -q "$VENV/bin" <<<"$PATH"; then
    echo "  Add the tools to your PATH:"
    echo "      ln -s $VENV/bin/wol-unlockctl ~/.local/bin/wol-unlockctl"
    echo "      ln -s $VENV/bin/wol-unlock    ~/.local/bin/wol-unlock"
fi
