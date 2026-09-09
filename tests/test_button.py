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
from custom_components.norman.const import DOMAIN, HUB_COMMAND_TRIGGER

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
    """Both blind types get every button, all enabled and all in the config category.

    The category is a layout decision, not a claim that the buttons are rarely used: the
    device page sorts uncategorised entities together by entity id, which interleaved
    "Middle rail" with the buttons. Categorising every button keeps a two-rail blind's two
    covers adjacent at the top of the page.

    Favorite included: single-rail blinds have a stored favorite too. A hub-wide Favorite
    left them where they were in one capture, but they were already sitting at 100 -- no
    movement was not evidence of no favorite.
    """
    for uid in (UID_LIVING, UID_BEDROOM):
        for description in BUTTONS:
            entry = _button(hass, uid, description.key)
            assert entry.entity_category is EntityCategory.CONFIG, description.key
            assert entry.disabled_by is None, f"{description.key} should be enabled"

    state = hass.states.get(_button(hass, UID_LIVING, "favorite").entity_id)
    assert state.attributes["friendly_name"] == "Living Drape Favorite position"
    # Icons come from icons.json, whose coverage tests/test_repo_consistency.py pins


@pytest.mark.parametrize(
    ("key", "verb", "value"),
    [
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


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("best_privacy", {"Switch": 0}),
        ("best_view", {"Switch": 1}),
        ("favorite", {"Favorite": 0}),
    ],
)
async def test_addressed_buttons_target_the_blind_by_room_and_group(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    key: str,
    expected: dict[str, int],
) -> None:
    """Switch and Favorite are addressed by RoomID + GroupID, not by PeripheralUID alone.

    Captured from the app's own per-blind buttons: sending GroupID 1 in a room moved only
    the group-1 blind, leaving group 2 untouched. The pair is unique per blind.
    """
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: _button(hass, UID_LIVING, key).entity_id},
        blocking=True,
    )

    call = fake_hub.control_calls[-1]
    assert {k: call[k] for k in expected} == expected
    # The room/group pair is what selects the blind.
    assert call["RoomID"] == 1
    assert call["GroupID"] == 10
    # The app sends the uid alongside; harmless, and it keeps the payload identical to it.
    assert call["PeripheralUID"] == UID_LIVING


async def test_there_are_no_run_to_limit_buttons(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The run-to-limit verbs are hold-to-run, so a button is the wrong shape for them.

    The app sends SetMotorToTop/BottomLimit every ~0.3 s for as long as its OPEN/CLOSE
    control is held, and only inside the Shade Limit Setting screen. A single press is one
    pulse of that signal. Best view and Best privacy reach the same end positions through
    the hub's own Switch verb; send_hub_command remains for the raw verbs.
    """
    assert not [d for d in BUTTONS if "limit" in d.key]


async def test_jog_is_addressed_by_uid_not_room_and_group(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The motor verbs use PeripheralUID; only Switch and Favorite use room + group.

    Both forms appear in captures of the same app session, so this is a real distinction
    rather than a style choice: MotorFineTuneToUp/Down were only ever sent with a
    PeripheralUID and no scope fields at all.
    """
    for key in ("jog_up", "jog_down"):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: _button(hass, UID_LIVING, key).entity_id},
            blocking=True,
        )
        call = fake_hub.control_calls[-1]
        assert call["PeripheralUID"] == UID_LIVING
        assert "RoomID" not in call
        assert "GroupID" not in call

    assert [d.addressed for d in BUTTONS if d.key.startswith("jog")] == [False, False]
