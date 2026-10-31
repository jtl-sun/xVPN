# Changelog

## 1.3.5 — 2026-11-01

- Added minimalist xVPN shield X icon: high-resolution PNG and multi-size Windows ICO.
- Added window title bar/taskbar icon, xVPN branded header, Windows shortcut IconLocation, and Ubuntu desktop-entry icon.
- Preserves VPN behavior, saved profiles/preferences, and external `.conf`/`.ovpn` files.
- Bundled icons require no third-party runtime image libraries.


## 1.3.4 — 2026-11-01

- New read-only WireGuard diagnostics: handshake, RX/TX counters, MTU, DNS, and allowed routes without printing authentication keys.
- Optional separate MTU test configuration profiles (1360 or 1280), preserving the original provider file and not auto-connecting.
- Scrollable Setup / Help window with permanently visible bottom buttons to prevent clipping on lower resolution/scaling.
- Clarified that US manual WireGuard and Japan official-app performance cannot be directly compared.
- 47 offline unit tests and Linux virtual-display GUI window-fit test pass. No live Windows speed verification.

## 1.3.3 — 2026-11-01

- Added WireGuard handshake-status inspection via the official `wg` status utility on Windows/Linux.
- Added a 22-second handshake verification watchdog on newly started Windows WireGuard tunnels. New tunnel is disconnected automatically if no handshake can be confirmed; previously active tunnels are never touched.
- Explicit warning when rollback fails, including direct WireGuard deactivate guidance.
- Added one-time Proton missing-app message, persistent download link and top-card download button, plus official Windows download URL.
- Warns when official Proton VPN adapter appears active before manual tunnel activation.
- Preserves profiles, theme, and configuration-file paths. Tested with offline tests and virtual-display GUI. Actual Windows VPN traffic is unverified.

## 1.3.2 — 2026-11-01

- Fixed **Check IP** HTTP 429 hard failure: ipapi.co is rate limited; xVPN now tries a separate HTTPS GeoJS IP/geo endpoint if the first source fails.
- IP verification uses user-triggered requests only; the 6-second Proton adapter monitor makes no IP API calls.
- Validates returned IP addresses and checks error responses; failed checks no longer imply Proton VPN has disconnected.
- Friendly status message shows which lookup service supplied the IP, plus limitations.
- Preserves existing Proton VPN detection, profiles, preferences, and official-app-only connection control.


## 1.3.1 — 2026-11-01

- Fixed Proton VPN 5.1.x installation detection: `ProtonVPN.Launcher.exe` and version-folder `ProtonVPN.Client.exe`.
- Fixed tasklist detection of Proton 5.x GUI processes, which may not be named `ProtonVPN.exe`.
- Added manual executable location button for non-standard Windows installations; persists only local program path, preserves current profiles and theme.
- Regression tests for 5.1.x paths and older Proton executables; no Proton session or tunnel is controlled.


## 1.3.0 — 2026-11-01

- Added pinned **Proton VPN · Official app** row visible even before importing any VPN configuration files.
- Added an always-visible Proton application status banner and a dedicated **Proton VPN** details tab.
- Detects the Windows Proton VPN installation under current Program Files/versioned directory or installed-application registry data.
- Refreshes process and VPN-adapter signals in the background about every 6 seconds; includes **Refresh** for an immediate update.
- Opens the **official Proton VPN application** for account sign-in and Connect/Disconnect, without attempting to manipulate proprietary local services or account data.
- Added **Check IP**, import .conf, and Proton official configuration download actions to the Proton tab.
- Double-click the official-app row to open Proton VPN; use its right-click menu for native launch and IP verification.
- Clarifies that an active adapter is a **signal, not proof of authenticated VPN traffic**. xVPN cannot determine whether the user has signed in to Proton's app.
- Retains independently controllable WireGuard and OpenVPN .conf/.ovpn profiles without modifying the profile storage schema.
- Preserves light/dark theme and the qBittorrent-style filters/columns/details/activity UI.
- Added Proton monitor unit tests and Linux virtual-display GUI smoke validation. **No real Windows 11/Proton sign-in or live tunnel testing was possible in this environment.**

## 1.2.0 — 2026-10-31

- qBittorrent-style list, filters, detail tabs, and light/dark themes.
- Added state polling, profile metadata editing, and Windows/Ubuntu setup documentation.