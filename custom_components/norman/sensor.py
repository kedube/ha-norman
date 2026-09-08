"""Diagnostic sensors for Norman peripherals."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import NormanConfigEntry, NormanCoordinator
from .entity import NormanEntity, NormanHubEntity, async_add_entities_for_new_devices
from .models import NormanHubData, NormanPeripheralData

_LOGGER = logging.getLogger(__name__)

# Push-updated by the coordinator; nothing to throttle.
PARALLEL_UPDATES = 0


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


@dataclass(frozen=True, kw_only=True)
class NormanSensorDescription(SensorEntityDescription):
    """Describes a Norman sensor and how to read it from the peripheral data."""

    value_fn: Callable[[NormanPeripheralData], Any]


SENSORS: tuple[NormanSensorDescription, ...] = (
    NormanSensorDescription(
        key="battery_level",
        translation_key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.battery_level,
    ),
    NormanSensorDescription(
        key="signal_strength",
        translation_key="signal_strength",
        # RssiMean is a unitless quality index (0 or 34 seen), not dBm, so no device class
        icon="mdi:signal",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.signal_strength,
    ),
    NormanSensorDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: parse_last_update(data.last_update),
    ),
    NormanSensorDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        # Already shown on the device page as sw_version; the sensor is for people who
        # want to automate on it or keep history, so it is opt-in.
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.display_firmware_version,
    ),
)


@dataclass(frozen=True, kw_only=True)
class NormanHubSensorDescription(SensorEntityDescription):
    """Describes a sensor on the hub device."""

    value_fn: Callable[[NormanHubData], Any]


HUB_SENSORS: tuple[NormanHubSensorDescription, ...] = (
    NormanHubSensorDescription(
        key="wifi_rssi",
        translation_key="wifi_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda hub: hub.wifi_rssi,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NormanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Norman diagnostic sensors."""
    coordinator = entry.runtime_data

    async_add_entities(
        NormanHubSensor(coordinator, entry, description) for description in HUB_SENSORS
    )

    def _sensors_for(device_id: int) -> list[NormanSensor]:
        return [NormanSensor(coordinator, device_id, entry, description) for description in SENSORS]

    async_add_entities_for_new_devices(entry, async_add_entities, _sensors_for)


class NormanHubSensor(NormanHubEntity, SensorEntity):
    """A value the hub reports about itself."""

    entity_description: NormanHubSensorDescription

    def __init__(
        self,
        coordinator: NormanCoordinator,
        entry: NormanConfigEntry,
        description: NormanHubSensorDescription,
    ) -> None:
        """Initialize the hub sensor."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return the value from the hub's latest status."""
        return self.entity_description.value_fn(self.coordinator.hub)


class NormanSensor(NormanEntity, SensorEntity):
    """A read-only value the hub reports for one peripheral."""

    entity_description: NormanSensorDescription

    def __init__(
        self,
        coordinator: NormanCoordinator,
        device_id: int,
        entry: NormanConfigEntry,
        description: NormanSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, entry)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return the value from the latest coordinator data."""
        data = self._data
        return self.entity_description.value_fn(data) if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """On the firmware sensor, both raw versions the hub reports."""
        if self.entity_description.key != "firmware_version" or not (data := self._data):
            return None
        return {
            "module_firmware": data.firmware_version,
            "rf_firmware": data.rf_firmware_version,
        }
