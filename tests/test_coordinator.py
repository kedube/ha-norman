"""Tests for data merging and the notification listener loop."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from unittest.mock import patch

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.norman.api import NormanConnectionError
from custom_components.norman.const import (
    CONF_POLL_INTERVAL,
    COVER_TYPE_SINGLE_RAIL,
    COVER_TYPE_TWO_RAIL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    POLL_DISABLED,
)
from custom_components.norman.coordinator import NormanCoordinator, _poll_interval
from custom_components.norman.entity import hub_identifier

from .conftest import HUB_MAC, FakeHub, cover_entity_id, settle
from .const import (
    HUB_SSID,
    MOCK_CONFIG,
    UID_BEDROOM,
    UID_LIVING,
    UID_STATUS_ONLY,
    devices_payload,
    status_payload,
)

process = NormanCoordinator._process_data


def test_process_data_merges_devices_and_status() -> None:
    """Room/group/name come from GetAllPeripheral, positions from status."""
    devices = process(devices_payload(), status_payload())

    assert set(devices) == {UID_LIVING, UID_BEDROOM, UID_STATUS_ONLY}

    living = devices[UID_LIVING]
    assert living.name == "Living Drape"
    assert living.type == COVER_TYPE_TWO_RAIL
    assert (living.room_id, living.room_name) == (1, "Living Room")
    assert (living.group_id, living.group_name) == (10, "Windows")
    assert (living.module_type, living.module_detail) == (33, 3)  # strings coerced
    assert (living.bottom_rail_position, living.middle_rail_position) == (40, 60)
    assert (living.target_bottom_rail_position, living.target_middle_rail_position) == (40, 60)
    assert living.battery_level == 73
    assert living.signal_strength == 34
    assert living.firmware_version == "0.5.3.8"
    assert living.rf_firmware_version is None
    assert living.last_update == 1700000000

    # String UIDs are coerced so the two payloads line up; ModuleType 32 is single-rail
    bedroom = devices[UID_BEDROOM]
    assert bedroom.name == "Bedroom Shade"
    assert bedroom.type == COVER_TYPE_SINGLE_RAIL
    assert bedroom.bottom_rail_position == 0
    assert bedroom.rf_firmware_version == "0.3.20"


def test_process_data_creates_placeholder_for_status_only_devices() -> None:
    """A peripheral in status but not in the device list still gets an entry."""
    devices = process(devices_payload(), status_payload())
    placeholder = devices[UID_STATUS_ONLY]
    assert placeholder.name == f"Norman {UID_STATUS_ONLY}"
    assert placeholder.room_name is None
    assert placeholder.bottom_rail_position == 100
    assert placeholder.module_type is None
    assert placeholder.type == COVER_TYPE_TWO_RAIL  # the default for unknown types


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


@pytest.mark.parametrize(
    ("device_info", "status"),
    [
        # A list replaced by a scalar, at each level of the nesting.
        ({"results": {"RoomList": "nope"}}, {}),
        ({"results": {"RoomList": [{"GroupList": "nope"}]}}, {}),
        ({"results": {"RoomList": [{"GroupList": [{"PeripheralList": "nope"}]}]}}, {}),
        ({}, {"Peripherals": "nope"}),
        # A list whose *entries* are not objects, at each level.
        ({"results": {"RoomList": ["nope"]}}, {}),
        ({"results": {"RoomList": [{"GroupList": ["nope"]}]}}, {}),
        ({"results": {"RoomList": [{"GroupList": [{"PeripheralList": ["nope"]}]}]}}, {}),
        ({}, {"Peripherals": ["nope"]}),
    ],
)
def test_process_data_survives_wrongly_typed_sections(device_info: dict, status: dict) -> None:
    """A section of the wrong type is skipped, not fatal.

    These all used to raise AttributeError straight out of ``_async_update_data``. Home
    Assistant catches that, but only by logging a stack trace and marking every entity on
    the hub unavailable -- so one malformed record took the whole house offline.
    """
    assert process(device_info, status) == {}


def test_process_data_keeps_good_records_alongside_malformed_ones() -> None:
    """One unreadable peripheral must not cost the user the blinds either side of it.

    This is the property that matters in practice: skipping bad data is only an improvement
    over failing if the *rest* of the payload still produces working entities.
    """
    devices = process(
        {
            "results": {
                "RoomList": [
                    "not-a-room",
                    {
                        "RoomID": 7,
                        "RoomName": "Den",
                        "GroupList": [
                            "not-a-group",
                            {
                                "GroupID": 1,
                                "PeripheralList": [
                                    "not-a-peripheral",
                                    {
                                        "PeripheralUID": 42,
                                        "PeripheralName": "Good blind",
                                        "ModuleType": 33,
                                    },
                                ],
                            },
                        ],
                    },
                ]
            }
        },
        {"Peripherals": ["not-a-peripheral", {"PeripheralUID": 42, "BottomRailPosition": 60}]},
    )

    assert list(devices) == [42]
    assert devices[42].name == "Good blind"
    assert devices[42].room_name == "Den"
    assert devices[42].bottom_rail_position == 60


def test_battery_level_is_a_clamped_percentage() -> None:
    """BatteryVoltage is a 0-100 level despite its name; junk becomes None."""
    status = {
        "Peripherals": [
            {"PeripheralUID": 1, "BatteryVoltage": "85"},
            {"PeripheralUID": 2, "BatteryVoltage": 130},
            {"PeripheralUID": 3, "BatteryVoltage": "low"},
        ]
    }
    devices = process({}, status)
    assert [devices[i].battery_level for i in (1, 2, 3)] == [85, 100, None]


async def test_unknown_module_type_is_warned_about_once(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A ModuleType the integration has not mapped is logged once, with the report hint."""

    def unknown_type_warnings() -> list[str]:
        # Setup happens in the fixture, so look at both the setup and call phases
        records = [*caplog.get_records("setup"), *caplog.get_records("call")]
        return [r.message for r in records if "unknown ModuleType" in r.message]

    warnings = unknown_type_warnings()
    assert len(warnings) == 1  # the status-only peripheral has no type at all
    assert f"peripheral {UID_STATUS_ONLY}" in warnings[0]
    assert "norman.get_hub_data" in warnings[0]

    await notifications.put({"PeripheralList": [UID_STATUS_ONLY]})
    await settle(hass)
    assert len(unknown_type_warnings()) == 1


async def test_hub_data_is_refreshed(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The hub's own model, firmware, name, and Wi-Fi signal are read from the payloads."""
    hub = init_integration.runtime_data.hub
    assert hub.model == "NienMadeHub"
    assert hub.firmware_version == "6.1.25"
    assert hub.custom_name == "ShadeAuto Hub"
    assert hub.mac_address == HUB_MAC
    assert hub.time_zone == "America/New_York"
    assert hub.wifi_ssid == HUB_SSID
    assert hub.wifi_rssi == -53
    assert hub.ota_in_progress is False
    assert hub.pairing_mode == 0


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


async def test_undocumented_fields_are_logged_once_each(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A field the hub sends that nobody has documented is reported once, at debug level.

    This is how a firmware change or an unmapped product surfaces: leave debug logging on
    and the new field names appear on their own.
    """
    fake_hub.status["SolarChargeLevel"] = 42
    fake_hub.peripheral_status(UID_LIVING)["VaneAngle"] = 17

    with caplog.at_level(logging.DEBUG, logger="custom_components.norman.coordinator"):
        await notifications.put({"PeripheralList": [UID_LIVING]})
        await settle(hass)
        await notifications.put({"PeripheralList": [UID_LIVING]})
        await settle(hass)

    messages = [r.getMessage() for r in caplog.records if "undocumented" in r.getMessage()]
    assert sum("SolarChargeLevel" in m for m in messages) == 1
    assert sum("VaneAngle" in m for m in messages) == 1
    assert all(
        record.levelno == logging.DEBUG
        for record in caplog.records
        if "undocumented" in record.getMessage()
    )


async def test_documented_fields_are_not_logged(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The fields real hubs send are all catalogued, so a healthy payload logs nothing.

    If this fails, a field was added to the test payloads without adding it to
    KNOWN_HUB_FIELDS / KNOWN_PERIPHERAL_FIELDS in const.py (and to docs/NORMAN_API.md).
    """
    with caplog.at_level(logging.DEBUG, logger="custom_components.norman.coordinator"):
        await notifications.put({"PeripheralList": [UID_LIVING]})
        await settle(hass)

    assert not [r.getMessage() for r in caplog.records if "undocumented" in r.getMessage()]


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


def _device(hass: HomeAssistant, entry: MockConfigEntry, identifier: str) -> dr.DeviceEntry:
    """Find one of the entry's devices by identifier (registry lookups are deprecated in tests)."""
    for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id):
        if (DOMAIN, identifier) in device.identifiers:
            return device
    raise AssertionError(f"no device with identifier {identifier}")


async def test_app_edits_re_read_the_device_list_and_rename_devices(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """An UpdateTime notification (a rename in the Norman app) re-reads names and applies them.

    The hub sends ``{"UpdateTime": {"peripheral": ...}}`` (or ``room`` / ``device``) when
    something is edited in the app; the device list is re-read and changed names are pushed
    into the device registry, which Home Assistant would otherwise never revisit.
    """
    device_calls = len(fake_hub.calls_to("GetAllPeripheral"))
    results = fake_hub.devices["results"]
    results["CustomDeviceName"] = "Annisquam Shade Hub"
    results["RoomList"][0]["GroupList"][0]["PeripheralList"][0]["PeripheralName"] = "Office_1"

    await notifications.put({"UpdateTime": {"peripheral": 1788831865}, "Timestamp": 1})
    await settle(hass)

    assert len(fake_hub.calls_to("GetAllPeripheral")) == device_calls + 1
    assert _device(hass, init_integration, str(UID_LIVING)).name == "Office_1"
    hub_device = _device(hass, init_integration, hub_identifier(init_integration))
    assert hub_device.name == "Annisquam Shade Hub"
    assert init_integration.runtime_data.hub.custom_name == "Annisquam Shade Hub"


async def test_user_renames_in_home_assistant_win_over_app_renames(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """A name set in Home Assistant is kept: only the hub-provided name is updated underneath."""
    device = _device(hass, init_integration, str(UID_LIVING))
    dr.async_get(hass).async_update_device(device.id, name_by_user="My Drape")
    fake_hub.devices["results"]["RoomList"][0]["GroupList"][0]["PeripheralList"][0][
        "PeripheralName"
    ] = "Office_1"

    await notifications.put({"UpdateTime": {"room": 1788830696}})
    await settle(hass)

    device = _device(hass, init_integration, str(UID_LIVING))
    assert device.name == "Office_1"
    assert device.name_by_user == "My Drape"


async def test_schedule_edits_do_not_re_read_the_device_list(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Schedules are not modelled, so a schedule edit only triggers the usual status refresh."""
    device_calls = len(fake_hub.calls_to("GetAllPeripheral"))
    status_calls = len(fake_hub.calls_to("/status"))

    await notifications.put({"UpdateTime": {"schedule": 1788830919}})
    await settle(hass)

    assert len(fake_hub.calls_to("GetAllPeripheral")) == device_calls
    assert len(fake_hub.calls_to("/status")) == status_calls + 1


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


async def test_listener_survives_an_unexpected_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An error that is not a connection drop must not kill the listener for good.

    The listener task is the only thing that refreshes state (there is no polling
    interval), so an exception escaping its loop would leave the integration loaded and
    apparently healthy while silently never updating again. It has to log and carry on.
    """
    caplog.set_level(logging.DEBUG, logger="custom_components.norman")

    with patch("custom_components.norman.coordinator.RECONNECT_INTERVAL", 0):
        await notifications.put(RuntimeError("something nobody predicted"))
        await settle(hass)

        assert any(
            r.levelno == logging.ERROR and "Unexpected error" in r.message for r in caplog.records
        ), "the unexpected error should be logged"

        # The point of the test: the listener is still running and still delivering.
        device_calls = len(fake_hub.calls_to("GetAllPeripheral"))
        await notifications.put({"PeripheralList": []})
        await settle(hass)

    assert len(fake_hub.calls_to("GetAllPeripheral")) >= device_calls, (
        "the listener stopped consuming notifications after an unexpected error"
    )
    assert init_integration.runtime_data.last_update_success


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


async def test_polling_refreshes_a_position_the_hub_never_pushed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
) -> None:
    """A blind whose radio slept still gets its real position picked up.

    The hub only pushes a notification when it hears from a blind. A battery blind's radio
    sleeps -- the Norman app shows it as "Disconnect" -- so a position changed at a remote
    (or simply never confirmed) generates no notification at all. Without a poll the cached
    position stays as it was indefinitely, and `is_closed` answers about the past, which
    silently breaks automations that check state before acting.
    """
    entity_id = cover_entity_id(hass, UID_LIVING)
    assert hass.states.get(entity_id).state == "open"

    # The blind closes without the hub saying so: no notification is queued.
    fake_hub.set_position(UID_LIVING, bottom=0)
    assert hass.states.get(entity_id).state == "open", "still the stale cached position"

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=DEFAULT_POLL_INTERVAL + 1))
    await settle(hass)

    assert hass.states.get(entity_id).state == "closed"


@pytest.mark.parametrize(
    ("option", "expected"),
    [
        (None, timedelta(seconds=DEFAULT_POLL_INTERVAL)),  # unset
        (30, timedelta(seconds=30)),
        (MIN_POLL_INTERVAL, timedelta(seconds=MIN_POLL_INTERVAL)),
        (MAX_POLL_INTERVAL, timedelta(seconds=MAX_POLL_INTERVAL)),
        (POLL_DISABLED, None),  # 0 means push only
        (5, timedelta(seconds=DEFAULT_POLL_INTERVAL)),  # below the floor
        (99999, timedelta(seconds=DEFAULT_POLL_INTERVAL)),  # above the ceiling
        (-1, timedelta(seconds=DEFAULT_POLL_INTERVAL)),  # negative
        ("banana", timedelta(seconds=DEFAULT_POLL_INTERVAL)),  # not a number
    ],
)
def test_poll_interval_option(option: object, expected: timedelta | None) -> None:
    """0 disables polling; anything unusable falls back to the default."""
    options = {} if option is None else {CONF_POLL_INTERVAL: option}
    entry = MockConfigEntry(domain=DOMAIN, options=options)
    assert _poll_interval(entry) == expected


async def test_poll_interval_of_zero_disables_polling(
    hass: HomeAssistant,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """With polling off, a change the hub never announced is not picked up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG,
        options={CONF_POLL_INTERVAL: POLL_DISABLED},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.update_interval is None

    entity_id = cover_entity_id(hass, UID_LIVING)
    fake_hub.set_position(UID_LIVING, bottom=0)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=DEFAULT_POLL_INTERVAL + 1))
    await settle(hass)

    assert hass.states.get(entity_id).state == "open", "no poll, so the change is missed"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_changing_the_poll_interval_reloads_the_entry(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """The interval is read at construction, so a change has to reload to take effect."""
    assert init_integration.runtime_data.update_interval == timedelta(seconds=DEFAULT_POLL_INTERVAL)

    hass.config_entries.async_update_entry(init_integration, options={CONF_POLL_INTERVAL: 30})
    await hass.async_block_till_done()

    assert init_integration.runtime_data.update_interval == timedelta(seconds=30)
