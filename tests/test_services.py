"""Tests for the integration-level ``get_hub_data`` action."""

from __future__ import annotations

import aiohttp
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
import voluptuous as vol

from custom_components.norman.const import DOMAIN

from .conftest import FakeHub
from .const import HUB_THING_NAME, HUB_URL, UID_LIVING


async def _get_hub_data(hass: HomeAssistant, **data) -> dict:
    return await hass.services.async_call(
        DOMAIN, "get_hub_data", data, blocking=True, return_response=True
    )


async def test_get_hub_data_returns_raw_payloads(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The response is the hub's own JSON, fetched live, unknown fields included."""
    fake_hub.status["Peripherals"][0]["SomethingNew"] = 42

    response = await _get_hub_data(hass)

    assert response["devices"]["results"]["RoomList"][0]["RoomName"] == "Living Room"
    # Home/network identifiers are blanked even in the live response
    assert response["devices"]["results"]["GeoLoc"] == "**REDACTED**"
    assert response["devices"]["results"]["ThingName"] == "**REDACTED**"
    assert HUB_THING_NAME not in str(response)
    living = next(p for p in response["status"]["Peripherals"] if p["PeripheralUID"] == UID_LIVING)
    assert living["SomethingNew"] == 42


async def test_get_hub_data_accepts_an_explicit_entry(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The entry id selector targets a specific hub."""
    response = await _get_hub_data(hass, config_entry_id=init_integration.entry_id)
    assert "Peripherals" in response["status"]


async def test_get_hub_data_rejects_unknown_entry(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A wrong id is a validation error, not a crash."""
    with pytest.raises(ServiceValidationError, match="No Norman hub") as excinfo:
        await _get_hub_data(hass, config_entry_id="nope")
    assert excinfo.value.translation_key == "unknown_entry"


async def test_get_hub_data_requires_entry_id_with_several_hubs(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """With more than one hub the id must be given."""
    MockConfigEntry(domain=DOMAIN, data={"host": "192.168.1.99"}, unique_id="Other").add_to_hass(
        hass
    )
    with pytest.raises(ServiceValidationError, match="2 Norman hubs"):
        await _get_hub_data(hass)


async def test_get_hub_data_requires_a_loaded_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The action exists as soon as the integration loads, but needs a loaded hub."""
    aioclient_mock.post(f"{HUB_URL}/NM/v1/registration", exc=aiohttp.ClientConnectionError())
    mock_config_entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY

    assert hass.services.has_service(DOMAIN, "get_hub_data")
    with pytest.raises(ServiceValidationError, match="not loaded"):
        await _get_hub_data(hass)


async def test_get_hub_data_reports_hub_failures(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A hub that cannot be read fails the call with a clear message."""
    fake_hub.status_exc = aiohttp.ClientConnectionError("gone")
    with pytest.raises(HomeAssistantError, match="Could not read from Norman hub"):
        await _get_hub_data(hass)


async def test_send_hub_command_posts_fields_and_returns_reply(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Arbitrary fields reach the control endpoint with the ids filled in; the reply comes back."""
    fake_hub.control_response = {"Error": 0, "PeripheralUID": UID_LIVING, "MotorStop": 1}
    status_calls = len(fake_hub.calls_to("/status"))

    response = await hass.services.async_call(
        DOMAIN,
        "send_hub_command",
        {"peripheral_uid": str(UID_LIVING), "fields": {"MotorStop": 1}},
        blocking=True,
        return_response=True,
    )

    call = fake_hub.control_calls[-1]
    assert call["PeripheralUID"] == UID_LIVING
    assert call["MotorStop"] == 1
    assert {"Timestamp", "TaskID"} <= set(call)
    assert response["reply"]["MotorStop"] == 1
    # A refresh follows so any resulting movement shows up
    assert len(fake_hub.calls_to("/status")) == status_calls + 1


async def test_send_hub_command_reports_rejection(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A non-zero Error from the hub fails the call with the hub's code."""
    fake_hub.control_response = {"Error": 7}
    with pytest.raises(HomeAssistantError, match="rejected the command.*error code: 7"):
        await hass.services.async_call(
            DOMAIN,
            "send_hub_command",
            {"peripheral_uid": UID_LIVING, "fields": {"MotorStop": 1}},
            blocking=True,
            return_response=True,
        )


async def test_send_hub_command_validates_input(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Missing or malformed fields never reach the hub."""
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "send_hub_command", {"fields": {"MotorStop": 1}}, blocking=True
        )
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "send_hub_command",
            {"peripheral_uid": UID_LIVING, "fields": {"Nested": {"a": 1}}},
            blocking=True,
        )
    assert fake_hub.control_calls == []


async def test_room_command_sends_the_room_wide_verb(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A room command addresses the room by RoomID, not one request per blind.

    This is the app's own Best Privacy: the hub accepts RoomID in place of PeripheralUID.
    """
    status_calls = len(fake_hub.calls_to("/status"))

    await hass.services.async_call(
        DOMAIN,
        "room_command",
        {"room": "Living Room", "command": "best_privacy"},
        blocking=True,
    )

    call = fake_hub.control_calls[-1]
    assert call["RoomID"] == 1
    assert call["Switch"] == 0
    # Addressing the room replaces the per-blind id; sending both would be ambiguous.
    assert "PeripheralUID" not in call
    assert {"Timestamp", "TaskID"} <= set(call)
    assert len(fake_hub.calls_to("/status")) == status_calls + 1


async def test_room_command_maps_each_button_to_its_verb(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """best_view opens the bottom rail, favorite runs to the stored position."""
    await hass.services.async_call(
        DOMAIN, "room_command", {"room": "Bedroom", "command": "best_view"}, blocking=True
    )
    assert fake_hub.control_calls[-1]["Switch"] == 1
    assert fake_hub.control_calls[-1]["RoomID"] == 2

    await hass.services.async_call(
        DOMAIN, "room_command", {"room": "Bedroom", "command": "favorite"}, blocking=True
    )
    assert fake_hub.control_calls[-1]["Favorite"] == 0
    assert "Switch" not in fake_hub.control_calls[-1]


async def test_room_command_matches_the_name_case_insensitively(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Room names come from the hub, so a user typing them should not have to match case."""
    await hass.services.async_call(
        DOMAIN, "room_command", {"room": "living room", "command": "best_view"}, blocking=True
    )
    assert fake_hub.control_calls[-1]["RoomID"] == 1


async def test_room_command_rejects_an_unknown_room(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A typo names the rooms that do exist rather than silently doing nothing."""
    before = len(fake_hub.control_calls)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "room_command", {"room": "Kitchen", "command": "best_view"}, blocking=True
        )

    assert "Kitchen" in str(err.value)
    assert len(fake_hub.control_calls) == before  # nothing was sent


async def test_room_command_validates_the_command(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Only the app's three buttons are accepted; anything else is a schema error."""
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "room_command", {"room": "Bedroom", "command": "explode"}, blocking=True
        )


async def test_room_command_reports_hub_rejection(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A hub error surfaces with the room and command in the message."""
    fake_hub.control_response = {"Error": 7}

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN, "room_command", {"room": "Bedroom", "command": "best_privacy"}, blocking=True
        )

    assert "Bedroom" in str(err.value)


async def test_room_command_without_a_room_addresses_the_whole_hub(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Omitting the room sends the verb with no RoomID, which the hub reads as everything."""
    await hass.services.async_call(DOMAIN, "room_command", {"command": "best_view"}, blocking=True)

    call = fake_hub.control_calls[-1]
    assert call["Switch"] == 1
    # No scope field at all: an omitted RoomID is what makes it hub-wide.
    assert "RoomID" not in call
    assert "PeripheralUID" not in call


async def test_hub_wide_favorite_sends_the_bare_verb(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Favorite works hub-wide too, as the bare verb with no scope field.

    Captured from the app's "All Rooms" screen. Every command the app offers per room it
    also offers for the whole house, so all three are allowed without a room.
    """
    await hass.services.async_call(DOMAIN, "room_command", {"command": "favorite"}, blocking=True)

    call = fake_hub.control_calls[-1]
    assert call["Favorite"] == 0
    assert "RoomID" not in call
    assert "PeripheralUID" not in call
