"""Test the Norman config flow."""

from __future__ import annotations

from ipaddress import ip_address
from unittest.mock import patch

import aiohttp
from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
import voluptuous_serialize

from custom_components.norman.const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    POLL_DISABLED,
    SUGGESTED_POLL_INTERVAL,
)

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


# ---- zeroconf discovery --------------------------------------------------------------------


def _discovery(host: str = HUB_HOST) -> ZeroconfServiceInfo:
    """What Home Assistant hands the flow for the hub's mDNS announcement (no TXT record)."""
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        port=10123,
        hostname="Dexatek.local.",
        type="_nien_made._tcp.local.",
        name="NienMadeLocal._nien_made._tcp.local.",
        properties={},
    )


async def _start_zeroconf_flow(hass: HomeAssistant, host: str = HUB_HOST):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_discovery(host)
    )


async def test_zeroconf_discovery_creates_entry_after_confirmation(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A discovered hub is validated, shown for confirmation, then added keyed by ThingName."""
    aioclient_mock.post(REGISTRATION, json={"Error": 0, "ThingName": HUB_THING_NAME})

    result = await _start_zeroconf_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    assert result["description_placeholders"] == {"host": HUB_HOST}
    assert aioclient_mock.call_count == 1  # validated before asking

    flow = hass.config_entries.flow.async_get(result["flow_id"])
    assert flow["context"]["title_placeholders"] == {"host": HUB_HOST}
    assert flow["context"]["unique_id"] == HUB_THING_NAME

    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Norman Hub ({HUB_HOST})"
    assert result["data"] == MOCK_CONFIG
    assert result["result"].unique_id == HUB_THING_NAME


async def test_zeroconf_discovery_of_known_hub_updates_host(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry
) -> None:
    """A configured hub announcing from a new address is not re-added; its address is refreshed."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.post(
        "http://192.168.1.99:10123/NM/v1/registration",
        json={"Error": 0, "ThingName": HUB_THING_NAME},
    )

    result = await _start_zeroconf_flow(hass, "192.168.1.99")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.99"


@pytest.mark.parametrize(
    ("mock_kwargs", "reason"),
    [
        ({"exc": aiohttp.ClientConnectionError("refused")}, "cannot_connect"),
        ({"json": {"Error": 7}}, "invalid_response"),
    ],
)
async def test_zeroconf_discovery_aborts_when_hub_does_not_answer(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_kwargs: dict, reason: str
) -> None:
    """Something answering on the service name but not as a hub is dropped, not offered."""
    aioclient_mock.post(REGISTRATION, **mock_kwargs)

    result = await _start_zeroconf_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    assert not hass.config_entries.flow.async_progress()


async def test_zeroconf_discovery_unknown_error_aborts(hass: HomeAssistant) -> None:
    """An unexpected failure during discovery aborts with the generic reason."""
    with patch(
        "custom_components.norman.config_flow.NormanApiClient.async_validate_connection",
        side_effect=RuntimeError("boom"),
    ):
        result = await _start_zeroconf_flow(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unknown"


async def _open_options(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    """Start the options flow for ``entry``."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return await hass.config_entries.options.async_init(entry.entry_id)


@pytest.mark.parametrize("value", [POLL_DISABLED, 10, 30, 3600])
async def test_options_flow_stores_the_poll_interval(hass: HomeAssistant, value: int) -> None:
    """0 (off) and every in-range value are accepted and stored as an int."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    result = await _open_options(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_POLL_INTERVAL: value}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_POLL_INTERVAL: value}
    assert isinstance(entry.options[CONF_POLL_INTERVAL], int)


@pytest.mark.parametrize("value", [1, 9])
async def test_options_flow_rejects_the_gap_between_off_and_the_floor(
    hass: HomeAssistant, value: int
) -> None:
    """A value between "off" and the floor is refused rather than silently corrected.

    Without this the form would accept, say, 1 second, and the coordinator would quietly
    substitute the default -- leaving the options page showing a number that is not the one
    in force. The selector cannot express the gap, so the step handler checks it and the
    form comes back with an error.
    """
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    result = await _open_options(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_POLL_INTERVAL: value}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_POLL_INTERVAL: "poll_interval_out_of_range"}
    assert entry.options == {}


@pytest.mark.parametrize("value", [-1, 5000])
async def test_options_flow_rejects_values_outside_the_selector(
    hass: HomeAssistant, value: int
) -> None:
    """Anything beyond the selector's own bounds is refused by the schema."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    result = await _open_options(hass, entry)

    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_POLL_INTERVAL: value}
        )
    assert entry.options == {}


async def test_options_flow_defaults_to_the_current_value(hass: HomeAssistant) -> None:
    """The form is seeded with what is configured, so saving twice is not destructive."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, options={CONF_POLL_INTERVAL: 120})
    result = await _open_options(hass, entry)

    schema = result["data_schema"].schema
    key = next(k for k in schema if str(k) == CONF_POLL_INTERVAL)
    assert key.description["suggested_value"] == 120
    assert key.default() == DEFAULT_POLL_INTERVAL


async def test_options_schema_is_serializable_for_the_frontend(hass: HomeAssistant) -> None:
    """The options form must survive being converted for the websocket API.

    The frontend fetches the schema over the websocket API, which runs it through
    voluptuous_serialize. That can only convert selectors and a few known validators: a
    plain function in the schema (a `vol.All(selector, _check)` wrapper, say) raises
    "Unable to convert schema" while the form is being built, which reaches the user as a
    bare "Config flow could not be loaded: 500 Internal Server Error" and a dialog that
    never opens. Every other options test drives the flow directly and never serializes,
    so nothing else here would catch it.
    """
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    result = await _open_options(hass, entry)

    converted = voluptuous_serialize.convert(
        result["data_schema"], custom_serializer=cv.custom_serializer
    )

    assert converted == [
        {
            "name": CONF_POLL_INTERVAL,
            "required": True,
            "default": DEFAULT_POLL_INTERVAL,
            # An unconfigured entry is offered a working interval rather than the 0 default.
            "description": {"suggested_value": SUGGESTED_POLL_INTERVAL},
            "selector": {
                "number": {
                    "min": float(POLL_DISABLED),
                    "max": float(MAX_POLL_INTERVAL),
                    "step": 1.0,
                    "unit_of_measurement": "seconds",
                    "mode": "box",
                }
            },
        }
    ]
