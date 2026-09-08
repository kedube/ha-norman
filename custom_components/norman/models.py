"""Data models for Norman integration."""

from __future__ import annotations

from dataclasses import dataclass


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
    bottom_rail_position: int | None = None
    middle_rail_position: int | None = None
    target_bottom_rail_position: int | None = None
    target_middle_rail_position: int | None = None
    battery_level: int | None = None  # percent; the hub calls the field BatteryVoltage
    signal_strength: int | None = None  # RssiMean, a unitless radio quality index
    firmware_version: str | None = None
    rf_firmware_version: str | None = None
    last_update: str | None = None


@dataclass
class NormanHubData:
    """What the hub reports about itself."""

    model: str | None = None  # "NienMadeHub" on the hubs seen so far
    firmware_version: str | None = None
    custom_name: str | None = None  # the name given in the Norman app
    wifi_rssi: int | None = None  # dBm
    ota_in_progress: bool | None = None
    pairing_mode: int | None = None


# Represents all peripherals keyed by their ID
type NormanDevices = dict[int, NormanPeripheralData]
