"""Diagnostics support for Norman."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
import ipaddress
import json
import re
from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .api import redact_hub_text
from .const import CONF_SIDEBAR_VIEW_WEATHER, SENSITIVE_HUB_KEYS
from .coordinator import NormanConfigEntry, NormanCoordinator
from .frontend import async_get_frontend_diagnostics

# The hub address maps the report to a home network; the hub's own payloads carry its
# location, Wi-Fi name and identity (SENSITIVE_HUB_KEYS). All are redacted wherever they
# appear: entry data, request payloads, and inside the raw response bodies kept by the
# traffic recorder. So is the weather entity in the options: one is usually named after the
# place it reports on (weather.<town>), which would name the home's location. Everything
# else is blind state, which is what bug reports need.
TO_REDACT = {CONF_HOST, "unique_id", CONF_SIDEBAR_VIEW_WEATHER, *SENSITIVE_HUB_KEYS}
# The same things about the hub as the integration's own model names them.
HUB_TO_REDACT = {"custom_name", "wifi_ssid", "mac_address", "time_zone"}


# An IPv4 address: a failed connection's error can name the address a host name resolved to,
# which is not among the values the entry knows.
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6_CANDIDATE = re.compile(r"[0-9A-Fa-f]*(?::[0-9A-Fa-f.]*){2,8}(?:%[\w.-]+)?")


def _without_addresses(text: str) -> str:
    """``text`` with every IPv6 and IPv4 address blanked."""

    def ipv6(match: re.Match[str]) -> str:
        try:
            ipaddress.IPv6Address(match.group())
        except ValueError:
            return match.group()
        return REDACTED

    return _IPV4.sub(REDACTED, _IPV6_CANDIDATE.sub(ipv6, text))


# A blind's id in reply text that does not parse: a PeripheralUID value, quoted or not, and
# the ids in a notification's PeripheralList, up to a list cut off at the end of the text.
_UID_VALUE = re.compile(r'("PeripheralUID"\s*:\s*)"?(\d+)"?')
_UID_LIST = re.compile(r'("PeripheralList"\s*:\s*\[)([\d\s,]*)(?=\]|$)')
# A bare number: a known blind's id whose key a read boundary cut off (a stream chunk).
_BARE_NUMBER = re.compile(r"(?<![\w.])\d+(?![\w.])")


def _as_uid(raw: Any) -> int | None:
    """A blind id as the hub sends one, a number or a string of digits; else None."""
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


class BlindAliases:
    """A stable alias for each blind's id, ``blind_1``, ``blind_2``..., within one export.

    A blind's PeripheralUID is its serial number (the Norman app shows it as one), and a
    diagnostics file is attached to public issues. Every id in the export is replaced, the
    same alias for the same blind everywhere, so the device list, the scenes and the raw
    traffic still line up with each other. The known blinds are numbered in order of their
    ids; one seen only in older traffic is numbered as it turns up.
    """

    def __init__(self, known: Iterable[int] = ()) -> None:
        """Number the known blinds first, so their aliases do not depend on the traffic."""
        self._aliases: dict[int, str] = {}
        for uid in sorted(set(known)):
            self.alias(uid)

    def alias(self, uid: int) -> str:
        """The alias for a blind id, numbering it if it is new."""
        if uid not in self._aliases:
            self._aliases[uid] = f"blind_{len(self._aliases) + 1}"
        return self._aliases[uid]

    def value(self, raw: Any) -> Any:
        """``raw`` as its alias when it is a blind id, as it is otherwise."""
        uid = _as_uid(raw)
        return raw if uid is None else self.alias(uid)

    def data(self, node: Any) -> Any:
        """``node`` with every PeripheralUID, and every id in a PeripheralList, aliased."""
        if isinstance(node, dict):
            aliased: dict[Any, Any] = {}
            for key, item in node.items():
                if key == "PeripheralUID":
                    aliased[key] = self.value(item)
                elif key == "PeripheralList" and isinstance(item, list):
                    aliased[key] = [
                        self.data(entry) if isinstance(entry, dict | list) else self.value(entry)
                        for entry in item
                    ]
                else:
                    aliased[key] = self.data(item)
            return aliased
        if isinstance(node, list):
            return [self.data(item) for item in node]
        return node

    def text(self, text: str) -> str:
        """The same for reply text that does not parse, matched key by key."""
        text = _UID_VALUE.sub(lambda m: f'{m.group(1)}"{self.value(m.group(2))}"', text)
        text = _UID_LIST.sub(
            lambda m: (
                m.group(1) + re.sub(r"\d+", lambda uid: f'"{self.value(uid.group())}"', m.group(2))
            ),
            text,
        )
        return _BARE_NUMBER.sub(
            lambda m: (
                f'"{self._aliases[int(m.group())]}"'
                if int(m.group()) in self._aliases
                else m.group()
            ),
            text,
        )


def blind_aliases(coordinator: NormanCoordinator) -> BlindAliases:
    """The aliases for one hub's blinds: its devices' ids and the ids its scenes name.

    A diagnostics download and the ``norman.get_hub_data`` response both use these, so a
    blind is ``blind_3`` in each when the hub's blinds have not changed in between.
    """
    return BlindAliases(
        [
            *(coordinator.data or {}),
            *(uid for scene in coordinator.scenes.values() for uid in scene.targets),
        ]
    )


def redact_raw_body(body: str, secrets: list[str], aliases: BlindAliases | None = None) -> str:
    """Redact a raw hub response by key, then by value, and alias its blind ids.

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
        data = async_redact_data(data, TO_REDACT)
        if aliases is not None:
            data = aliases.data(data)
        # Unescaped, so names stay readable: a Japanese room name would otherwise be リ...
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    else:
        body = redact_hub_text(body)
        if aliases is not None:
            body = aliases.text(body)
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
    secrets = [str(value) for value in (api.host, api.thing_name) if value]
    devices = coordinator.data or {}
    aliases = blind_aliases(coordinator)

    traffic = api.traffic.as_dict()
    traffic["latest_raw"] = {
        endpoint: redact_raw_body(body, secrets, aliases)
        for endpoint, body in traffic["latest_raw"].items()
    }
    for exchange in traffic["exchanges"]:
        if exchange.get("request"):
            exchange["request"] = aliases.data(exchange["request"])
        if exchange.get("response"):
            exchange["response"] = redact_raw_body(exchange["response"], secrets, aliases)
        if exchange.get("error"):
            # A connection error names the hub's address.
            exchange["error"] = _without_addresses(_without_secrets(exchange["error"], secrets))
    traffic = async_redact_data(traffic, TO_REDACT)

    return {
        # The options say the command spacing and how the sidebar page is drawn.
        "entry": async_redact_data(
            {
                "data": dict(entry.data),
                "options": dict(entry.options),
                "unique_id": entry.unique_id,
            },
            TO_REDACT,
        ),
        "last_update_success": coordinator.last_update_success,
        # What the hub says about itself, and the integration's link to it: whether its
        # notification stream is connected, whether its device list reads, and how many moves
        # are in flight and being watched.
        "hub": {
            **async_redact_data(asdict(coordinator.hub), HUB_TO_REDACT),
            **coordinator.diagnostics_state(),
        },
        "frontend": async_get_frontend_diagnostics(hass),
        # Blinds by alias (BlindAliases): a blind's id is its serial number. One the device
        # list does not name is called after its id (parsing.parse_devices), so that name
        # takes the alias too.
        "devices": {
            aliases.alias(device_id): {
                **asdict(device),
                "id": aliases.alias(device_id),
                "name": device.name.replace(str(device_id), aliases.alias(device_id))
                if device.name == f"Norman {device_id}"
                else device.name,
            }
            for device_id, device in devices.items()
        },
        # As parsed from the device list; blinds keyed by alias, like the devices above.
        "scenes": {
            key: {
                **asdict(scene),
                "targets": {
                    aliases.alias(uid): asdict(target) for uid, target in scene.targets.items()
                },
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
