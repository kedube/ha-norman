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


# Represents all peripherals keyed by their ID
type NormanDevices = dict[int, NormanPeripheralData]
