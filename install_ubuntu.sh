#!/usr/bin/env bash
set -euo pipefail
app_dir="${XDG_DATA_HOME:-$HOME/.local/share}/xvpn-manager"
bin_dir="$HOME/.local/bin"
desktop_dir="$HOME/.local/share/applications"
mkdir -p "$app_dir" "$bin_dir" "$desktop_dir"
cp -R "$(dirname "$0")/xvpn" "$app_dir/"
cp "$(dirname "$0")/app.py" "$app_dir/"
install -m 755 "$(dirname "$0")/run_ubuntu.sh" "$app_dir/run_ubuntu.sh"
ln -sf "$app_dir/run_ubuntu.sh" "$bin_dir/xvpn-manager"
desktop_file="$desktop_dir/xvpn-manager.desktop"
printf '%s\n' \
  '[Desktop Entry]' \
  'Type=Application' \
  'Name=xVPN Manager' \
  'Comment=Manage trusted OpenVPN and WireGuard profiles' \
  "Exec=$app_dir/run_ubuntu.sh" \
  "Icon=$app_dir/xvpn/assets/xvpn_compact.png" \
  'Terminal=false' \
  'Categories=Network;Security;' > "$desktop_file"
chmod 755 "$desktop_file"
echo "xVPN Manager installed. Open it from the application menu or run: xvpn-manager"
echo "Recommended dependencies: sudo apt install python3-tk network-manager-openvpn wireguard-tools"
