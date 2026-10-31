from __future__ import annotations

import json
import os
import platform
from pathlib import Path

from .models import VPNProfile


def app_data_dir() -> Path:
    if platform.system() == "Windows":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "xVPNManager"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "xvpn-manager"


class ProfileStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "profiles.json"

    def load(self) -> list[VPNProfile]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [VPNProfile.from_dict(item) for item in raw.get("profiles", [])]
        except (OSError, ValueError, TypeError, KeyError):
            return []

    def save(self, profiles: list[VPNProfile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": 1, "profiles": [p.to_dict() for p in profiles]}
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        if os.name != "nt":
            os.chmod(temp, 0o600)
        temp.replace(self.path)
