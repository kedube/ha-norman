"""The Norman Shades sidebar panel (``frontend.async_add_entry_panel`` / ``async_remove_entry_panel``).

Every set-up hub whose "Show Norman Shades in the sidebar" option is on gets a sidebar entry
that opens the card full screen; turning the option off, or unloading the entry, takes it
away. One hub gets a plain "Norman Shades" entry with no hub pinned; with several, each entry
pins its hub, since the card would otherwise show every hub's blinds together.

These run against Home Assistant's real panel registry (``frontend.async_register_built_in_panel``
keeps it in ``hass.data``), so what is asserted is what the sidebar would list.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components import frontend
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.norman.const import (
    CONF_SHOW_SIDEBAR_PANEL,
    CONF_SIDEBAR_VIEW,
    CONF_SIDEBAR_VIEW_FORECAST,
    CONF_SIDEBAR_VIEW_MOTION,
    CONF_SIDEBAR_VIEW_WEATHER,
    DOMAIN,
    SIDEBAR_VIEW_NONE,
)
from custom_components.norman.frontend import (
    PANEL_ELEMENT,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_TITLES,
    PANEL_URL_PATH,
    WWW_URL_BASE,
    async_add_entry_panel,
    async_get_frontend_diagnostics,
    async_remove_entry_panel,
)

from .conftest import FakeHub, loaded
from .const import MOCK_CONFIG

VERSION = json.loads(
    (
        pathlib.Path(__file__).parent.parent / "custom_components" / "norman" / "manifest.json"
    ).read_text(encoding="utf-8")
)["version"]


@pytest.fixture(autouse=True)
async def _loaded_integration(hass: HomeAssistant) -> None:
    """Make the panel's ?v= stamp resolve to the manifest version, as in a real install."""
    await async_get_integration(hass, DOMAIN)


def _entry(
    hass: HomeAssistant, entry_id: str, title: str = "Norman Hub", **options
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data=MOCK_CONFIG, title=title, entry_id=entry_id, options=options
    )
    entry.add_to_hass(hass)
    return entry


def _sidebar(hass: HomeAssistant) -> dict[str, frontend.Panel]:
    """The panels Home Assistant would list, keyed by url path."""
    return dict(hass.data.get(frontend.DATA_PANELS, {}))


# What a panel carries for the page's view when the hub's view options are left alone, and
# the keys the view's part of the config can have (www/norman-panel.js reads them).
DEFAULT_VIEW = {"view": "coast", "view_motion": True}
VIEW_KEYS = ("view", "view_motion", "weather_entity")


def _pinned(panel: frontend.Panel) -> dict[str, str | bool]:
    """The config a panel carries, without panel_custom's own bookkeeping."""
    return {k: v for k, v in (panel.config or {}).items() if k != "_panel_custom"}


def _hub(panel: frontend.Panel) -> dict[str, str | bool]:
    """The card's part of a panel's config: the hub it is pinned to, if any."""
    return {k: v for k, v in _pinned(panel).items() if k not in VIEW_KEYS}


def _view(panel: frontend.Panel) -> dict[str, str | bool]:
    """The view's part of a panel's config."""
    return {k: v for k, v in _pinned(panel).items() if k in VIEW_KEYS}


async def test_one_hub_gets_a_plain_entry(hass: HomeAssistant) -> None:
    entry = _entry(hass, "a")
    await async_add_entry_panel(hass, entry)

    sidebar = _sidebar(hass)
    assert list(sidebar) == [PANEL_URL_PATH]
    panel = sidebar[PANEL_URL_PATH]
    assert panel.sidebar_title == PANEL_TITLE == "Norman Shades"
    assert panel.sidebar_icon == PANEL_ICON
    assert panel.component_name == "custom"
    assert panel.require_admin is False
    custom = panel.config["_panel_custom"]
    assert custom["name"] == PANEL_ELEMENT
    # Stamped like the card, so an upgrade never serves a cached old panel.
    assert custom["module_url"] == f"{WWW_URL_BASE}/norman-panel.js?v={VERSION}"
    assert _pinned(panel) == DEFAULT_VIEW  # no hub pinned: the card shows the only one


@pytest.mark.parametrize(
    ("language", "title"),
    [
        ("de", "Norman-Rollos"),
        ("de-CH", "Norman-Rollos"),
        ("ja", "Norman ブラインド"),
        ("zh-Hant", "Norman 窗簾"),
        ("zh-TW", "Norman 窗簾"),
        ("zh-CN", "Norman 窗帘"),
        ("pt-BR", "Norman Shades"),
    ],
)
async def test_the_sidebar_title_follows_the_servers_language(
    hass: HomeAssistant, language: str, title: str
) -> None:
    """Home Assistant shows a custom panel's title as registered, so the server's language
    picks it; a language the integration does not ship falls back to English."""
    hass.config.language = language
    await async_add_entry_panel(hass, _entry(hass, "a"))
    assert _sidebar(hass)[PANEL_URL_PATH].sidebar_title == title


def test_every_language_has_a_sidebar_title_matching_the_card() -> None:
    """One title per shipped translation, and each is the card's own name in that language,
    so the sidebar entry and the card picker never disagree."""
    component = pathlib.Path(__file__).parent.parent / "custom_components" / "norman"
    shipped = sorted(path.stem for path in (component / "translations").glob("*.json"))
    assert sorted(PANEL_TITLES) == shipped
    # The card's words, shared with the panel (www/norman-strings.js).
    words = (component / "www" / "norman-strings.js").read_text(encoding="utf-8")
    for title in PANEL_TITLES.values():
        assert f'card_name: "{title}"' in words, title


def test_the_sidebar_option_names_the_page_as_the_sidebar_does() -> None:
    """The options form's sidebar toggle uses each language's sidebar title, so the setting
    names the entry it adds."""
    component = pathlib.Path(__file__).parent.parent / "custom_components" / "norman"
    for language, title in PANEL_TITLES.items():
        path = component / "translations" / f"{language}.json"
        init = json.loads(path.read_text(encoding="utf-8"))["options"]["step"]["init"]
        assert title in init["data"]["show_sidebar_panel"], language
        assert title in init["data_description"]["show_sidebar_panel"], language


def test_the_panel_does_not_sit_under_the_static_path() -> None:
    """A panel at /norman would send a page reload there to the static file handler that
    serves /norman/<card>.js (a directory: an error) instead of Home Assistant's app."""
    assert f"/{PANEL_URL_PATH}" != WWW_URL_BASE
    assert not f"/{PANEL_URL_PATH}/".startswith(f"{WWW_URL_BASE}/")


async def test_the_option_turns_the_entry_off_and_on(hass: HomeAssistant) -> None:
    entry = _entry(hass, "a", **{CONF_SHOW_SIDEBAR_PANEL: False})
    await async_add_entry_panel(hass, entry)
    assert _sidebar(hass) == {}

    # Changing an option reloads the entry: unload, then set up with the new options.
    await async_remove_entry_panel(hass, entry)
    hass.config_entries.async_update_entry(entry, options={CONF_SHOW_SIDEBAR_PANEL: True})
    await async_add_entry_panel(hass, entry)
    assert list(_sidebar(hass)) == [PANEL_URL_PATH]

    await async_remove_entry_panel(hass, entry)
    hass.config_entries.async_update_entry(entry, options={CONF_SHOW_SIDEBAR_PANEL: False})
    await async_add_entry_panel(hass, entry)
    assert _sidebar(hass) == {}


async def test_unloading_takes_the_entry_away(hass: HomeAssistant) -> None:
    entry = _entry(hass, "a")
    await async_add_entry_panel(hass, entry)
    await async_remove_entry_panel(hass, entry)
    assert _sidebar(hass) == {}


async def test_several_hubs_each_get_an_entry_pinned_to_their_hub(hass: HomeAssistant) -> None:
    first = _entry(hass, "a", "Norman Hub (192.168.1.50)")
    second = _entry(hass, "b", "Norman Hub (192.168.1.50)")
    third = _entry(hass, "c", "Cabin")
    # Entries finish setting up in any order; addresses follow the config-entry order.
    for entry in (second, first, third):
        await async_add_entry_panel(hass, entry)

    assert {url: (p.sidebar_title, _hub(p)) for url, p in _sidebar(hass).items()} == {
        PANEL_URL_PATH: ("Norman Hub (192.168.1.50)", {"config_entry_id": "a"}),
        f"{PANEL_URL_PATH}-2": ("Norman Hub (192.168.1.50) 2", {"config_entry_id": "b"}),
        f"{PANEL_URL_PATH}-3": ("Cabin", {"config_entry_id": "c"}),
    }


async def test_a_second_hub_turns_the_plain_entry_into_a_pinned_one(hass: HomeAssistant) -> None:
    first, second = _entry(hass, "a", "Home"), _entry(hass, "b", "Cabin")
    await async_add_entry_panel(hass, first)
    assert _hub(_sidebar(hass)[PANEL_URL_PATH]) == {}

    await async_add_entry_panel(hass, second)
    sidebar = _sidebar(hass)
    assert sidebar[PANEL_URL_PATH].sidebar_title == "Home"
    assert _hub(sidebar[PANEL_URL_PATH]) == {"config_entry_id": "a"}
    assert _hub(sidebar[f"{PANEL_URL_PATH}-2"]) == {"config_entry_id": "b"}

    # Back to one hub: back to the plain entry.
    await async_remove_entry_panel(hass, second)
    sidebar = _sidebar(hass)
    assert list(sidebar) == [PANEL_URL_PATH]
    assert sidebar[PANEL_URL_PATH].sidebar_title == PANEL_TITLE
    assert _hub(sidebar[PANEL_URL_PATH]) == {}


async def test_a_hub_without_the_panel_still_counts_as_another_hub(hass: HomeAssistant) -> None:
    """With two hubs the card must be told which one to show, even if only one of them has a
    sidebar entry."""
    shown = _entry(hass, "a", "Home")
    hidden = _entry(hass, "b", "Cabin", **{CONF_SHOW_SIDEBAR_PANEL: False})
    await async_add_entry_panel(hass, shown)
    await async_add_entry_panel(hass, hidden)

    sidebar = _sidebar(hass)
    assert list(sidebar) == [PANEL_URL_PATH]
    assert _hub(sidebar[PANEL_URL_PATH]) == {"config_entry_id": "a"}


async def test_the_view_options_reach_the_page(hass: HomeAssistant) -> None:
    """The place, whether it moves and the weather entity go to the page in the panel's config,
    and the weather turned off goes as the card's own hide_weather."""
    entry = _entry(
        hass,
        "a",
        **{
            CONF_SIDEBAR_VIEW: "lake",
            CONF_SIDEBAR_VIEW_MOTION: False,
            CONF_SIDEBAR_VIEW_FORECAST: False,
            CONF_SIDEBAR_VIEW_WEATHER: "weather.lakehouse",
        },
    )
    await async_add_entry_panel(hass, entry)

    assert _pinned(_sidebar(hass)[PANEL_URL_PATH]) == {
        "view": "lake",
        "view_motion": False,
        "weather_entity": "weather.lakehouse",
        "hide_weather": True,
    }


@pytest.mark.parametrize("view", [SIDEBAR_VIEW_NONE, "desert"])
async def test_without_a_view_the_page_is_the_plain_card(hass: HomeAssistant, view: str) -> None:
    """ "None" leaves the view out of the config altogether, and so does a place this release
    has no photographs of (one stored by a later release, then downgraded)."""
    entry = _entry(
        hass,
        "a",
        **{
            CONF_SIDEBAR_VIEW: view,
            CONF_SIDEBAR_VIEW_MOTION: False,
            CONF_SIDEBAR_VIEW_FORECAST: False,
        },
    )
    await async_add_entry_panel(hass, entry)

    assert _pinned(_sidebar(hass)[PANEL_URL_PATH]) == {}


async def test_each_hub_keeps_its_own_view(hass: HomeAssistant) -> None:
    home = _entry(hass, "a", "Home")
    cabin = _entry(hass, "b", "Cabin", **{CONF_SIDEBAR_VIEW: "lake"})
    for entry in (home, cabin):
        await async_add_entry_panel(hass, entry)

    sidebar = _sidebar(hass)
    assert _pinned(sidebar[PANEL_URL_PATH]) == {"config_entry_id": "a", **DEFAULT_VIEW}
    assert _pinned(sidebar[f"{PANEL_URL_PATH}-2"]) == {
        "config_entry_id": "b",
        "view": "lake",
        "view_motion": True,
    }


async def test_changing_the_view_updates_the_page_without_a_reload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Saving another place registers the panel again with it, and the hub stays connected:
    a reload would drop the notification stream and every move being watched."""
    hass.http = MagicMock(async_register_static_paths=AsyncMock())

    async with loaded(hass, mock_config_entry):
        assert _view(_sidebar(hass)[PANEL_URL_PATH]) == DEFAULT_VIEW
        coordinator = mock_config_entry.runtime_data

        result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
        shown = {
            str(k): k.description["suggested_value"]
            for k in result["data_schema"].schema
            if k.description
        }
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={**shown, CONF_SIDEBAR_VIEW: "lake", CONF_SIDEBAR_VIEW_MOTION: False},
        )
        await hass.async_block_till_done()

        assert mock_config_entry.state is ConfigEntryState.LOADED
        assert mock_config_entry.runtime_data is coordinator
        assert _view(_sidebar(hass)[PANEL_URL_PATH]) == {"view": "lake", "view_motion": False}


async def test_turning_the_weather_off_updates_the_page_without_a_reload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """The weather is on until it is turned off, which registers the panel again with the
    card told to leave it out; the hub stays connected, as for any other view option."""
    hass.http = MagicMock(async_register_static_paths=AsyncMock())

    async with loaded(hass, mock_config_entry):
        assert "hide_weather" not in _pinned(_sidebar(hass)[PANEL_URL_PATH])
        coordinator = mock_config_entry.runtime_data

        result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
        shown = {
            str(k): k.description["suggested_value"]
            for k in result["data_schema"].schema
            if k.description
        }
        assert shown[CONF_SIDEBAR_VIEW_FORECAST] is True
        await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={**shown, CONF_SIDEBAR_VIEW_FORECAST: False}
        )
        await hass.async_block_till_done()

        assert mock_config_entry.state is ConfigEntryState.LOADED
        assert mock_config_entry.runtime_data is coordinator
        assert _pinned(_sidebar(hass)[PANEL_URL_PATH]) == {**DEFAULT_VIEW, "hide_weather": True}


async def test_a_sidebar_failure_never_fails_setup(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    entry = _entry(hass, "a")
    with patch(
        "custom_components.norman.frontend.panel_custom.async_register_panel",
        side_effect=ValueError("Overwriting panel norman-shades"),
    ):
        await async_add_entry_panel(hass, entry)  # logged, not raised
    assert _sidebar(hass) == {}
    assert "could not add its sidebar panel" in caplog.text

    # Nothing was recorded as registered, so the next sync tries again.
    await async_add_entry_panel(hass, entry)
    assert list(_sidebar(hass)) == [PANEL_URL_PATH]


async def test_diagnostics_list_the_sidebar_entries(hass: HomeAssistant) -> None:
    hass.data.pop("lovelace", None)
    entry = _entry(hass, "a")
    await async_add_entry_panel(hass, entry)
    assert async_get_frontend_diagnostics(hass)["sidebar_panels"] == [PANEL_URL_PATH]


# ---- through the integration's own setup ----------------------------------------------------


async def test_setting_up_a_hub_puts_it_in_the_sidebar(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """No dashboard, no resource, no option to find: setup alone adds the entry, and
    unloading takes it away again."""
    hass.http = MagicMock(async_register_static_paths=AsyncMock())

    async with loaded(hass, mock_config_entry):
        assert list(_sidebar(hass)) == [PANEL_URL_PATH]

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert _sidebar(hass) == {}


async def test_turning_the_option_off_removes_the_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Saving the options brings the sidebar in line with them, without a reload."""
    hass.http = MagicMock(async_register_static_paths=AsyncMock())

    async with loaded(hass, mock_config_entry):
        assert list(_sidebar(hass)) == [PANEL_URL_PATH]

        result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_SHOW_SIDEBAR_PANEL: False}
        )
        await hass.async_block_till_done()

        assert mock_config_entry.state is ConfigEntryState.LOADED
        assert _sidebar(hass) == {}


async def test_the_panel_keeps_clear_of_the_safe_areas_itself(hass: HomeAssistant) -> None:
    """The panel pads itself for a phone's notch and home indicator, so it opts out of
    Home Assistant's padding (2026.8+), which painted those strips in another colour."""
    await async_add_entry_panel(hass, _entry(hass, "a"))

    panel = _sidebar(hass)[PANEL_URL_PATH]
    assert panel.config["_panel_custom"]["handle_safe_area"] is True


async def test_a_release_without_the_safe_area_option_still_gets_the_panel(
    hass: HomeAssistant,
) -> None:
    """Before 2026.8 there is no option to pass; the panel is registered without it."""
    registered: list[str] = []

    async def register_panel_2026_7(  # the signature before handle_safe_area existed
        hass: HomeAssistant,
        frontend_url_path: str,
        webcomponent_name: str,
        sidebar_title: str | None = None,
        sidebar_icon: str | None = None,
        js_url: str | None = None,
        module_url: str | None = None,
        embed_iframe: bool = False,
        trust_external: bool = False,
        config: dict | None = None,
        require_admin: bool = False,
        config_panel_domain: str | None = None,
    ) -> None:
        registered.append(frontend_url_path)

    with patch(
        "custom_components.norman.frontend.panel_custom.async_register_panel",
        register_panel_2026_7,
    ):
        await async_add_entry_panel(hass, _entry(hass, "a"))

    assert registered == [PANEL_URL_PATH]
