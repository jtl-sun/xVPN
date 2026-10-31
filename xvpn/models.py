from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import uuid


@dataclass
class VPNProfile:
    id: str
    name: str
    provider: str
    country: str
    protocol: str
    config_path: str
    endpoint_host: str = ""
    endpoint_port: int = 0
    nm_connection: str = ""
    latency_ms: float | None = None

    @classmethod
    def create(
        cls,
        *,
        config_path: str,
        name: str,
        provider: str,
        country: str,
        protocol: str,
        endpoint_host: str = "",
        endpoint_port: int = 0,
    ) -> "VPNProfile":
        return cls(
            id=uuid.uuid4().hex,
            name=name.strip() or Path(config_path).stem,
            provider=provider.strip() or "Other",
            country=country.strip() or "Unknown",
            protocol=protocol,
            config_path=str(Path(config_path).resolve()),
            endpoint_host=endpoint_host,
            endpoint_port=endpoint_port,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "VPNProfile":
        allowed = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in value.items() if k in allowed})
