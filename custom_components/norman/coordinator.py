"""Data update coordinator for Norman devices."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NormanApiClient, NormanApiError, NormanConnectionError
from .const import (
    CONF_POLL_INTERVAL,
    DEFAULT_COVER_TYPE,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    KNOWN_HUB_FIELDS,
    KNOWN_PERIPHERAL_FIELDS,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    MODULE_TYPE_COVER_TYPES,
    POLL_DISABLED,
    RECONNECT_INTERVAL,
)
from .models import NormanDevices, NormanHubData, NormanPeripheralData

_LOGGER = logging.getLogger(__name__)

type NormanConfigEntry = ConfigEntry[NormanCoordinator]


def hub_identifier(entry: ConfigEntry) -> str:
    """Device-registry identifier of the hub device for ``entry``."""
    return f"hub_{entry.entry_id}"


def _poll_interval(entry: NormanConfigEntry) -> timedelta | None:
    """The configured poll interval, or None when polling is switched off.

    ``POLL_DISABLED`` (0) means "push only": returning None leaves the coordinator without
    an ``update_interval``, so it refreshes solely on notifications and commands.

    A value that is missing, non-numeric, or out of range falls back to the default rather
    than raising: options are user input, and a bad one should not stop the integration from
    loading. 0 is the one value outside the range that is honoured rather than corrected.
    """
    raw = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        return timedelta(seconds=DEFAULT_POLL_INTERVAL)
    if seconds == POLL_DISABLED:
        return None
    if not MIN_POLL_INTERVAL <= seconds <= MAX_POLL_INTERVAL:
        seconds = DEFAULT_POLL_INTERVAL
    return timedelta(seconds=seconds)


class NormanCoordinator(DataUpdateCoordinator[NormanDevices]):
    """Norman data update coordinator.

    The hub pushes state changes over a long-poll (see ``listen_notifications``): every
    notification, reconnect, and command triggers a refresh. A slow poll backs that up,
    because a sleeping blind generates no notifications and its cached position would
    otherwise go stale without ever being corrected. The interval is configurable in the
    integration's options; the entry is reloaded when it changes.
    """

    config_entry: NormanConfigEntry

    def __init__(self, hass: HomeAssistant, entry: NormanConfigEntry, api: NormanApiClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data.get('host', '')}".strip(),
            update_interval=_poll_interval(entry),
        )
        self.api = api
        # Registry id of the hub device, set by async_setup_entry once it is created
        self.hub_device_id: str | None = None
        # What the hub says about itself; refreshed alongside the peripherals
        self.hub = NormanHubData(model=api.hub_model, firmware_version=api.hub_firmware_version)
        self._device_info: dict[str, Any] = {}
        self._unknown_fields: set[tuple[str, str]] = set()
        self._unknown_module_types: set[int | None] = set()
        # True while the notification stream is known to be down, so that the outage is
        # logged once at error level rather than on every reconnect attempt.
        self._listener_offline = False

    async def listen_notifications(self) -> None:
        """Continuously listen for hub notifications and refresh data on change.

        Runs as a config-entry background task; cancellation ends the loop.
        """
        while True:
            try:
                async for notification in self.api.async_listen_notifications():
                    _LOGGER.debug("Received notification: %s", notification)
                    if self._listener_offline:
                        self._listener_offline = False
                        _LOGGER.info("Norman hub notification stream restored")
                    if self._structure_changed(notification):
                        # A rename, room edit, or hub rename in the Norman app: re-read
                        # the device list so names and rooms follow.
                        self._device_info = {}
                    await self.async_refresh()
            except NormanConnectionError as err:
                if not self._listener_offline:
                    self._listener_offline = True
                    _LOGGER.error(
                        "Notification listener disconnected: %s; retrying every %s seconds",
                        err,
                        RECONNECT_INTERVAL,
                    )
                else:
                    _LOGGER.debug("Notification listener still down: %s", err)
                await asyncio.sleep(RECONNECT_INTERVAL)
            except Exception:  # noqa: BLE001 - the listener must outlive any single failure
                # POLL_INTERVAL would keep state moving, but at a fraction of the push
                # path's responsiveness. Letting an unexpected error escape the loop would
                # leave the integration loaded and apparently healthy while every change made
                # at a remote or in the app went unnoticed until the next poll -- a far worse
                # failure than a logged exception and a retry. async_refresh() is inside the try above and reaches
                # the device registry, so this is not merely theoretical.
                _LOGGER.exception(
                    "Unexpected error in the Norman notification listener; retrying in %s seconds",
                    RECONNECT_INTERVAL,
                )
                await asyncio.sleep(RECONNECT_INTERVAL)
            else:
                # The stream was cycled on purpose after NOTIF_MAX_DURATION; reconnect
                # right away.
                _LOGGER.debug("Reconnecting notification listener")

            # Re-fetch the device list and states before the next connection so anything
            # that changed while the stream was down (or a newly paired blind) is picked up.
            self._device_info = {}
            await self.async_refresh()

    @staticmethod
    def _structure_changed(notification: dict[str, Any]) -> bool:
        """Whether a notification says the room / blind / hub metadata changed.

        ``UpdateTime`` carries one key per changed thing: ``room``, ``peripheral``,
        ``device`` (the hub itself), or ``schedule``. Schedules are not modelled, so they
        do not invalidate anything.
        """
        update = notification.get("UpdateTime")
        if not isinstance(update, dict):
            return False
        return any(key != "schedule" for key in update)

    async def _async_update_data(self) -> NormanDevices:
        """Fetch data from API.

        Returns:
            Dictionary with peripheral data keyed by device ID

        Raises:
            UpdateFailed: If the update operation fails

        """
        try:
            # The device list rarely changes, so it is only re-read when it has been
            # invalidated (first refresh, or a listener reconnect).
            if not self._device_info:
                self._device_info = await self.api.async_get_devices()

            # Status is the lightweight call that carries positions
            status_data = await self.api.async_get_status()
        except NormanConnectionError as err:
            raise UpdateFailed(f"Error communicating with Norman hub: {err}") from err
        except NormanApiError as err:
            raise UpdateFailed(f"Invalid response from Norman hub: {err}") from err

        self._log_unknown_fields(self._device_info, status_data)
        self._update_hub_data(self._device_info, status_data)
        devices = self._process_data(self._device_info, status_data)
        self._warn_about_unknown_module_types(devices)
        self._sync_device_names(devices)
        return devices

    def _sync_device_names(self, devices: NormanDevices) -> None:
        """Carry renames made in the Norman app into the device registry.

        Devices are named when they are created and Home Assistant does not re-read
        ``DeviceInfo`` afterwards, so the hub's names are pushed here. A name the user set
        in Home Assistant (``name_by_user``) is untouched: it always takes precedence.
        """
        registry = dr.async_get(self.hass)
        wanted = {str(device_id): data.name for device_id, data in devices.items()}
        if self.hub_device_id and self.hub.custom_name:
            wanted[hub_identifier(self.config_entry)] = self.hub.custom_name
        # Devices are looked up through the entry rather than by identifier: identifiers
        # are no longer unique across config entries in Home Assistant 2026.9.
        for device in dr.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            for domain, identifier in device.identifiers:
                name = wanted.get(identifier) if domain == DOMAIN else None
                if name and device.name != name:
                    registry.async_update_device(device.id, name=name)

    def _update_hub_data(self, device_info: dict[str, Any], status_data: dict[str, Any]) -> None:
        """Refresh the hub's own attributes from the two payloads."""
        results = device_info.get("results")
        if isinstance(results, dict):
            self.hub.custom_name = results.get("CustomDeviceName") or self.hub.custom_name
            self.hub.time_zone = results.get("TimeZone") or self.hub.time_zone
        self.hub.model = self.api.hub_model or self.hub.model
        self.hub.firmware_version = self.api.hub_firmware_version or self.hub.firmware_version
        self.hub.wifi_ssid = self.api.hub_wifi_ssid or self.hub.wifi_ssid
        rssi = status_data.get("WiFiRSSI")
        self.hub.wifi_rssi = int(rssi) if isinstance(rssi, int | float) else None
        ota = status_data.get("OTA")
        self.hub.ota_in_progress = bool(ota) if ota is not None else None
        pairing = status_data.get("PairingMode")
        self.hub.pairing_mode = int(pairing) if isinstance(pairing, int) else None

    def _log_unknown_fields(self, *payloads: dict[str, Any]) -> None:
        """Note any field the hub sends that this integration has never seen.

        The hub's protocol is reverse-engineered, so a firmware update or an unmapped
        product can start sending fields nobody has documented. Each new name is logged once
        per Home Assistant run at debug level (not warning: an unknown field is interesting,
        not a problem) so that turning on debug logging for a while is enough to find them.
        """
        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        for payload in payloads:
            results = payload.get("results")
            top: dict[str, Any] = results if isinstance(results, dict) else payload
            self._note_unknown("hub", KNOWN_HUB_FIELDS, top)
            for peripheral in top.get("Peripherals") or []:
                if isinstance(peripheral, dict):
                    self._note_unknown("peripheral", KNOWN_PERIPHERAL_FIELDS, peripheral)
            for room in top.get("RoomList") or []:
                if not isinstance(room, dict):
                    continue
                for group in room.get("GroupList") or []:
                    if not isinstance(group, dict):
                        continue
                    for peripheral in group.get("PeripheralList") or []:
                        if isinstance(peripheral, dict):
                            self._note_unknown("peripheral", KNOWN_PERIPHERAL_FIELDS, peripheral)

    def _note_unknown(self, scope: str, known: frozenset[str], payload: dict[str, Any]) -> None:
        """Log each field in ``payload`` that is not in ``known``, once per name."""
        for field in payload:
            if field in known or (scope, field) in self._unknown_fields:
                continue
            self._unknown_fields.add((scope, field))
            _LOGGER.debug(
                "Norman hub sent an undocumented %s field %r (value %r). Please open an issue "
                "at https://github.com/kedube/ha-norman/issues so it can be documented",
                scope,
                field,
                payload[field],
            )

    def _warn_about_unknown_module_types(self, devices: NormanDevices) -> None:
        """Log once per unknown ModuleType so owners can report it."""
        for device in devices.values():
            if (
                device.module_type in MODULE_TYPE_COVER_TYPES
                or device.module_type in self._unknown_module_types
            ):
                continue
            self._unknown_module_types.add(device.module_type)
            _LOGGER.warning(
                "Norman peripheral %s (%s) reports unknown ModuleType %s/%s; treating it as a "
                "two-rail blind. Please run the norman.get_hub_data action and open an issue "
                "with the result so the type can be mapped",
                device.id,
                device.name,
                device.module_type,
                device.module_detail,
            )

    @staticmethod
    def _process_data(device_info: dict[str, Any], status_data: dict[str, Any]) -> NormanDevices:
        """Process and combine data from GetAllPeripheral and status endpoints.

        Args:
            device_info: Data from GetAllPeripheral endpoint
            status_data: Data from status endpoint

        Returns:
            Combined data keyed by device ID

        """
        devices: NormanDevices = {}

        # Process device information (names, room, group)
        results = device_info.get("results")
        room_list = results.get("RoomList") if isinstance(results, dict) else None
        for room in _dicts(room_list):
            room_id = room.get("RoomID")
            room_name = room.get("RoomName", "")

            for group in _dicts(room.get("GroupList")):
                group_id = group.get("GroupID")
                group_name = group.get("GroupName", "")

                for peripheral in _dicts(group.get("PeripheralList")):
                    peripheral_uid = _parse_uid(peripheral.get("PeripheralUID"))
                    if peripheral_uid is None:
                        continue

                    module_type = _parse_int(peripheral.get("ModuleType"))
                    devices[peripheral_uid] = NormanPeripheralData(
                        id=peripheral_uid,
                        name=peripheral.get("PeripheralName") or f"Norman {peripheral_uid}",
                        type=_cover_type(module_type),
                        room_id=_parse_int(room_id),
                        room_name=room_name,
                        group_id=_parse_int(group_id),
                        group_name=group_name,
                        module_type=module_type,
                        module_detail=_parse_int(peripheral.get("ModuleDetail")),
                    )

        # Add status information
        for peripheral in _dicts(status_data.get("Peripherals")):
            peripheral_uid = _parse_uid(peripheral.get("PeripheralUID"))
            if peripheral_uid is None:
                continue

            if peripheral_uid not in devices:
                # Create minimal device if not found in device_info
                module_type = _parse_int(peripheral.get("ModuleType"))
                devices[peripheral_uid] = NormanPeripheralData(
                    id=peripheral_uid,
                    name=f"Norman {peripheral_uid}",
                    type=_cover_type(module_type),
                    module_type=module_type,
                    module_detail=_parse_int(peripheral.get("ModuleDetail")),
                )

            device = devices[peripheral_uid]
            device.bottom_rail_position = _parse_position(peripheral.get("BottomRailPosition"))
            device.middle_rail_position = _parse_position(peripheral.get("MiddleRailPosition"))
            device.target_bottom_rail_position = _parse_position(
                peripheral.get("TargetBottomRailPosition")
            )
            device.target_middle_rail_position = _parse_position(
                peripheral.get("TargetMiddleRailPosition")
            )
            # Despite its name the field is a 0-100 level on every hub seen so far
            device.battery_level = _parse_position(peripheral.get("BatteryVoltage"))
            device.signal_strength = _parse_int(peripheral.get("RssiMean"))
            device.firmware_version = peripheral.get("FirmwareVersion") or None
            device.rf_firmware_version = peripheral.get("RfFirmwareVersion") or None
            device.last_update = peripheral.get("Timestamp")

        return devices


def _cover_type(module_type: int | None) -> str:
    """The cover type for a ModuleType, defaulting when it is unknown or missing."""
    if module_type is None:
        return DEFAULT_COVER_TYPE
    return MODULE_TYPE_COVER_TYPES.get(module_type, DEFAULT_COVER_TYPE)


def _dicts(raw: Any) -> list[dict[str, Any]]:
    """The dict entries of ``raw``, or an empty list if it is not a list of dicts.

    The hub's payloads are reverse-engineered and unvalidated, so a firmware change (or a
    partial write) can put a string, a null, or a scalar where a list of objects belongs.
    Reaching ``.get()`` on one of those raises AttributeError out of ``_async_update_data``,
    which Home Assistant catches -- but only by logging a stack trace and marking EVERY
    entity on the hub unavailable, for what may be one malformed record among twenty.
    Skipping what cannot be read keeps the rest of the house working, and matches the
    isinstance guards ``_log_unknown_fields`` already applies to the same structures.
    """
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _parse_int(raw: Any) -> int | None:
    """Coerce a value the hub sends as int in one payload and str in another.

    ``bool`` is rejected explicitly: it is an ``int`` subclass, so a stray ``true`` would
    otherwise become 1 and read as a real id or position.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# A PeripheralUID parses exactly like any other hub int; the alias keeps the call sites
# reading as what they are without a second identical implementation to keep in step.
_parse_uid = _parse_int


def _parse_position(raw: Any) -> int | None:
    """Coerce a rail position to an int clamped to 0-100, or None if unusable."""
    value = _parse_int(raw)
    return None if value is None else max(0, min(100, value))
