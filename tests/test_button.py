"""Tests for the per-blind verb buttons."""

from __future__ import annotations

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.norman.button import BUTTONS
from custom_components.norman.const import DOMAIN, HUB_COMMAND_SETTING, HUB_COMMAND_TRIGGER

from .conftest import FakeHub
from .const import UID_BEDROOM, UID_LIVING


def _button(hass: HomeAssistant, uid: int, key: str) -> er.RegistryEntry:
    entry = er.async_get(hass).async_get(
        er.async_get(hass).async_get_entity_id(BUTTON_DOMAIN, DOMAIN, f"{uid}_{key}") or ""
    )
    assert entry, f"no {key} button for peripheral {uid}"
    return entry


async def test_every_blind_gets_the_buttons(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Both blind types get all five buttons, all enabled; the limit pair is configuration.

    Run-to-limit reaches the motor's stored limit rather than a position, so it can work
    when position tracking has drifted -- it is a distinct capability, not a duplicate of
    open/close, and is enabled for that reason.
    """
    for uid in (UID_LIVING, UID_BEDROOM):
        for description in BUTTONS:
            entry = _button(hass, uid, description.key)
            limit = description.key.startswith("run_to")
            assert (entry.entity_category == EntityCategory.CONFIG) is limit
            assert entry.disabled_by is None, f"{description.key} should be enabled"
    state = hass.states.get(_button(hass, UID_LIVING, "favorite").entity_id)
    assert state.attributes["friendly_name"] == "Living Drape Favourite position"
    # Icons come from icons.json, whose coverage tests/test_repo_consistency.py pins


@pytest.mark.parametrize(
    ("key", "verb", "value"),
    [
        ("favorite", "Favorite", HUB_COMMAND_SETTING),
        ("jog_up", "MotorFineTuneToUp", HUB_COMMAND_TRIGGER),
        ("jog_down", "MotorFineTuneToDown", HUB_COMMAND_TRIGGER),
    ],
)
async def test_press_sends_the_verb_and_refreshes(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    key: str,
    verb: str,
    value: int,
) -> None:
    """A press is one control call carrying exactly the verb, then a status re-read."""
    status_calls = len(fake_hub.calls_to("/status"))

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: _button(hass, UID_LIVING, key).entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()

    call = fake_hub.control_calls[-1]
    assert call["PeripheralUID"] == UID_LIVING
    assert call[verb] == value
    assert set(call) == {"PeripheralUID", "Timestamp", "TaskID", verb}
    assert len(fake_hub.calls_to("/status")) == status_calls + 1


async def test_press_failure_names_the_button_and_blind(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A hub error becomes a HomeAssistantError naming the verb and the blind."""
    fake_hub.control_response = {"Error": 9}
    with pytest.raises(HomeAssistantError, match="Failed to send jog_up to Living Drape"):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: _button(hass, UID_LIVING, "jog_up").entity_id},
            blocking=True,
        )
