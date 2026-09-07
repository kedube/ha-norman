"""Integration for Norman window coverings."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import NormanApiClient, NormanApiError, NormanConnectionError
from .const import DOMAIN, MANUFACTURER, PLATFORMS
from .coordinator import NormanConfigEntry, NormanCoordinator
from .entity import hub_identifier
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

__all__ = ["NormanConfigEntry"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-level actions; entries are set up separately."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NormanConfigEntry) -> bool:
    """Set up Norman from a config entry."""
    api = NormanApiClient(entry.data[CONF_HOST], async_get_clientsession(hass))

    try:
        thing_name = await api.async_validate_connection()
    except (NormanConnectionError, NormanApiError) as err:
        raise ConfigEntryNotReady(f"Failed to connect to Norman hub: {err}") from err

    _async_migrate_unique_id(hass, entry, thing_name)

    coordinator = NormanCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # The hub itself gets a device so every blind can hang off it as a via-device.
    hub_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, hub_identifier(entry))},
        manufacturer=MANUFACTURER,
        model="Hub",
        name=entry.title,
        configuration_url=str(api.base_url),
    )
    coordinator.hub_device_id = hub_device.id

    # Listen to hub notifications for real-time updates. The task is cancelled
    # automatically when the entry is unloaded.
    entry.async_create_background_task(
        hass, coordinator.listen_notifications(), "norman-notification-listener"
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NormanConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: NormanConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow deleting a blind's device from the UI once the hub no longer reports it.

    The hub device and blinds that are still reported are refused: they would be
    recreated on the next refresh.
    """
    live = {(DOMAIN, str(uid)) for uid in entry.runtime_data.data}
    live.add((DOMAIN, hub_identifier(entry)))
    return not (device_entry.identifiers & live)


@callback
def _async_migrate_unique_id(
    hass: HomeAssistant, entry: NormanConfigEntry, thing_name: str | None
) -> None:
    """Move entries created before 0.11 from a host-based unique id to the hub's ThingName.

    Older versions keyed the entry by the address the user typed, so an address change or
    a re-add by hostname was not recognised as the same hub. If another entry already
    claims the ThingName (the same hub added twice under the old scheme) leave both alone
    and say so; merging them is the user's call.
    """
    if not thing_name or entry.unique_id == thing_name:
        return
    if entry.unique_id not in (None, entry.data[CONF_HOST]):
        return
    if hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, thing_name):
        _LOGGER.warning(
            "Norman hub %s is also configured under another entry; remove one of them",
            thing_name,
        )
        return
    _LOGGER.info("Migrating Norman config entry unique id from host to hub %s", thing_name)
    hass.config_entries.async_update_entry(entry, unique_id=thing_name)
