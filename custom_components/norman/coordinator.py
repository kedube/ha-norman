"""Data update coordinator for Norman devices."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NormanApiClient, NormanApiError, NormanConnectionError
from .const import COVER_TYPE_SMARTDRAPE, DOMAIN, RECONNECT_INTERVAL
from .models import NormanDevices, NormanPeripheralData

_LOGGER = logging.getLogger(__name__)

type NormanConfigEntry = ConfigEntry[NormanCoordinator]


class NormanCoordinator(DataUpdateCoordinator[NormanDevices]):
    """Norman data update coordinator.

    The hub pushes state changes over a long-poll (see ``listen_notifications``), so there
    is no polling interval: every notification, reconnect, and command triggers a refresh.
    """

    config_entry: NormanConfigEntry

    def __init__(self, hass: HomeAssistant, entry: NormanConfigEntry, api: NormanApiClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data.get('host', '')}".strip(),
            update_interval=None,
        )
        self.api = api
        # Registry id of the hub device, set by async_setup_entry once it is created
        self.hub_device_id: str | None = None
        self._device_info: dict[str, Any] = {}
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
            else:
                # The stream was cycled on purpose after NOTIF_MAX_DURATION; reconnect
                # right away.
                _LOGGER.debug("Reconnecting notification listener")

            # Re-fetch the device list and states before the next connection so anything
            # that changed while the stream was down (or a newly paired blind) is picked up.
            self._device_info = {}
            await self.async_refresh()

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

        return self._process_data(self._device_info, status_data)

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
        for room in room_list or []:
            room_id = room.get("RoomID")
            room_name = room.get("RoomName", "")

            for group in room.get("GroupList") or []:
                group_id = group.get("GroupID")
                group_name = group.get("GroupName", "")

                for peripheral in group.get("PeripheralList") or []:
                    peripheral_uid = _parse_uid(peripheral.get("PeripheralUID"))
                    if peripheral_uid is None:
                        continue

                    devices[peripheral_uid] = NormanPeripheralData(
                        id=peripheral_uid,
                        name=peripheral.get("PeripheralName") or f"Norman {peripheral_uid}",
                        # TODO: derive the cover type from ModuleType once other kinds of
                        # blinds have been mapped; everything is treated as SmartDrape.
                        type=COVER_TYPE_SMARTDRAPE,
                        room_id=room_id,
                        room_name=room_name,
                        group_id=group_id,
                        group_name=group_name,
                        module_type=peripheral.get("ModuleType"),
                        module_detail=peripheral.get("ModuleDetail"),
                    )

        # Add status information
        for peripheral in status_data.get("Peripherals") or []:
            peripheral_uid = _parse_uid(peripheral.get("PeripheralUID"))
            if peripheral_uid is None:
                continue

            if peripheral_uid not in devices:
                # Create minimal device if not found in device_info
                devices[peripheral_uid] = NormanPeripheralData(
                    id=peripheral_uid,
                    name=f"Norman {peripheral_uid}",
                    type=COVER_TYPE_SMARTDRAPE,
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
            device.battery_voltage = peripheral.get("BatteryVoltage")
            device.firmware_version = peripheral.get("FirmwareVersion")
            device.last_update = peripheral.get("Timestamp")

        return devices


def _parse_uid(raw: Any) -> int | None:
    """Coerce a PeripheralUID to int, or None if it is missing or malformed."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_position(raw: Any) -> int | None:
    """Coerce a rail position to an int clamped to 0-100, or None if unusable."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return max(0, min(100, int(raw)))
    except (TypeError, ValueError):
        return None
