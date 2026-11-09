#!/usr/bin/env bash
# Per-user install of BS3 Control. Needs python + pyside6 (pacman -S pyside6).
# The udev rule is the only root step; it is printed at the end if missing.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/share/bs3-control"
RULE=/etc/udev/rules.d/70-flydigi-cooler.rules

if [[ "${1:-}" == "--uninstall" ]]; then
    pkill -f "$DEST/bs3-control" 2>/dev/null || true
    rm -rf "$DEST"
    rm -f "$HOME/.local/bin/bs3-control" \
          "$HOME/.local/share/applications/bs3-control.desktop" \
          "$HOME/.local/share/icons/hicolor/scalable/apps/bs3-control.svg" \
          "$HOME/.config/autostart/bs3-control.desktop"
    echo "Removed. To drop device access too: sudo rm $RULE"
    exit 0
fi

python3 -c 'import PySide6' 2>/dev/null || { echo "PySide6 missing: sudo pacman -S pyside6"; exit 1; }

rm -rf "$DEST"
mkdir -p "$DEST" "$HOME/.local/bin" "$HOME/.local/share/applications" \
         "$HOME/.local/share/icons/hicolor/scalable/apps" "$HOME/.config/autostart"
cp -r "$SRC/bs3control" "$SRC/icons" "$SRC/bs3-control" "$DEST/"
find "$DEST" -name __pycache__ -prune -exec rm -rf {} +

# Flydigi's product photo is never shipped; use a local copy when there is one
if [[ -d "$SRC/assets" ]]; then
    cp -r "$SRC/assets" "$DEST/"
fi
ln -sf "$DEST/bs3-control" "$HOME/.local/bin/bs3-control"
cp "$SRC/icons/bs3-control.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/"
cp "$SRC/bs3-control.desktop" "$HOME/.local/share/applications/"
sed 's|^Exec=.*|Exec=bs3-control gui --tray|' "$SRC/bs3-control.desktop" \
    > "$HOME/.config/autostart/bs3-control.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "Installed to $DEST (tray icon starts at login)."
if [[ ! -f $RULE ]]; then
    echo "Device access missing. Run once:"
    echo "  sudo install -m644 '$SRC/70-flydigi-cooler.rules' /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw"
fi
