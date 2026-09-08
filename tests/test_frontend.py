"""Tests for serving and registering the Lovelace card.

The card's JavaScript is not executed here (there is no browser in the test suite), so these
tests cover the two things that break silently in the wild: the file not being served at the
URL the resource points at, and the resource list ending up with a stale or duplicated entry
after an upgrade. The JS itself is pinned structurally by ``test_repo_consistency.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.norman.frontend import (
    CARD_FILENAME,
    CARD_RESOURCE_URL,
    CARD_URL_PATH,
    INTEGRATION_VERSION,
    async_get_frontend_diagnostics,
    async_register_card,
)


class FakeResources:
    """A stand-in for Lovelace's storage-mode resource collection."""

    def __init__(self, items: list[dict[str, Any]] | None = None, *, yaml_mode: bool = False):
        self.loaded = False
        self._items = items or []
        self.store = None if yaml_mode else MagicMock()
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self.deleted: list[str] = []

    async def async_load(self) -> None:
        self.loaded = True

    def async_items(self) -> list[dict[str, Any]]:
        return self._items

    async def async_create_item(self, item: dict[str, Any]) -> None:
        self.created.append(item)
        self._items.append({**item, "id": f"id-{len(self._items)}"})

    async def async_update_item(self, item_id: str, changes: dict[str, Any]) -> None:
        self.updated.append((item_id, changes))
        for item in self._items:
            if item.get("id") == item_id:
                item.update(changes)

    async def async_delete_item(self, item_id: str) -> None:
        self.deleted.append(item_id)
        self._items = [item for item in self._items if item.get("id") != item_id]


@pytest.fixture
def lovelace(hass: HomeAssistant) -> FakeResources:
    """Put a storage-mode Lovelace resource collection in place."""
    resources = FakeResources()
    hass.data["lovelace"] = MagicMock(resources=resources)
    return resources


async def test_card_is_served_and_registered(hass: HomeAssistant, lovelace: FakeResources) -> None:
    """The card file is served at a versioned URL and added to the resource list."""
    hass.http = MagicMock(async_register_static_paths=AsyncMock())

    await async_register_card(hass)

    (paths,) = hass.http.async_register_static_paths.call_args.args
    assert paths[0].url_path == "/norman"
    assert paths[0].path.endswith("/www")
    assert paths[0].cache_headers is True

    assert lovelace.created == [{"res_type": "module", "url": CARD_RESOURCE_URL}]
    # The version stamp is what busts a browser's cache on upgrade
    assert f"{CARD_URL_PATH}?v={INTEGRATION_VERSION}" == CARD_RESOURCE_URL


async def test_registration_is_idempotent(hass: HomeAssistant, lovelace: FakeResources) -> None:
    """Calling twice (two config entries, or a reload) registers one resource."""
    hass.http = MagicMock(async_register_static_paths=AsyncMock())

    await async_register_card(hass)
    await async_register_card(hass)

    assert len(lovelace.created) == 1
    assert hass.http.async_register_static_paths.call_count == 1


async def test_an_already_registered_card_is_left_alone(hass: HomeAssistant) -> None:
    """A resource already carrying the current URL is not duplicated."""
    resources = FakeResources([{"id": "a", "url": CARD_RESOURCE_URL}])
    hass.data["lovelace"] = MagicMock(resources=resources)
    hass.http = MagicMock(async_register_static_paths=AsyncMock())

    await async_register_card(hass)

    assert resources.created == []
    assert resources.updated == []
    assert resources.deleted == []


async def test_a_stale_version_is_repointed(hass: HomeAssistant) -> None:
    """After an upgrade the old ?v= entry is moved to the new URL, not left behind.

    Leaving it would load the previous card build alongside the new one; the second
    customElements.define() throws and whichever loaded first wins.
    """
    resources = FakeResources([{"id": "a", "url": f"{CARD_URL_PATH}?v=0.1"}])
    hass.data["lovelace"] = MagicMock(resources=resources)
    hass.http = MagicMock(async_register_static_paths=AsyncMock())

    await async_register_card(hass)

    assert resources.updated == [("a", {"url": CARD_RESOURCE_URL})]
    assert resources.created == []


async def test_duplicate_entries_are_removed(hass: HomeAssistant) -> None:
    """A hand-added resource alongside the auto-registered one is cleaned up."""
    resources = FakeResources(
        [
            {"id": "a", "url": CARD_RESOURCE_URL},
            {"id": "b", "url": CARD_URL_PATH},
            {"id": "c", "url": f"{CARD_URL_PATH}?v=0.1"},
        ]
    )
    hass.data["lovelace"] = MagicMock(resources=resources)
    hass.http = MagicMock(async_register_static_paths=AsyncMock())

    await async_register_card(hass)

    assert sorted(resources.deleted) == ["b", "c"]
    assert resources.created == []


async def test_yaml_mode_only_logs(hass: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """A YAML-mode resource list cannot be written to, so the URL is logged instead."""
    resources = FakeResources(yaml_mode=True)
    hass.data["lovelace"] = MagicMock(resources=resources)
    hass.http = MagicMock(async_register_static_paths=AsyncMock())

    await async_register_card(hass)

    assert resources.created == []
    assert CARD_RESOURCE_URL in caplog.text


async def test_a_missing_card_file_does_not_register_anything(
    hass: HomeAssistant, lovelace: FakeResources, caplog: pytest.LogCaptureFixture
) -> None:
    """If the JS is missing, nothing is served and nothing is registered."""
    hass.http = MagicMock(async_register_static_paths=AsyncMock())

    with patch("custom_components.norman.frontend.Path.is_file", autospec=True, return_value=False):
        await async_register_card(hass)

    assert lovelace.created == []
    assert hass.http.async_register_static_paths.call_count == 0
    assert CARD_FILENAME in caplog.text or not hass.data.get("norman_frontend_registered")


async def test_serving_failure_never_blocks_setup(
    hass: HomeAssistant, lovelace: FakeResources
) -> None:
    """The card is a convenience: a failure to serve it must not raise."""
    hass.http = MagicMock(
        async_register_static_paths=AsyncMock(side_effect=RuntimeError("no http"))
    )

    await async_register_card(hass)  # must not raise

    assert lovelace.created == []


async def test_setup_registers_the_card(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub, notifications
) -> None:
    """Setting up the integration serves the card without the user doing anything."""
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    hass.data["lovelace"] = MagicMock(resources=FakeResources())
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.data.get("norman_frontend_registered") is True
    assert hass.http.async_register_static_paths.call_count == 1


async def test_diagnostics_report_the_card_version(
    hass: HomeAssistant, lovelace: FakeResources
) -> None:
    """A stale cached card is visible from a diagnostics download."""
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    await async_register_card(hass)

    report = async_get_frontend_diagnostics(hass)

    assert report["integration_version"] == INTEGRATION_VERSION
    assert report["expected_resource"] == CARD_RESOURCE_URL
    assert report["registered_resources"] == [CARD_RESOURCE_URL]


async def test_diagnostics_flag_a_stale_registered_card(hass: HomeAssistant) -> None:
    """A resource left on an old ?v= is reported as a version mismatch.

    This is the shape of the problem users actually hit: the card loads, but it is the
    previous build, so behaviour does not match the release notes.
    """
    resources = FakeResources([{"id": "a", "url": f"{CARD_URL_PATH}?v=0.1"}])
    hass.data["lovelace"] = MagicMock(resources=resources)

    report = async_get_frontend_diagnostics(hass)

    assert report["registered_versions"] == ["0.1"]
    assert report["version_matches"] is False


async def test_diagnostics_report_a_matching_version(
    hass: HomeAssistant, lovelace: FakeResources
) -> None:
    """A card registered at the current version reports as matching."""
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    await async_register_card(hass)

    report = async_get_frontend_diagnostics(hass)

    assert report["registered_versions"] == [INTEGRATION_VERSION]
    assert report["version_matches"] is True


async def test_diagnostics_report_an_unstamped_resource(hass: HomeAssistant) -> None:
    """A hand-added resource with no ?v= reports as unknown, not as a match."""
    resources = FakeResources([{"id": "a", "url": CARD_URL_PATH}])
    hass.data["lovelace"] = MagicMock(resources=resources)

    report = async_get_frontend_diagnostics(hass)

    assert report["registered_versions"] == ["unknown"]
    assert report["version_matches"] is False


async def test_diagnostics_without_lovelace(hass: HomeAssistant) -> None:
    """Diagnostics never fail just because Lovelace is not loaded."""
    hass.data.pop("lovelace", None)
    report = async_get_frontend_diagnostics(hass)
    assert report["registered_resources"] == []
    # No card registered is not the same as a stale one, so this is None rather than False.
    assert report["version_matches"] is None
