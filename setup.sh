#!/usr/bin/env bash
# Install system deps, groups, the uinput rule, the venv, and the user services.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

echo "==> System packages"
sudo apt-get update
sudo apt-get install -y \
  libportaudio2 ydotool libnotify-bin wl-clipboard \
  libcanberra-gtk3-module gnome-session-canberra xdotool ffmpeg

echo "==> Groups"
relogin=0
for grp in input render; do
  if ! id -nG "$USER" | tr ' ' '\n' | grep -qx "$grp"; then
    sudo usermod -aG "$grp" "$USER"
    echo "   added $USER to '$grp'"
    relogin=1
  fi
done
[ "$relogin" -eq 1 ] && echo "   >>> log out and back in before the service will work"

echo "==> uinput udev rule"
sudo install -m 0644 udev/99-uinput.rules /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "==> Python venv"
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

mkdir -p "$UNIT_DIR"

echo "==> ydotoold user service"
if systemctl --user list-unit-files 2>/dev/null | grep -q '^ydotool\.service'; then
  systemctl --user enable --now ydotool.service
else
  install -m 0644 systemd/ydotoold.service "$UNIT_DIR/ydotoold.service"
  systemctl --user daemon-reload
  systemctl --user enable --now ydotoold.service
fi

echo "==> lightweight-stt user service"
sed "s#@INSTALL_DIR@#$HERE#g" systemd/lightweight-stt.service > "$UNIT_DIR/lightweight-stt.service"
systemctl --user daemon-reload
systemctl --user enable --now lightweight-stt.service

cat <<EOF

Done.
  status:  systemctl --user status lightweight-stt
  logs:    journalctl --user -u lightweight-stt -f
  config:  $HOME/.config/lightweight-stt/config.toml  (optional)
  model:   run ./convert.sh if whisper-small-ov/ is missing
EOF
