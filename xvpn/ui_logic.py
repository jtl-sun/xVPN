"""Presentation-only helpers: never infer a real VPN connection from a label."""
from __future__ import annotations

from typing import Iterable

from .models import VPNProfile


def is_active_state(state: str) -> bool:
    """Tunnel-active labels; different from proof of Internet access."""
    return state in {"Active*", "Connected (WG)", "No handshake", "Handshake stale", "Active (unverified)"}


def visible_profiles(
    profiles: Iterable[VPNProfile],
    states: dict[str, str],
    category: str = "all",
    search: str = "",
) -> list[VPNProfile]:
    """Filter by labels explicitly entered by the user, not geolocated IPs."""
    query = search.casefold().strip()
    shown = []
    for profile in profiles:
        state = states.get(profile.id, "Checking...")
        if category == "active" and not is_active_state(state):
            continue
        if category == "inactive" and state != "Inactive":
            continue
        if category.startswith("country:") and profile.country != category[8:]:
            continue
        if category.startswith("provider:") and profile.provider != category[9:]:
            continue
        if query and query not in " ".join((
            profile.name, profile.provider, profile.country,
            profile.protocol, profile.endpoint_host,
        )).casefold():
            continue
        shown.append(profile)
    return shown


def sort_profiles(
    profiles: Iterable[VPNProfile], states: dict[str, str],
    column: str = "name", descending: bool = False,
) -> list[VPNProfile]:
    def key(p: VPNProfile):
        value = {
            "status": states.get(p.id, "Checking..."),
            "name": p.name,
            "country": p.country,
            "provider": p.provider,
            "protocol": p.protocol,
            "endpoint": f"{p.endpoint_host}:{p.endpoint_port}" if p.endpoint_host else "",
            "response": p.latency_ms if p.latency_ms is not None else float("inf"),
        }.get(column, p.name)
        return (value.casefold() if isinstance(value, str) else value, p.name.casefold())

    return sorted(profiles, key=key, reverse=descending)


def count_active(states: dict[str, str], profiles: Iterable[VPNProfile]) -> int:
    return sum(is_active_state(states.get(p.id, "")) for p in profiles)
