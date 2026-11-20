"""Test the Norman config flow."""

from __future__ import annotations

from ipaddress import ip_address
from unittest.mock import patch

import aiohttp
from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF, ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery_flow import DiscoveryKey
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.norman.const import (
    CONF_CONTROL_INTERVAL,
    CONF_SHOW_SIDEBAR_PANEL,
    CONF_SIDEBAR_VIEW,
    CONF_SIDEBAR_VIEW_FORECAST,
    CONF_SIDEBAR_VIEW_MOTION,
    CONF_SIDEBAR_VIEW_WEATHER,
    DEFAULT_CONTROL_INTERVAL,
    DEFAULT_SHOW_SIDEBAR_PANEL,
    DEFAULT_SIDEBAR_VIEW,
    DEFAULT_SIDEBAR_VIEW_FORECAST,
    DEFAULT_SIDEBAR_VIEW_MOTION,
    DOMAIN,
    MAX_CONTROL_INTERVAL,
    MIN_CONTROL_INTERVAL,
    PHOTO_CREDITS_URL,
    SIDEBAR_VIEW_NONE,
    SIDEBAR_VIEWS,
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


async def test_reconfigure_keeps_a_chosen_title(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry
) -> None:
    """A new address does not undo a title from the hub's name or from Home Assistant."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, title="Lakehouse Shades")
    aioclient_mock.post(
        "http://192.168.1.99:10123/NM/v1/registration",
        json={"Error": 0, "ThingName": HUB_THING_NAME},
    )

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "192.168.1.99"}
    )

    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.99"
    assert mock_config_entry.title == "Lakehouse Shades"


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


@pytest.mark.parametrize(
    ("reply", "unique_id"),
    [
        ({"Error": 0}, "192.168.1.99"),
        ({"Error": 0, "ThingName": HUB_THING_NAME}, HUB_THING_NAME),
    ],
    ids=["without-a-thing-name", "added-before-0.11"],
)
async def test_reconfigure_moves_an_entry_keyed_by_its_address(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, reply: dict, unique_id: str
) -> None:
    """An entry keyed by its old address moves, and takes the key its hub gives at the new one.

    A hub that answers without a ThingName is keyed by its address, and so is an entry from
    before 0.11 that has not been set up since; neither key can match the hub at a new one.
    """
    entry = MockConfigEntry(
        domain=DOMAIN, title=f"Norman Hub ({HUB_HOST})", data=MOCK_CONFIG, unique_id=HUB_HOST
    )
    entry.add_to_hass(hass)
    aioclient_mock.post("http://192.168.1.99:10123/NM/v1/registration", json=reply)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_HOST: "192.168.1.99"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "192.168.1.99"
    assert entry.unique_id == unique_id


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
    """A valid hub mDNS announcement without optional TXT fields."""
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


async def test_rediscovering_a_loaded_hub_at_its_address_asks_it_nothing(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry
) -> None:
    """Every hub announces itself at each start; one loaded at that address is not contacted.

    The discovery is still recorded on its entry, so removing the entry offers the hub again.
    """
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.mock_state(hass, ConfigEntryState.LOADED)
    aioclient_mock.post(REGISTRATION, json={"Error": 0, "ThingName": HUB_THING_NAME})
    key = DiscoveryKey(
        domain="zeroconf",
        key=("_nien_made._tcp.local.", "NienMadeLocal._nien_made._tcp.local."),
        version=1,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF, "discovery_key": key}, data=_discovery()
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert aioclient_mock.call_count == 0
    assert mock_config_entry.discovery_keys["zeroconf"] == (key,)


async def test_rediscovering_a_hub_waiting_to_retry_setup_reloads_it(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry
) -> None:
    """A hub that failed to set up is asked who it is, and found, it is set up again at once."""
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    aioclient_mock.post(REGISTRATION, json={"Error": 0, "ThingName": HUB_THING_NAME})

    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        result = await _start_zeroconf_flow(hass)

    assert result["reason"] == "already_configured"
    assert aioclient_mock.call_count == 1
    reload.assert_called_once_with(mock_config_entry.entry_id)


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


# What the options form stores for the sidebar page's view when its fields are left alone.
VIEW_DEFAULTS = {
    CONF_SIDEBAR_VIEW: DEFAULT_SIDEBAR_VIEW,
    CONF_SIDEBAR_VIEW_MOTION: DEFAULT_SIDEBAR_VIEW_MOTION,
    CONF_SIDEBAR_VIEW_FORECAST: DEFAULT_SIDEBAR_VIEW_FORECAST,
}


async def _open_options(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    """Start the options flow for ``entry``."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return await hass.config_entries.options.async_init(entry.entry_id)


@pytest.mark.parametrize("value", [0.0, MIN_CONTROL_INTERVAL - 0.1, MAX_CONTROL_INTERVAL + 1])
async def test_options_flow_rejects_values_outside_the_selector(
    hass: HomeAssistant, value: float
) -> None:
    """Anything beyond the selector's own bounds is refused by the schema."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    result = await _open_options(hass, entry)

    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_CONTROL_INTERVAL: value}
        )
    assert entry.options == {}


async def test_options_flow_defaults_to_the_current_value(hass: HomeAssistant) -> None:
    """The form is seeded with what is configured, so saving twice is not destructive."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, options={CONF_CONTROL_INTERVAL: 2.5})
    result = await _open_options(hass, entry)

    schema = result["data_schema"].schema
    key = next(k for k in schema if str(k) == CONF_CONTROL_INTERVAL)
    assert key.description["suggested_value"] == 2.5
    assert key.default() == DEFAULT_CONTROL_INTERVAL


async def test_options_schema_is_serializable_for_the_frontend(hass: HomeAssistant) -> None:
    """The options form must survive being converted for the websocket API.

    The frontend fetches the schema over the websocket API, which runs it through
    ``to_field_list`` -- the same call used here. That understands selectors and a few known
    validators only: a plain function in the schema (a `vol.All(selector, _check)` wrapper,
    say) fails to convert while the form is being built, which reaches the user as a bare
    "Config flow could not be loaded: 500 Internal Server Error" and a dialog that never
    opens. Every other options test drives the flow directly and never serializes, so
    nothing else here would catch it.
    """
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    result = await _open_options(hass, entry)

    # Home Assistant 2026.9 replaced voluptuous_serialize.convert with probatio's
    # to_field_list for this (2026.10 calls it from probatio directly, no longer re-exported
    # from helpers.data_entry_flow); use whichever the installed release has.
    try:
        from probatio import to_field_list as _serialize
    except ImportError:  # pragma: no cover - Home Assistant < 2026.9
        from voluptuous_serialize import convert as _serialize

    converted = _serialize(result["data_schema"], custom_serializer=cv.custom_serializer)

    assert converted == [
        {
            "name": CONF_CONTROL_INTERVAL,
            "required": True,
            "default": DEFAULT_CONTROL_INTERVAL,
            # No "off" value, so the default is also what an unconfigured entry is offered.
            "description": {"suggested_value": DEFAULT_CONTROL_INTERVAL},
            "selector": {
                "number": {
                    "min": float(MIN_CONTROL_INTERVAL),
                    "max": float(MAX_CONTROL_INTERVAL),
                    "step": 0.1,
                    "unit_of_measurement": "seconds",
                    "mode": "box",
                }
            },
        },
        {
            "name": CONF_SHOW_SIDEBAR_PANEL,
            "required": True,
            "default": DEFAULT_SHOW_SIDEBAR_PANEL,
            "description": {"suggested_value": DEFAULT_SHOW_SIDEBAR_PANEL},
            "selector": {"boolean": {}},
        },
        {
            "name": CONF_SIDEBAR_VIEW,
            "required": True,
            "default": DEFAULT_SIDEBAR_VIEW,
            "description": {"suggested_value": DEFAULT_SIDEBAR_VIEW},
            "selector": {
                "select": {
                    # The places, then "none"; their names come from the translations.
                    "options": [*SIDEBAR_VIEWS, SIDEBAR_VIEW_NONE],
                    "translation_key": CONF_SIDEBAR_VIEW,
                    "mode": "dropdown",
                    "multiple": False,
                    "custom_value": False,
                    "sort": False,
                }
            },
        },
        {
            "name": CONF_SIDEBAR_VIEW_MOTION,
            "required": True,
            "default": DEFAULT_SIDEBAR_VIEW_MOTION,
            "description": {"suggested_value": DEFAULT_SIDEBAR_VIEW_MOTION},
            "selector": {"boolean": {}},
        },
        {
            "name": CONF_SIDEBAR_VIEW_FORECAST,
            "required": True,
            "default": DEFAULT_SIDEBAR_VIEW_FORECAST,
            "description": {"suggested_value": DEFAULT_SIDEBAR_VIEW_FORECAST},
            "selector": {"boolean": {}},
        },
        {
            # Optional, with nothing suggested: left empty, the page finds a weather entity.
            "name": CONF_SIDEBAR_VIEW_WEATHER,
            "required": False,
            "optional": True,
            "selector": {"entity": {"domain": ["weather"], "multiple": False, "reorder": False}},
        },
    ]


async def test_options_form_suggests_the_defaults(
    hass: HomeAssistant,
) -> None:
    """A fresh entry is offered the defaults, and nothing else.

    Command spacing has no "off" value, so its suggestion is simply its default; the sidebar
    entry is on, with its view on the coast and moving. No weather entity is suggested: the
    page finds one itself.
    """
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    result = await _open_options(hass, entry)

    schema = result["data_schema"].schema
    suggested = {str(k): k.description["suggested_value"] for k in schema if k.description}
    assert suggested == {
        CONF_CONTROL_INTERVAL: DEFAULT_CONTROL_INTERVAL,
        CONF_SHOW_SIDEBAR_PANEL: True,
        **VIEW_DEFAULTS,
    }
    assert CONF_SIDEBAR_VIEW_WEATHER in {str(k) for k in schema}
    # The view option's description links to the photographs' credits.
    assert result["description_placeholders"] == {"credits": PHOTO_CREDITS_URL}


async def test_saving_the_untouched_form_stores_only_the_change(
    hass: HomeAssistant,
) -> None:
    """Submitting the form as first shown stores the defaults beside the one change made.

    The frontend submits a field's suggested value unless the user clears it. The form once
    suggested a wake sweep and a poll, so opening Configure to change anything else switched
    both on, and on a hub of type 48 roller shades the sweep closed every shade (issue #5).
    """
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    result = await _open_options(hass, entry)
    as_shown = {
        str(k): k.description["suggested_value"]
        for k in result["data_schema"].schema
        if k.description
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={**as_shown, CONF_CONTROL_INTERVAL: 2.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_CONTROL_INTERVAL: 2.0,
        CONF_SHOW_SIDEBAR_PANEL: True,
        **VIEW_DEFAULTS,
    }


async def test_options_flow_turns_the_sidebar_entry_off(hass: HomeAssistant) -> None:
    """Unticking the sidebar toggle is stored, so the next setup leaves the panel out."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    result = await _open_options(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_SHOW_SIDEBAR_PANEL: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SHOW_SIDEBAR_PANEL] is False


async def test_options_saved_before_the_sidebar_toggle_show_it_on(hass: HomeAssistant) -> None:
    """Options stored by an older release have no sidebar key; the form offers it ticked.

    The other fields are seeded from what is stored, so this one must not come back blank,
    which would read as "off" to someone who never chose that.
    """
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, options={CONF_CONTROL_INTERVAL: 2.0})
    result = await _open_options(hass, entry)

    schema = result["data_schema"].schema
    key = next(k for k in schema if str(k) == CONF_SHOW_SIDEBAR_PANEL)
    assert key.default() is True


async def test_options_flow_stores_the_view(hass: HomeAssistant) -> None:
    """The place, whether it moves, the forecast and the weather entity are all stored."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    result = await _open_options(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_SIDEBAR_VIEW: "lake",
            CONF_SIDEBAR_VIEW_MOTION: False,
            CONF_SIDEBAR_VIEW_FORECAST: False,
            CONF_SIDEBAR_VIEW_WEATHER: "weather.lakehouse",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SIDEBAR_VIEW] == "lake"
    assert entry.options[CONF_SIDEBAR_VIEW_MOTION] is False
    assert entry.options[CONF_SIDEBAR_VIEW_FORECAST] is False
    assert entry.options[CONF_SIDEBAR_VIEW_WEATHER] == "weather.lakehouse"


async def test_options_flow_turns_the_view_off(hass: HomeAssistant) -> None:
    """ "None" is a choice like the places: the page goes back to the plain card."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    result = await _open_options(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_SIDEBAR_VIEW: SIDEBAR_VIEW_NONE}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SIDEBAR_VIEW] == SIDEBAR_VIEW_NONE


async def test_options_flow_refuses_a_place_there_are_no_photographs_of(
    hass: HomeAssistant,
) -> None:
    """The view is one of the places that ship, or none: anything else is refused."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG)
    result = await _open_options(hass, entry)

    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_SIDEBAR_VIEW: "desert"}
        )
    assert entry.options == {}


async def test_clearing_the_weather_entity_forgets_it(hass: HomeAssistant) -> None:
    """A weather entity chosen earlier is shown, and goes when its field is cleared.

    The frontend leaves a cleared optional field out of what it submits. The entity must not
    linger in the options then: an absent key is what tells the page to find one itself.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG,
        options={CONF_SIDEBAR_VIEW_WEATHER: "weather.lakehouse"},
    )
    result = await _open_options(hass, entry)
    key = next(k for k in result["data_schema"].schema if str(k) == CONF_SIDEBAR_VIEW_WEATHER)
    assert key.description["suggested_value"] == "weather.lakehouse"

    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_SIDEBAR_VIEW_WEATHER not in entry.options


async def test_options_saved_before_the_view_show_it_on(hass: HomeAssistant) -> None:
    """Options stored by an older release have no view keys; the form offers the defaults."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, options={CONF_CONTROL_INTERVAL: 2.0})
    result = await _open_options(hass, entry)

    defaults = {
        str(k): k.default() for k in result["data_schema"].schema if str(k) in VIEW_DEFAULTS
    }
    assert defaults == VIEW_DEFAULTS


@pytest.mark.parametrize(
    ("state", "reloads"),
    [(ConfigEntryState.SETUP_RETRY, 1), (ConfigEntryState.LOADED, 0)],
    ids=["retrying", "loaded"],
)
async def test_a_known_hub_found_at_a_new_address_is_reloaded_once(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    state: ConfigEntryState,
    reloads: int,
) -> None:
    """The flow reloads a hub waiting to retry setup; a loaded one reloads itself.

    A loaded hub's update listener reloads it when its address changes, so the flow
    reloading it too set it up twice.
    """
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.mock_state(hass, state)
    aioclient_mock.post(
        "http://192.168.1.99:10123/NM/v1/registration",
        json={"Error": 0, "ThingName": HUB_THING_NAME},
    )

    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        result = await _start_zeroconf_flow(hass, "192.168.1.99")

    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.99"
    assert reload.call_count == reloads
