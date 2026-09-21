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

from custom_components.norman.button import BUTTONS, HUB_BUTTONS
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
            expected = (
                EntityCategory.DIAGNOSTIC
                if description.key == "request_status"
                else EntityCategory.CONFIG
            )
            assert entry.entity_category is expected, description.key
            assert entry.disabled_by is None, f"{description.key} should be enabled"

    state = hass.states.get(_button(hass, UID_LIVING, "favorite").entity_id)
    assert state.attributes["friendly_name"] == "Living Drape Favorite position"
    # Icons come from icons.json, whose coverage tests/test_repo_consistency.py pins


@pytest.mark.parametrize(
    ("key", "verb", "value"),
    [
        ("jog_up", "MotorFineTuneToUp", HUB_COMMAND_TRIGGER),
        ("jog_down", "MotorFineTuneToDown", HUB_COMMAND_TRIGGER),
        # The app's per-blind status request, value 0 like every non-motor verb; the
        # blind answered within 5 s each time it was tried on hardware (2026-09-18).
        ("request_status", "StatusRequest", HUB_COMMAND_SETTING),
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


def _hub_button(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> er.RegistryEntry:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(BUTTON_DOMAIN, DOMAIN, f"{entry.entry_id}_{key}")
    found = registry.async_get(entity_id or "")
    assert found, f"no {key} button on the hub"
    return found


async def test_hub_gets_its_buttons(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """The hub device carries the three All Rooms verbs, refresh, and start pairing."""
    assert [d.key for d in HUB_BUTTONS] == [
        "all_best_privacy",
        "all_best_view",
        "all_favorite",
        "refresh_blinds",
        "start_pairing",
    ]
    entry = _hub_button(hass, init_integration, "refresh_blinds")
    assert entry.entity_category is EntityCategory.DIAGNOSTIC
    assert entry.disabled_by is None
    state = hass.states.get(entry.entity_id)
    assert state.attributes["friendly_name"] == "ShadeAuto Hub Refresh blinds"

    pairing = _hub_button(hass, init_integration, "start_pairing")
    assert pairing.entity_category is EntityCategory.CONFIG
    assert hass.states.get(pairing.entity_id).attributes["friendly_name"] == (
        "ShadeAuto Hub Start pairing"
    )


async def test_start_pairing_opens_the_window_and_re_reads_status(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """One press is `{"PairingMode": 5}` with no scope field, then a status re-read.

    Captured from the app on 2026-09-18; the hub reported PairingMode 5 for ten minutes
    after it. The re-read is what flips the Pairing mode sensor at once.
    """
    status_calls = len(fake_hub.calls_to("/status"))
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: _hub_button(hass, init_integration, "start_pairing").entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()

    call = fake_hub.control_calls[-1]
    assert set(call) == {"Timestamp", "TaskID", "PairingMode"}
    assert call["PairingMode"] == 5
    assert len(fake_hub.calls_to("/status")) == status_calls + 1


async def test_refresh_blinds_sweeps_the_hub_then_pokes_each_wired_blind(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """One press is `{"ReportBatteryLevel": 0}` with no scope field, then one StatusRequest
    per single-rail blind.

    Captured from the app's refresh button on 2026-09-18. On hardware the hub-wide sweep
    never reached the wired (single-rail) blinds, while a per-blind status request did, so
    the button follows up with one for each of them. The battery blinds answer the sweep on
    their own, one notification at a time over the next half minute.
    """
    before = len(fake_hub.control_calls)
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: _hub_button(hass, init_integration, "refresh_blinds").entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()

    calls = fake_hub.control_calls[before:]
    assert set(calls[0]) == {"Timestamp", "TaskID", "ReportBatteryLevel"}
    assert calls[0]["ReportBatteryLevel"] == HUB_COMMAND_SETTING
    assert [c["PeripheralUID"] for c in calls[1:]] == [UID_BEDROOM]
    assert calls[1]["StatusRequest"] == HUB_COMMAND_SETTING


async def test_refresh_blinds_failure_names_the_hub(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A hub error on the hub button reads as a hub failure, not a blind's."""
    fake_hub.control_response = {"Error": 9}
    with pytest.raises(HomeAssistantError, match="Failed to send refresh_blinds to the hub"):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: _hub_button(hass, init_integration, "refresh_blinds").entity_id},
            blocking=True,
        )


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("all_best_privacy", {"Switch": 0}),
        ("all_best_view", {"Switch": 1}),
        ("all_favorite", {"Favorite": 0}),
    ],
)
async def test_hub_wide_buttons_send_the_bare_verb(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    key: str,
    expected: dict[str, int],
) -> None:
    """The All Rooms verbs carry no scope field at all -- an omitted scope means everything.

    One request reaches every blind: the hub fans out over its own radio, so this is not
    thirteen paced commands. Verified on hardware with every blind staged at 50/50 first,
    single-rail blinds included (docs/NORMAN_API.md, "Room-wide and hub-wide control").
    """
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: _hub_button(hass, init_integration, key).entity_id},
        blocking=True,
    )

    call = fake_hub.control_calls[-1]
    assert {k: call[k] for k in expected} == expected
    # No scope field: not a room, not a blind, and no all-rooms marker either.
    assert set(call) == {"Timestamp", "TaskID", *expected}


async def test_hub_wide_buttons_are_config_entities(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """They sit with the hub's other configuration entities, not its diagnostics."""
    for key in ("all_best_privacy", "all_best_view", "all_favorite"):
        entry = _hub_button(hass, init_integration, key)
        assert entry.entity_category is EntityCategory.CONFIG, key
        assert entry.disabled_by is None, key
    state = hass.states.get(_hub_button(hass, init_integration, "all_favorite").entity_id)
    assert state.attributes["friendly_name"] == "ShadeAuto Hub All blinds favorite position"
