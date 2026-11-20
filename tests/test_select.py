"""Tests for each blind's color and its window's divided lights: the selects the card draws it with."""

from __future__ import annotations

import asyncio

import aiohttp
from homeassistant.components.select import (
    ATTR_OPTION,
    ATTR_OPTIONS,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from custom_components.norman.const import DOMAIN
from custom_components.norman.select import (
    DEFAULT_SHADE_COLOR,
    DEFAULT_SHUTTER_COLOR,
    DEFAULT_WINDOW_LIGHTS,
    SHADE_COLORS,
    SHUTTER_COLORS,
    WINDOW_LIGHTS,
)

from .conftest import FakeHub, loaded
from .const import UID_BEDROOM, UID_LIVING, UID_ROLLER, UID_SHUTTER


def color_entity_id(hass: HomeAssistant, uid: int, key: str = "shade_color") -> str | None:
    return er.async_get(hass).async_get_entity_id(SELECT_DOMAIN, DOMAIN, f"{uid}_{key}")


async def _choose(hass: HomeAssistant, entity_id: str, option: str) -> None:
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: option},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_every_shade_has_a_color_starting_at_the_cloth_the_card_drew(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A shade's color is one of its fabrics, ivory until one is chosen, under Configuration."""
    for uid in (UID_LIVING, UID_BEDROOM):
        entity_id = color_entity_id(hass, uid)
        assert entity_id, f"no color for {uid}"
        state = hass.states.get(entity_id)
        assert state.state == DEFAULT_SHADE_COLOR == "ivory"
        assert state.attributes[ATTR_OPTIONS] == list(SHADE_COLORS)
        entry = er.async_get(hass).async_get(entity_id)
        assert entry.entity_category is EntityCategory.CONFIG
        assert entry.disabled_by is None
        assert entry.translation_key == "shade_color"
        # A shade has no Shutter's paints.
        assert color_entity_id(hass, uid, "shutter_color") is None
    assert hass.states.get(color_entity_id(hass, UID_LIVING)).attributes["friendly_name"] == (
        "Living Drape Shade color"
    )


async def test_choosing_a_color_keeps_it_and_sends_nothing_to_the_hub(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The color is Home Assistant's own: choosing one changes the state and nothing else."""
    entity_id = color_entity_id(hass, UID_LIVING)
    assert entity_id
    sent = len(fake_hub.control_calls)

    await _choose(hass, entity_id, "navy")

    assert hass.states.get(entity_id).state == "navy"
    assert len(fake_hub.control_calls) == sent
    # The other blind keeps its own.
    assert hass.states.get(color_entity_id(hass, UID_BEDROOM)).state == DEFAULT_SHADE_COLOR


async def test_a_color_stays_while_the_hub_is_out_of_reach(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The shades keep their colors when the hub drops off, rather than turning ivory again."""
    entity_id = color_entity_id(hass, UID_LIVING)
    assert entity_id
    await _choose(hass, entity_id, "sage")

    fake_hub.status_exc = aiohttp.ClientConnectionError("unreachable")
    await init_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    cover = er.async_get(hass).async_get_entity_id("cover", DOMAIN, str(UID_LIVING))
    assert cover
    assert hass.states.get(cover).state == "unavailable"
    assert hass.states.get(entity_id).state == "sage"


async def test_a_color_chosen_comes_back_after_a_restart(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """The color is restored at start; one no longer offered falls back to the default."""
    mock_restore_cache(
        hass,
        (
            State(f"{SELECT_DOMAIN}.living_drape_shade_color", "terracotta"),
            State(f"{SELECT_DOMAIN}.bedroom_shade_shade_color", "plaid"),
        ),
    )
    registry = er.async_get(hass)
    mock_config_entry.add_to_hass(hass)
    for uid, object_id in (
        (UID_LIVING, "living_drape_shade_color"),
        (UID_BEDROOM, "bedroom_shade_shade_color"),
    ):
        registry.async_get_or_create(
            SELECT_DOMAIN,
            DOMAIN,
            f"{uid}_shade_color",
            suggested_object_id=object_id,
            config_entry=mock_config_entry,
        )

    async with loaded(hass, mock_config_entry):
        assert hass.states.get(f"{SELECT_DOMAIN}.living_drape_shade_color").state == "terracotta"
        assert (
            hass.states.get(f"{SELECT_DOMAIN}.bedroom_shade_shade_color").state
            == DEFAULT_SHADE_COLOR
        )


async def test_a_shutter_is_painted_or_stained(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry
) -> None:
    """A Shutter's color is a paint or a stain, white until one is chosen; any other blind's a fabric."""
    entity_id = color_entity_id(hass, UID_SHUTTER, "shutter_color")
    assert entity_id
    state = hass.states.get(entity_id)
    assert state.state == DEFAULT_SHUTTER_COLOR == "white"
    assert state.attributes[ATTR_OPTIONS] == list(SHUTTER_COLORS)
    assert color_entity_id(hass, UID_SHUTTER) is None

    await _choose(hass, entity_id, "walnut")
    assert hass.states.get(entity_id).state == "walnut"

    roller = color_entity_id(hass, UID_ROLLER)
    assert roller
    assert hass.states.get(roller).attributes[ATTR_OPTIONS] == list(SHADE_COLORS)


async def test_every_window_has_divided_lights_starting_at_the_glass_the_card_drew(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry
) -> None:
    """Every blind, a Shutter too, has its window's divided lights, two over two until chosen."""
    for uid in (UID_LIVING, UID_BEDROOM, UID_ROLLER, UID_SHUTTER):
        entity_id = color_entity_id(hass, uid, "window_lights")
        assert entity_id, f"no divided lights for {uid}"
        state = hass.states.get(entity_id)
        assert state.state == DEFAULT_WINDOW_LIGHTS == "two_over_two"
        assert state.attributes[ATTR_OPTIONS] == list(WINDOW_LIGHTS)
        entry = er.async_get(hass).async_get(entity_id)
        assert entry.entity_category is EntityCategory.CONFIG
        assert entry.disabled_by is None
        assert entry.translation_key == "window_lights"
    assert hass.states.get(color_entity_id(hass, UID_LIVING, "window_lights")).attributes[
        "friendly_name"
    ] == ("Living Drape Divided lights")


async def test_choosing_divided_lights_keeps_them_through_an_outage_and_a_restart(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Like a color, the divided lights are Home Assistant's own: kept, never sent, restored."""
    mock_restore_cache(hass, (State(f"{SELECT_DOMAIN}.bedroom_shade_divided_lights", "prairie"),))
    registry = er.async_get(hass)
    mock_config_entry.add_to_hass(hass)
    registry.async_get_or_create(
        SELECT_DOMAIN,
        DOMAIN,
        f"{UID_BEDROOM}_window_lights",
        suggested_object_id="bedroom_shade_divided_lights",
        config_entry=mock_config_entry,
    )

    async with loaded(hass, mock_config_entry):
        bedroom = f"{SELECT_DOMAIN}.bedroom_shade_divided_lights"
        assert hass.states.get(bedroom).state == "prairie"
        entity_id = color_entity_id(hass, UID_LIVING, "window_lights")
        assert entity_id
        sent = len(fake_hub.control_calls)

        await _choose(hass, entity_id, "six_over_six")
        assert hass.states.get(entity_id).state == "six_over_six"
        assert len(fake_hub.control_calls) == sent

        fake_hub.status_exc = aiohttp.ClientConnectionError("unreachable")
        await mock_config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == "six_over_six"
