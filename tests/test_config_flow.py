"""Test the Norman config flow."""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.norman.const import DOMAIN

from .const import HUB_HOST, HUB_THING_NAME, HUB_URL, MOCK_CONFIG

REGISTRATION = f"{HUB_URL}/NM/v1/registration"


@pytest.fixture(autouse=True)
def _bypass_setup():
    """Prevent the entry from actually being set up after the flow creates it."""
    with patch("custom_components.norman.async_setup_entry", return_value=True):
        yield


async def _start_user_flow(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})


async def test_form(hass: HomeAssistant) -> None:
    """The initial step shows the host form with no errors."""
    result = await _start_user_flow(hass)
    assert result["handler"] == DOMAIN
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    assert result["data_schema"] is not None
    assert CONF_HOST in result["data_schema"].schema


async def test_flow_success(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A reachable hub creates an entry keyed by the hub's ThingName."""
    aioclient_mock.post(REGISTRATION, json={"Error": 0, "ThingName": HUB_THING_NAME})

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: f"  {HUB_HOST} "}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Norman Hub ({HUB_HOST})"
    assert result["data"] == MOCK_CONFIG  # whitespace stripped
    assert result["result"].unique_id == HUB_THING_NAME
    assert aioclient_mock.call_count == 1


async def test_flow_falls_back_to_host_as_unique_id(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A hub that does not report a ThingName is keyed by its address instead."""
    aioclient_mock.post(REGISTRATION, json={"Error": 0})

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == HUB_HOST


@pytest.mark.parametrize("host", ["", "bad host", "192.168.1.5:10123", "http://hub"])
async def test_invalid_host_is_rejected_before_connecting(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, host: str
) -> None:
    """Malformed hosts are caught locally; no request is made."""
    aioclient_mock.post(REGISTRATION, json={"Error": 0, "ThingName": HUB_THING_NAME})

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: host}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_host"}
    assert aioclient_mock.call_count == 0


@pytest.mark.parametrize(
    ("mock_kwargs", "error"),
    [
        ({"exc": aiohttp.ClientConnectionError("refused")}, "cannot_connect"),
        ({"exc": TimeoutError()}, "cannot_connect"),
        ({"json": {"Error": 7}}, "invalid_response"),
        ({"text": "<html>not json</html>"}, "invalid_response"),
        ({"status": 500, "json": {}}, "invalid_response"),
    ],
)
async def test_flow_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_kwargs: dict,
    error: str,
) -> None:
    """Connection and protocol failures map to the right form error and keep the form open."""
    aioclient_mock.post(REGISTRATION, **mock_kwargs)

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    # The form recovers once the hub answers
    aioclient_mock.clear_requests()
    aioclient_mock.post(REGISTRATION, json={"Error": 0, "ThingName": HUB_THING_NAME})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_CONFIG
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_flow_unknown_error(hass: HomeAssistant) -> None:
    """Anything unexpected is logged and reported as unknown rather than crashing the flow."""
    result = await _start_user_flow(hass)
    with patch(
        "custom_components.norman.config_flow.NormanApiClient.async_validate_connection",
        side_effect=RuntimeError("boom"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=MOCK_CONFIG
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_already_configured_updates_host(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry
) -> None:
    """Re-adding a known hub by a new address aborts and refreshes the stored address."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.post(
        "http://192.168.1.99:10123/NM/v1/registration",
        json={"Error": 0, "ThingName": HUB_THING_NAME},
    )

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "192.168.1.99"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.99"


async def test_reconfigure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry
) -> None:
    """The reconfigure step moves the entry to a new address of the same hub."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.post(
        "http://192.168.1.99:10123/NM/v1/registration",
        json={"Error": 0, "ThingName": HUB_THING_NAME},
    )

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "192.168.1.99"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.99"
    assert mock_config_entry.title == "Norman Hub (192.168.1.99)"


async def test_reconfigure_rejects_a_different_hub(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry
) -> None:
    """Pointing an entry at some other hub is refused so entities are not silently swapped."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.post(
        "http://192.168.1.99:10123/NM/v1/registration",
        json={"Error": 0, "ThingName": "SomeOtherHub"},
    )

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "192.168.1.99"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_hub"
    assert mock_config_entry.data[CONF_HOST] == HUB_HOST


async def test_reconfigure_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry
) -> None:
    """Reconfigure validates the address the same way the user step does."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.post(
        "http://192.168.1.99:10123/NM/v1/registration", exc=aiohttp.ClientConnectionError()
    )

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "not a host"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_host"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "192.168.1.99"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert mock_config_entry.data[CONF_HOST] == HUB_HOST
