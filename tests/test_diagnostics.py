"""Tests for the config entry diagnostics export."""

from __future__ import annotations

import json
import re

import aiohttp
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.norman.api import NormanApiClient, NormanConnectionError
from custom_components.norman.const import (
    CONF_CONTROL_INTERVAL,
    CONF_SHOW_SIDEBAR_PANEL,
    DOMAIN,
)
from custom_components.norman.diagnostics import BlindAliases, redact_raw_body

from .conftest import FakeHub, cover_entity_id, loaded
from .const import (
    HUB_FIRMWARE,
    HUB_HOST,
    HUB_LATITUDE,
    HUB_MODEL,
    HUB_SSID,
    HUB_THING_NAME,
    MOCK_CONFIG,
    UID_BEDROOM,
    UID_LIVING,
    UID_STATUS_ONLY,
)

# The stream reader itself, kept before the ``notifications`` fixture replaces it.
_REAL_LISTEN = NormanApiClient.async_listen_notifications


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
    living = next(d for d in diagnostics["devices"].values() if d["name"] == "Living Drape")
    assert living["id"].startswith("blind_")
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


async def test_a_thing_name_sent_as_a_number_is_blanked_too(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: object,
) -> None:
    """A hub that names itself with a number: the export downloads, without the number."""
    fake_hub.registration["ThingName"] = 880042137
    async with loaded(hass, mock_config_entry) as entry:
        diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert "880042137" not in str(diagnostics)


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


async def test_names_in_raw_bodies_are_kept_as_written(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: object,
) -> None:
    """A room named in Japanese reads as it does in the app, not as \\u escapes."""
    fake_hub.devices["results"]["RoomList"][0]["RoomName"] = "リビング"
    async with loaded(hass, mock_config_entry) as entry:
        diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    raw_devices = diagnostics["hub_traffic"]["latest_raw"]["/NM/v1/GetAllPeripheral"]
    assert '"RoomName":"リビング"' in raw_devices
    assert '"GeoLoc":"**REDACTED**"' in raw_devices


async def test_diagnostics_include_the_options(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    fake_hub: FakeHub,
    notifications: object,
) -> None:
    """The command spacing and the sidebar switch are in the report."""
    options = {
        CONF_CONTROL_INTERVAL: 2.0,
        CONF_SHOW_SIDEBAR_PANEL: False,
    }
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, unique_id=HUB_THING_NAME, options=options
    )
    async with loaded(hass, entry):
        diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["entry"]["options"] == options


@pytest.mark.parametrize(
    "resolved",
    [("10.0.0.7", 10123), ("2001:db8:85a3::8a2e:370:7334", 10123, 0, 0)],
    ids=["ipv4", "ipv6"],
)
async def test_a_failed_request_does_not_name_the_hubs_address(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    resolved: tuple,
) -> None:
    """Connection errors name the hub's address, and an address it resolved to.

    A hub added by host name on a dual-stack network may resolve to an IPv6 address, and a
    global one names the home network's prefix.
    """
    fake_hub.status_exc = aiohttp.ClientConnectionError(f"Connect call failed {resolved}")
    await init_integration.runtime_data.async_refresh()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)

    errors = [e["error"] for e in diagnostics["hub_traffic"]["exchanges"] if e.get("error")]
    assert errors
    assert HUB_HOST not in str(errors)
    assert resolved[0] not in str(errors)


def test_text_cut_mid_value_loses_its_identifying_fields() -> None:
    """A piece of a reply is redacted key by key, up to a value cut off at the end."""
    text = '{"results":{"CustomDeviceName":"Hub","GeoLoc":{"Latitude":"42.6","Longitude":"-70'

    redacted = redact_raw_body(text, [])

    assert redacted == ('{"results":{"CustomDeviceName":"**REDACTED**","GeoLoc":"**REDACTED**"')


async def test_diagnostics_alias_every_blind_id(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
) -> None:
    """A blind's id is its serial number; the export calls each blind by an alias instead.

    The same alias everywhere, so the device list, the scenes and the raw traffic -- request
    payloads and reply bodies alike -- still line up with each other.
    """
    await hass.services.async_call(
        DOMAIN,
        "room_command",
        {"blinds": [cover_entity_id(hass, UID_BEDROOM)], "command": "refresh"},
        blocking=True,
    )

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)
    export = json.dumps(diagnostics, ensure_ascii=False)
    for uid in (UID_LIVING, UID_BEDROOM, UID_STATUS_ONLY):
        assert not re.search(rf"(?<![\w.]){uid}(?![\w.])", export), f"{uid} left in the export"

    alias = {device["name"]: key for key, device in diagnostics["devices"].items()}
    bedroom = alias["Bedroom Shade"]
    assert diagnostics["devices"][bedroom]["id"] == bedroom
    raw_status = diagnostics["hub_traffic"]["latest_raw"]["/NM/v1/status"]
    assert f'"PeripheralUID":"{bedroom}"' in raw_status
    request = next(
        exchange["request"]
        for exchange in reversed(diagnostics["hub_traffic"]["exchanges"])
        if exchange["endpoint"] == "/NM/v1/control"
    )
    assert request["PeripheralUID"] == bedroom
    # A blind the device list does not name is called after its id, so the name is aliased.
    assert any(name.startswith("Norman blind_") for name in alias)


def test_ids_in_text_that_does_not_parse_are_aliased() -> None:
    """A clipped body or a piece of the stream still loses its blind ids, key by key."""
    aliases = BlindAliases([1001, 1002])
    text = '{"Status":1788827049448,"PeripheralList":[1001,1002]}{"PeripheralUID":"1001","Bottom'

    assert redact_raw_body(text, [], aliases) == (
        '{"Status":1788827049448,"PeripheralList":["blind_1","blind_2"]}'
        '{"PeripheralUID":"blind_1","Bottom'
    )


async def test_a_blind_id_a_stream_read_cut_from_its_key_is_aliased(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
) -> None:
    """The stream is recorded as read, ``READ_CHUNK_SIZE`` bytes at a time.

    A burst of notifications is cut wherever a read ends, here inside a ``PeripheralList``
    key: the id after the cut, with no key before it, is aliased all the same.
    """
    ack = '{"Error":"Success."}'
    one = f'{{"Status":1788827049448,"PeripheralList":[{UID_BEDROOM}]}}'
    two = f'{{"Status":1788827049448,"PeripheralList":[{UID_BEDROOM},{UID_STATUS_ONLY}]}}'
    edit = '{"UpdateTime":{"room":1788830696},"Timestamp":1788830696000}'
    last = f'{{"Status":1788827049448,"PeripheralList":[{UID_LIVING}]}}'
    # Long enough before the last notification for the first read to end inside its key.
    fake_hub.notification_body = ack + one * 11 + two * 5 + edit * 3 + last
    api = init_integration.runtime_data.api

    with pytest.raises(NormanConnectionError, match="closed by hub"):
        async for _ in _REAL_LISTEN(api):
            pass

    chunks = [
        e["response"]
        for e in api.traffic.as_dict()["exchanges"]
        if e["kind"] == "stream" and e["response"]
    ]
    assert len(chunks) == 2 and chunks[1].startswith('eralList":['), "a read ends in the key"
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)
    export = json.dumps(diagnostics, ensure_ascii=False)
    for uid in (UID_LIVING, UID_BEDROOM, UID_STATUS_ONLY):
        assert not re.search(rf"(?<![\w.]){uid}(?![\w.])", export), f"{uid} left in the export"


async def test_diagnostics_describe_the_hub_and_its_link(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
) -> None:
    """The hub's own state is in the report, less what identifies it or its network."""
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)
    hub = diagnostics["hub"]

    assert hub["model"] == HUB_MODEL
    assert hub["firmware_version"] == HUB_FIRMWARE
    for field in ("custom_name", "wifi_ssid", "mac_address", "time_zone"):
        assert hub[field] in (None, "**REDACTED**"), field
    assert hub["mac_address"] == "**REDACTED**"
    assert hub["has_device_list"] is True
    assert hub["device_list_failing"] is False
    assert {"push_connected", "listening", "control_interval", "moves_in_flight"} <= set(hub)
    assert HUB_SSID not in str(hub)
