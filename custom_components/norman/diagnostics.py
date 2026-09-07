"""Diagnostics support for Norman."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import NormanConfigEntry

# The hub address maps the report to a home network and the ThingName identifies the hub, so
# both are redacted wherever they appear: in the entry, in request payloads, and inside the raw
# response bodies kept by the traffic recorder. Everything else is blind state.
TO_REDACT = {CONF_HOST, "unique_id", "ThingName"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NormanConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    api = coordinator.api
    secrets = [value for value in (api.host, api.thing_name) if value]

    def scrub(value: Any) -> Any:
        """Blank the hub address and identity inside raw text bodies."""
        if isinstance(value, str):
            for secret in secrets:
                value = value.replace(secret, "**REDACTED**")
            return value
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return {
        "entry": async_redact_data(
            {"data": dict(entry.data), "unique_id": entry.unique_id},
            TO_REDACT,
        ),
        "last_update_success": coordinator.last_update_success,
        "devices": {
            str(device_id): asdict(device) for device_id, device in (coordinator.data or {}).items()
        },
        # Raw exchanges with the hub, below the parsing layer: the last response per endpoint
        # in full, then the most recent requests and stream chunks. Fields the integration
        # does not understand survive here, which is what a "support my blind" report needs.
        # The hub may send fields nobody has seen yet, so users are told to review it.
        "hub_traffic": scrub(async_redact_data(api.traffic.as_dict(), TO_REDACT)),
    }
