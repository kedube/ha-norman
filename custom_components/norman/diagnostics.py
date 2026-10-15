"""Diagnostics support for Norman."""

from __future__ import annotations

from dataclasses import asdict
import json
import re
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .api import redact_hub_text
from .const import SENSITIVE_HUB_KEYS
from .coordinator import NormanConfigEntry
from .frontend import async_get_frontend_diagnostics

# The hub address maps the report to a home network; the hub's own payloads carry its
# location, Wi-Fi name and identity (SENSITIVE_HUB_KEYS). All are redacted wherever they
# appear: entry data, request payloads, and inside the raw response bodies kept by the
# traffic recorder. Everything else is blind state, which is what bug reports need.
TO_REDACT = {CONF_HOST, "unique_id", *SENSITIVE_HUB_KEYS}


# An IPv4 address: a failed connection's error can name the address a host name resolved to,
# which is not among the values the entry knows.
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def redact_raw_body(body: str, secrets: list[str]) -> str:
    """Redact a raw hub response by key, then by value.

    Raw bodies are kept as text so unknown fields survive; parsing them here only to apply
    the key-based redaction keeps that property while still blanking sensitive keys. Text
    that does not parse -- a body clipped by the recorder, a piece of the stream -- is
    redacted key by key where the keys can still be found (``redact_hub_text``).
    """
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict | list):
        # Unescaped, so names stay readable: a Japanese room name would otherwise be \u30ea...
        body = json.dumps(
            async_redact_data(data, TO_REDACT), ensure_ascii=False, separators=(",", ":")
        )
    else:
        body = redact_hub_text(body)
    return _without_secrets(body, secrets)


def _without_secrets(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    return text


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
        if exchange.get("error"):
            # A connection error names the hub's address.
            exchange["error"] = _IPV4.sub(REDACTED, _without_secrets(exchange["error"], secrets))
    traffic = async_redact_data(traffic, TO_REDACT)

    return {
        # The options say whether the poll and the wake sweep run, and the command spacing.
        "entry": async_redact_data(
            {
                "data": dict(entry.data),
                "options": dict(entry.options),
                "unique_id": entry.unique_id,
            },
            TO_REDACT,
        ),
        "last_update_success": coordinator.last_update_success,
        "frontend": async_get_frontend_diagnostics(hass),
        "devices": {
            str(device_id): asdict(device) for device_id, device in (coordinator.data or {}).items()
        },
        # As parsed from the device list; blinds keyed by id as text, like the devices above.
        "scenes": {
            key: {
                **asdict(scene),
                "targets": {str(uid): asdict(target) for uid, target in scene.targets.items()},
            }
            for key, scene in coordinator.scenes.items()
        },
        "scene_groups": {
            group_id: asdict(group) for group_id, group in coordinator.scene_groups.items()
        },
        # Raw exchanges with the hub, below the parsing layer: the last response per endpoint
        # in full, then the most recent requests and stream chunks. Fields the integration
        # does not understand survive here, which is what a "support my blind" report needs.
        # The hub may send fields nobody has seen yet, so users are told to review it.
        "hub_traffic": traffic,
    }
