"""Frontend resource registration for the Norman shades Lovelace card.

The integration ships a hand-written Lovelace card (``www/norman-shades-card.js``) that
groups a hub's blinds by room and gives each rail a percentage slider. To make it usable
without the user adding a dashboard resource by hand, the integration:

  1. serves the file from a stable URL via a static path, and
  2. registers that URL as a Lovelace module resource (storage mode), or logs where to add
     it manually (YAML mode), once per Home Assistant start.

Registration is best-effort: a failure here never blocks setup, since every entity works
without the card.

It also puts a **Norman Shades** entry in the sidebar: a custom panel (``www/norman-panel.js``)
that shows the card full screen, one per hub whose "Show Norman Shades in the sidebar" option
is on, so the card is there without building a dashboard at all.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.loader import IntegrationNotLoaded, async_get_loaded_integration

from .const import CONF_SHOW_SIDEBAR_PANEL, DEFAULT_SHOW_SIDEBAR_PANEL, DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILENAME = "norman-shades-card.js"
# The integration's www/ directory is served at /norman/, so everything in it gets a stable
# URL from a single mount.
WWW_URL_BASE = f"/{DOMAIN}"
CARD_URL_PATH = f"{WWW_URL_BASE}/{CARD_FILENAME}"

_REGISTERED_KEY = f"{DOMAIN}_frontend_registered"

# The sidebar panel: a web component hosting the card full screen. It lives BESIDE, not
# under, the static /norman/ path: a panel at /norman would send a page reload there to the
# static file handler (a directory) instead of Home Assistant's app.
PANEL_FILENAME = "norman-panel.js"
PANEL_ELEMENT = "norman-panel"
PANEL_URL_PATH = "norman-shades"
PANEL_TITLE = "Norman Shades"
PANEL_ICON = "mdi:blinds"
# Entries that are set up (entry id -> entry), and the panels registered (url -> spec).
_PANEL_ENTRIES_KEY = f"{DOMAIN}_panel_entries"
_PANELS_KEY = f"{DOMAIN}_panels"

# A sidebar panel as registered: its title and the card config it carries.
type _PanelSpec = tuple[str, tuple[tuple[str, str], ...]]


def integration_version(hass: HomeAssistant) -> str:
    """The version from manifest.json, as Home Assistant already parsed it.

    manifest.json is the single source of this version: the release workflow bumps it and
    nothing else, then tags the commit it created. Home Assistant loads and caches that
    manifest when it sets the integration up, so asking the loader costs nothing and --
    unlike reading the file here -- touches no disk.

    That matters: this module is imported on the event loop when a user downloads
    diagnostics, and Home Assistant instruments ``Path.read_text`` precisely to catch
    blocking calls made there. Doing the read at import time put it wherever the first
    import happened to land.

    Falls back to "unknown" rather than raising if the integration is not loaded (the
    loader raises in that case). Registering a card at ``?v=unknown`` is a cosmetic loss;
    an exception out of the diagnostics export or of setup is not.
    """
    try:
        return async_get_loaded_integration(hass, DOMAIN).version or "unknown"
    except IntegrationNotLoaded:
        _LOGGER.debug("Norman integration not loaded; card version unknown")
        return "unknown"


def card_resource_url(hass: HomeAssistant) -> str:
    """The URL the card is registered at, carrying the version as a ``?v=`` cache-buster.

    Every release therefore invalidates a browser's cached copy without the user clearing
    anything, and the JavaScript reads the same value back off its own URL rather than
    carrying a constant that could fall behind.
    """
    return f"{CARD_URL_PATH}?v={integration_version(hass)}"


def panel_module_url(hass: HomeAssistant) -> str:
    """The sidebar panel's module URL, stamped like the card so an upgrade is never cached."""
    return f"{WWW_URL_BASE}/{PANEL_FILENAME}?v={integration_version(hass)}"


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve the integration's www/ assets and register the card (idempotent)."""
    if hass.data.get(_REGISTERED_KEY):
        return
    hass.data[_REGISTERED_KEY] = True

    # No HTTP component (some test and minimal configurations) means nothing to serve from.
    http = getattr(hass, "http", None)
    if http is None:
        _LOGGER.debug("HTTP component unavailable; skipping card registration")
        hass.data[_REGISTERED_KEY] = False
        return

    www_dir = Path(__file__).parent / "www"
    card_file = www_dir / CARD_FILENAME
    # is_file() hits the disk, which must not happen on the event loop.
    card_present = await hass.async_add_executor_job(card_file.is_file)
    if not card_present:
        _LOGGER.warning("Norman shades card file not found in %s", www_dir)
        hass.data[_REGISTERED_KEY] = False
        return

    try:
        # cache_headers=True is safe because each release registers a NEW URL (the ?v=
        # stamp changes), so staleness is busted by the URL rather than by refetching.
        await http.async_register_static_paths(
            [StaticPathConfig(WWW_URL_BASE, str(www_dir), cache_headers=True)]
        )
    except Exception:  # noqa: BLE001 - serving assets is best-effort, never block setup
        _LOGGER.exception("Norman could not serve the frontend assets")
        hass.data[_REGISTERED_KEY] = False
        return

    await _async_register_lovelace_resource(hass)


async def _async_register_lovelace_resource(hass: HomeAssistant) -> None:
    """Add the card URL to the Lovelace resource list when in storage mode.

    In YAML-mode Lovelace the resource list is user-managed, so all we can do is log where
    to add it. In storage mode the resource is created, and any entry left over from an
    earlier version is repointed at the new URL rather than left to load a stale module.
    """
    resource_url = card_resource_url(hass)
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if resources is None:
        _LOGGER.debug("Lovelace resources unavailable; skipping card auto-registration")
        return

    try:
        if not resources.loaded:
            await resources.async_load()
            resources.loaded = True
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not load Lovelace resources; the card must be added manually")
        return

    # YAML-mode resource stores cannot be mutated (they have no store attribute).
    if getattr(resources, "store", None) is None:
        _LOGGER.info(
            "The Norman shades card is served at %s. Add it under Settings > Dashboards > "
            "Resources (or your YAML `resources:`) as a JavaScript module.",
            resource_url,
        )
        return

    matches = [
        (str(item.get("url", "")), item.get("id"))
        for item in resources.async_items()
        if isinstance(item, dict) and str(item.get("url", "")).startswith(CARD_URL_PATH)
    ]
    stale = [(url, item_id) for url, item_id in matches if url != resource_url]
    current = len(matches) - len(stale)

    # Two entries for the same card make the browser load the module twice, and the second
    # customElements.define() throws -- so every stale entry is migrated or removed, not
    # just the first one.
    for index, (stale_url, item_id) in enumerate(stale):
        try:
            if current == 0 and index == 0:
                await resources.async_update_item(item_id, {"url": resource_url})
                _LOGGER.info("Updated Norman card resource %s -> %s", stale_url, resource_url)
            else:
                await resources.async_delete_item(item_id)
                _LOGGER.info("Removed duplicate Norman card resource %s", stale_url)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Norman could not migrate the card resource %s", stale_url)

    if matches:
        return
    try:
        await resources.async_create_item({"res_type": "module", "url": resource_url})
        _LOGGER.info("Registered the Norman shades card at %s", resource_url)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Norman could not auto-register the card resource")


async def async_add_entry_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Note a set-up hub and bring the sidebar in line (called at entry setup)."""
    hass.data.setdefault(_PANEL_ENTRIES_KEY, {})[entry.entry_id] = entry
    await _async_sync_panels_safely(hass)


async def async_remove_entry_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Forget an unloaded hub and bring the sidebar in line (called at entry unload)."""
    hass.data.setdefault(_PANEL_ENTRIES_KEY, {}).pop(entry.entry_id, None)
    await _async_sync_panels_safely(hass)


async def _async_sync_panels_safely(hass: HomeAssistant) -> None:
    try:
        await _async_sync_panels(hass)
    except Exception:  # noqa: BLE001 - the sidebar must never fail an entry's setup or unload
        _LOGGER.exception("Norman could not update its sidebar panel")


def _wanted_panels(entries: list[ConfigEntry]) -> dict[str, _PanelSpec]:
    """The sidebar panels these set-up entries call for: url path -> (title, config items).

    One hub gets plain "Norman Shades" at /norman-shades and a card with no hub pinned, which
    shows the same blinds as a card added to a dashboard. With several hubs each panel is
    titled after its entry and pins its hub, since the card otherwise shows every hub's blinds
    together and its whole-house buttons would not know which hub to send to.
    """
    several = len(entries) > 1
    wanted: dict[str, _PanelSpec] = {}
    titles: set[str] = set()
    showing = [
        entry
        for entry in entries
        if entry.options.get(CONF_SHOW_SIDEBAR_PANEL, DEFAULT_SHOW_SIDEBAR_PANEL)
    ]
    for number, entry in enumerate(showing, start=1):
        url_path = PANEL_URL_PATH if number == 1 else f"{PANEL_URL_PATH}-{number}"
        title = (entry.title or PANEL_TITLE) if several else PANEL_TITLE
        if title in titles:
            title = f"{title} {number}"
        titles.add(title)
        config = (("config_entry_id", entry.entry_id),) if several else ()
        wanted[url_path] = (title, config)
    return wanted


async def _async_sync_panels(hass: HomeAssistant) -> None:
    """Register the panels the set-up entries want and remove the ones they no longer do."""
    active: dict[str, ConfigEntry] = hass.data.setdefault(_PANEL_ENTRIES_KEY, {})
    # Config-entry order, not setup order (entries set up concurrently), keeps each hub's
    # sidebar address stable across restarts.
    order = [entry.entry_id for entry in hass.config_entries.async_entries(DOMAIN)]
    entries = sorted(
        active.values(),
        key=lambda entry: order.index(entry.entry_id) if entry.entry_id in order else len(order),
    )
    wanted = _wanted_panels(entries)
    registered: dict[str, _PanelSpec] = hass.data.setdefault(_PANELS_KEY, {})
    for url_path, spec in list(registered.items()):
        if wanted.get(url_path) == spec:
            continue
        try:
            frontend.async_remove_panel(hass, url_path, warn_if_unknown=False)
        except Exception:  # noqa: BLE001 - the sidebar is best-effort
            _LOGGER.debug("Could not remove the Norman sidebar panel %s", url_path)
        del registered[url_path]
    for url_path, (title, config) in wanted.items():
        if url_path in registered:
            continue
        try:
            await panel_custom.async_register_panel(
                hass,
                frontend_url_path=url_path,
                webcomponent_name=PANEL_ELEMENT,
                sidebar_title=title,
                sidebar_icon=PANEL_ICON,
                module_url=panel_module_url(hass),
                config=dict(config),
                require_admin=False,
            )
        except Exception:  # noqa: BLE001 - the sidebar is best-effort
            _LOGGER.exception("Norman could not add its sidebar panel at /%s", url_path)
            continue
        registered[url_path] = (title, config)
        _LOGGER.debug("Added the Norman sidebar panel at /%s", url_path)


def _resource_version(url: str) -> str:
    """The ``?v=`` stamp on a registered resource URL, or "unknown" without one.

    This mirrors what the card itself does in the browser (it reads its version from the
    same stamp), so the two can be compared directly.
    """
    _, _, query = url.partition("?")
    for part in query.split("&"):
        key, _, value = part.partition("=")
        if key == "v":
            return value or "unknown"
    return "unknown"


def async_get_frontend_diagnostics(hass: HomeAssistant) -> dict[str, object]:
    """Card-version info for the diagnostics export.

    Compares the URL this build expects against what Lovelace has registered, so a user
    running a cached older card is visible straight from a diagnostics download.
    """
    version = integration_version(hass)
    registered: list[str] = []
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if resources is not None:
        try:
            registered = [
                str(item.get("url", ""))
                for item in resources.async_items()
                if isinstance(item, dict)
                and str(item.get("url", "")).startswith(f"{WWW_URL_BASE}/")
            ]
        except Exception:  # noqa: BLE001 - diagnostics must never fail the export
            _LOGGER.debug("Could not read Lovelace resources for diagnostics")
    # The registered URL is what the browser is told to fetch, so its ?v= is the version
    # the card will report in its console banner. Comparing it here turns "the card looks
    # wrong" into a single boolean in the diagnostics download.
    versions = [_resource_version(url) for url in registered]
    return {
        "integration_version": version,
        "expected_resource": card_resource_url(hass),
        "registered_resources": registered,
        "registered_versions": versions,
        # None (rather than True) when nothing is registered: there is no card to be stale.
        "version_matches": all(v == version for v in versions) if versions else None,
        "sidebar_panels": sorted(hass.data.get(_PANELS_KEY, {})),
    }
