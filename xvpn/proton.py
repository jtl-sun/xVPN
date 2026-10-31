"""Read-only Proton VPN Windows app integration and safe official-app launcher.

No stored credentials, proprietary API, impersonation, or service manipulation.
Adapter-up is only a local signal, never proof of VPN routing/authentication.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess

PROTON_DOWNLOAD_URL = 'https://protonvpn.com/download-windows'
PROTON_CONFIG_URL = 'https://account.protonvpn.com/downloads'
PROTON_HELP_URL = 'https://protonvpn.com/support/wireguard-configurations'
# Proton 5.x uses a top-level launcher and a versioned UI client. Older
# versions used ProtonVPN.exe. Keep all supported names for upgrades.
PROTON_EXECUTABLES = ('ProtonVPN.Launcher.exe', 'ProtonVPN.Client.exe',
                      'ProtonVPN.exe', 'ProtonVPN.App.exe')
PROTON_PROCESS_NAMES = frozenset(name.casefold() for name in PROTON_EXECUTABLES)


@dataclass(frozen=True)
class ProtonStatus:
    supported: bool
    installed: bool
    app_path: str = ''
    running: bool = False
    adapter_up: bool = False
    adapter_name: str = ''
    adapter_detected: bool = False
    error: str = ''

    @property
    def label(self) -> str:
        if not self.supported:
            return 'Monitoring available on Windows'
        if not self.installed:
            return 'Not installed'
        if self.adapter_up:
            return 'Tunnel adapter active*'
        if self.running:
            return 'App open · tunnel unverified'
        return 'Installed · app closed'

    @property
    def explanation(self) -> str:
        if not self.supported:
            return 'On this system, Proton VPN must be managed in its official application.'
        if not self.installed:
            return 'Install Proton VPN, then sign in through its official application.'
        if self.adapter_up:
            return 'An identifiable Proton VPN network adapter is Up. This does not prove successful routing. Click Check IP.'
        if self.running:
            return 'Proton VPN is running. xVPN cannot read your signed-in account or confirm a VPN tunnel from app activity alone.'
        return 'Proton VPN is installed. Open its official app to sign in or manage the tunnel.'


def is_proton_adapter(name: str, description: str) -> bool:
    """Be conservative: generic WireGuard/Wintun may belong to another VPN."""
    return any(marker in (name + ' ' + description).casefold()
               for marker in ('protonvpn', 'proton vpn', 'proton wireguard'))


def parse_adapters(raw: str) -> tuple[bool, bool, str]:
    """Read-only PowerShell JSON: (any matching, any Up, Up/first name)."""
    data = json.loads(raw.strip() or '[]')
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return False, False, ''
    matches = [item for item in data if isinstance(item, dict)
               and is_proton_adapter(str(item.get('Name', '')), str(item.get('InterfaceDescription', '')))]
    up = [item for item in matches if str(item.get('Status', '')).casefold() == 'up']
    found = up[0] if up else (matches[0] if matches else {})
    return bool(matches), bool(up), str(found.get('Name', ''))


def parse_tasks(raw: str) -> bool:
    """Only exact process names, not substring matches of a command line."""
    for row in csv.reader(io.StringIO(raw)):
        if row and row[0].strip().lower() in PROTON_PROCESS_NAMES:
            return True
    return False


def _version_key(path: Path) -> tuple[int, ...]:
    """Numeric sorting of v5.1.10 over v5.1.9, not lexicographic."""
    match = re.search(r'(?i)^v?(\d+(?:\.\d+){1,3})$', path.name)
    if match:
        return tuple(int(part) for part in match.group(1).split('.'))
    return ()


def _folder_executables(folder: Path) -> list[Path]:
    """Possible launcher and versioned Proton GUI binaries in a VPN folder."""
    candidates = [folder / name for name in PROTON_EXECUTABLES]
    try:
        versions = sorted((entry for entry in folder.iterdir() if entry.is_dir() and
                           _version_key(entry)), key=_version_key, reverse=True)
        for version in versions:
            # Root launcher is preferred; versioned Client.exe is the fall-back.
            candidates.extend(version / name for name in PROTON_EXECUTABLES)
    except OSError:
        pass
    return candidates


def _candidate_paths(env: dict[str, str] | None = None) -> list[Path]:
    env = os.environ if env is None else env
    folders: list[Path] = []
    for key in ('ProgramFiles', 'ProgramW6432', 'ProgramFiles(x86)'):
        if root := env.get(key):
            folders.append(Path(root) / 'Proton' / 'VPN')
    if local := env.get('LOCALAPPDATA'):
        folders.extend((Path(local) / 'Programs' / 'Proton' / 'VPN',
                        Path(local) / 'Proton' / 'VPN'))
    candidates: list[Path] = []
    for folder in dict.fromkeys(folders):
        candidates.extend(_folder_executables(folder))
    return candidates


def _uninstall_path(path_text: str) -> Path | None:
    """Parse a Windows uninstall DisplayIcon value including quoted exe, index."""
    text = path_text.strip()
    if not text:
        return None
    if text.startswith('"'):
        match = re.match(r'^"([^"]+)"', text)
        text = match.group(1) if match else text.strip('"')
    else:
        text = re.sub(r',\s*-?\d+$', '', text)
    return Path(text.strip()) if text.strip() else None


def _registry_executables() -> list[Path]:
    try:
        import winreg
    except ImportError:
        return []
    matches: list[Path] = []
    roots = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
    locations = (r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                 r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')
    for root in roots:
        for location in locations:
            try:
                with winreg.OpenKey(root, location) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            with winreg.OpenKey(key, winreg.EnumKey(key, i)) as subkey:
                                name = str(winreg.QueryValueEx(subkey, 'DisplayName')[0])
                                if not re.search(r'\bProton\s*VPN\b', name, re.I):
                                    continue
                                try:
                                    folder = str(winreg.QueryValueEx(subkey, 'InstallLocation')[0]).strip('" ')
                                    if folder:
                                        matches.extend(_folder_executables(Path(folder)))
                                except OSError:
                                    pass
                                try:
                                    raw_icon = str(winreg.QueryValueEx(subkey, 'DisplayIcon')[0])
                                    if icon := _uninstall_path(raw_icon):
                                        if icon.suffix.lower() == '.exe':
                                            matches.append(icon)
                                            matches.extend(_folder_executables(icon.parent))
                                except OSError:
                                    pass
                        except OSError:
                            continue
            except OSError:
                continue
    return matches


def find_proton_app(preferred_path: str = '') -> Path | None:
    """Find known Proton GUI binaries without running downloaded binaries.

    Prefer the stable official launcher so app updates do not break opening.
    An explicitly chosen path is honored only when it has a known filename.
    """
    candidates = []
    if preferred_path:
        candidates.append(Path(preferred_path))
    candidates.extend(_candidate_paths())
    candidates.extend(_registry_executables())
    for path in dict.fromkeys(candidates):
        try:
            if path.name.casefold() in PROTON_PROCESS_NAMES and path.is_file():
                return path
        except OSError:
            continue
    return None


def _run_readonly(args: list[str], timeout: int = 9) -> str:
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, encoding='utf-8', errors='replace',
                            timeout=timeout, creationflags=flags, check=False)
    if result.returncode:
        raise RuntimeError(f'{args[0]} returned exit code {result.returncode}')
    return result.stdout


def read_proton_status(preferred_path: str = '') -> ProtonStatus:
    if platform.system() != 'Windows':
        return ProtonStatus(supported=False, installed=False)
    path = find_proton_app(preferred_path)
    if path is None:
        return ProtonStatus(supported=True, installed=False)
    errors: list[str] = []
    running = False
    detected = up = False
    name = ''
    try:
        running = parse_tasks(_run_readonly(['tasklist.exe', '/FO', 'CSV', '/NH']))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        errors.append(f'Process check unavailable: {type(exc).__name__}')
    try:
        output = _run_readonly(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                                'Get-NetAdapter | Select-Object Name,InterfaceDescription,Status | ConvertTo-Json -Compress'], timeout=12)
        detected, up, name = parse_adapters(output)
    except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        errors.append(f'Adapter check unavailable: {type(exc).__name__}')
    return ProtonStatus(supported=True, installed=True, app_path=str(path),
                        running=running, adapter_up=up, adapter_detected=detected,
                        adapter_name=name, error='; '.join(errors))


def launch_proton_app(status: ProtonStatus | None = None) -> str:
    """Launch official GUI only. Does not connect, authenticate, or write settings."""
    status = status or read_proton_status()
    if not status.supported:
        raise RuntimeError('Automatic Proton app launch is supported on Windows only.')
    if not status.installed or not status.app_path:
        raise FileNotFoundError('Proton VPN is not installed. Use the official download link.')
    path = Path(status.app_path)
    if not path.is_file() or path.name.casefold() not in PROTON_PROCESS_NAMES:
        raise FileNotFoundError('The Proton VPN executable could not be verified at its detected location.')
    subprocess.Popen([str(path)], cwd=str(path.parent), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return 'Opened official Proton VPN. Sign in and connect there; then return to xVPN.'
