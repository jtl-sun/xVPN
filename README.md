# xVPN Manager 1.3.5

**Personal VPN profile manager** for trusted WireGuard (`.conf`) and OpenVPN (`.ovpn`) configuration files. Lightweight cross-platform Python/Tkinter desktop application. No subscription, no third-party Python dependencies (Python 3.10+ and Tk required).

> xVPN Manager is **not itself a VPN provider**. It does not create free servers, bypass a provider's plan restrictions, fetch VPN accounts automatically, or connect merely because another VPN app is installed. You must supply a provider-issued configuration file and have the appropriate WireGuard/OpenVPN system software. Displaying a country label does not give you an IP address in that country.

## New in v1.3.5 — Minimal xVPN application icon

- Installed the approved **minimal navy / cyan shield X logo** as an actual application icon, not a screenshot mockup.
- Added a multi-resolution `.ico` with simplified small-icon artwork (16/24/32/48/64 pixels) and the complete approved design for larger sizes (128/256 pixels).
- **Windows:** Tk application title bar, taskbar icon, and desktop shortcut now use bundled xVPN branding. `install_windows.bat` recreates the shortcut with a specific icon path. If Windows keeps the old icon, unpin/re-pin the shortcut or refresh Explorer's icon cache.
- **Ubuntu:** Tk window icon and the .desktop application-menu launcher also use the icon.
- The top-left xVPN interface header now has a matching small shield next to the brand text.
- No changes to WireGuard/OpenVPN behavior, Proton detection, configured servers, profiles, or credentials. Configuration files are not overwritten.

## New in v1.3.4 — Slow manual connections and window-fit repair

**Why a manual US tunnel may feel slow when the official Proton app using Japan is fast:** the screenshots show that the US manual WireGuard handshake succeeded, but the official app connected to a *different country and server*. A successful WireGuard handshake is not proof of good throughput; different routing, server load, congestion, ISP handling, DNS, and MTU can all matter. xVPN cannot guarantee a faster Proton connection, and the provider-issued original `.conf` is never altered.

- **Connection → WireGuard diagnostics and MTU test...** and **Overview → Diagnostics** show only *non-secret* metadata: configured endpoint, MTU, DNS, allowed routes, local tunnel state, handshake age, and WireGuard RX/TX byte counters when available. No speed is guessed from these counters; no external IP/geolocation API call is made during diagnostics. Keys are not displayed or logged.
- Optional **Create MTU test copy...** makes an explicitly user-requested, separate `.conf` with `MTU = 1360` or `1280` to investigate packet-size/PMTU issues. Only valid 1280–1420 values are accepted. The original file is preserved, and the new profile is added to the list **without connecting automatically**. Use only one tunnel at a time.
- MTU copies contain the provider's **same WireGuard private key**, stored under the user's xVPN application-data `mtu-test-configs` folder. Keep private. On Linux the folder/file are restricted to owner access; Windows uses the current user's application-data folder ACLs. Remove test profiles/configs when no longer needed. Config copy storage is not part of the profile delete command.
- **Setup / Help** now uses a scrollable text panel and fixed footer buttons, so actions remain reachable on smaller displays or at higher Windows display scaling. Includes instructions for testing the same-country servers in both clients.
- No changes to default routing, actual VPN client programs, Proton login, or automatic connection behavior. Windows VPN speed fixes are not validated on a real Windows machine; MTU variants are optional diagnostic experiments.

**Recommended troubleshooting:**

1. Disconnect manual WireGuard. In Proton **official app**, connect to a **US server** if your plan/current selection permits and compare speeds; using Japan is not a direct comparison.
2. With Proton official app disconnected, connect the original US WireGuard profile. Choose **Check IP** and **Diagnostics**. For handshakes with no useful RX, check server and routing. If RX flows but web pages stall, compare another US server.
3. Optionally create **MTU 1360** test profile and connect it after disconnecting original. Compare ordinary browsing; if the problem persists try **MTU 1280** as an additional test. If it becomes worse, revert to original. Lower MTU does **not** guarantee faster throughput.
4. If traffic stalls, immediately disconnect in xVPN or deactivate in official WireGuard. Previous 1.3.3 auto-recovery only addresses **missing handshakes**, not authenticated but slow tunnels.

Useful official information: [Proton speed troubleshooting](https://protonvpn.com/support/increase-vpn-speeds) and [manual WireGuard setup](https://protonvpn.com/support/wireguard-manual-windows).

## New in v1.3.3 — Verified WireGuard status and safe recovery

- For **Windows WireGuard tunnels imported as `.conf`**, xVPN now distinguishes:
  - **Connected (WG)** — recent authenticated WireGuard handshake (within 3 minutes); **does not prove public IP or actual Internet reachability**.
  - **No handshake** — a local tunnel exists but `wg.exe` reports no authenticated peer exchange.
  - **Handshake stale** — a handshake exists but is older than 3 minutes; idle tunnels can produce this status.
  - **Active (unverified)** — a tunnel is running but the handshake cannot be read.
  - **Inactive** — no running managed tunnel.
- When **xVPN starts a new Windows WireGuard tunnel**, it checks for a real handshake for up to **22 seconds**. It sends at most one empty UDP datagram to a **private RFC1918 DNS address specified in that configuration** to encourage initial handshake, without querying outside IP services. If it cannot confirm a recent handshake, xVPN **automatically disconnects only the tunnel started by that same attempt** to restore the normal network route. If recovery fails, it displays explicit manual-deactivation instructions.
- If the separate WireGuard `wg.exe` status tool is unavailable, xVPN **refuses to start a new Windows WireGuard tunnel** because it cannot perform its safety verification. Repair/install the official WireGuard Windows client first.
- **Existing VPN tunnels are never automatically disconnected** by this new watchdog; manual Activate/Deactivate actions remain available in the official WireGuard application. Proton VPN official app routing and credentials remain exclusively under the official app's control.
- Proton VPN missing on Windows: one-time guidance, an always-visible **Download Proton VPN** button when not installed, and the verified official link: https://protonvpn.com/download-windows. If detection misses a custom install, use **Locate Proton App...**.
- Keep **Proton's official app disconnected** when testing manual WireGuard. When xVPN detects an active Proton adapter, it warns and blocks a new imported-profile connection to reduce routing conflicts.
- `Check IP` remains explicitly user-triggered and optional; successful handshake alone is not proof of geolocation, DNS/IPv6 protection, or leak prevention.
- This feature is intended to **prevent indefinite loss of Internet access due to a new unresponsive WireGuard tunnel**. It cannot fix upstream ISP UDP blocking, server congestion, invalid provider configurations, or every Windows routing issue.

### How to test on Windows 11

1. Quit xVPN, install v1.3.3 using `install_windows.bat`. Existing profiles/theme remain in `%LOCALAPPDATA%\xVPNManager`.
2. Disconnect the **official Proton VPN app**, and preferably exit it during the manual-tunnel test.
3. Launch xVPN as Windows **Administrator** using **Tools → Restart as administrator**.
4. Select the imported Proton `.conf` and click **Connect**. xVPN will verify the WireGuard handshake (up to 22 seconds).
5. If **Connected (WG)** appears, click **Check IP** and confirm the correct country; separately check normal browsing and the provider's website. If a warning says **recovered**, xVPN disconnected its newly started tunnel due to lack of handshake, preventing indefinite loss of Internet access.
6. If the automatic recovery itself fails, immediately open WireGuard and **Deactivate** the tunnel, then retry only after investigating WireGuard's **Log** tab. Do **not** publish `.conf` files or private keys from your configuration.

**Not a live Windows validation:** VPN traffic, Windows elevation, WireGuard service timing and Proton login were **not tested on a physical Windows computer**. Offline unit tests and a Linux virtual-display GUI smoke test are available.

## Fix in v1.3.2 — HTTP 429 on Check IP

- `Check IP` first uses ipapi.co; if it fails (including HTTP 429), it tries GeoJS over HTTPS.
- If both public-IP services fail, xVPN explains this is a lookup problem, **not** evidence of VPN disconnection.
- IP checks remain user-triggered only and are not part of the 6-second Proton monitoring poll.
- The public IP is sent to the selected lookup provider; no Proton credentials are used.

## Fix in v1.3.1 — Proton VPN 5.1.7 / Windows detection

- Detects **ProtonVPN.Launcher.exe** in `C:\Program Files\Proton\VPN` and **ProtonVPN.Client.exe** in `v5.x.x` directories. The old 1.3.0 detector incorrectly assumed `ProtonVPN.exe` was still the main executable.
- Monitors Launcher/Client/legacy process names rather than filtering `tasklist` to only the old `ProtonVPN.exe`.
- **Locate Proton App...** in the Proton tab or Tools menu handles custom installation folders. Select the **installed** Launcher/Client binary, *not* the downloaded installer.
- Existing Proton VPN installation and login are untouched; xVPN stores only the optional local program location, not any passwords or VPN tokens.
- The official app still performs login and VPN connection. xVPN can detect activity, not attest to a signed-in account or successful routing.

## What was new in v1.3.0 — Proton VPN official app companion

Proton VPN on **Windows 11** now has a dedicated card, a permanent entry in the connection table and a **Proton VPN** details tab, **even when the profile library is empty**.

1. Install Proton VPN from its [official website](https://protonvpn.com/download-windows).
2. Launch xVPN Manager, click **Open / Sign in** in the Proton card. It opens the **real Proton VPN application**.
3. Sign in and complete authentication **in Proton VPN**, not in xVPN.
4. Press **Connect** within the official Proton VPN app. Return to xVPN; its status automatically refreshes about every 6 seconds. You can also click **Refresh**.
5. Select **Check IP** to inspect the public IP/country. This is **not** a DNS/IPv6 leak test and cannot prove all traffic is tunneled.
6. To disconnect, open Proton VPN through xVPN and use its **Disconnect** control.

**Supported monitoring**: Installation found / not found; official GUI process running / not running; identifiable Proton VPN network adapter Up / not confirmed. **An app window or an Up adapter never proves Proton login, authentication, or Internet routing.** xVPN does **not** read login tokens, passwords, account details, or Proton service internals. These signals can be missing on certain adapter versions; connection controls remain with the official app. Clicking or double-clicking the Proton row launches the official GUI and does **not** silently connect a tunnel.

### Optional: Connect or Disconnect directly inside xVPN

Proton's official Windows app does not have a documented external connect/disconnect control API for use here. For direct xVPN control, visit [Proton WireGuard configurations](https://account.protonvpn.com/downloads), sign in to Proton in the **web browser**, generate/download an authorized `.conf`, and click **Import Proton config** / **Add Profile** in xVPN. You'll also need the official [WireGuard Windows software](https://www.wireguard.com/install/) and Windows administrator permission for tunnel operations. The configuration-file approach is **separate** from the installed Proton VPN official app and does not inherit its login session, kill switch, or every app feature. Avoid running both VPN tunnels simultaneously.

**Proton VPN Free** permits supported manual WireGuard configuration files, subject to the server choices and feature limits of the account. Read the [official configuration guide](https://protonvpn.com/support/wireguard-configurations). This app does not bypass Proton account restrictions or offer free servers.

### Previous improvements (v1.2.0)

- qBittorrent-inspired desktop layout: top toolbar, left filter/navigation tree, sortable VPN server table, bottom details/activity tabs, and a status bar.
- Sidebar filters for All / Active tunnels / Inactive, and countries/providers of imported profiles.
- Search by name, country, provider, protocol, and endpoint; click a column heading to sort.
- Double-click an imported profile to connect or disconnect; double-click **Proton VPN · Official app** to open the official client instead.
- Overview, Configuration, Activity log, and now Proton VPN tabs.
- Light and dark themes; separate profile metadata editor and saved settings.

### User interface

The display has five areas:

1. **Toolbar:** Add Profile, Connect/Disconnect for imported profiles, **Open Proton VPN**, Check IP, Refresh, Setup / Help.
2. **At a glance:** Managed-tunnel/Proton adapter signals, observed public IP, observed IP location, imported profile count, and pinned Proton application status.
3. **Filters:** All profiles / Proton VPN official app / Active tunnels / Inactive / Countries / Providers.
4. **Table:** A permanent Proton official-app row plus imported WireGuard/OpenVPN profiles; columns show status, profile, country, provider, protocol, endpoint, TCP response time.
5. **Bottom tabs:** Overview (imported-profile actions), Configuration, Activity log, Proton VPN (official app monitoring).

Double-click a managed .conf/.ovpn profile to toggle Connect/Disconnect; double-click the Proton official app row to launch its GUI. The context menu offers additional actions. Keys: **Ctrl+O** Add, **Ctrl+F** search, **Ctrl+I** check IP, **F5** refresh, **Enter** toggle selected, **Delete** remove selected.

**Important:** The displayed WireGuard handshake state does not establish correct Internet routing. For OpenVPN, Active* only means a local process is running, not confirmed VPN routing. Use **Check IP** for a public-IP routing clue. This is **not** a DNS/IPv6 leak test. A TCP response measurement is available only for TCP OpenVPN profiles, and it is *not* a VPN speed test.

## Windows 11 install / update

1. Close xVPN Manager. Keep your original `.conf` and `.ovpn` files in their existing locations.
2. Extract the entire ZIP to a folder. **Do not run from inside ZIP.**
3. Double-click **`install_windows.bat`**. Python 3.10+ with the Python Launcher and Tkinter must already be installed.
4. Launch **xVPN Manager** from the desktop shortcut (no console window), or type `xvpn` in a *new* PowerShell window.
5. For Proton, use **Open / Sign in** and connect from the official app; you need not import a profile. Or add a separate official configuration file with **Add Profile** if you want xVPN direct control. Install the official WireGuard or OpenVPN client software if Setup / Help says it is missing.
6. If Windows tunnel control needs elevation: **Tools → Restart as administrator**. Confirm the normal Windows UAC prompt.
7. Select a profile, click Connect, and then Check IP to verify the public-IP location.

**Update safety:** `install_windows.bat` updates application code in `%LOCALAPPDATA%\xVPNManager`, preserving `%LOCALAPPDATA%\xVPNManager\profiles.json` and `preferences.json`. Imported configurations remain at their original locations. It does not uninstall any VPN client.

## Ubuntu 24.04 install / update

```bash
sudo apt update
sudo apt install python3-tk network-manager-openvpn wireguard-tools
bash install_ubuntu.sh
```

Launch from the application menu or via `xvpn-manager` (ensure `~/.local/bin` is in PATH). Ubuntu typically authorizes NetworkManager changes through system prompts. Your profiles are kept in `~/.config/xvpn-manager/profiles.json`.

## First-use notes

- Use provider-issued configuration files and **never** download random VPN configuration files from untrusted sources.
- Free VPN services may **not** allow downloading OpenVPN or WireGuard configurations on the free plan. Their official apps can still work separately, without xVPN Manager.
- You cannot select a country by typing a name into the Country field. It is metadata; the actual exit IP depends on the VPN server in the configuration.
- Avoid running another VPN client simultaneously. xVPN checks only profiles registered in its own library, not every possible third-party tunnel.
- On Windows, the WireGuard service may already be registered; the program refuses duplicate registration rather than removing an existing service.
- Closing xVPN stops OpenVPN processes launched directly by xVPN; WireGuard and NetworkManager connections stay active until you explicitly disconnect them.
- **Check IP** uses `https://ipapi.co/json/`, with HTTPS `https://get.geojs.io/v1/ip/geo.json` as a fallback if the first service fails (including HTTP 429). It runs only on user request, not as an automatic traffic monitor. No provider credentials are sent; external services receive your public exit IP. Both services can fail, and geolocation is approximate.
- OpenVPN credentials are not stored in the profile library. The system NetworkManager can retain connection settings. Keep configuration files and WireGuard private keys protected.

## Diagnostics

- **Connect does not work:** Verify WireGuard/OpenVPN installed, run as administrator on Windows, disconnect other VPN clients, and confirm provider configuration and account eligibility.
- **No country shown for my IP:** Select Check IP while online; the provider may limit requests or classify cloud IPs differently.
- **Tunnel active/handshake but unchanged IP:** Check the VPN config's route/AllowedIPs and your system routes; do not assume a working tunnel without verification.
- **Profile not found:** Restore the original `.conf`/`.ovpn` to the imported location or remove/re-import the profile.

Official client downloads:
- WireGuard: https://www.wireguard.com/install/
- OpenVPN community: https://openvpn.net/community-downloads/

## Tests and compatibility

```bash
python -m unittest discover -s tests -v
```

Automated tests cover parsing/security checks, storage, Windows command behavior, filtering/sorting, UI preferences and the new Proton-monitor data logic. UI layout has also been rendered using Tkinter in a Linux virtual display. **Windows 11 Proton detection, actual Proton sign-in, native Connect/Disconnect operations, UAC elevation, VPN tunnels and IP verification were not tested on a real Windows computer. The status/UI preview uses simulated data, not an authenticated Proton session.**

The `qBittorrent 4.3.zip` provided as a visual reference is **not** included, modified, or redistributed in this project; the UI is an independently written Tkinter interface.