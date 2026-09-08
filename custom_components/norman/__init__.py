"""Integration for Norman window coverings."""

from __future__ import annotations

from functools import partial
import logging

from getmac import get_mac_address
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import (
    config_validation as cv,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.network import is_ip_address

from .api import NormanApiClient, NormanApiError, NormanConnectionError
from .const import DOMAIN, MANUFACTURER, PLATFORMS
from .coordinator import NormanConfigEntry, NormanCoordinator
from .entity import hub_identifier
from .frontend import async_register_card
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
    await _async_migrate_entity_unique_ids(hass, entry)

    coordinator = NormanCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    coordinator.hub.mac_address = await _async_resolve_mac(hass, entry.data[CONF_HOST])

    # The hub itself gets a device so every blind can hang off it as a via-device.
    hub_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, hub_identifier(entry))},
        connections=(
            {(dr.CONNECTION_NETWORK_MAC, coordinator.hub.mac_address)}
            if coordinator.hub.mac_address
            else set()
        ),
        manufacturer=MANUFACTURER,
        model=coordinator.hub.model or "Hub",
        sw_version=coordinator.hub.firmware_version,
        name=coordinator.hub.custom_name or entry.title,
        configuration_url=str(api.base_url),
    )
    coordinator.hub_device_id = hub_device.id

    # Listen to hub notifications for real-time updates. The task is cancelled
    # automatically when the entry is unloaded.
    entry.async_create_background_task(
        hass, coordinator.listen_notifications(), "norman-notification-listener"
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Serve and register the dashboard card. Best-effort: every entity works without it.
    await async_register_card(hass)
    return True


async def _async_resolve_mac(hass: HomeAssistant, host: str) -> str | None:
    """Look up the hub's MAC address on the local network.

    No hub payload carries a MAC, so it is read from the ARP table (getmac), which works
    only when Home Assistant is on the same network segment as the hub. Elsewhere it is
    simply unknown; a failed lookup is never an error.
    """
    lookup = {"ip": host} if is_ip_address(host) else {"hostname": host}
    try:
        mac = await hass.async_add_executor_job(partial(get_mac_address, **lookup))
    except Exception:  # noqa: BLE001 - getmac shells out; any failure means "unknown"
        _LOGGER.debug("Could not resolve the MAC address of %s", host, exc_info=True)
        return None
    return dr.format_mac(mac) if mac else None


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


# Entity unique-id suffixes renamed after release 0.11; old -> new
_RENAMED_ENTITY_KEYS = {"_battery_voltage": "_battery_level"}


async def _async_migrate_entity_unique_ids(hass: HomeAssistant, entry: NormanConfigEntry) -> None:
    """Keep entity ids and history when a sensor's unique id suffix is renamed.

    0.11 shipped the battery level as ``<uid>_battery_voltage``; real hubs turned out to
    report a percentage, so the sensor was renamed. Migrating the registry entry keeps the
    entity id and the recorded history instead of creating a second entity.
    """

    @callback
    def _migrate(entity_entry: er.RegistryEntry) -> dict[str, str] | None:
        for old, new in _RENAMED_ENTITY_KEYS.items():
            if entity_entry.unique_id.endswith(old):
                return {"new_unique_id": entity_entry.unique_id.removesuffix(old) + new}
        return None

    await er.async_migrate_entries(hass, entry.entry_id, _migrate)


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
