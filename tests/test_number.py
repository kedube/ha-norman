"""Tests for the per-rail position sliders."""

from __future__ import annotations

from homeassistant.components.number import (
    ATTR_MAX,
    ATTR_MIN,
    ATTR_STEP,
    ATTR_VALUE,
    SERVICE_SET_VALUE,
)
from homeassistant.components.number import (
    DOMAIN as NUMBER_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.norman.const import DOMAIN

from .conftest import FakeHub
from .const import UID_BEDROOM, UID_LIVING


def number_entity_id(hass: HomeAssistant, uid: int, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(NUMBER_DOMAIN, DOMAIN, f"{uid}_{key}")


async def _set(hass: HomeAssistant, entity_id: str, value: float) -> None:
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_sliders_report_each_rail(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A two-rail blind gets one slider per rail, 0-100 in steps of 10."""
    bottom_id = number_entity_id(hass, UID_LIVING, "bottom_rail_position")
    middle_id = number_entity_id(hass, UID_LIVING, "middle_rail_position")
    assert bottom_id and middle_id

    bottom = hass.states.get(bottom_id)
    assert float(bottom.state) == 40  # BottomRailPosition
    assert bottom.attributes[ATTR_MIN] == 0
    assert bottom.attributes[ATTR_MAX] == 100
    assert bottom.attributes[ATTR_STEP] == 10
    assert bottom.attributes["mode"] == "slider"
    assert bottom.attributes["unit_of_measurement"] == "%"
    assert bottom.attributes["friendly_name"] == "Living Drape Bottom rail position"

    assert float(hass.states.get(middle_id).state) == 60  # MiddleRailPosition

    # Configuration category, so the device page keeps its Controls group to the covers
    registry = er.async_get(hass)
    assert registry.async_get(bottom_id).entity_category is EntityCategory.CONFIG
    assert registry.async_get(bottom_id).disabled_by is None


async def test_single_rail_blinds_have_no_middle_slider(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A single-rail blind's middle rail is a constant 0, so it gets no slider for it."""
    assert number_entity_id(hass, UID_BEDROOM, "bottom_rail_position")
    assert number_entity_id(hass, UID_BEDROOM, "middle_rail_position") is None


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("bottom_rail_position", 30, (30, 60)),
        ("middle_rail_position", 20, (40, 20)),
    ],
)
async def test_setting_a_slider_moves_only_that_rail(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    key: str,
    value: int,
    expected: tuple[int, int],
) -> None:
    """Each slider sends its own rail and the other rail's current target, as the hub needs."""
    status_calls = len(fake_hub.calls_to("/status"))

    await _set(hass, number_entity_id(hass, UID_LIVING, key), value)

    call = fake_hub.control_calls[-1]
    assert (call["BottomRailPosition"], call["MiddleRailPosition"]) == expected
    assert call["PeripheralUID"] == UID_LIVING
    assert len(fake_hub.calls_to("/status")) == status_calls + 1


async def test_slider_failure_names_the_blind(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A hub error becomes a translated HomeAssistantError naming the blind."""
    fake_hub.control_response = {"Error": 5}
    with pytest.raises(HomeAssistantError, match="Living Drape") as excinfo:
        await _set(hass, number_entity_id(hass, UID_LIVING, "bottom_rail_position"), 50)
    assert excinfo.value.translation_key == "command_failed"


async def test_slider_and_cover_agree(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The slider reads the same hub value as the cover, so the two never disagree."""
    from .conftest import cover_entity_id

    fake_hub.set_position(UID_LIVING, bottom=70)
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {
            ATTR_ENTITY_ID: number_entity_id(hass, UID_LIVING, "bottom_rail_position"),
            ATTR_VALUE: 70,
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    cover = hass.states.get(cover_entity_id(hass, UID_LIVING))
    slider = hass.states.get(number_entity_id(hass, UID_LIVING, "bottom_rail_position"))
    assert cover.attributes["current_position"] == float(slider.state) == 70
