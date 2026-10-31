from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


MAX_CONFIG_BYTES = 2 * 1024 * 1024
DANGEROUS_OPENVPN_DIRECTIVES = {
    "up", "down", "route-up", "route-pre-down", "ipchange", "client-connect",
    "client-disconnect", "learn-address", "plugin", "config", "cd", "iproute",
    "tls-verify", "auth-user-pass-verify", "tls-crypt-v2-verify",
}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedConfig:
    protocol: str
    host: str
    port: int
    needs_credentials: bool = False
    warnings: tuple[str, ...] = ()


def _read_safe(path: Path) -> str:
    if not path.is_file():
        raise ConfigError("Configuration file does not exist.")
    if path.stat().st_size > MAX_CONFIG_BYTES:
        raise ConfigError("Configuration file is unexpectedly large.")
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConfigError("Configuration must be a UTF-8 text file.") from exc


def parse_config(path_value: str | Path) -> ParsedConfig:
    path = Path(path_value)
    suffix = path.suffix.lower()
    text = _read_safe(path)
    if suffix == ".conf":
        for line in text.splitlines():
            if line.split("=", 1)[0].strip().lower() in {"preup", "postup", "predown", "postdown"}:
                raise ConfigError("WireGuard configuration scripts are not allowed.")
    if suffix == ".ovpn":
        return _parse_openvpn(text)
    if suffix == ".conf":
        return _parse_wireguard(text)
    raise ConfigError("Only .ovpn (OpenVPN) and .conf (WireGuard) files are supported.")


def _parse_openvpn(text: str) -> ParsedConfig:
    host = ""
    port = 0
    needs_credentials = False
    warnings: list[str] = []
    for original in text.splitlines():
        line = original.strip()
        if not line or line.startswith(("#", ";", "<")):
            continue
        parts = re.split(r"\s+", line)
        directive = parts[0].lower().lstrip("-")
        if directive in DANGEROUS_OPENVPN_DIRECTIVES:
            raise ConfigError(
                f"Unsafe OpenVPN directive '{directive}' was found. "
                "For safety, xVPN Manager does not run profiles that can execute external programs."
            )
        if directive == "script-security" and len(parts) > 1 and parts[1] not in {"0", "1"}:
            warnings.append("The profile requests elevated script security, but no external scripts are allowed.")
        if directive == "remote" and len(parts) >= 2 and not host:
            host = parts[1]
            try:
                port = int(parts[2]) if len(parts) >= 3 else 1194
            except ValueError:
                port = 1194
        if directive == "auth-user-pass":
            if len(parts) > 1:
                raise ConfigError("Profiles that reference a credential file are not accepted. Remove the path and import again.")
            needs_credentials = True
    if not host:
        raise ConfigError("No OpenVPN 'remote' endpoint was found.")
    return ParsedConfig("OpenVPN", host, port, needs_credentials, tuple(warnings))


def _parse_wireguard(text: str) -> ParsedConfig:
    host = ""
    port = 0
    in_peer = False
    for original in text.splitlines():
        line = original.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            in_peer = line.lower() == "[peer]"
            continue
        if in_peer and line.lower().startswith("endpoint") and "=" in line:
            endpoint = line.split("=", 1)[1].strip()
            if endpoint.startswith("[") and "]:" in endpoint:
                host, port_text = endpoint[1:].rsplit("]: ", 1) if "]: " in endpoint else endpoint[1:].rsplit("]:", 1)
            else:
                host, sep, port_text = endpoint.rpartition(":")
                if not sep:
                    continue
            try:
                port = int(port_text)
            except ValueError:
                port = 51820
            break
    if not host:
        raise ConfigError("No WireGuard peer Endpoint was found.")
    return ParsedConfig("WireGuard", host, port or 51820)
