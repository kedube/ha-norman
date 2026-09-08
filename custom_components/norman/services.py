"""Integration-level actions (not tied to one entity)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .api import NormanApiError, NormanConnectionError
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_FIELDS,
    ATTR_PERIPHERAL_UID,
    DOMAIN,
    SENSITIVE_HUB_KEYS,
    SERVICE_GET_HUB_DATA,
    SERVICE_SEND_HUB_COMMAND,
)
from .coordinator import NormanConfigEntry

GET_HUB_DATA_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})

SEND_HUB_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_PERIPHERAL_UID): vol.Coerce(int),
        vol.Required(ATTR_FIELDS): vol.Schema({cv.string: vol.Any(int, float, str, bool)}),
    }
)


def _resolve_entry(hass: HomeAssistant, call: ServiceCall) -> NormanConfigEntry:
    """Find the entry the call targets; with a single hub the id can be omitted."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(f"No Norman hub with config entry id {entry_id}")
    elif len(entries) == 1:
        entry = entries[0]
    else:
        raise ServiceValidationError(
            f"{len(entries)} Norman hubs are configured; pass {ATTR_CONFIG_ENTRY_ID}"
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(f"Norman hub {entry.title} is not loaded")
    return entry


async def _async_get_hub_data(call: ServiceCall) -> ServiceResponse:
    """Return the hub's raw device list and status, fetched live.

    This is the JSON the hub sends, including fields the integration does not (yet)
    understand, which is what a "please support my blind" report needs. Only the keys that
    identify the home or network (location, Wi-Fi name, hub identity) are blanked; they have
    no diagnostic value and the response is meant to be pasted into issues.
    """
    entry = _resolve_entry(call.hass, call)
    api = entry.runtime_data.api
    try:
        devices: dict[str, Any] = await api.async_get_devices()
        status: dict[str, Any] = await api.async_get_status()
    except (NormanConnectionError, NormanApiError) as err:
        raise HomeAssistantError(f"Could not read from Norman hub {entry.title}: {err}") from err
    return async_redact_data({"devices": devices, "status": status}, SENSITIVE_HUB_KEYS)


async def _async_send_hub_command(call: ServiceCall) -> ServiceResponse:
    """POST arbitrary fields to the hub's control endpoint for one peripheral.

    An advanced tool for probing commands the hub advertises but the integration does not
    know how to send yet (``MotorStop``, limits, favourites, ...). The hub's reply is
    returned so the outcome can be seen. The blind will do whatever the hub makes of it.
    """
    entry = _resolve_entry(call.hass, call)
    api = entry.runtime_data.api
    uid: int = call.data[ATTR_PERIPHERAL_UID]
    fields: dict[str, Any] = dict(call.data[ATTR_FIELDS])
    try:
        reply = await api.async_send_control(uid, fields)
    except (NormanConnectionError, NormanApiError) as err:
        raise HomeAssistantError(
            f"Norman hub {entry.title} rejected the command for {uid}: {err}"
        ) from err
    await entry.runtime_data.async_request_refresh()
    return {"reply": reply}


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions. Called once from async_setup."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_HUB_DATA,
        _async_get_hub_data,
        schema=GET_HUB_DATA_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_HUB_COMMAND,
        _async_send_hub_command,
        schema=SEND_HUB_COMMAND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
