"""Integration-level actions (not tied to one entity)."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .api import NormanApiError, NormanConnectionError
from .const import ATTR_CONFIG_ENTRY_ID, DOMAIN, SERVICE_GET_HUB_DATA
from .coordinator import NormanConfigEntry

GET_HUB_DATA_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})


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

    This is the untouched JSON the hub sends, including fields the integration does not
    (yet) understand, which is what a "please support my blind" report needs.
    """
    entry = _resolve_entry(call.hass, call)
    api = entry.runtime_data.api
    try:
        devices: dict[str, Any] = await api.async_get_devices()
        status: dict[str, Any] = await api.async_get_status()
    except (NormanConnectionError, NormanApiError) as err:
        raise HomeAssistantError(f"Could not read from Norman hub {entry.title}: {err}") from err
    return {"thing_name": api.thing_name, "devices": devices, "status": status}


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions. Called once from async_setup."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_HUB_DATA,
        _async_get_hub_data,
        schema=GET_HUB_DATA_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
