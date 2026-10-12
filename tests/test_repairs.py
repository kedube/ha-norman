"""Repairs raised about the hub's own settings: its time zone and its location."""

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
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A hub with a location, in Home Assistant's time zone, raises nothing."""
    assert _issues(hass, init_integration) == {}


async def test_a_hub_without_its_settings_raises_both_repairs(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """No TimeZone and no GeoLoc: one repair each, and the sensor no longer shows a zone."""
    _without_hub_settings(fake_hub)

    async with loaded(hass, mock_config_entry) as entry:
        issues = _issues(hass, entry)
        assert issues["time_zone"].translation_key == "hub_time_zone_missing"
        assert issues["location"].translation_key == "hub_location_missing"
        assert issues["location"].translation_placeholders == {"hub": "ShadeAuto Hub"}
        assert all(not issue.is_fixable for issue in issues.values())
        assert all(issue.severity is ir.IssueSeverity.WARNING for issue in issues.values())
        assert _time_zone_state(hass, entry) == "unknown"


@pytest.mark.parametrize("geo_loc", [{}, {"Latitude": "", "Longitude": "-70.1"}, "nope"])
async def test_a_partial_location_counts_as_none(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub, geo_loc: Any
) -> None:
    """A location missing either coordinate cannot drive sunrise or sunset schedules."""
    fake_hub.devices["results"]["GeoLoc"] = geo_loc

    async with loaded(hass, mock_config_entry) as entry:
        assert set(_issues(hass, entry)) == {"location"}


async def test_a_different_clock_raises_a_mismatch(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The hub's zone keeps a different time from Home Assistant's: say which two."""
    await hass.config.async_set_time_zone("Europe/Paris")

    async with loaded(hass, mock_config_entry) as entry:
        issue = _issues(hass, entry)["time_zone"]
        assert issue.translation_key == "hub_time_zone_mismatch"
        assert issue.translation_placeholders == {
            "hub": "ShadeAuto Hub",
            "hub_time_zone": "America/New_York",
            "ha_time_zone": "Europe/Paris",
        }


async def test_an_alias_of_the_same_zone_matches(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """US/Eastern and America/New_York keep the same time, so there is nothing to fix."""
    await hass.config.async_set_time_zone("US/Eastern")

    async with loaded(hass, mock_config_entry) as entry:
        assert _issues(hass, entry) == {}


async def test_repairs_clear_once_the_hub_reports_its_settings(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Setting them again in the Norman app clears both repairs on the next read."""
    settings = _without_hub_settings(fake_hub)

    async with loaded(hass, mock_config_entry) as entry:
        assert set(_issues(hass, entry)) == {"time_zone", "location"}

        fake_hub.devices["results"].update(settings)
        await notifications.put(None)  # a reconnect re-reads the device list
        await settle(hass)

        assert _issues(hass, entry) == {}
        assert _time_zone_state(hass, entry) == "America/New_York"


async def test_no_repair_while_the_device_list_is_unreadable(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Nothing is known about the hub's settings until its device list has been read."""
    fake_hub.devices = {"status": {"code": 1, "error": "Request process fail."}}

    async with loaded(hass, mock_config_entry) as entry:
        assert _issues(hass, entry) == {}


async def test_removing_the_hub_clears_its_repairs(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A repair about a hub that is no longer configured has nothing left to fix."""
    _without_hub_settings(fake_hub)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert _issues(hass, mock_config_entry)

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _issues(hass, mock_config_entry) == {}
