"""Small independent user-interface preferences file (never contains VPN keys)."""
from __future__ import annotations

import json
from pathlib import Path
from .store import app_data_dir


class Preferences:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "preferences.json"

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {"theme": data.get("theme", "light") if data.get("theme") in ("dark", "light") else "light",
                    "proton_path": data.get("proton_path", "") if isinstance(data.get("proton_path", ""), str) else ""}
        except (OSError, ValueError, TypeError, AttributeError):
            return {"theme": "light", "proton_path": ""}

    def save(self, theme: str, proton_path: str | None = None) -> None:
        if theme not in ("light", "dark"):
            raise ValueError("Invalid theme")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        if proton_path is None:
            proton_path = self.load().get("proton_path", "")
        temp.write_text(json.dumps({"theme": theme, "proton_path": proton_path}, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def set_proton_path(self, path: str) -> None:
        self.save(self.load()["theme"], path)
