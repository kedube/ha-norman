"""Tests for the config entry diagnostics export."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .const import HUB_HOST, HUB_THING_NAME, UID_LIVING


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
    assert living["battery_voltage"] == 12.4


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
