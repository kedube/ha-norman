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
from homeassistant.const import EntityCategory, UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import NormanConfigEntry
from .entity import NormanEntity, async_add_entities_for_new_devices
from .models import NormanPeripheralData

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
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value_fn=lambda data: data.battery_voltage,
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
        value_fn=lambda data: data.firmware_version,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NormanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Norman diagnostic sensors."""
    coordinator = entry.runtime_data

    def _sensors_for(device_id: int) -> list[NormanSensor]:
        return [NormanSensor(coordinator, device_id, entry, description) for description in SENSORS]

    async_add_entities_for_new_devices(entry, async_add_entities, _sensors_for)


class NormanSensor(NormanEntity, SensorEntity):
    """A read-only value the hub reports for one peripheral."""

    entity_description: NormanSensorDescription

    def __init__(
        self,
        coordinator: Any,
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
