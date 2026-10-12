"""Repairs raised when the hub's schedules lack the time zone or location they need."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.norman.const import DOMAIN
from custom_components.norman.coordinator import hub_issue_id

from .conftest import FakeHub, loaded, settle

TIMED = {
    "ScheduleID": "timed",
    "Conditions": {"Days": [1, 2, 3, 4, 5], "Time": [7, 30]},
    "Executions": {"RoomIdList": [{"RoomID": "1", "Switch": "1"}]},
    "ScheduleEnable": True,
}
AT_SUNSET = {
    "ScheduleID": "sunset",
    "Conditions": {"Days": [1, 2, 3, 4, 5, 6, 7], "SunsetOffsetMin": -15},
    "Executions": {"RoomIdList": [{"RoomID": "1", "Switch": "0"}]},
    "ScheduleEnable": True,
}


def _issues(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, ir.IssueEntry]:
    """The entry's hub-settings repairs, by setting."""
    registry = ir.async_get(hass)
    found = {}
    for setting in ("time_zone", "location"):
        issue = registry.async_get_issue(DOMAIN, hub_issue_id(entry, setting))
        if issue is not None:
            found[setting] = issue
    return found


def _time_zone_state(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_time_zone"
    )
    assert entity_id
    return hass.states.get(entity_id).state


def _without_hub_settings(fake_hub: FakeHub) -> dict[str, Any]:
    """Drop TimeZone and GeoLoc from the device list, as the reference hub did; return them."""
    results = fake_hub.devices["results"]
    return {key: results.pop(key) for key in ("TimeZone", "GeoLoc")}


async def test_no_repair_when_the_hub_matches(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Schedules on a hub with a location, in Home Assistant's time zone, raise nothing."""
    fake_hub.schedules = [TIMED, AT_SUNSET]

    async with loaded(hass, mock_config_entry) as entry:
        assert _issues(hass, entry) == {}


async def test_a_hub_without_schedules_needs_neither_setting(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The reference hub's case: both settings gone, but nothing runs by them."""
    _without_hub_settings(fake_hub)

    async with loaded(hass, mock_config_entry) as entry:
        assert _issues(hass, entry) == {}
        assert _time_zone_state(hass, entry) == "unknown"
        assert len(fake_hub.calls_to("GetAllSchedule")) == 1


async def test_a_timed_schedule_needs_only_the_time_zone(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A schedule at a set time runs by the hub's clock, not its location."""
    _without_hub_settings(fake_hub)
    fake_hub.schedules = [TIMED]

    async with loaded(hass, mock_config_entry) as entry:
        issues = _issues(hass, entry)
        assert set(issues) == {"time_zone"}
        issue = issues["time_zone"]
        assert issue.translation_key == "hub_time_zone_missing"
        assert issue.translation_placeholders["hub"] == "ShadeAuto Hub"
        assert not issue.is_fixable
        assert issue.severity is ir.IssueSeverity.WARNING


async def test_a_sunset_schedule_needs_both(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Sunrise and sunset need the hub's location as well as its clock."""
    _without_hub_settings(fake_hub)
    fake_hub.schedules = [AT_SUNSET]

    async with loaded(hass, mock_config_entry) as entry:
        issues = _issues(hass, entry)
        assert issues["time_zone"].translation_key == "hub_time_zone_missing"
        assert issues["location"].translation_key == "hub_location_missing"
        assert issues["location"].translation_placeholders == {"hub": "ShadeAuto Hub"}


@pytest.mark.parametrize("enabled", [False, 0, "0", "false"])
async def test_a_disabled_schedule_needs_nothing(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub, enabled: Any
) -> None:
    """A schedule that does not run cannot run at the wrong time."""
    _without_hub_settings(fake_hub)
    fake_hub.schedules = [{**AT_SUNSET, "ScheduleEnable": enabled}]

    async with loaded(hass, mock_config_entry) as entry:
        assert _issues(hass, entry) == {}


@pytest.mark.parametrize("geo_loc", [{}, {"Latitude": "", "Longitude": "-70.1"}, "nope"])
async def test_a_partial_location_counts_as_none(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub, geo_loc: Any
) -> None:
    """A location missing either coordinate cannot drive sunrise or sunset schedules."""
    fake_hub.devices["results"]["GeoLoc"] = geo_loc
    fake_hub.schedules = [AT_SUNSET]

    async with loaded(hass, mock_config_entry) as entry:
        assert set(_issues(hass, entry)) == {"location"}


async def test_a_different_clock_raises_a_mismatch(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The hub's zone keeps a different time from Home Assistant's: say which two."""
    await hass.config.async_set_time_zone("Europe/Paris")
    fake_hub.schedules = [TIMED]

    async with loaded(hass, mock_config_entry) as entry:
        issue = _issues(hass, entry)["time_zone"]
        assert issue.translation_key == "hub_time_zone_mismatch"
        assert issue.translation_placeholders == {
            "hub": "ShadeAuto Hub",
            "hub_time_zone": "America/New_York",
            "ha_time_zone": "Europe/Paris",
        }


async def test_a_different_clock_without_schedules_is_fine(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Without schedules the hub's clock decides nothing."""
    await hass.config.async_set_time_zone("Europe/Paris")

    async with loaded(hass, mock_config_entry) as entry:
        assert _issues(hass, entry) == {}


async def test_an_alias_of_the_same_zone_matches(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """US/Eastern and America/New_York keep the same time, so there is nothing to fix."""
    await hass.config.async_set_time_zone("US/Eastern")
    fake_hub.schedules = [TIMED]

    async with loaded(hass, mock_config_entry) as entry:
        assert _issues(hass, entry) == {}


async def test_repairs_clear_once_the_schedules_are_gone(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Deleting the hub's schedules in the Norman app clears the repairs it notifies about."""
    _without_hub_settings(fake_hub)
    fake_hub.schedules = [AT_SUNSET]

    async with loaded(hass, mock_config_entry) as entry:
        assert set(_issues(hass, entry)) == {"time_zone", "location"}

        fake_hub.schedules = []
        await notifications.put({"UpdateTime": {"schedule": 1700000000}})
        await settle(hass)

        assert _issues(hass, entry) == {}


async def test_repairs_clear_once_the_hub_reports_its_settings(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """A hub that reports both settings again clears both repairs on the next read."""
    settings = _without_hub_settings(fake_hub)
    fake_hub.schedules = [AT_SUNSET]

    async with loaded(hass, mock_config_entry) as entry:
        assert set(_issues(hass, entry)) == {"time_zone", "location"}

        fake_hub.devices["results"].update(settings)
        await notifications.put(None)  # a reconnect re-reads the device list
        await settle(hass)

        assert _issues(hass, entry) == {}
        assert _time_zone_state(hass, entry) == "America/New_York"


async def test_an_unreadable_schedule_list_raises_nothing(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Without the schedules nothing is known to depend on the settings, and setup goes on."""
    _without_hub_settings(fake_hub)
    fake_hub.schedule_response = {"status": {"code": 1, "error": "Request process fail."}}

    async with loaded(hass, mock_config_entry) as entry:
        assert entry.runtime_data.last_update_success
        assert _issues(hass, entry) == {}


async def test_no_repair_while_the_device_list_is_unreadable(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Nothing is known about the hub's settings until its device list has been read."""
    fake_hub.devices = {"status": {"code": 1, "error": "Request process fail."}}
    fake_hub.schedules = [AT_SUNSET]

    async with loaded(hass, mock_config_entry) as entry:
        assert _issues(hass, entry) == {}
        assert not fake_hub.calls_to("GetAllSchedule")


async def test_removing_the_hub_clears_its_repairs(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A repair about a hub that is no longer configured has nothing left to fix."""
    _without_hub_settings(fake_hub)
    fake_hub.schedules = [AT_SUNSET]
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert _issues(hass, mock_config_entry)

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _issues(hass, mock_config_entry) == {}
