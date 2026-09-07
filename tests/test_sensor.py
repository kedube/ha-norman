"""Tests for the diagnostic sensors."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_UNIT_OF_MEASUREMENT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.norman.const import DOMAIN
from custom_components.norman.sensor import parse_last_update

from .conftest import FakeHub, settle
from .const import UID_LIVING, UID_STATUS_ONLY


def sensor_entity_id(hass: HomeAssistant, uid: int, key: str) -> str:
    """Resolve a sensor's entity id from its unique id."""
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{uid}_{key}")
    assert entity_id, f"no {key} sensor for peripheral {uid}"
    return entity_id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1700000000", datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)),
        (1700000000, datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)),
        (1700000000000, datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)),
        ("2023-11-14T22:13:20+00:00", datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)),
        ("2023-11-14T23:13:20+01:00", datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)),
        (None, None),
        (0, None),
        (True, None),
        ("soon", None),
        (1e30, None),
    ],
)
def test_parse_last_update(raw: object, expected: datetime | None) -> None:
    """Epoch seconds, epoch milliseconds, and ISO strings all parse; junk is None."""
    assert parse_last_update(raw) == expected


async def test_battery_and_last_seen_sensors(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Battery voltage and last-seen are diagnostic entities with the right classes."""
    battery = hass.states.get(sensor_entity_id(hass, UID_LIVING, "battery_voltage"))
    assert battery.state == "12.4"
    assert battery.attributes[ATTR_UNIT_OF_MEASUREMENT] == "V"
    assert battery.attributes[ATTR_DEVICE_CLASS] == "voltage"
    assert battery.attributes["friendly_name"] == "Living Drape Battery voltage"

    last_seen = hass.states.get(sensor_entity_id(hass, UID_LIVING, "last_seen"))
    assert last_seen.state == "2023-11-14T22:13:20+00:00"
    assert last_seen.attributes[ATTR_DEVICE_CLASS] == "timestamp"

    registry = er.async_get(hass)
    for key in ("battery_voltage", "last_seen"):
        entry = registry.async_get(sensor_entity_id(hass, UID_LIVING, key))
        assert entry.entity_category is EntityCategory.DIAGNOSTIC
        assert entry.disabled_by is None


async def test_firmware_sensor_is_opt_in(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Firmware is already on the device page, so its sensor starts disabled."""
    entry = er.async_get(hass).async_get(sensor_entity_id(hass, UID_LIVING, "firmware_version"))
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entry.entity_category is EntityCategory.DIAGNOSTIC


async def test_missing_values_are_unknown(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A peripheral that reports no battery or timestamp shows unknown, not an error."""
    assert hass.states.get(sensor_entity_id(hass, UID_STATUS_ONLY, "battery_voltage")).state == (
        "unknown"
    )
    assert hass.states.get(sensor_entity_id(hass, UID_STATUS_ONLY, "last_seen")).state == "unknown"


async def test_sensors_follow_hub_updates(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """A notification refresh updates the sensors like the covers."""
    fake_hub.peripheral_status(UID_LIVING)["BatteryVoltage"] = 11.75
    await notifications.put({"PeripheralList": []})
    await settle(hass)

    assert hass.states.get(sensor_entity_id(hass, UID_LIVING, "battery_voltage")).state == "11.75"


async def test_sensors_are_created_for_new_blinds(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Sensors use the same dynamic-add path as covers."""
    fake_hub.devices["results"]["RoomList"][0]["GroupList"][0]["PeripheralList"].append(
        {"PeripheralUID": 2001, "PeripheralName": "Hall Drape", "ModuleType": 7}
    )
    fake_hub.status["Peripherals"].append({"PeripheralUID": 2001, "BatteryVoltage": 12.0})

    await notifications.put(None)
    await settle(hass)

    assert hass.states.get(sensor_entity_id(hass, 2001, "battery_voltage")).state == "12.0"
