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
    with pytest.raises(ServiceValidationError, match="No Norman hub"):
        await _get_hub_data(hass, config_entry_id="nope")


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
