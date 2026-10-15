"""Tests for the config entry diagnostics export."""

from __future__ import annotations

import aiohttp
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.norman.diagnostics import redact_raw_body

from .conftest import FakeHub, loaded
from .const import HUB_HOST, HUB_LATITUDE, HUB_SSID, HUB_THING_NAME, UID_LIVING


async def test_diagnostics_redacts_network_details(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
) -> None:
    """The export carries blind state but not the hub address or identity."""
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)

    assert diagnostics["entry"]["data"]["host"] == "**REDACTED**"
    assert diagnostics["entry"]["unique_id"] == "**REDACTED**"
    assert HUB_HOST not in str(diagnostics)
    assert HUB_THING_NAME not in str(diagnostics)

    assert diagnostics["last_update_success"] is True
    living = diagnostics["devices"][str(UID_LIVING)]
    assert living["name"] == "Living Drape"
    assert living["bottom_rail_position"] == 40
    assert living["battery_level"] == 73


async def test_diagnostics_include_scrubbed_hub_traffic(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
) -> None:
    """Raw exchanges are exported with the hub's address and identity blanked everywhere."""
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)
    traffic = diagnostics["hub_traffic"]

    assert set(traffic["latest_raw"]) >= {"/NM/v1/GetAllPeripheral", "/NM/v1/status"}
    assert '"RoomList"' in traffic["latest_raw"]["/NM/v1/GetAllPeripheral"]
    endpoints = [e["endpoint"] for e in traffic["exchanges"]]
    assert endpoints[:3] == ["/NM/v1/registration", "/NM/v1/GetAllPeripheral", "/NM/v1/status"]

    # The GetAllPeripheral request carries the ThingName and the registration reply returns
    # it; neither may survive, in dict fields or inside raw text.
    get_all = next(e for e in traffic["exchanges"] if e["endpoint"] == "/NM/v1/GetAllPeripheral")
    assert get_all["request"]["ThingName"] == "**REDACTED**"
    assert HUB_THING_NAME not in str(diagnostics)
    assert HUB_HOST not in str(diagnostics)


async def test_diagnostics_redact_location_and_network_inside_raw_bodies(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
) -> None:
    """Real hubs send their coordinates and Wi-Fi name; neither may leave in an export."""
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)
    export = str(diagnostics)

    assert HUB_LATITUDE not in export
    assert HUB_SSID not in export
    assert "ShadeAuto Hub" not in export
    assert "America/New_York" not in export

    raw_devices = diagnostics["hub_traffic"]["latest_raw"]["/NM/v1/GetAllPeripheral"]
    assert '"GeoLoc":"**REDACTED**"' in raw_devices
    assert '"RoomName":"Living Room"' in raw_devices  # blind data survives


async def test_a_device_list_clipped_in_the_traffic_log_is_still_redacted(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: object,
) -> None:
    """A device list past the traffic log's clip no longer parses, and still loses its location.

    A real hub's is about 4 KB per blind, so any hub with a few blinds is clipped; its
    location, name and time zone come before the rooms, in the part that is kept.
    """
    fake_hub.devices["results"]["RoomList"][0]["RoomName"] = "Living Room" + " " * 20000
    async with loaded(hass, mock_config_entry) as entry:
        diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    exchanges = str(diagnostics["hub_traffic"]["exchanges"])
    assert "more bytes]" in exchanges
    assert HUB_LATITUDE not in exchanges
    assert "America/New_York" not in exchanges
    assert "ShadeAuto Hub" not in exchanges


async def test_a_failed_request_does_not_name_the_hubs_address(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
) -> None:
    """Connection errors name the hub's address, and an address it resolved to."""
    fake_hub.status_exc = aiohttp.ClientConnectionError("Connect call failed ('10.0.0.7', 10123)")
    await init_integration.runtime_data.async_refresh()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)

    errors = [e["error"] for e in diagnostics["hub_traffic"]["exchanges"] if e.get("error")]
    assert errors
    assert HUB_HOST not in str(errors)
    assert "10.0.0.7" not in str(errors)


def test_text_cut_mid_value_loses_its_identifying_fields() -> None:
    """A piece of a reply is redacted key by key, up to a value cut off at the end."""
    text = '{"results":{"CustomDeviceName":"Hub","GeoLoc":{"Latitude":"42.6","Longitude":"-70'

    redacted = redact_raw_body(text, [])

    assert redacted == ('{"results":{"CustomDeviceName":"**REDACTED**","GeoLoc":"**REDACTED**"')
