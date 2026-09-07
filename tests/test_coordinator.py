"""Tests for data merging and the notification listener loop."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch

import aiohttp
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.norman.api import NormanConnectionError
from custom_components.norman.const import COVER_TYPE_SMARTDRAPE
from custom_components.norman.coordinator import NormanCoordinator

from .conftest import FakeHub, cover_entity_id, settle
from .const import UID_BEDROOM, UID_LIVING, UID_STATUS_ONLY, devices_payload, status_payload

process = NormanCoordinator._process_data


def test_process_data_merges_devices_and_status() -> None:
    """Room/group/name come from GetAllPeripheral, positions from status."""
    devices = process(devices_payload(), status_payload())

    assert set(devices) == {UID_LIVING, UID_BEDROOM, UID_STATUS_ONLY}

    living = devices[UID_LIVING]
    assert living.name == "Living Drape"
    assert living.type == COVER_TYPE_SMARTDRAPE
    assert (living.room_id, living.room_name) == (1, "Living Room")
    assert (living.group_id, living.group_name) == (10, "Windows")
    assert (living.module_type, living.module_detail) == (7, 2)
    assert (living.bottom_rail_position, living.middle_rail_position) == (40, 60)
    assert (living.target_bottom_rail_position, living.target_middle_rail_position) == (40, 60)
    assert living.battery_voltage == 12.4
    assert living.firmware_version == "1.2.3"
    assert living.last_update == "1700000000"

    # String UIDs are coerced so the two payloads line up
    assert devices[UID_BEDROOM].name == "Bedroom Drape"
    assert devices[UID_BEDROOM].bottom_rail_position == 0


def test_process_data_creates_placeholder_for_status_only_devices() -> None:
    """A peripheral in status but not in the device list still gets an entry."""
    devices = process(devices_payload(), status_payload())
    placeholder = devices[UID_STATUS_ONLY]
    assert placeholder.name == f"Norman {UID_STATUS_ONLY}"
    assert placeholder.room_name is None
    assert placeholder.bottom_rail_position == 100


def test_process_data_skips_malformed_uids() -> None:
    """Missing, non-numeric, and boolean UIDs are ignored rather than crashing."""
    status = status_payload()
    status["Peripherals"].append({"PeripheralUID": True, "BottomRailPosition": 5})
    devices = process(devices_payload(), status)
    assert True not in devices
    assert all(isinstance(uid, int) for uid in devices)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("55", 55), (150, 100), (-3, 0), ("x", None), (None, None), (True, None), (7.9, 7)],
)
def test_process_data_normalises_positions(raw: object, expected: int | None) -> None:
    """Positions are coerced to ints in 0-100, or None when unusable."""
    status = {"Peripherals": [{"PeripheralUID": 1, "BottomRailPosition": raw}]}
    assert process({}, status)[1].bottom_rail_position == expected


@pytest.mark.parametrize(
    ("device_info", "status"),
    [
        ({}, {}),
        ({"results": None}, {"Peripherals": None}),
        ({"results": "nope"}, {"Peripherals": []}),
        ({"results": {"RoomList": [{"GroupList": None}]}}, {}),
        ({"results": {"RoomList": [{"GroupList": [{"PeripheralList": None}]}]}}, {}),
    ],
)
def test_process_data_tolerates_missing_sections(device_info: dict, status: dict) -> None:
    """Any missing or null section yields no devices instead of an exception."""
    assert process(device_info, status) == {}


def test_process_data_defaults_missing_names() -> None:
    """An empty PeripheralName falls back to a generated one."""
    info = {
        "results": {
            "RoomList": [
                {"GroupList": [{"PeripheralList": [{"PeripheralUID": 5, "PeripheralName": ""}]}]}
            ]
        }
    }
    assert process(info, {})[5].name == "Norman 5"


# ---- listener loop ---------------------------------------------------------------------


async def test_notification_triggers_refresh(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Each notification re-reads status, without re-reading the device list."""
    device_calls = len(fake_hub.calls_to("GetAllPeripheral"))
    fake_hub.set_position(UID_LIVING, bottom=90)

    await notifications.put({"PeripheralList": [{"PeripheralUID": UID_LIVING}]})
    await settle(hass)

    assert hass.states.get(cover_entity_id(hass, UID_LIVING)).attributes["current_position"] == 90
    assert len(fake_hub.calls_to("GetAllPeripheral")) == device_calls


async def test_periodic_reconnect_refreshes_device_list(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """When the stream is cycled, the device list is re-read so new blinds are found."""
    device_calls = len(fake_hub.calls_to("GetAllPeripheral"))

    await notifications.put(None)
    await settle(hass)

    assert len(fake_hub.calls_to("GetAllPeripheral")) == device_calls + 1


async def test_stream_outage_is_logged_once_and_recovery_announced(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Repeated reconnect failures do not spam the log; recovery is reported once."""
    caplog.set_level(logging.DEBUG, logger="custom_components.norman")

    with patch("custom_components.norman.coordinator.RECONNECT_INTERVAL", 0):
        await notifications.put(NormanConnectionError("first drop"))
        await settle(hass)
        await notifications.put(NormanConnectionError("second drop"))
        await settle(hass)

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "first drop" in errors[0].message
        assert any("still down: second drop" in r.message for r in caplog.records)

        await notifications.put({"PeripheralList": []})
        await settle(hass)

    assert any(r.levelno == logging.INFO and "restored" in r.message for r in caplog.records)


async def test_hub_outage_makes_entities_unavailable_until_it_recovers(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """A failed refresh marks covers unavailable; the next good refresh restores them."""
    fake_hub.status_exc = aiohttp.ClientConnectionError("hub offline")
    await notifications.put({"PeripheralList": []})
    await settle(hass)
    assert hass.states.get(cover_entity_id(hass, UID_LIVING)).state == "unavailable"

    fake_hub.status_exc = None
    await notifications.put({"PeripheralList": []})
    await settle(hass)
    assert hass.states.get(cover_entity_id(hass, UID_LIVING)).state == "open"
