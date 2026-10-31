# xVPN Manager v1.3.5

Desktop VPN profile manager for Windows and Ubuntu.

## Highlights
- New minimal xVPN shield-X application icon on title bar and launchers.
- WireGuard handshake health verification with rollback after a missing new handshake.
- WireGuard diagnostics and optional MTU test copies (original profiles preserved).
- Proton VPN official app installation detection, launch, and link to official download.
- Public IP verification with fallback provider and a 429 rate-limit error message.
- Updated responsive Setup/Help and Diagnostics windows.

## Installation
1. Download `20261101-06_xVPN_Manager_1.3.5.zip` from this release and extract it.
2. On Windows, run `install_windows.bat`. Python 3.10+ is required. Install the official WireGuard or OpenVPN client as appropriate.
3. On Ubuntu, see `README.md` and run `install_ubuntu.sh`.
4. VPN provider settings (`.conf` / `.ovpn`) must be obtained from the provider. **Do not upload config files containing private keys to GitHub.**

## Important
- xVPN is **not a VPN service**, and is not affiliated with Proton VPN.
- The Proton official app retains control of its own sign-in and connection. Direct WireGuard profiles are a separate connection mode.
- A WireGuard handshake does not guarantee high speed or that the expected exit country is in use. Check public IP after connection.
- Windows + Proton real-world connectivity and speed cannot be validated by the source bundle's automated tests.

## Verification
- Python unit tests: 50 passed in the preparation environment.
