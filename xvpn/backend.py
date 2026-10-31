from __future__ import annotations

from dataclasses import dataclass
import ctypes
import ipaddress
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from .models import VPNProfile
from .config_parser import parse_config


def _run(*args, **kwargs):
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(*args, **kwargs)


class VPNError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolStatus:
    openvpn: bool
    wireguard: bool
    network_manager: bool


def _find_windows_executable(names: list[str], candidates: list[str]) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for value in candidates:
        expanded = os.path.expandvars(value)
        if Path(expanded).is_file():
            return expanded
    return None


@dataclass(frozen=True)
class WireGuardHandshake:
    """Last authenticated peer exchange. Not proof of Internet routing."""
    state: str  # verified, missing, stale, unavailable
    age_seconds: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class ConnectionAttempt:
    message: str
    handshake_verified: bool = False
    recovered: bool = False
    recovery_failed: bool = False


def parse_latest_handshakes(output: str, *, now: float | None = None) -> WireGuardHandshake:
    """Parse wg(8) latest-handshakes. Do not expose peer keys in diagnostics."""
    epochs: list[int] = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            stamp = int(parts[-1])
            if stamp > 0:
                epochs.append(stamp)
        except ValueError:
            continue
    if not epochs:
        return WireGuardHandshake("missing")
    age = max(0, int((time.time() if now is None else now) - max(epochs)))
    return WireGuardHandshake("verified" if age <= 180 else "stale", age)


class VPNBackend:
    def __init__(self) -> None:
        self.system = platform.system()
        self.processes: dict[str, subprocess.Popen[str]] = {}
        self.auth_files: dict[str, str] = {}

    def tool_status(self) -> ToolStatus:
        return ToolStatus(
            openvpn=bool(self._openvpn_executable()),
            wireguard=bool(self._wireguard_executable() or shutil.which("wg-quick")),
            network_manager=bool(shutil.which("nmcli")),
        )

    def _openvpn_executable(self) -> str | None:
        if self.system == "Windows":
            return _find_windows_executable(
                ["openvpn.exe"],
                [r"%ProgramFiles%\OpenVPN\bin\openvpn.exe"],
            )
        return shutil.which("openvpn")

    def _wireguard_executable(self) -> str | None:
        if self.system == "Windows":
            return _find_windows_executable(
                ["wireguard.exe"], [r"%ProgramFiles%\WireGuard\wireguard.exe"]
            )
        return shutil.which("wg-quick")

    def _wg_status_executable(self) -> str | None:
        if self.system == "Windows":
            return _find_windows_executable(
                ["wg.exe"], [r"%ProgramFiles%\WireGuard\wg.exe"]
            )
        return shutil.which("wg")

    def wireguard_handshake(self, profile: VPNProfile) -> WireGuardHandshake:
        """Inspect a managed tunnel read-only; never infer a connection from 'Active'."""
        executable = self._wg_status_executable()
        if not executable:
            return WireGuardHandshake("unavailable", detail="wg status tool was not found")
        tunnel_name = Path(profile.config_path).stem
        try:
            result = _run([executable, "show", tunnel_name, "latest-handshakes"],
                          check=False, capture_output=True, text=True, timeout=6)
        except (OSError, subprocess.TimeoutExpired):
            return WireGuardHandshake("unavailable", detail="wg status query failed")
        if result.returncode != 0:
            return WireGuardHandshake("unavailable", detail="wg status query was not available")
        return parse_latest_handshakes(result.stdout)

    def wireguard_transfer(self, profile: VPNProfile) -> tuple[int, int] | None:
        """Read WireGuard RX/TX counters without exposing peer public keys."""
        executable = self._wg_status_executable()
        if not executable:
            return None
        try:
            result = _run([executable, "show", Path(profile.config_path).stem, "transfer"],
                          check=False, capture_output=True, text=True, timeout=6)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        rx = tx = 0
        count = 0
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) != 3:
                continue
            try:
                received, sent = int(fields[1]), int(fields[2])
            except ValueError:
                continue
            if received < 0 or sent < 0:
                continue
            rx += received
            tx += sent
            count += 1
        return (rx, tx) if count else None

    def _probe_wireguard_internal_dns(self, profile: VPNProfile) -> None:
        """Provoke WireGuard's initial handshake via the config's private DNS IP.

        No third-party web calls, DNS queries, credentials or payloads. The only
        possible destination is an RFC1918 internal IPv4 address in the profile.
        """
        try:
            contents = Path(profile.config_path).read_text(encoding="utf-8-sig")
            in_interface = False
            for line in contents.splitlines():
                line = line.split("#", 1)[0].strip()
                if line.startswith("["):
                    in_interface = line.lower() == "[interface]"
                if in_interface and line.lower().startswith("dns") and "=" in line:
                    for candidate in line.split("=", 1)[1].split(","):
                        try:
                            address = ipaddress.ip_address(candidate.strip())
                        except ValueError:
                            continue
                        private_ranges = (ipaddress.ip_network("10.0.0.0/8"),
                                          ipaddress.ip_network("172.16.0.0/12"),
                                          ipaddress.ip_network("192.168.0.0/16"))
                        if isinstance(address, ipaddress.IPv4Address) and any(address in net for net in private_ranges):
                            # Sending a *zero-payload* UDP datagram triggers route
                            # selection; never leak sensitive data into a request.
                            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                                sock.settimeout(0.4)
                                sock.sendto(b"", (str(address), 53))
                            return
        except (OSError, UnicodeError):
            return

    def _wait_for_handshake(self, profile: VPNProfile, timeout: float = 22.0,
                            interval: float = 2.0) -> WireGuardHandshake:
        deadline = time.monotonic() + timeout
        last = WireGuardHandshake("missing")
        probed = False
        while True:
            last = self.wireguard_handshake(profile)
            # Windows service startup can take a few seconds. Retry a transient
            # status-query error instead of immediately rolling back a good tunnel.
            if last.state == "verified":
                return last
            if not probed:
                self._probe_wireguard_internal_dns(profile)
                probed = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return last
            time.sleep(min(interval, remaining))

    def connect_verified(self, profile: VPNProfile, username: str = "", password: str = "") -> ConnectionAttempt:
        """For NEW Windows WireGuard tunnels, roll back if no handshake.

        Only a tunnel installed by this exact call can be auto-disconnected;
        preexisting/manual tunnels are never removed by the watchdog.
        """
        if self.system != "Windows" or profile.protocol != "WireGuard":
            return ConnectionAttempt(self.connect(profile, username, password))
        if self.active(profile):
            return ConnectionAttempt("Tunnel is already active. No automatic recovery was attempted.")
        if not self._wg_status_executable():
            raise VPNError("WireGuard status tool (wg.exe) was not found. Install or repair the official WireGuard client before connecting; this safety check prevents an unverified tunnel from blocking Internet access.")
        activation_message = self.connect(profile, username, password)
        if "already" in activation_message.casefold():
            return ConnectionAttempt("Tunnel was already running. xVPN will not auto-disconnect a preexisting tunnel.")
        try:
            handshake = self._wait_for_handshake(profile)
        except Exception:  # A verification error must not strand a newly installed tunnel.
            handshake = WireGuardHandshake("unavailable")
        if handshake.state == "verified":
            return ConnectionAttempt("WireGuard handshake confirmed. Use Check IP to verify the US exit location.", handshake_verified=True)
        reason = ("No WireGuard server handshake was received within 22 seconds." if handshake.state != "unavailable"
                  else "The WireGuard handshake could not be checked after activation.")
        try:
            self.disconnect(profile)
            return ConnectionAttempt(reason + " xVPN automatically disconnected ONLY the tunnel it just started, to restore normal Internet routing.", recovered=True)
        except (OSError, VPNError) as exc:
            return ConnectionAttempt(reason + " AUTOMATIC RECOVERY FAILED. Open WireGuard and click Deactivate for this tunnel immediately. Details: " + str(exc), recovery_failed=True)

    def is_admin(self) -> bool:
        if self.system == "Windows":
            try:
                return bool(ctypes.windll.shell32.IsUserAnAdmin())
            except Exception:
                return False
        return os.geteuid() == 0

    def latency(self, profile: VPNProfile, timeout: float = 3.0) -> float:
        parsed = parse_config(profile.config_path)
        if parsed.protocol == "WireGuard":
            raise VPNError("WireGuard uses UDP. A TCP/DNS timing is not a VPN latency measurement. Use public IP verification after activation.")
        text = Path(profile.config_path).read_text(encoding="utf-8-sig").lower()
        if "tcp" not in text:
            raise VPNError("TCP response testing is available only for TCP OpenVPN profiles.")
        start = time.perf_counter()
        try:
            with socket.create_connection((profile.endpoint_host, profile.endpoint_port), timeout=timeout):
                return round((time.perf_counter() - start) * 1000, 1)
        except OSError as exc:
            raise VPNError("Server did not accept a TCP connection. No response time was measured.") from exc

    def public_ip(self) -> dict[str, str]:
        """Check the public exit IP, with a separate HTTPS geolocation fallback.

        External IP services are queried *only* on user action, never by the
        background Proton process/adapter monitor. No credentials are sent.
        """
        services = (
            ("ipapi.co", "https://ipapi.co/json/", "country_name"),
            ("GeoJS", "https://get.geojs.io/v1/ip/geo.json", "country"),
        )
        failures: list[str] = []
        for provider, url, country_field in services:
            request = urllib.request.Request(url, headers={
                "User-Agent": "xVPN-Manager/1.3.5",
                "Accept": "application/json",
            })
            try:
                with urllib.request.urlopen(request, timeout=8) as response:
                    data = json.loads(response.read().decode("utf-8"))
                if not isinstance(data, dict) or data.get("error") or data.get("success") is False:
                    raise ValueError("Provider returned an error response")
                ip = str(data.get("ip") or "").strip()
                ipaddress.ip_address(ip)  # Reject missing/invalid/untrusted responses.
                return {
                    "ip": ip,
                    "country": str(data.get(country_field) or "Unknown"),
                    "city": str(data.get("city") or "Unknown"),
                    "source": provider,
                }
            except urllib.error.HTTPError as exc:
                failures.append(f"{provider}: HTTP {exc.code}")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
                failures.append(f"{provider}: {type(exc).__name__}")
        raise VPNError(
            "Public IP lookup is temporarily unavailable (" + "; ".join(failures) + "). "
            "This does not mean Proton VPN has disconnected. Try again later, "
            "or check your public IP from a browser."
        )

    def connect(self, profile: VPNProfile, username: str = "", password: str = "") -> str:
        parse_config(profile.config_path)
        if self.active(profile):
            return "Tunnel/process already active; public IP verification recommended."
        if self.system == "Windows" and not self.is_admin():
            raise VPNError("Administrator permission is required. Use Setup → Restart as administrator, then connect again.")
        if profile.id in self.processes and self.processes[profile.id].poll() is None:
            return "Already connected"
        if self.system == "Linux" and shutil.which("nmcli"):
            return self._connect_nm(profile, username, password)
        if profile.protocol == "WireGuard":
            return self._connect_wireguard(profile)
        return self._connect_openvpn(profile, username, password)

    def _nm_connections(self) -> dict[str, str]:
        result = _run(
            ["nmcli", "-t", "-f", "UUID,NAME", "connection", "show"],
            check=False, capture_output=True, text=True, timeout=10,
        )
        values: dict[str, str] = {}
        for line in result.stdout.splitlines():
            uuid, separator, name = line.partition(":")
            if separator:
                values[uuid] = name.replace(r"\:", ":")
        return values

    def _connect_nm(self, profile: VPNProfile, username: str, password: str) -> str:
        connection = profile.nm_connection
        if not connection:
            before = self._nm_connections()
            kind = "openvpn" if profile.protocol == "OpenVPN" else "wireguard"
            result = _run(
                ["nmcli", "connection", "import", "type", kind, "file", profile.config_path],
                check=False, capture_output=True, text=True, timeout=20,
            )
            if result.returncode != 0:
                raise VPNError(result.stderr.strip() or result.stdout.strip() or "NetworkManager import failed")
            after = self._nm_connections()
            new_ids = [uuid for uuid in after if uuid not in before]
            connection = after[new_ids[-1]] if new_ids else Path(profile.config_path).stem
            profile.nm_connection = connection
        auth_path = ""
        try:
            if profile.protocol == "OpenVPN" and username:
                changed = _run(
                    ["nmcli", "connection", "modify", "id", connection, "vpn.user-name", username],
                    check=False, capture_output=True, text=True, timeout=10,
                )
                if changed.returncode != 0:
                    raise VPNError(changed.stderr.strip() or "Could not set the temporary VPN username")
            command = ["nmcli", "connection", "up", "id", connection]
            if password:
                fd, auth_path = tempfile.mkstemp(prefix="xvpn-nm-auth-")
                try:
                    os.write(fd, f"vpn.secrets.password:{password}\n".encode("utf-8"))
                finally:
                    os.close(fd)
                os.chmod(auth_path, 0o600)
                command.extend(["passwd-file", auth_path])
            result = _run(
                command, check=False, capture_output=True, text=True, timeout=45,
            )
        finally:
            if auth_path:
                Path(auth_path).unlink(missing_ok=True)
        if result.returncode != 0:
            raise VPNError(result.stderr.strip() or result.stdout.strip() or "VPN connection failed")
        return result.stdout.strip() or "Connected"

    def _connect_wireguard(self, profile: VPNProfile) -> str:
        executable = self._wireguard_executable()
        if not executable:
            raise VPNError("WireGuard is not installed.")
        if self.system == "Windows":
            query = _run(["sc.exe", "query", f"WireGuardTunnel${Path(profile.config_path).stem}"],
                         capture_output=True, text=True, timeout=8)
            if query.returncode == 0:
                raise VPNError("A tunnel with this filename is already registered. Open WireGuard and manage that existing tunnel, or import a uniquely named configuration. No existing tunnel was removed.")
            if query.returncode != 1060:
                raise VPNError("Could not check the existing WireGuard service. Check Windows permissions before retrying.")
            result = _run(
                [executable, "/installtunnelservice", profile.config_path],
                check=False, capture_output=True, text=True, timeout=30,
            )
        else:
            pkexec = shutil.which("pkexec")
            command = ([pkexec] if pkexec else ["sudo"]) + [executable, "up", profile.config_path]
            result = _run(command, check=False, capture_output=True, text=True, timeout=45)
        if result.returncode != 0:
            raise VPNError(result.stderr.strip() or result.stdout.strip() or "WireGuard connection failed")
        return "Tunnel activated. Check public IP to verify routing."

    def _connect_openvpn(self, profile: VPNProfile, username: str, password: str) -> str:
        executable = self._openvpn_executable()
        if not executable:
            raise VPNError("OpenVPN is not installed.")
        command = [executable, "--config", profile.config_path, "--auth-nocache"]
        if username or password:
            fd, auth_path = tempfile.mkstemp(prefix="xvpn-auth-")
            try:
                os.write(fd, f"{username}\n{password}\n".encode("utf-8"))
            finally:
                os.close(fd)
            if os.name != "nt":
                os.chmod(auth_path, 0o600)
            command.extend(["--auth-user-pass", auth_path])
            self.auth_files[profile.id] = auth_path
        flags = subprocess.CREATE_NO_WINDOW if self.system == "Windows" else 0
        process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            text=True, creationflags=flags,
        )
        self.processes[profile.id] = process
        time.sleep(1.2)
        if process.poll() is not None:
            self._cleanup_auth(profile.id)
            raise VPNError("OpenVPN exited before the tunnel was established. Run the app as Administrator and check the profile.")
        return "Connecting"

    def disconnect(self, profile: VPNProfile) -> str:
        if self.system == "Linux" and shutil.which("nmcli") and profile.nm_connection:
            result = _run(
                ["nmcli", "connection", "down", "id", profile.nm_connection],
                check=False, capture_output=True, text=True, timeout=25,
            )
            if result.returncode != 0:
                raise VPNError(result.stderr.strip() or "Disconnect failed")
            return "Disconnected"
        if profile.protocol == "WireGuard":
            executable = self._wireguard_executable()
            if not executable:
                raise VPNError("WireGuard is not installed.")
            if self.system == "Windows":
                tunnel_name = Path(profile.config_path).stem
                command = [executable, "/uninstalltunnelservice", tunnel_name]
            else:
                pkexec = shutil.which("pkexec")
                command = ([pkexec] if pkexec else ["sudo"]) + [executable, "down", profile.config_path]
            result = _run(command, check=False, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                raise VPNError(result.stderr.strip() or result.stdout.strip() or "Disconnect failed")
            return "Disconnected"
        process = self.processes.pop(profile.id, None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        self._cleanup_auth(profile.id)
        return "Disconnected"

    def _cleanup_auth(self, profile_id: str) -> None:
        auth_path = self.auth_files.pop(profile_id, "")
        if auth_path:
            try:
                Path(auth_path).unlink(missing_ok=True)
            except OSError:
                pass

    def active(self, profile: VPNProfile) -> bool:
        process = self.processes.get(profile.id)
        if process and process.poll() is None:
            return True
        if self.system == "Linux" and profile.nm_connection and shutil.which("nmcli"):
            result = _run(
                ["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"],
                check=False, capture_output=True, text=True, timeout=8,
            )
            return profile.nm_connection in result.stdout.splitlines()
        if self.system == "Windows" and profile.protocol == "WireGuard":
            result = _run(
                ["sc.exe", "query", f"WireGuardTunnel${Path(profile.config_path).stem}"],
                check=False, capture_output=True, text=True, timeout=8,
            )
            return result.returncode == 0 and "RUNNING" in result.stdout
        if self.system == "Linux" and profile.protocol == "WireGuard" and shutil.which("wg"):
            # wg-quick tunnels are not NetworkManager connections. Check the
            # actual interface instead of always reporting Inactive.
            result = _run(
                ["wg", "show", "interfaces"], check=False,
                capture_output=True, text=True, timeout=8,
            )
            return result.returncode == 0 and Path(profile.config_path).stem in result.stdout.split()
        return False

    def shutdown(self) -> None:
        for profile_id, process in list(self.processes.items()):
            if process.poll() is None:
                process.terminate()
            self._cleanup_auth(profile_id)
