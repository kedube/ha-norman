"""Integration-level actions (not tied to one entity)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service import async_register_admin_service

try:
    import probatio as vol
except ImportError:  # pragma: no cover - Home Assistant < 2026.9 (see config_flow.py)
    import voluptuous as vol  # type: ignore[no-redef]

from .api import NormanApiError, NormanConnectionError
from .const import (
    ATTR_BLINDS,
    ATTR_COMMAND,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_FIELDS,
    ATTR_PERIPHERAL_UID,
    ATTR_ROOM,
    ATTR_SHOW_SERIAL_NUMBERS,
    DOMAIN,
    HUB_CMD_REQUEST_STATUS,
    HUB_CMD_STOP,
    HUB_COMMAND_TRIGGER,
    HUB_WIDE_COMMANDS,
    ROOM_COMMAND_REFRESH,
    ROOM_COMMAND_STOP,
    ROOM_COMMANDS,
    ROOM_PRESETS,
    SENSITIVE_HUB_KEYS,
    SERVICE_GET_HUB_DATA,
    SERVICE_ROOM_COMMAND,
    SERVICE_SEND_HUB_COMMAND,
)
from .coordinator import NormanConfigEntry
from .diagnostics import blind_aliases

GET_HUB_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_SHOW_SERIAL_NUMBERS, default=False): cv.boolean,
    }
)

# A room by the hub's name for it, or blinds by their covers; neither is the whole hub.
ROOM_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Exclusive(ATTR_ROOM, "scope", msg="name a room or pick blinds, not both"): cv.string,
        vol.Exclusive(
            ATTR_BLINDS, "scope", msg="name a room or pick blinds, not both"
        ): cv.entity_ids,
        vol.Required(ATTR_COMMAND): vol.In(sorted(ROOM_COMMANDS)),
    }
)

SEND_HUB_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_PERIPHERAL_UID): vol.Coerce(int),
        vol.Required(ATTR_FIELDS): vol.Schema({cv.string: vol.Any(int, float, str, bool)}),
    }
)


def _resolve_entry(hass: HomeAssistant, call: ServiceCall) -> NormanConfigEntry:
    """Find the entry the call targets; with a single hub the id can be omitted.

    A hub that is ignored or disabled never counts. Nor does one that is not set up while
    another is: the sidebar panel and the card leave the hub out then too, as there is
    only one to address.
    """
    entries = hass.config_entries.async_entries(
        DOMAIN, include_ignore=False, include_disabled=False
    )
    loaded = [entry for entry in entries if entry.state is ConfigEntryState.LOADED]
    if entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_entry",
                translation_placeholders={"entry_id": str(entry_id)},
            )
    elif len(loaded) == 1:
        entry = loaded[0]
    elif not loaded and len(entries) == 1:
        # Reported below: the one hub is not set up.
        entry = entries[0]
    else:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="multiple_hubs",
            translation_placeholders={
                "count": str(len(loaded) or len(entries)),
                "field": ATTR_CONFIG_ENTRY_ID,
            },
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"hub": entry.title},
        )
    return entry


async def _async_get_hub_data(call: ServiceCall) -> ServiceResponse:
    """Return the hub's raw device list and status, fetched live.

    This is the JSON the hub sends, including fields the integration does not (yet)
    understand, which is what a "please support my blind" report needs. The response is
    meant to be pasted into issues, so the keys that identify the home or network (location,
    Wi-Fi name, hub identity) are blanked, and each blind's id, its serial number, is the
    alias a diagnostics download gives it. Neither helps a report. ``show_serial_numbers``
    keeps the ids, for a script that matches the blinds up with their devices.
    """
    entry = _resolve_entry(call.hass, call)
    api = entry.runtime_data.api
    try:
        # Unvalidated: a reply carrying an error is what a report about a failing hub needs.
        devices: dict[str, Any] = await api.async_get_devices(validate=False)
        status: dict[str, Any] = await api.async_get_status(validate=False)
    except (NormanConnectionError, NormanApiError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="hub_read_failed",
            translation_placeholders={"hub": entry.title, "error": str(err)},
        ) from err
    response = async_redact_data({"devices": devices, "status": status}, SENSITIVE_HUB_KEYS)
    if call.data[ATTR_SHOW_SERIAL_NUMBERS]:
        return response
    aliased: dict[str, Any] = blind_aliases(entry.runtime_data).data(response)
    return aliased


async def _async_send_hub_command(call: ServiceCall) -> ServiceResponse:
    """POST arbitrary fields to the hub's control endpoint for one peripheral.

    An advanced tool for probing commands the hub advertises but the integration does not
    know how to send yet (limits, motor speed, ...). The hub's reply is
    returned so the outcome can be seen. The blind will do whatever the hub makes of it.

    Note this always addresses by ``PeripheralUID``, matching the app's per-blind motor
    verbs but **not** how it targets ``Switch`` or ``Favorite`` -- those take ``RoomID`` +
    ``GroupID`` (see docs/NORMAN_API.md). Pass those fields yourself to reproduce the app's
    payload; they are merged in as given. ``norman.room_command`` already does this for the
    three commands that need it.

    Anything but a status request takes the blind over, as the buttons do: a move still in
    flight would otherwise be watched, read as never arriving, and sent again on top of a
    limit setting or a calibration. A ``RoomID`` with no ``GroupID`` takes the room over.
    """
    entry = _resolve_entry(call.hass, call)
    coordinator = entry.runtime_data
    api = coordinator.api
    uid: int = call.data[ATTR_PERIPHERAL_UID]
    fields: dict[str, Any] = dict(call.data[ATTR_FIELDS])
    if set(fields) - {HUB_CMD_REQUEST_STATUS}:
        coordinator.async_supersede([uid])
        if isinstance(room_id := fields.get("RoomID"), int) and "GroupID" not in fields:
            coordinator.async_supersede_room(room_id)
    try:
        reply = await api.async_send_control(uid, fields)
    except (NormanConnectionError, NormanApiError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="hub_command_rejected",
            translation_placeholders={"hub": entry.title, "uid": str(uid), "error": str(err)},
        ) from err
    await entry.runtime_data.async_request_refresh()
    return {"reply": reply}


async def _async_send_room_fields(
    entry: NormanConfigEntry, room_id: int | None, command: str, room: str | None
) -> None:
    """Send one room command, to the room named ``room`` or (both None) to the whole hub."""
    coordinator = entry.runtime_data
    try:
        if command == ROOM_COMMAND_REFRESH:
            # A safe status request for the whole hub, or one per blind in the room.
            await coordinator.async_refresh_blinds(room_id)
        elif command == ROOM_COMMAND_STOP:
            # One request, served ahead of everything waiting: the room's own Stop button.
            await coordinator.async_send_room_verb(room_id, {HUB_CMD_STOP: HUB_COMMAND_TRIGGER})
        else:
            # A preset: one request, then every blind it reached is watched. The watches
            # read the hub for their targets at once, which serves as the refresh too.
            await coordinator.async_send_room_preset(room_id, ROOM_PRESETS[command])
    except (NormanConnectionError, NormanApiError) as err:
        if room is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="hub_button_failed",
                translation_placeholders={"command": command, "error": str(err)},
            ) from err
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="room_command_failed",
            translation_placeholders={"room": room, "command": command, "error": str(err)},
        ) from err
    if command in (ROOM_COMMAND_REFRESH, ROOM_COMMAND_STOP):
        await coordinator.async_request_refresh()


def _blind_of(devices: dr.DeviceRegistry, entity: er.RegistryEntry) -> int | None:
    """The hub id of the blind an entity belongs to, or None for a hub's or a room's entity."""
    device = devices.async_get(entity.device_id) if entity.device_id else None
    for domain, identifier in device.identifiers if device else ():
        if domain == DOMAIN and identifier.isdigit():
            return int(identifier)
    return None


def _blinds_by_hub(
    hass: HomeAssistant, call: ServiceCall
) -> list[tuple[NormanConfigEntry, list[int]]]:
    """The blinds ``blinds`` names, grouped by the hub each is on.

    Any of a blind's Norman entities names it; the dashboard card sends its covers. With
    ``config_entry_id`` they must all be on that hub. A hub that is not set up is refused,
    as it is for a room.
    """
    entity_ids: list[str] = call.data[ATTR_BLINDS]
    if not entity_ids:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_blinds_picked")
    wanted = call.data.get(ATTR_CONFIG_ENTRY_ID)
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    found: dict[str, set[int]] = {}
    for entity_id in entity_ids:
        entity = entities.async_get(entity_id)
        uid = (
            _blind_of(devices, entity)
            if entity is not None and entity.platform == DOMAIN and entity.config_entry_id
            else None
        )
        if entity is None or entity.config_entry_id is None or uid is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_a_norman_blind",
                translation_placeholders={"entity": entity_id},
            )
        if wanted and entity.config_entry_id != wanted:
            other = hass.config_entries.async_get_entry(wanted)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="blind_on_other_hub",
                translation_placeholders={
                    "entity": entity_id,
                    "hub": other.title if other else str(wanted),
                },
            )
        found.setdefault(entity.config_entry_id, set()).add(uid)

    hubs: list[tuple[NormanConfigEntry, list[int]]] = []
    for entry_id, uids in found.items():
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_loaded",
                translation_placeholders={"hub": entry.title if entry else entry_id},
            )
        hubs.append((entry, sorted(uids)))
    return hubs


async def _async_send_blind_command(
    entry: NormanConfigEntry, device_ids: list[int], command: str
) -> None:
    """Run one room command on exactly these blinds of one hub.

    A whole room among them gets the room-wide request, one for the room; the rest get one
    each (the coordinator's ``async_send_presets`` and ``async_stop_blinds``). Refresh asks
    each blind to report in, as a room's refresh does.
    """
    coordinator = entry.runtime_data
    addressable = device_ids
    if command in ROOM_PRESETS:
        # A preset is addressed by the blind's room and group, as its own button sends it.
        addressable = [
            device_id
            for device_id in device_ids
            if (device := coordinator.data.get(device_id))
            and device.room_id is not None
            and device.group_id is not None
        ]
        if not addressable:
            device = coordinator.data.get(device_ids[0])
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="button_needs_room",
                translation_placeholders={
                    "command": command,
                    "name": device.name if device else str(device_ids[0]),
                },
            )
    try:
        if command == ROOM_COMMAND_REFRESH:
            await coordinator.async_request_status_of(device_ids)
        elif command == ROOM_COMMAND_STOP:
            await coordinator.async_stop_blinds(device_ids)
        else:
            await coordinator.async_send_presets(addressable, ROOM_PRESETS[command])
    except (NormanConnectionError, NormanApiError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="blinds_command_failed",
            translation_placeholders={"command": command, "error": str(err)},
        ) from err
    # A preset's watches read the hub for their targets at once, which serves as the read.
    if command in (ROOM_COMMAND_REFRESH, ROOM_COMMAND_STOP):
        await coordinator.async_request_refresh()


async def _async_room_command(call: ServiceCall) -> None:
    """Run one of the app's room-wide commands, for one room or the whole hub.

    These are the Norman app's own room buttons: ``best_privacy`` puts the bottom rail at 0
    and the middle rail at 100 (the blackout across the window, the sheer stacked open), ``best_view``
    opens both rails, and ``favorite`` runs to the stored favorite position. Each is a
    single request to the hub, not one per blind, and ``favorite`` has no Home Assistant
    equivalent.

    Omit ``room`` to address every blind on the hub: the hub accepts all three verbs with no
    ``RoomID`` at all, which is what the app's own "All Rooms" screen sends. All three reach
    every blind whatever its rail count.

    ``refresh`` asks for fresh status instead: one ``StatusRequest`` per blind in a room, or
    one unscoped request for the whole hub, since ``RoomID`` does not confine that verb.
    ``stop`` sends the room's, or the hub's, one ``MotorStop``.

    ``blinds`` names blinds instead of a room: the command reaches exactly those, whatever
    Home Assistant area they are in (``_async_send_blind_command``).
    """
    command = str(call.data[ATTR_COMMAND])
    if ATTR_BLINDS in call.data:
        for hub, device_ids in _blinds_by_hub(call.hass, call):
            await _async_send_blind_command(hub, device_ids, command)
        return
    entry = _resolve_entry(call.hass, call)
    coordinator = entry.runtime_data
    wanted = call.data.get(ATTR_ROOM)

    if wanted is None:
        if command not in HUB_WIDE_COMMANDS:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="command_needs_a_room",
                translation_placeholders={
                    "command": command,
                    "commands": ", ".join(sorted(HUB_WIDE_COMMANDS)),
                },
            )
        await _async_send_room_fields(entry, None, command, None)
        return

    wanted = str(wanted)
    # Match the hub's own room names, case-insensitively; the areas Home Assistant seeded
    # from them may since have been renamed, so the hub name is what counts here.
    rooms = {
        device.room_name: device.room_id
        for device in coordinator.data.values()
        if device.room_name and device.room_id is not None
    }
    room_id = next(
        (rid for name, rid in rooms.items() if name.casefold() == wanted.casefold()), None
    )
    if room_id is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_room",
            translation_placeholders={
                "room": wanted,
                "rooms": ", ".join(sorted(rooms)) or "none",
            },
        )

    await _async_send_room_fields(entry, room_id, command, wanted)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions. Called once from async_setup."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_HUB_DATA,
        _async_get_hub_data,
        schema=GET_HUB_DATA_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ROOM_COMMAND,
        _async_room_command,
        schema=ROOM_COMMAND_SCHEMA,
    )
    # Admin only: it reaches the verbs that rewrite or wipe a blind's limits and pairing.
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_SEND_HUB_COMMAND,
        _async_send_hub_command,
        schema=SEND_HUB_COMMAND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
