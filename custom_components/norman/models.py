"""Data models for Norman integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import UNRESPONSIVE_AFTER


def parse_last_update(raw: Any) -> datetime | None:
    """Turn the hub's ``Timestamp`` into an aware datetime.

    The hub's exact format is not documented. Unix seconds (as a number or numeric
    string) are the observed form; millisecond epochs and ISO 8601 strings are accepted
    too so a firmware change does not silently blank the sensor. Anything else is None.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        parsed = dt_util.parse_datetime(str(raw)) if isinstance(raw, str) else None
        return dt_util.as_utc(parsed) if parsed else None
    if value <= 0:
        return None
    if value > 1e11:  # milliseconds since the epoch
        value /= 1000
    try:
        return dt_util.utc_from_timestamp(value)
    except (OverflowError, OSError, ValueError):
        return None


@dataclass
class NormanPeripheralData:
    """Local model for storing Norman peripheral data."""

    id: int
    name: str
    type: str
    room_id: int | None = None
    room_name: str | None = None
    group_id: int | None = None
    group_name: str | None = None
    module_type: int | None = None
    module_detail: int | None = None
    stack: str | None = None  # a SmartDrape's MSDStackType: "left", "right" or "split"
    bottom_rail_position: int | None = None
    middle_rail_position: int | None = None
    target_bottom_rail_position: int | None = None
    target_middle_rail_position: int | None = None
    position: int | None = None  # a Shutter's louvers, 0-7 (the hub's Position)
    target_position: int | None = None  # TargetPosition
    battery_level: int | None = None  # percent; the hub calls the field BatteryVoltage
    signal_strength: int | None = None  # RssiMean, a unitless radio quality index
    firmware_version: str | None = None  # the hub's FirmwareVersion field
    rf_firmware_version: str | None = None  # RfFirmwareVersion, single-rail blinds only
    last_update: str | None = None

    @property
    def display_firmware_version(self) -> str | None:
        """The version the Norman app shows for this blind.

        Single-rail blinds report two versions and the app shows ``RfFirmwareVersion``
        (Den_1: app 0.3.20, hub FirmwareVersion 4.1.0.4). Two-rail blinds report only
        ``FirmwareVersion``. So: the radio firmware when present, otherwise the only one.
        """
        return self.rf_firmware_version or self.firmware_version

    def disconnected(self, now: datetime) -> bool | None:
        """Whether the hub has not heard from this blind for ``UNRESPONSIVE_AFTER``.

        None when undated. The threshold is the Norman app's for "Disconnect", applied to the
        hub's own last-heard time. The connection sensor shows it, and the wake sweep asks
        only these blinds to report in.
        """
        last_seen = parse_last_update(self.last_update)
        if last_seen is None:
            return None
        return now - last_seen > UNRESPONSIVE_AFTER


@dataclass
class NormanHubData:
    """What the hub reports about itself."""

    model: str | None = None  # "NienMadeHub" on the hubs seen so far
    firmware_version: str | None = None
    custom_name: str | None = None  # the name given in the Norman app
    mac_address: str | None = None  # resolved from the network; the hub never reports it
    time_zone: str | None = None  # IANA name, as configured in the app
    wifi_ssid: str | None = None
    wifi_rssi: int | None = None  # dBm
    ota_in_progress: bool | None = None
    pairing_mode: int | None = None


@dataclass(frozen=True)
class NormanSceneTarget:
    """Where a saved scene sends one blind, as the hub stored it.

    The hub stores every rail field for every blind, whatever its type: a Shutter's louvers
    are ``position``, every other blind's rails are ``bottom`` and ``middle``.
    """

    bottom: int | None = None
    middle: int | None = None
    position: int | None = None


def scene_key(room_id: int, scene_id: int) -> str:
    """A key for a room scene that is unique on the hub: scene ids are numbered per room."""
    return f"{room_id}_{scene_id}"


@dataclass
class NormanScene:
    """A scene saved in one of the hub's rooms, as the Norman app makes them."""

    room_id: int
    scene_id: int
    name: str
    targets: dict[int, NormanSceneTarget]
    # The hub's name for the room, which names its device when the room holds no blind.
    room_name: str = ""

    @property
    def key(self) -> str:
        """This scene's ``scene_key``."""
        return scene_key(self.room_id, self.scene_id)


@dataclass
class NormanSceneGroup:
    """Room scenes the hub runs together, across rooms (the app's scene groups)."""

    group_id: str
    name: str
    scene_keys: list[str]  # NormanScene.key of each member scene


# Represents all peripherals keyed by their ID
type NormanDevices = dict[int, NormanPeripheralData]
