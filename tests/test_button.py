"""Tests for the per-blind verb buttons."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.norman.button import BUTTONS, HUB_BUTTONS
from custom_components.norman.const import (
    DOMAIN,
    HUB_COMMAND_SETTING,
    HUB_COMMAND_TRIGGER,
    MOVE_ATTEMPTS,
)
from custom_components.norman.coordinator import NormanCoordinator

from .conftest import FakeHub, enable_buttons
from .const import (
    UID_BEDROOM,
    UID_LIVING,
    UID_ROLLER,
    UID_ROLLER_MRS2,
    UID_ROMAN,
    UID_SHEER,
    UID_SHUTTER,
    UID_SMARTDRAPE,
    UID_STATUS_ONLY,
    UID_TDBU,
)

# The buttons filed under Diagnostic: the report-in, and the motor routines from the Norman
# app's Advanced Settings page. Everything else is under Configuration.
DIAGNOSTIC_BUTTONS = {"request_status", "calibration", "find_top"}
# The routines are also disabled by default: the app asks the user to clear the window first,
# and a press asks nothing.
DISABLED_BUTTONS = {"calibration", "find_top"}


def _button(hass: HomeAssistant, uid: int, key: str) -> er.RegistryEntry:
    entry = er.async_get(hass).async_get(
        er.async_get(hass).async_get_entity_id(BUTTON_DOMAIN, DOMAIN, f"{uid}_{key}") or ""
    )
    assert entry, f"no {key} button for peripheral {uid}"
    return entry


async def test_every_blind_gets_the_buttons(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Both blind types get every button offered for their type, all but the routines enabled.

    The everyday ones are in the config category. That is a layout decision, not a claim
    that the buttons are rarely used: the device page sorts uncategorised entities together
    by entity id, which interleaved "Middle rail" with the buttons. Categorising every button
    keeps a two-rail blind's two covers adjacent at the top of the page.

    Favorite included: single-rail blinds have a stored favorite too. A hub-wide Favorite
    left them where they were in one capture, but they were already sitting at 100 -- no
    movement was not evidence of no favorite.
    """
    for uid, module_type in ((UID_LIVING, 33), (UID_BEDROOM, 32)):
        for description in BUTTONS:
            if description.module_types is not None and module_type not in (
                description.module_types
            ):
                continue
            entry = _button(hass, uid, description.key)
            expected = (
                EntityCategory.DIAGNOSTIC
                if description.key in DIAGNOSTIC_BUTTONS
                else EntityCategory.CONFIG
            )
            assert entry.entity_category is expected, description.key
            disabled = (
                er.RegistryEntryDisabler.INTEGRATION
                if description.key in DISABLED_BUTTONS
                else None
            )
            assert entry.disabled_by is disabled, description.key

    state = hass.states.get(_button(hass, UID_LIVING, "favorite").entity_id)
    assert state.attributes["friendly_name"] == "Living Drape Favorite position"
    # Icons come from icons.json, whose coverage tests/test_repo_consistency.py pins


@pytest.mark.parametrize(
    ("key", "verb", "value", "reads"),
    [
        ("jog_up", "MotorFineTuneToUp", HUB_COMMAND_TRIGGER, 1),
        ("jog_down", "MotorFineTuneToDown", HUB_COMMAND_TRIGGER, 1),
        # The app's per-blind status request, value 0 like every non-motor verb; the
        # blind answered within 5 s each time it was tried on hardware (2026-09-18). Its
        # answer comes as a notification with a read of its own, so none follows the press.
        ("request_status", "StatusRequest", HUB_COMMAND_SETTING, 0),
        # The Advanced Settings routines, built by the app's network library exactly like the
        # status request. The motor runs, so the hub is read after, as for a jog.
        ("calibration", "Calibration", HUB_COMMAND_SETTING, 1),
        ("find_top", "FindTop", HUB_COMMAND_SETTING, 1),
    ],
)
async def test_press_sends_the_verb_and_refreshes(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    key: str,
    verb: str,
    value: int,
    reads: int,
) -> None:
    """A press is one control call carrying exactly the verb, then a status re-read if needed."""
    if key in DISABLED_BUTTONS:
        await enable_buttons(hass, init_integration, UID_LIVING, key)
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
    assert len(fake_hub.calls_to("/status")) == status_calls + reads


async def test_request_status_reads_the_hub_while_the_stream_is_down(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """With no notification to bring the answer's read, the press reads the hub itself."""
    coordinator = init_integration.runtime_data
    coordinator._listener_offline = True
    status_calls = len(fake_hub.calls_to("/status"))

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: _button(hass, UID_LIVING, "request_status").entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(fake_hub.calls_to("/status")) == status_calls + 1
    coordinator._listener_offline = False


async def test_a_preset_press_reads_the_hub_once(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The preset's watch reads the hub for its target at once; no second read follows."""
    status_calls = len(fake_hub.calls_to("/status"))

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: _button(hass, UID_LIVING, "best_privacy").entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(fake_hub.calls_to("/status")) == status_calls + 1
    init_integration.runtime_data.async_supersede()


async def test_press_failure_names_the_button_and_blind(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A hub error becomes a HomeAssistantError naming the verb and the blind."""
    fake_hub.control_response = {"Error": 9}
    with pytest.raises(HomeAssistantError, match="Failed to send Jog up to Living Drape"):
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


@pytest.mark.parametrize(
    ("uid", "expected"),
    [
        (UID_LIVING, {"calibration", "find_top"}),  # 33/3, the one type with Find Top
        (UID_BEDROOM, {"calibration"}),  # 32/2
        (UID_TDBU, {"calibration"}),  # 32/4
        (UID_ROLLER, {"calibration"}),  # 48/1
        (UID_ROMAN, {"calibration"}),  # 48/2
        (UID_SHEER, {"calibration"}),  # 49/3
        (UID_ROLLER_MRS2, {"calibration"}),  # 49
        (UID_SHUTTER, {"calibration"}),  # 1
        (UID_SMARTDRAPE, set()),  # 80: its page has the drape type and limits instead
    ],
)
async def test_each_product_gets_the_routines_the_app_offers(
    hass: HomeAssistant,
    init_with_every_product: MockConfigEntry,
    uid: int,
    expected: set[str],
) -> None:
    """Calibration and Find top only where the Norman app's Advanced Settings lists them.

    ShadeAuto 0.8.33 builds that page from the blind's ModuleType: Calibration for every
    type but the SmartDrape, and Find Top for the dual-rail cellular shade alone.
    """
    registry = er.async_get(hass)
    found = {
        key
        for key in ("calibration", "find_top")
        if registry.async_get_entity_id(BUTTON_DOMAIN, DOMAIN, f"{uid}_{key}")
    }
    assert found == expected


async def test_a_blind_of_unknown_type_gets_neither_routine(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The app offers neither on a type it does not know, so neither is sent to one.

    This peripheral is listed only in status, without a ModuleType. It still gets every
    other button.
    """
    registry = er.async_get(hass)
    assert registry.async_get_entity_id(BUTTON_DOMAIN, DOMAIN, f"{UID_STATUS_ONLY}_jog_up")
    for key in ("calibration", "find_top"):
        assert not registry.async_get_entity_id(BUTTON_DOMAIN, DOMAIN, f"{UID_STATUS_ONLY}_{key}")


def _hub_button(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> er.RegistryEntry:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(BUTTON_DOMAIN, DOMAIN, f"{entry.entry_id}_{key}")
    found = registry.async_get(entity_id or "")
    assert found, f"no {key} button on the hub"
    return found


async def test_hub_gets_its_buttons(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """The hub device carries the three All Rooms verbs, stop and jog, refresh, and pairing."""
    assert [d.key for d in HUB_BUTTONS] == [
        "all_best_privacy",
        "all_best_view",
        "all_favorite",
        "all_stop",
        "all_jog_up",
        "all_jog_down",
        "refresh_blinds",
        "report_battery_levels",
        "start_pairing",
    ]
    # Stop is a control, beside the hub's sliders; the jogs are moves, with the presets.
    assert _hub_button(hass, init_integration, "all_stop").entity_category is None
    for key in ("all_jog_up", "all_jog_down"):
        assert _hub_button(hass, init_integration, key).entity_category is EntityCategory.CONFIG
    entry = _hub_button(hass, init_integration, "refresh_blinds")
    assert entry.entity_category is EntityCategory.DIAGNOSTIC
    assert entry.disabled_by is None
    state = hass.states.get(entry.entity_id)
    assert state.attributes["friendly_name"] == "ShadeAuto Hub Refresh blinds"

    battery_report = _hub_button(hass, init_integration, "report_battery_levels")
    assert battery_report.entity_category is EntityCategory.DIAGNOSTIC
    assert (
        "may close shades" in hass.states.get(battery_report.entity_id).attributes["friendly_name"]
    )

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


async def test_refresh_blinds_requests_status_from_the_whole_hub(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The safe hub refresh is one unscoped StatusRequest, with no battery report."""
    before = len(fake_hub.control_calls)
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: _hub_button(hass, init_integration, "refresh_blinds").entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()

    calls = fake_hub.control_calls[before:]
    assert len(calls) == 1
    assert set(calls[0]) == {"Timestamp", "TaskID", "StatusRequest"}
    assert calls[0]["StatusRequest"] == HUB_COMMAND_SETTING


@pytest.mark.parametrize(("listening", "reads"), [(True, 0), (False, 1)])
async def test_refresh_blinds_reads_the_hub_only_while_the_stream_is_down(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    listening: bool,
    reads: int,
) -> None:
    """The blinds' answers come seconds later, each a notification with a read of its own.

    A read straight after the press sees none of them, and holds back the first answer's
    read until the refresh cooldown is over. With the stream down it is the only read.
    """
    coordinator: NormanCoordinator = init_integration.runtime_data
    coordinator._listener_offline = not listening
    before = len(fake_hub.calls_to("/status"))
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: _hub_button(hass, init_integration, "refresh_blinds").entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(fake_hub.calls_to("/status")) == before + reads
    coordinator._listener_offline = False


@pytest.mark.parametrize(
    ("key", "verb"),
    [
        ("jog_up", "MotorFineTuneToUp"),
        ("calibration", "Calibration"),
        ("find_top", "FindTop"),
    ],
)
async def test_a_motor_verb_taken_over_while_it_waits_is_not_sent(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    key: str,
    verb: str,
) -> None:
    """A stop or a newer command for the blind, issued while the verb waits its turn, drops it."""
    if key in DISABLED_BUTTONS:
        await enable_buttons(hass, init_integration, UID_LIVING, key)
    coordinator: NormanCoordinator = init_integration.runtime_data
    api = coordinator.api
    await api._control_lock.acquire()
    try:
        press = asyncio.create_task(
            hass.services.async_call(
                BUTTON_DOMAIN,
                SERVICE_PRESS,
                {ATTR_ENTITY_ID: _button(hass, UID_LIVING, key).entity_id},
                blocking=True,
            )
        )
        for _ in range(25):
            await asyncio.sleep(0)
        coordinator.async_supersede([UID_LIVING])
    finally:
        api._control_lock.release()
    await press

    assert not [call for call in fake_hub.control_calls if verb in call]


@pytest.mark.parametrize("key", ["calibration", "find_top"])
async def test_a_routine_ends_the_move_watch(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub, key: str
) -> None:
    """A routine runs the motor, so it replaces the move in flight, as a jog does.

    Left running, the move's watch would see the blind somewhere else, take the move for one
    that never arrived, and send it again in the middle of the routine.
    """
    await enable_buttons(hass, init_integration, UID_LIVING, key)
    coordinator: NormanCoordinator = init_integration.runtime_data
    slider = er.async_get(hass).async_get_entity_id(
        "number", DOMAIN, f"{UID_LIVING}_bottom_rail_position"
    )
    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: slider, "value": 10}, blocking=True
    )
    move_watch = coordinator._move_watchers[UID_LIVING]

    await _press(hass, UID_LIVING, key)
    await hass.async_block_till_done()

    assert move_watch.cancelled()
    assert UID_LIVING not in coordinator._move_watchers
    assert coordinator.commanded_rails(UID_LIVING) is None


async def test_refresh_blinds_failure_names_the_hub(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A hub error on the hub button reads as a hub failure, not a blind's."""
    fake_hub.control_response = {"Error": 9}
    with pytest.raises(HomeAssistantError, match="Failed to send Refresh blinds to the hub"):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: _hub_button(hass, init_integration, "refresh_blinds").entity_id},
            blocking=True,
        )


async def test_battery_report_is_a_separate_hub_command(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The app's battery report is available explicitly and never sent by Refresh blinds."""
    before = len(fake_hub.control_calls)
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: _hub_button(hass, init_integration, "report_battery_levels").entity_id},
        blocking=True,
    )
    calls = fake_hub.control_calls[before:]
    assert len(calls) == 1
    assert set(calls[0]) == {"Timestamp", "TaskID", "ReportBatteryLevel"}
    assert calls[0]["ReportBatteryLevel"] == 0


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("all_best_privacy", {"Switch": 0}),
        ("all_best_view", {"Switch": 1}),
        ("all_favorite", {"Favorite": 0}),
        # Not from the app; an unscoped stop and jog were confirmed by direct tests.
        ("all_stop", {"MotorStop": HUB_COMMAND_TRIGGER}),
        ("all_jog_up", {"MotorFineTuneToUp": HUB_COMMAND_TRIGGER}),
        ("all_jog_down", {"MotorFineTuneToDown": HUB_COMMAND_TRIGGER}),
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


async def _preset_watchdog_done(coordinator: NormanCoordinator, uid: int) -> None:
    """Wait for the blind's preset watchdog to finish.

    Not ``async_block_till_done(wait_background_tasks=True)``: that would also wait on the
    notification listener, which never ends.
    """
    if task := coordinator._move_watchers.get(uid):
        await task
    await coordinator.hass.async_block_till_done()


async def _press(hass: HomeAssistant, uid: int, key: str) -> None:
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: _button(hass, uid, key).entity_id},
        blocking=True,
    )


def _switches(fake_hub: FakeHub, uid: int) -> list[dict]:
    """Every Switch command the hub received for ``uid`` (addressed by room + group)."""
    return [c for c in fake_hub.control_calls if "Switch" in c and c.get("PeripheralUID") == uid]


async def test_preset_watchdog_resends_a_preset_the_blind_ignored(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A preset the blind never acted on is asked about, then sent again.

    A preset has no position for the caller to aim at -- the blind resolves it to its own
    stored one -- so the goal is whatever target the hub recorded when it took the command.
    The hub acks a command it never delivers, so without this a missed Best Privacy is
    silent.
    """
    coordinator: NormanCoordinator = init_integration.runtime_data
    # Park the blind away from the hub's recorded target so it reads as "never arrived".
    fake_hub.set_position(UID_LIVING, bottom=40, target_bottom=0)
    await coordinator.async_refresh()

    with (
        patch("custom_components.norman.coordinator.MOVE_TIMEOUT", 0),
        patch("custom_components.norman.coordinator.MOVE_REPORT_WAIT", 0),
    ):
        await _press(hass, UID_LIVING, "best_privacy")
        await _preset_watchdog_done(coordinator, UID_LIVING)

    assert len(_switches(fake_hub, UID_LIVING)) == MOVE_ATTEMPTS, "the press, then resends"
    status_requests = [c for c in fake_hub.control_calls if c.get("StatusRequest") == 0]
    assert [c["PeripheralUID"] for c in status_requests] == [UID_LIVING] * MOVE_ATTEMPTS


async def test_preset_watchdog_is_not_fooled_when_the_hub_overwrites_its_target(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A blind reporting in resets the hub's target to wherever the blind is.

    Diagnostics, 2026-09-21: a blind ignored Best Privacy (target 0, still at 100), was
    asked to report in, and the hub then showed its target as 100 -- matching its position.
    The watch compared against that overwritten target, called the blind arrived, and never
    resent. It now keeps the goal the hub recorded when the preset went out.
    """
    coordinator: NormanCoordinator = init_integration.runtime_data
    fake_hub.set_position(UID_LIVING, bottom=100, middle=100)
    await coordinator.async_refresh()
    orig = fake_hub._control

    async def _hub(method, url, data):  # noqa: ANN001
        body = json.loads(data) if isinstance(data, str | bytes) else data
        peripheral = fake_hub.peripheral_status(UID_LIVING)
        if "Switch" in body:
            # Stored on accept, whether or not the blind ever hears the command.
            peripheral["TargetBottomRailPosition"] = 0
        if "StatusRequest" in body:
            # The blind reports in where it is, and the hub's target follows it there.
            peripheral["TargetBottomRailPosition"] = peripheral["BottomRailPosition"]
            peripheral["Timestamp"] += 5
        return await orig(method, url, data)

    with (
        patch.object(fake_hub, "_control", _hub),
        patch("custom_components.norman.coordinator.MOVE_TIMEOUT", 0),
        patch("custom_components.norman.coordinator.MOVE_REPORT_WAIT", 0),
    ):
        fake_hub.mock.clear_requests()
        fake_hub._register()
        await _press(hass, UID_LIVING, "best_privacy")
        await _preset_watchdog_done(coordinator, UID_LIVING)

    assert len(_switches(fake_hub, UID_LIVING)) == MOVE_ATTEMPTS
    assert f"did not move after {MOVE_ATTEMPTS} attempts; giving up" in caplog.text


async def test_preset_watchdog_is_quiet_when_the_blind_arrives(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A blind sitting at the hub's recorded target gets no status request and no resend."""
    coordinator: NormanCoordinator = init_integration.runtime_data
    fake_hub.set_position(UID_LIVING, bottom=0, target_bottom=0)
    await coordinator.async_refresh()

    with (
        patch("custom_components.norman.coordinator.MOVE_TIMEOUT", 0),
        patch("custom_components.norman.coordinator.MOVE_REPORT_WAIT", 0),
    ):
        await _press(hass, UID_LIVING, "best_privacy")
        await _preset_watchdog_done(coordinator, UID_LIVING)

    assert len(_switches(fake_hub, UID_LIVING)) == 1
    assert not [c for c in fake_hub.control_calls if "StatusRequest" in c]


async def test_a_preset_a_roller_shade_is_already_at_is_not_resent(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Issue #2: a nightly Best Privacy to closed roller shades warned on every one of them.

    Driven as two-rail, the shade was judged on a middle rail it does not have: Best Privacy
    records a middle-rail target of 100 and the shade reports 0, so it never looked arrived --
    it was asked to report in, sent the preset twice more, and given up on. As a single-rail
    shade only its bottom rail counts, and that is already where Best Privacy puts it.
    """
    coordinator: NormanCoordinator = init_with_every_product.runtime_data

    with (
        patch("custom_components.norman.coordinator.MOVE_TIMEOUT", 0),
        patch("custom_components.norman.coordinator.MOVE_REPORT_WAIT", 0),
    ):
        await _press(hass, UID_ROLLER, "best_privacy")
        await _preset_watchdog_done(coordinator, UID_ROLLER)

    assert len(_switches(fake_hub, UID_ROLLER)) == 1
    assert not [c for c in fake_hub.control_calls if "StatusRequest" in c]


async def test_preset_watchdog_forgets_itself_when_it_finishes(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The finished watcher is removed from the registry rather than left behind.

    Without this the dict keeps one completed task per blind that has ever run a preset, and
    ``async_cancel_move_watch`` then "cancels" a task that has already returned.
    """
    coordinator: NormanCoordinator = init_integration.runtime_data
    fake_hub.set_position(UID_LIVING, bottom=0, target_bottom=0)
    await coordinator.async_refresh()

    with (
        patch("custom_components.norman.coordinator.MOVE_TIMEOUT", 0),
        patch("custom_components.norman.coordinator.MOVE_REPORT_WAIT", 0),
    ):
        await _press(hass, UID_LIVING, "best_privacy")
        assert UID_LIVING in coordinator._move_watchers, "scheduled while it runs"
        await _preset_watchdog_done(coordinator, UID_LIVING)

    assert UID_LIVING not in coordinator._move_watchers


async def test_a_second_preset_keeps_the_replacement_watcher(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A preset pressed twice leaves the *live* watcher tracked, not the cancelled one.

    The replacement cancels its predecessor and takes the slot; the cancelled task's cleanup
    runs afterwards, so a cleanup that popped unconditionally would drop the live watcher and
    leave nothing for a later stop to cancel.
    """
    coordinator: NormanCoordinator = init_integration.runtime_data
    fake_hub.set_position(UID_LIVING, bottom=40, target_bottom=0)
    await coordinator.async_refresh()

    await _press(hass, UID_LIVING, "best_privacy")
    first = coordinator._move_watchers[UID_LIVING]
    await _press(hass, UID_LIVING, "best_view")
    second = coordinator._move_watchers[UID_LIVING]

    assert first is not second
    await hass.async_block_till_done()
    assert coordinator._move_watchers.get(UID_LIVING) is second, "the live watcher survives"

    coordinator.async_cancel_move_watch(UID_LIVING)
    assert UID_LIVING not in coordinator._move_watchers


async def test_a_preset_stopped_while_it_waits_its_turn_is_not_watched(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A stop while a blind's preset waits to be sent drops the preset, unsent and unwatched.

    Sent, it would start the stopped blind moving again; watched, the blind would read as a
    preset that never arrived and be sent it again.
    """
    coordinator = init_integration.runtime_data
    api = coordinator.api
    await api._control_lock.acquire()
    try:
        press = asyncio.create_task(
            hass.services.async_call(
                BUTTON_DOMAIN,
                SERVICE_PRESS,
                {ATTR_ENTITY_ID: _button(hass, UID_LIVING, "best_privacy").entity_id},
                blocking=True,
            )
        )
        for _ in range(25):
            await asyncio.sleep(0)
        coordinator.async_supersede([UID_LIVING])
    finally:
        api._control_lock.release()
    await press

    assert [call.get("Switch") for call in fake_hub.control_calls if "Switch" in call] == []
    assert UID_LIVING not in coordinator._move_watchers
