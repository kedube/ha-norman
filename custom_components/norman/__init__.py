"""Integration for Norman window coverings."""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
import logging
from typing import Any

from getmac import get_mac_address
from homeassistant.config_entries import ConfigEntryState
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
from homeassistant.util.network import is_ipv4_address, is_ipv6_address

from . import coordinator as norman_coordinator
from .api import NormanApiClient, NormanApiError, NormanConnectionError
from .const import (
    CONF_CONTROL_INTERVAL,
    CONF_POLL_INTERVAL,
    CONF_SHOW_SIDEBAR_PANEL,
    CONF_WAKE_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_WAKE_INTERVAL,
    DOMAIN,
    MANUFACTURER,
    PLATFORMS,
    is_default_title,
)
from .coordinator import (
    NormanConfigEntry,
    NormanCoordinator,
    room_identifier,
    rooms_of,
)
from .entity import hub_identifier
from .frontend import (
    async_add_entry_panel,
    async_register_card,
    async_remove_card_resource,
    async_remove_entry_panel,
)
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
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="connect_failed",
            translation_placeholders={"hub": entry.title, "error": str(err)},
        ) from err

    _async_migrate_unique_id(hass, entry, thing_name)
    await _async_migrate_entity_unique_ids(hass, entry)

    coordinator = NormanCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    # Before the update listener below is added: a title change would otherwise reload the entry
    _async_title_after_hub(hass, entry, coordinator.hub.custom_name)
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

    # The optional wake sweep (have every blind report in on a timer) runs alongside.
    coordinator.async_start_wake_sweep()

    # A changed poll or wake interval is applied by reloading: both are read from the
    # options at construction / setup.
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # With the hub's device list unreadable, rooms are named after their blinds' areas,
    # which exist (or are restored on a re-add) only now that the platforms have run.
    coordinator.async_apply_registry_names()

    # Serve and register the dashboard card. Best-effort: every entity works without it.
    await async_register_card(hass)
    # The sidebar entry that opens the card full screen (when the option is on).
    await async_add_entry_panel(hass, entry)
    return True


@callback
def _async_title_after_hub(
    hass: HomeAssistant, entry: NormanConfigEntry, hub_name: str | None
) -> None:
    """Title the entry after the hub's name in the Norman app, as its device is named.

    Only a title the integration gave is replaced: the ``Norman Hub (<host>)`` a new entry
    gets, or the hub's previous name (its device's name until this setup renames it). A
    title chosen in Home Assistant stays.
    """
    if not hub_name or entry.title == hub_name:
        return
    previous = next(
        (
            device.name
            for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
            if (DOMAIN, hub_identifier(entry)) in device.identifiers
        ),
        None,
    )
    if is_default_title(entry.title) or entry.title == previous:
        hass.config_entries.async_update_entry(entry, title=hub_name)


async def _async_resolve_mac(hass: HomeAssistant, host: str) -> str | None:
    """Look up the hub's MAC address on the local network.

    No hub payload carries a MAC, so it is read from the ARP table (getmac), which works
    only when Home Assistant is on the same network segment as the hub. Elsewhere it is
    simply unknown; a failed lookup is never an error. getmac takes an IPv6 address only as
    ``ip6``: passed as ``ip`` it is looked up as IPv4 and never found.
    """
    if is_ipv4_address(host):
        lookup = partial(get_mac_address, ip=host)
    elif is_ipv6_address(host):
        lookup = partial(get_mac_address, ip6=host)
    else:
        lookup = partial(get_mac_address, hostname=host)
    try:
        mac = await hass.async_add_executor_job(lookup)
    except Exception:  # noqa: BLE001 - getmac shells out; any failure means "unknown"
        _LOGGER.debug("Could not resolve the MAC address of %s", host, exc_info=True)
        return None
    return dr.format_mac(mac) if mac else None


# Options applied to the running hub by the update listener. Every other option, and the
# entry's data, is read at setup and reloads the entry when it changes.
_LIVE_OPTIONS = frozenset({CONF_CONTROL_INTERVAL, CONF_SHOW_SIDEBAR_PANEL})
# What an option the entry does not store yet amounts to, so that saving the options form for
# the first time does not count as a change to an interval it leaves at its default.
_SETUP_OPTION_DEFAULTS = {
    CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL,
    CONF_WAKE_INTERVAL: DEFAULT_WAKE_INTERVAL,
}


def _read_at_setup(
    data: Mapping[str, Any], options: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The part of an entry's data and options that only a setup reads."""
    options = {**_SETUP_OPTION_DEFAULTS, **options}
    return dict(data), {key: value for key, value in options.items() if key not in _LIVE_OPTIONS}


async def _async_entry_updated(hass: HomeAssistant, entry: NormanConfigEntry) -> None:
    """Reload when the hub's address or an interval changed; apply anything else live.

    The poll and wake sweep intervals are read at setup, so a change to either reloads the
    entry. Command spacing is set on the running client, derived as setup derives it, and the
    sidebar is brought in line with its switch and with the title, which only the sidebar
    shows (with more than one hub). Reloading for those would reconnect the hub's stream and
    drop every move watch in flight for nothing.
    """
    coordinator = entry.runtime_data
    if _read_at_setup(entry.data, entry.options) != _read_at_setup(*coordinator.config_at_setup):
        await hass.config_entries.async_reload(entry.entry_id)
        return
    coordinator.api.control_interval = norman_coordinator._control_interval(entry)
    await async_add_entry_panel(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: NormanConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await async_remove_entry_panel(hass, entry)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: NormanConfigEntry) -> None:
    """Take the dashboard card's resource away with the last hub removed.

    A hub that is ignored or disabled does not count: Home Assistant does not set the
    integration up for one, so after a restart nothing would serve the card. Enabling a
    disabled hub registers the resource again when it is set up.
    """
    if not hass.config_entries.async_entries(DOMAIN, include_ignore=False, include_disabled=False):
        await async_remove_card_resource(hass)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: NormanConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow deleting a blind's or a room's device from the UI once the hub no longer has it.

    The hub device, and blinds and rooms that are still reported, are refused: they would
    be recreated on the next refresh. A room is reported while it holds a blind or a scene.

    While the hub is not set up (unreachable, or disabled) there is no report to check
    against, so any device may go; a blind or room the hub still has is recreated at the
    next setup.
    """
    if entry.state is not ConfigEntryState.LOADED:
        return True
    data = entry.runtime_data.data
    live = {(DOMAIN, str(uid)) for uid in data}
    live.update((DOMAIN, room_identifier(entry, room_id)) for room_id in rooms_of(data))
    # A room is reported, too, while it holds a scene: the scene's entity lives on its device.
    live.update(
        (DOMAIN, room_identifier(entry, scene.room_id))
        for scene in entry.runtime_data.scenes.values()
    )
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
