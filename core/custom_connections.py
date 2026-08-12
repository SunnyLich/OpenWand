"""Stable identities and persistence helpers for custom OpenAI-compatible endpoints."""
from __future__ import annotations

import re
from collections.abc import Mapping

ENV_PREFIX = "OPENWAND_CUSTOM_CONNECTION_"
COUNT_KEY = "OPENWAND_CUSTOM_CONNECTION_COUNT"
ROUTE_PREFIX = "custom@"
LEGACY_ID = "legacy"


def normalize_id(value: str) -> str:
    """Return an env/keychain-safe stable connection id."""
    normalized = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-_")
    return normalized or LEGACY_ID


def route_id(connection_id: str) -> str:
    return f"{ROUTE_PREFIX}{normalize_id(connection_id)}"


def connection_id(provider: str) -> str:
    provider = str(provider or "").strip().lower()
    if provider == "custom":
        return LEGACY_ID
    if provider.startswith(ROUTE_PREFIX):
        return normalize_id(provider[len(ROUTE_PREFIX):])
    return ""


def is_custom(provider: str) -> bool:
    return bool(connection_id(provider))


def secret_name(connection_id_value: str) -> str:
    connection = normalize_id(connection_id_value)
    if connection == LEGACY_ID:
        return "CUSTOM_API_KEY"
    suffix = re.sub(r"[^A-Z0-9]+", "_", connection.upper()).strip("_")
    return f"OPENWAND_CUSTOM_API_KEY_{suffix}"


def load_connections(env: Mapping[str, str]) -> list[dict[str, str]]:
    """Load ordered custom connections; migrate the old singleton in memory."""
    try:
        count = max(0, int(str(env.get(COUNT_KEY, "0") or "0")))
    except ValueError:
        count = 0
    connections: list[dict[str, str]] = []
    used: set[str] = set()
    for index in range(1, count + 1):
        prefix = f"{ENV_PREFIX}{index}_"
        cid = normalize_id(str(env.get(prefix + "ID", "") or f"custom-{index}"))
        if cid in used:
            cid = normalize_id(f"{cid}-{index}")
        used.add(cid)
        connections.append({
            "id": cid,
            "alias": str(env.get(prefix + "ALIAS", "") or "").strip(),
            "base_url": str(env.get(prefix + "BASE_URL", "") or "").strip(),
        })
    if not connections:
        legacy_url = str(env.get("CUSTOM_BASE_URL", "") or "").strip()
        if legacy_url:
            connections.append({
                "id": LEGACY_ID,
                "alias": str(env.get("OPENWAND_CONNECTION_ALIAS_CUSTOM", "") or "").strip(),
                "base_url": legacy_url,
            })
    return connections


def env_values(connections: list[dict[str, str]]) -> dict[str, str]:
    values = {COUNT_KEY: str(len(connections))}
    for index, connection in enumerate(connections, 1):
        prefix = f"{ENV_PREFIX}{index}_"
        values[prefix + "ID"] = normalize_id(connection.get("id", ""))
        values[prefix + "ALIAS"] = str(connection.get("alias", "") or "").strip()
        values[prefix + "BASE_URL"] = str(connection.get("base_url", "") or "").strip()
    return values


def env_keys(env: Mapping[str, str]) -> set[str]:
    return {key for key in env if key == COUNT_KEY or key.startswith(ENV_PREFIX)}


def find(connections: list[dict[str, str]], provider: str) -> dict[str, str] | None:
    cid = connection_id(provider)
    return next((item for item in connections if normalize_id(item.get("id", "")) == cid), None)
