"""Private, local-only WireGuard configuration diagnostics and safe MTU experiments."""
from __future__ import annotations

import os
from pathlib import Path
import re
import uuid

from .config_parser import ConfigError, parse_config


def wireguard_settings(path: str | Path) -> dict[str, str]:
    """Return non-secret display fields only, never key or peer identity values."""
    parsed = parse_config(path)
    if parsed.protocol != 'WireGuard':
        raise ConfigError('WireGuard configuration required.')
    settings = {'endpoint': f'{parsed.host}:{parsed.port}', 'mtu': 'Automatic (not set)',
                'dns': 'Not specified', 'routes': 'Not specified'}
    section = ''
    for raw in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = raw.split('#', 1)[0].strip()
        if line.startswith('['):
            section = line.lower()
        if '=' not in line:
            continue
        key, value = (s.strip() for s in line.split('=', 1))
        if section == '[interface]' and key.lower() == 'mtu':
            settings['mtu'] = value
        if section == '[interface]' and key.lower() == 'dns':
            settings['dns'] = value
        if section == '[peer]' and key.lower() == 'allowedips':
            settings['routes'] = value
    return settings


def make_mtu_test_copy(source: str | Path, target_dir: str | Path, mtu: int = 1360) -> Path:
    """Generate a separate WireGuard .conf, leaving the source untouched.

    The resulting file contains the original private key. Only create under the
    user's app-data directory; limit Unix permissions and never log contents.
    """
    if not isinstance(mtu, int) or not 1280 <= mtu <= 1420:
        raise ValueError('MTU must be a whole number between 1280 and 1420.')
    parsed = parse_config(source)
    if parsed.protocol != 'WireGuard':
        raise ConfigError('MTU experiments are supported only for WireGuard.')
    content = Path(source).read_text(encoding='utf-8-sig')
    match = re.search(r'(?im)^\s*\[interface\]\s*$', content)
    if not match:
        raise ConfigError('The configuration has no [Interface] section.')
    next_section = re.search(r'(?im)^\s*\[[^\]]+\]\s*$', content[match.end():])
    end = match.end() + next_section.start() if next_section else len(content)
    original_interface = content[match.end():end]
    modified_interface, substitutions = re.subn(
        r'(?im)^\s*MTU\s*=\s*[^\r\n]*', f'MTU = {mtu}', original_interface
    )
    if not substitutions:
        modified_interface = '\nMTU = ' + str(mtu) + '\n' + original_interface
    modified = content[:match.end()] + modified_interface + content[end:]
    dest = Path(target_dir)
    dest.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        os.chmod(dest, 0o700)
    # Limit the filename to a safe Windows-compatible subset, and never overwrite.
    stem = re.sub(r'[^A-Za-z0-9_-]+', '_', Path(source).stem)[:65] or 'wireguard'
    for _ in range(5):
        output = dest / f'{stem}_MTU{mtu}_{uuid.uuid4().hex[:8]}.conf'
        try:
            fd = os.open(str(output), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
                f.write(modified)
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        return output
    raise FileExistsError('Could not create a unique MTU test configuration.')
