"""Frontend resource registration for the Norman shades Lovelace card.

The integration ships a hand-written Lovelace card (``www/norman-shades-card.js``) that
groups a hub's blinds by room and gives each rail a percentage slider. To make it usable
without the user adding a dashboard resource by hand, the integration:

  1. serves the file from a stable URL via a static path, and
  2. registers that URL as a Lovelace module resource (storage mode), or logs where to add
     it manually (YAML mode), once per Home Assistant start.

Registration is best-effort: a failure here never blocks setup, since every entity works
without the card.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import IntegrationNotLoaded, async_get_loaded_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILENAME = "norman-shades-card.js"
# The integration's www/ directory is served at /norman/, so everything in it gets a stable
# URL from a single mount.
WWW_URL_BASE = f"/{DOMAIN}"
CARD_URL_PATH = f"{WWW_URL_BASE}/{CARD_FILENAME}"

_REGISTERED_KEY = f"{DOMAIN}_frontend_registered"


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
    }
