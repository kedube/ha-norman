"""Diagnostics support for Norman."""

from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import SENSITIVE_HUB_KEYS
from .coordinator import NormanConfigEntry
from .frontend import async_get_frontend_diagnostics

# The hub address maps the report to a home network; the hub's own payloads carry its
# location, Wi-Fi name and identity (SENSITIVE_HUB_KEYS). All are redacted wherever they
# appear: entry data, request payloads, and inside the raw response bodies kept by the
# traffic recorder. Everything else is blind state, which is what bug reports need.
TO_REDACT = {CONF_HOST, "unique_id", *SENSITIVE_HUB_KEYS}


def redact_raw_body(body: str, secrets: list[str]) -> str:
    """Redact a raw hub response: by key when it is JSON, by value otherwise.

    Raw bodies are kept as text so unknown fields survive; parsing them here only to apply
    the key-based redaction keeps that property while still blanking sensitive keys.
    """
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict | list):
        body = json.dumps(async_redact_data(data, TO_REDACT), separators=(",", ":"))
    for secret in secrets:
        body = body.replace(secret, "**REDACTED**")
    return body


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NormanConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    api = coordinator.api
    secrets = [value for value in (api.host, api.thing_name) if value]

    traffic = api.traffic.as_dict()
    traffic["latest_raw"] = {
        endpoint: redact_raw_body(body, secrets) for endpoint, body in traffic["latest_raw"].items()
    }
    for exchange in traffic["exchanges"]:
        if exchange.get("response"):
            exchange["response"] = redact_raw_body(exchange["response"], secrets)
    traffic = async_redact_data(traffic, TO_REDACT)

    return {
        "entry": async_redact_data(
            {"data": dict(entry.data), "unique_id": entry.unique_id},
            TO_REDACT,
        ),
        "last_update_success": coordinator.last_update_success,
        "frontend": async_get_frontend_diagnostics(hass),
        "devices": {
            str(device_id): asdict(device) for device_id, device in (coordinator.data or {}).items()
        },
        # Raw exchanges with the hub, below the parsing layer: the last response per endpoint
        # in full, then the most recent requests and stream chunks. Fields the integration
        # does not understand survive here, which is what a "support my blind" report needs.
        # The hub may send fields nobody has seen yet, so users are told to review it.
        "hub_traffic": traffic,
    }
