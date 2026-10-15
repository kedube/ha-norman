"""Tests for config entry setup and teardown."""

from __future__ import annotations

import aiohttp
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.norman.const import DOMAIN

from .conftest import HUB_MAC, FakeHub, cover_entity_id, loaded, settle
from .const import (
    HUB_HOST,
    HUB_THING_NAME,
    HUB_URL,
    MOCK_CONFIG,
    UID_BEDROOM,
    UID_LIVING,
    UID_STATUS_ONLY,
)


async def test_setup_creates_devices_and_unloads_cleanly(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Setup registers a hub device, one cover per peripheral hanging off it, and unloads."""
    entry = init_integration
    assert entry.state is ConfigEntryState.LOADED

    device_registry = dr.async_get(hass)
    devices = {
        identifier: device
        for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id)
        for identifier in device.identifiers
    }
    hub = devices.get((DOMAIN, f"hub_{entry.entry_id}"))
    assert hub is not None
    assert hub.manufacturer == "Norman"
    assert hub.model == "NienMadeHub"
    assert hub.sw_version == "6.1.25"
    assert hub.name == "ShadeAuto Hub"
    assert hub.configuration_url == f"{HUB_URL}"
    assert hub.connections == {(dr.CONNECTION_NETWORK_MAC, HUB_MAC)}

    blind = devices.get((DOMAIN, str(UID_LIVING)))
    assert blind is not None
    assert blind.name == "Living Drape"
    assert blind.via_device_id == hub.id
    assert blind.sw_version == "0.5.3.8"
    assert blind.serial_number == str(UID_LIVING)
    assert blind.model == "Cellular Shade (dual rail)"
    assert blind.model_id == "33/3"

    # A single-rail blind reports two versions; the app shows RfFirmwareVersion
    shade = devices.get((DOMAIN, str(UID_BEDROOM)))
    assert shade.sw_version == "0.3.20"
    # Reading DeviceEntry.suggested_area is deprecated; check the area it was placed in
    assert ar.async_get(hass).async_get_area(blind.area_id).name == "Living Room"

    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    covers = sorted(e.unique_id for e in entries if e.domain == "cover")
    # Two-rail blinds (and the untyped status-only one, treated as two-rail) get a
    # middle-rail cover as well
    assert covers == ["1001", "1001_middle", "1002", "1003", "1003_middle"]
    assert f"{entry.entry_id}_wifi_rssi" in {e.unique_id for e in entries}
    assert {e.domain for e in entries} == {"binary_sensor", "button", "cover", "number", "sensor"}
    living = cover_entity_id(hass, UID_LIVING)
    assert hass.states.get(living).attributes["friendly_name"] == "Living Drape Bottom rail"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(living).state == "unavailable"


@pytest.mark.parametrize(
    "mock_kwargs",
    [
        {"exc": aiohttp.ClientConnectionError("refused")},
        {"exc": TimeoutError()},
        {"json": {"Error": 4}},
        {"text": "garbage"},
    ],
    ids=["connection", "timeout", "hub-error", "not-json"],
)
async def test_setup_retries_when_registration_fails(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    mock_kwargs: dict,
) -> None:
    """Any registration failure defers setup instead of failing it permanently."""
    aioclient_mock.post(f"{HUB_URL}/NM/v1/registration", **mock_kwargs)
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_retries_when_first_refresh_fails(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Registration alone is not enough; the first data fetch must succeed too."""
    fake_hub.status_exc = TimeoutError()
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_legacy_host_unique_id_is_migrated_to_thing_name(
    hass: HomeAssistant, fake_hub: FakeHub, notifications
) -> None:
    """Entries from before 0.11 were keyed by address; setup re-keys them by hub identity."""
    legacy = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: HUB_HOST}, unique_id=HUB_HOST)
    legacy.add_to_hass(hass)

    assert await hass.config_entries.async_setup(legacy.entry_id)
    await hass.async_block_till_done()

    assert legacy.unique_id == HUB_THING_NAME


async def test_unique_id_migration_leaves_a_duplicate_hub_alone(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If another entry already owns the ThingName, warn rather than create a clash."""
    mock_config_entry.add_to_hass(hass)  # already keyed by HUB_THING_NAME
    legacy = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: "192.168.1.99"}, unique_id="192.168.1.99"
    )
    legacy.add_to_hass(hass)
    fake_hub.mock.post(
        "http://192.168.1.99:10123/NM/v1/registration",
        json={"Error": 0, "ThingName": HUB_THING_NAME},
    )
    for endpoint in ("GetAllPeripheral", "status"):
        fake_hub.mock.post(f"http://192.168.1.99:10123/NM/v1/{endpoint}", json=fake_hub.status)

    assert await hass.config_entries.async_setup(legacy.entry_id)
    await hass.async_block_till_done()

    assert legacy.unique_id == "192.168.1.99"
    assert "also configured under another entry" in caplog.text


async def test_remove_device_only_for_blinds_the_hub_dropped(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications,
) -> None:
    """Live blinds and the hub refuse deletion; a vanished blind can be removed."""
    from custom_components.norman import async_remove_config_entry_device

    entry = init_integration
    registry = dr.async_get(hass)
    by_identifier = {
        identifier: device
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
        for identifier in device.identifiers
    }
    hub = by_identifier[(DOMAIN, f"hub_{entry.entry_id}")]
    living = by_identifier[(DOMAIN, str(UID_LIVING))]
    status_only = by_identifier[(DOMAIN, str(UID_STATUS_ONLY))]

    assert not await async_remove_config_entry_device(hass, entry, hub)
    assert not await async_remove_config_entry_device(hass, entry, living)
    assert not await async_remove_config_entry_device(hass, entry, status_only)

    fake_hub.status["Peripherals"] = [
        p for p in fake_hub.status["Peripherals"] if p.get("PeripheralUID") != UID_STATUS_ONLY
    ]
    await notifications.put({"PeripheralList": []})
    await settle(hass)

    assert await async_remove_config_entry_device(hass, entry, status_only)
    assert not await async_remove_config_entry_device(hass, entry, living)


async def test_the_entry_is_titled_after_the_hub(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The default ``Norman Hub (<host>)`` gives way to the name set in the Norman app."""
    assert init_integration.title == "ShadeAuto Hub"
    # Renamed before the update listener exists, so the entry was not reloaded for it
    assert len(fake_hub.calls_to("registration")) == 1


async def test_the_entry_title_follows_a_hub_rename(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A title taken from the hub's old name follows its new one."""
    async with loaded(hass, mock_config_entry) as entry:
        assert entry.title == "ShadeAuto Hub"
        fake_hub.devices["results"]["CustomDeviceName"] = "Annisquam Shades"
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.title == "Annisquam Shades"


async def test_the_entry_title_follows_a_hub_renamed_while_running(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications,
) -> None:
    """A rename in the Norman app retitles the entry at once, without reloading it.

    Renamed only at the next setup, the title was compared with a hub device already
    renamed, and stayed on the old name for good.
    """
    async with loaded(hass, mock_config_entry) as entry:
        registrations = len(fake_hub.calls_to("/registration"))
        fake_hub.devices["results"]["CustomDeviceName"] = "Annisquam Shades"
        await notifications.put({"UpdateTime": {"device": 1}})
        await settle(hass)

        assert entry.title == "Annisquam Shades"
        assert len(fake_hub.calls_to("/registration")) == registrations


async def test_a_new_title_does_not_reload_the_hub(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Only the hub's address and the options are read at setup; a title is not."""
    registrations = len(fake_hub.calls_to("/registration"))

    hass.config_entries.async_update_entry(init_integration, title="Upstairs")
    await hass.async_block_till_done()

    assert len(fake_hub.calls_to("/registration")) == registrations


async def test_a_title_chosen_in_home_assistant_stays(
    hass: HomeAssistant, fake_hub: FakeHub
) -> None:
    """Only titles the integration gave are replaced."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Upstairs shades", data=MOCK_CONFIG, unique_id=HUB_THING_NAME
    )
    async with loaded(hass, entry):
        assert entry.title == "Upstairs shades"


async def test_a_new_address_reloads_the_hub_once(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reconfiguring a loaded hub sets it up again once, through its update listener.

    The flow reloading it as well set the hub up twice, and Home Assistant flags a flow
    that reloads an entry with an update listener.
    """
    new_url = "http://192.168.1.99:10123/NM/v1"
    handlers = {
        "registration": None,
        "GetAllPeripheral": fake_hub._devices,
        "status": fake_hub._status,
        "control": fake_hub._control,
        "notification": fake_hub._notification,
    }
    for endpoint, handler in handlers.items():
        if handler is None:
            aioclient_mock.post(
                f"{new_url}/{endpoint}", json={"Error": 0, "ThingName": HUB_THING_NAME}
            )
        else:
            aioclient_mock.post(f"{new_url}/{endpoint}", side_effect=handler)
    registrations = len(fake_hub.calls_to("/registration"))

    result = await init_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "192.168.1.99"}
    )
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert init_integration.state is ConfigEntryState.LOADED
    # The flow checks the new address once, and one setup registers once more.
    assert len(fake_hub.calls_to("/registration")) == registrations + 2
    assert "update listener" not in caplog.text
