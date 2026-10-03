"""Tests for the cover entities and the nudge services."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import patch

import aiohttp
from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_CURRENT_TILT_POSITION,
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverEntityFeature,
    CoverState,
)
from homeassistant.components.cover import (
    DOMAIN as COVER_DOMAIN,
)
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_CLOSE_COVER,
    SERVICE_CLOSE_COVER_TILT,
    SERVICE_OPEN_COVER,
    SERVICE_OPEN_COVER_TILT,
    SERVICE_SET_COVER_POSITION,
    SERVICE_SET_COVER_TILT_POSITION,
    SERVICE_STOP_COVER,
    SERVICE_STOP_COVER_TILT,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceNotSupported
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    issue_registry as ir,
)
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.norman.const import (
    DOMAIN,
    EVENT_COMMAND_FAILED,
    HUB_BUSY_RETRIES,
    HUB_CMD_STOP,
    HUB_COMMAND_TRIGGER,
    MOVE_ATTEMPTS,
)
from custom_components.norman.coordinator import NormanCoordinator

from .conftest import FakeHub, cover_entity_id, settle
from .const import UID_BEDROOM, UID_LIVING, UID_STATUS_ONLY

ALL_FEATURES = (
    CoverEntityFeature.OPEN
    | CoverEntityFeature.CLOSE
    | CoverEntityFeature.SET_POSITION
    | CoverEntityFeature.STOP
    | CoverEntityFeature.OPEN_TILT
    | CoverEntityFeature.CLOSE_TILT
    | CoverEntityFeature.SET_TILT_POSITION
    | CoverEntityFeature.STOP_TILT
)


@pytest.fixture
def living(hass: HomeAssistant, init_integration: MockConfigEntry) -> str:
    """Entity id of the living-room drape."""
    return cover_entity_id(hass, UID_LIVING)


async def _call(hass: HomeAssistant, domain: str, service: str, **data: Any) -> None:
    await hass.services.async_call(
        domain,
        service,
        {ATTR_ENTITY_ID: cover_entity_id(hass, UID_LIVING), **data},
        blocking=True,
    )
    await hass.async_block_till_done()


def _last_control(fake_hub: FakeHub) -> tuple[int, int, int]:
    call = fake_hub.control_calls[-1]
    return call["PeripheralUID"], call["BottomRailPosition"], call["MiddleRailPosition"]


async def test_entity_state_and_attributes(
    hass: HomeAssistant, init_integration: MockConfigEntry, living: str
) -> None:
    """State reflects the bottom rail; tilt the middle rail; targets are exposed."""
    state = hass.states.get(living)
    assert state.state == CoverState.OPEN
    assert state.attributes[ATTR_CURRENT_POSITION] == 40
    assert state.attributes[ATTR_CURRENT_TILT_POSITION] == 60
    assert state.attributes["target_position"] == 40
    assert state.attributes["target_tilt"] == 60
    assert state.attributes[ATTR_DEVICE_CLASS] == "blind"
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == ALL_FEATURES
    # Each cover is named for its rail, not for the device, so a two-rail blind reads as
    # "<blind> Bottom rail" and "<blind> Middle rail" rather than one entity taking the
    # device name.
    assert state.attributes["friendly_name"] == "Living Drape Bottom rail"

    bedroom = hass.states.get(cover_entity_id(hass, UID_BEDROOM))
    assert bedroom.state == CoverState.CLOSED
    # Single-rail (ModuleType 32): no tilt, shade device class, no tilt attributes
    assert bedroom.attributes[ATTR_SUPPORTED_FEATURES] == (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.STOP
    )
    assert bedroom.attributes[ATTR_DEVICE_CLASS] == "shade"
    assert ATTR_CURRENT_TILT_POSITION not in bedroom.attributes
    assert "target_tilt" not in bedroom.attributes

    status_only = hass.states.get(cover_entity_id(hass, UID_STATUS_ONLY))
    assert status_only.state == CoverState.OPEN
    assert status_only.attributes[ATTR_CURRENT_POSITION] == 100
    assert status_only.attributes["target_position"] is None


@pytest.mark.parametrize(
    ("service", "data", "expected"),
    [
        (SERVICE_SET_COVER_POSITION, {ATTR_POSITION: 60}, (60, 60)),
        (SERVICE_CLOSE_COVER, {}, (0, 60)),
        (SERVICE_SET_COVER_POSITION, {ATTR_POSITION: 25}, (25, 60)),
        (SERVICE_OPEN_COVER_TILT, {}, (40, 100)),
        (SERVICE_SET_COVER_TILT_POSITION, {ATTR_TILT_POSITION: 53}, (40, 53)),
    ],
)
async def test_cover_commands_preserve_the_other_rail(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    service: str,
    data: dict,
    expected: tuple[int, int],
) -> None:
    """Every command sends both rails; the untouched one keeps its current target.

    Each move here stays on its own side of the other rail. Moves that would pass it are in
    test_a_rail_moved_past_the_other_carries_it_along.
    """
    status_calls = len(fake_hub.calls_to("/status"))

    await _call(hass, COVER_DOMAIN, service, **data)

    assert _last_control(fake_hub) == (UID_LIVING, *expected)
    # A refresh follows the command so the state catches up with the hub
    assert len(fake_hub.calls_to("/status")) == status_calls + 1


@pytest.mark.parametrize("service", [SERVICE_STOP_COVER, SERVICE_STOP_COVER_TILT])
async def test_stop_sends_the_motor_stop_verb(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    service: str,
) -> None:
    """Stop (position or tilt) sends ``MotorStop: 170`` as the Norman app does, then refreshes.

    The hub has a single motor stop, so both services send the same command, and no rail
    positions go along with it.
    """
    status_calls = len(fake_hub.calls_to("/status"))

    await _call(hass, COVER_DOMAIN, service)

    call = fake_hub.control_calls[-1]
    assert call["PeripheralUID"] == UID_LIVING
    assert call[HUB_CMD_STOP] == HUB_COMMAND_TRIGGER
    assert "BottomRailPosition" not in call
    assert {"Timestamp", "TaskID"} <= call.keys()
    assert len(fake_hub.calls_to("/status")) == status_calls + 1


async def test_stop_failure_names_the_cover(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A hub error on stop surfaces as a HomeAssistantError naming the blind."""
    fake_hub.control_response = {"Error": 3}
    with pytest.raises(HomeAssistantError, match="Failed to stop Living Drape") as excinfo:
        await _call(hass, COVER_DOMAIN, SERVICE_STOP_COVER)
    # Raised with a translation key so the message can be localised
    assert excinfo.value.translation_key == "stop_failed"
    assert excinfo.value.translation_placeholders["name"] == "Living Drape"


def middle_rail_entity_id(hass: HomeAssistant, uid: int) -> str | None:
    return er.async_get(hass).async_get_entity_id("cover", DOMAIN, f"{uid}_middle")


async def test_two_rail_blinds_get_a_middle_rail_cover(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A two-rail blind is two covers: the device-named primary and a "Middle rail" shade.

    Day/night and top-down/bottom-up shades have a second fabric on the middle rail and
    the app shows two sliders; a single position+tilt cover hid the second one behind a
    tilt control nobody recognised. Single-rail blinds have no middle rail and get none.
    """
    middle_id = middle_rail_entity_id(hass, UID_LIVING)
    assert middle_id
    assert middle_rail_entity_id(hass, UID_BEDROOM) is None

    # Both covers are uncategorised, so the device page groups them together above the
    # divider; every button is categorised as configuration and sits below it.
    registry = er.async_get(hass)
    assert registry.async_get(middle_id).entity_category is None
    assert registry.async_get(cover_entity_id(hass, UID_LIVING)).entity_category is None

    middle = hass.states.get(middle_id)
    assert middle.attributes["friendly_name"] == "Living Drape Middle rail"
    assert middle.attributes[ATTR_DEVICE_CLASS] == "shade"
    assert middle.attributes[ATTR_CURRENT_POSITION] == 60  # MiddleRailPosition
    assert middle.attributes["target_position"] == 60
    assert ATTR_CURRENT_TILT_POSITION not in middle.attributes
    assert middle.attributes[ATTR_SUPPORTED_FEATURES] == (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.STOP
    )


@pytest.mark.parametrize(
    ("service", "data", "expected"),
    [
        (SERVICE_OPEN_COVER, {}, (40, 100)),
        (SERVICE_SET_COVER_POSITION, {ATTR_POSITION: 40}, (40, 40)),
        (SERVICE_SET_COVER_POSITION, {ATTR_POSITION: 75}, (40, 75)),
    ],
)
async def test_middle_rail_commands_move_only_the_middle_rail(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    service: str,
    data: dict,
    expected: tuple[int, int],
) -> None:
    """Middle-rail commands send the bottom rail back at its target and move the middle."""
    await hass.services.async_call(
        COVER_DOMAIN,
        service,
        {ATTR_ENTITY_ID: middle_rail_entity_id(hass, UID_LIVING), **data},
        blocking=True,
    )
    assert _last_control(fake_hub) == (UID_LIVING, *expected)


@pytest.mark.parametrize(
    ("domain", "service", "entity", "data", "expected"),
    [
        # The bottom rail (40) raised above the middle rail (60) takes the middle rail up.
        (COVER_DOMAIN, SERVICE_OPEN_COVER, "cover", {}, (100, 100)),
        (COVER_DOMAIN, SERVICE_SET_COVER_POSITION, "cover", {ATTR_POSITION: 80}, (80, 80)),
        ("number", "set_value", "bottom_rail_position", {"value": 70}, (70, 70)),
        # The middle rail lowered below the bottom rail takes the bottom rail down.
        (COVER_DOMAIN, SERVICE_CLOSE_COVER_TILT, "cover", {}, (0, 0)),
        (
            COVER_DOMAIN,
            SERVICE_SET_COVER_TILT_POSITION,
            "cover",
            {ATTR_TILT_POSITION: 33},
            (33, 33),
        ),
        (COVER_DOMAIN, SERVICE_CLOSE_COVER, "middle", {}, (0, 0)),
        (COVER_DOMAIN, SERVICE_SET_COVER_POSITION, "middle", {ATTR_POSITION: 25}, (25, 25)),
        ("number", "set_value", "middle_rail_position", {"value": 20}, (20, 20)),
    ],
)
async def test_a_rail_moved_past_the_other_carries_it_along(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    domain: str,
    service: str,
    entity: str,
    data: dict,
    expected: tuple[int, int],
) -> None:
    """A two-rail blind's middle rail hangs above its bottom rail, so they cannot cross.

    Sending one rail past the other would ask the hub for a shape the blind cannot make, so
    the other rail goes with it in the same command -- whichever entity started the move.
    This is also what lets the dashboard card pull the middle rail down from fully open.
    """
    if entity == "cover":
        entity_id = cover_entity_id(hass, UID_LIVING)
    elif entity == "middle":
        entity_id = middle_rail_entity_id(hass, UID_LIVING)
    else:
        entity_id = er.async_get(hass).async_get_entity_id(
            "number", DOMAIN, f"{UID_LIVING}_{entity}"
        )

    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )

    assert _last_control(fake_hub) == (UID_LIVING, *expected)


async def test_middle_rail_nudge_and_stop(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Nudging the middle-rail cover is relative to the middle rail; stop is the motor stop."""
    middle_id = middle_rail_entity_id(hass, UID_LIVING)
    fake_hub.set_position(UID_LIVING, target_middle=70)
    await notifications.put({"PeripheralList": []})
    await settle(hass)
    await hass.services.async_call(
        DOMAIN, "nudge_position", {ATTR_ENTITY_ID: middle_id, "step": -20}, blocking=True
    )
    assert _last_control(fake_hub) == (UID_LIVING, 40, 50)

    await hass.services.async_call(
        COVER_DOMAIN, SERVICE_STOP_COVER, {ATTR_ENTITY_ID: middle_id}, blocking=True
    )
    assert fake_hub.control_calls[-1][HUB_CMD_STOP] == HUB_COMMAND_TRIGGER


async def test_commands_follow_the_target_while_moving(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Mid-move, the untouched rail is sent where it is heading, not where it is now.

    That is the hub's target for a move made elsewhere, and the move itself for one sent
    from here: this fake hub never records the tilt as its target, and the close still
    keeps it.
    """
    fake_hub.set_position(UID_LIVING, target_bottom=80, target_middle=10)
    await notifications.put({"PeripheralList": []})
    await settle(hass)

    await _call(hass, COVER_DOMAIN, SERVICE_OPEN_COVER_TILT)
    assert _last_control(fake_hub) == (UID_LIVING, 80, 100)

    await _call(hass, COVER_DOMAIN, SERVICE_CLOSE_COVER)
    assert _last_control(fake_hub) == (UID_LIVING, 0, 100)


async def test_commands_fall_back_to_current_then_open(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Without a target the current position is used; without either, fully open."""
    peripheral = fake_hub.peripheral_status(UID_LIVING)
    del peripheral["TargetBottomRailPosition"]
    del peripheral["TargetMiddleRailPosition"]
    await notifications.put({"PeripheralList": []})
    await settle(hass)

    await _call(hass, COVER_DOMAIN, SERVICE_CLOSE_COVER)
    assert _last_control(fake_hub) == (UID_LIVING, 0, 60)

    # While that close is in flight it stands in for the hub; this is about the hub's fields.
    init_integration.runtime_data.async_supersede()
    del peripheral["MiddleRailPosition"]
    await notifications.put({"PeripheralList": []})
    await settle(hass)

    await _call(hass, COVER_DOMAIN, SERVICE_CLOSE_COVER)
    assert _last_control(fake_hub) == (UID_LIVING, 0, 100)


@pytest.mark.parametrize(
    ("service", "step", "expected"),
    [
        ("nudge_position", 10, (50, 60)),
        ("nudge_position", -10, (30, 60)),
        # Nudged past the middle rail (60), the bottom rail takes it along.
        ("nudge_position", 100, (100, 100)),
        ("nudge_position", -100, (0, 60)),
        ("nudge_tilt", 30, (40, 90)),
        # Nudged past the bottom rail (40), the middle rail takes it along.
        ("nudge_tilt", -100, (0, 0)),
        ("nudge_tilt", 100, (40, 100)),
    ],
)
async def test_nudge_services(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    service: str,
    step: int,
    expected: tuple[int, int],
) -> None:
    """Nudges are relative to the current target and clamped to 0-100."""
    await _call(hass, DOMAIN, service, step=step)
    assert _last_control(fake_hub) == (UID_LIVING, *expected)


async def test_nudge_is_relative_to_target_while_moving(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Two quick nudges add up instead of both being measured from the stale position."""
    fake_hub.set_position(UID_LIVING, target_bottom=80, target_middle=100)
    await notifications.put({"PeripheralList": []})
    await settle(hass)

    await _call(hass, DOMAIN, "nudge_position", step=5)
    assert _last_control(fake_hub) == (UID_LIVING, 85, 100)


@pytest.mark.parametrize("step", [101, -101, "lots"])
async def test_nudge_rejects_out_of_range_steps(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub, step: Any
) -> None:
    """The service schema validates the step before anything reaches the hub."""
    with pytest.raises(Exception, match="step"):
        await _call(hass, DOMAIN, "nudge_position", step=step)
    assert fake_hub.control_calls == []


async def test_single_rail_cover_echoes_middle_rail_and_ignores_tilt(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A single-rail shade sends its (zero) middle rail back and offers no tilt service."""
    bedroom = cover_entity_id(hass, UID_BEDROOM)
    await hass.services.async_call(
        COVER_DOMAIN, SERVICE_OPEN_COVER, {ATTR_ENTITY_ID: bedroom}, blocking=True
    )
    assert _last_control(fake_hub) == (UID_BEDROOM, 100, 0)

    # nudge_tilt is registered with required_features, so HA refuses it for a shade
    with pytest.raises(ServiceNotSupported):
        await hass.services.async_call(
            DOMAIN, "nudge_tilt", {ATTR_ENTITY_ID: bedroom, "step": 10}, blocking=True
        )
    assert len(fake_hub.control_calls) == 1

    # From where the open is heading, fully up.
    await hass.services.async_call(
        DOMAIN, "nudge_position", {ATTR_ENTITY_ID: bedroom, "step": -25}, blocking=True
    )
    assert _last_control(fake_hub) == (UID_BEDROOM, 75, 0)

    # Stop is a motor command, so the shade has it; stop_tilt is not offered
    await hass.services.async_call(
        COVER_DOMAIN, SERVICE_STOP_COVER, {ATTR_ENTITY_ID: bedroom}, blocking=True
    )
    assert fake_hub.control_calls[-1][HUB_CMD_STOP] == HUB_COMMAND_TRIGGER
    features = hass.states.get(bedroom).attributes[ATTR_SUPPORTED_FEATURES]
    assert features & CoverEntityFeature.STOP
    assert not features & CoverEntityFeature.STOP_TILT


async def test_each_cover_reports_its_device_class(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Device classes are picked per product, and nothing falls back to the base class.

    ``COVER_CLASSES`` maps every known cover type, and an unmapped ModuleType is defaulted
    to the two-rail type before it ever reaches the lookup -- so ``NormanCoverBase`` is
    never instantiated and its BLIND device class is unreachable. This pins the classes
    that users actually see, which no other test asserted.
    """
    from homeassistant.components.cover import CoverDeviceClass
    from homeassistant.const import ATTR_DEVICE_CLASS

    def device_class(entity_id: str) -> str | None:
        return hass.states.get(entity_id).attributes.get(ATTR_DEVICE_CLASS)

    # Two-rail blind: the bottom rail is a blind, its middle rail a shade.
    assert device_class(cover_entity_id(hass, UID_LIVING)) == CoverDeviceClass.BLIND
    assert device_class(middle_rail_entity_id(hass, UID_LIVING)) == CoverDeviceClass.SHADE
    # Single-rail product: a shade, not a blind.
    assert device_class(cover_entity_id(hass, UID_BEDROOM)) == CoverDeviceClass.SHADE


async def test_nudge_tilt_requires_tilt_support(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The tilt service is registered against the tilt feature."""
    assert hass.services.has_service(DOMAIN, "nudge_tilt")
    assert hass.services.has_service(DOMAIN, "nudge_position")


@pytest.mark.parametrize(
    ("control_response", "control_exc", "match"),
    [
        ({"Error": 3}, None, "error code: 3"),
        (None, aiohttp.ClientConnectionError("gone"), "Failed to connect"),
        (None, TimeoutError(), "Timed out"),
    ],
    ids=["hub-error", "connection", "timeout"],
)
async def test_command_failures_raise_home_assistant_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    control_response: dict | None,
    control_exc: Exception | None,
    match: str,
) -> None:
    """Hub and transport failures become a HomeAssistantError naming the cover."""
    if control_response is not None:
        fake_hub.control_response = control_response
    fake_hub.control_exc = control_exc

    with pytest.raises(HomeAssistantError, match=f"Failed to set position.*Living Drape.*{match}"):
        await _call(hass, COVER_DOMAIN, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 10})


async def test_a_busy_hub_is_retried_before_the_move_fails(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Error 2 on a move is retried a few times, spaced out; success on a retry is success.

    Every move sent while the hub was sweeping its blinds after a refresh answered Error 2,
    and the identical moves a minute later answered 0 (captured 2026-09-18). Any other code
    still fails at once (the parametrized failure test above covers Error 3).
    """
    fake_hub.control_responses = [{"Error": 2}, {"Error": 2}, {"Error": 0}]
    with patch("custom_components.norman.api.HUB_BUSY_RETRY_DELAY", 0):
        await _call(hass, COVER_DOMAIN, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 10})

    moves = [c for c in fake_hub.control_calls if "BottomRailPosition" in c]
    assert len(moves) == 3
    assert {m["BottomRailPosition"] for m in moves} == {10}


async def test_a_hub_that_stays_busy_fails_with_the_code(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """After the last retry the error reaches the user with the hub's code in it."""
    fake_hub.control_response = {"Error": 2}
    with (
        patch("custom_components.norman.api.HUB_BUSY_RETRY_DELAY", 0),
        pytest.raises(HomeAssistantError, match="Failed to set position.*error code: 2"),
    ):
        await _call(hass, COVER_DOMAIN, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 10})

    moves = [c for c in fake_hub.control_calls if "BottomRailPosition" in c]
    assert len(moves) == 1 + HUB_BUSY_RETRIES


async def _watchdog_done(coordinator: NormanCoordinator, uid: int) -> None:
    """Wait for the blind's move watchdog to run to completion.

    Not ``async_block_till_done(wait_background_tasks=True)``: that would also wait for the
    notification listener, which never ends.
    """
    if task := coordinator._move_watchers.get(uid):
        await task
    await settle_hass(coordinator)


async def settle_hass(coordinator: NormanCoordinator) -> None:
    await coordinator.hass.async_block_till_done()


def _moves(fake_hub: FakeHub, uid: int) -> list[dict[str, Any]]:
    return [
        c
        for c in fake_hub.control_calls
        if c.get("PeripheralUID") == uid and "BottomRailPosition" in c
    ]


def _status_requests(fake_hub: FakeHub, uid: int) -> list[dict[str, Any]]:
    return [
        c
        for c in fake_hub.control_calls
        if c.get("StatusRequest") == 0 and c.get("PeripheralUID") == uid
    ]


def _registry_id(hass: HomeAssistant, entry: MockConfigEntry, uid: int) -> str:
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if (DOMAIN, str(uid)) in device.identifiers:
            return device.id
    raise KeyError(uid)


def _reports_in(fake_hub: FakeHub, uid: int, bottom: int) -> None:
    """The blind reports in at ``bottom``: its position and its last-heard stamp move."""
    fake_hub.set_position(uid, bottom=bottom)
    fake_hub.peripheral_status(uid)["Timestamp"] += 30


async def test_move_watchdog_chases_a_blind_that_never_moved(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A blind that stays silent is asked where it is, then sent the move again.

    Captured 2026-09-18: blind 8399 answered a move to middle 100 with Error 0 and then
    sat at middle 0 with target 100 for twelve minutes, until a report-in cleared it. So a
    blind that has not reported moving after the travel time is asked to report in, and if
    it still has not moved the move goes again -- up to MOVE_ATTEMPTS sends in all.
    """
    coordinator: NormanCoordinator = init_integration.runtime_data
    with (
        patch("custom_components.norman.coordinator.MOVE_TIMEOUT", 0),
        patch("custom_components.norman.coordinator.MOVE_REPORT_WAIT", 0),
    ):
        await _call(hass, COVER_DOMAIN, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 10})
        await _watchdog_done(coordinator, UID_LIVING)

    calls = fake_hub.control_calls
    moves = _moves(fake_hub, UID_LIVING)
    assert len(moves) == MOVE_ATTEMPTS, "the move, then one resend per further attempt"
    unstamped = {"Timestamp": 0, "TaskID": 0}
    assert all(move | unstamped == moves[0] | unstamped for move in moves)
    requests = _status_requests(fake_hub, UID_LIVING)
    assert len(requests) == MOVE_ATTEMPTS, "one before each resend, and one before giving up"
    for request, resend in zip(requests, moves[1:], strict=False):
        assert calls.index(request) < calls.index(resend)


async def test_a_blind_that_ignores_every_attempt_is_logged_and_fires_an_event(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Giving up is not silent: a warning names the blind, and an event fires.

    It is not a repair issue: one command going unanswered is not something the user has
    to fix. The next command the blind does act on fires nothing.
    """
    coordinator: NormanCoordinator = init_integration.runtime_data
    events = async_capture_events(hass, EVENT_COMMAND_FAILED)
    with (
        patch("custom_components.norman.coordinator.MOVE_TIMEOUT", 0),
        patch("custom_components.norman.coordinator.MOVE_REPORT_WAIT", 0),
    ):
        await _call(hass, COVER_DOMAIN, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 10})
        await _watchdog_done(coordinator, UID_LIVING)

    assert f"Living Drape did not move after {MOVE_ATTEMPTS} attempts; giving up" in caplog.text
    assert not [key for key in ir.async_get(hass).issues if key[0] == DOMAIN]
    assert [event.data for event in events] == [
        {
            "device_id": _registry_id(hass, init_integration, UID_LIVING),
            "peripheral_uid": UID_LIVING,
            "name": "Living Drape",
            "attempts": MOVE_ATTEMPTS,
            "bottom_rail_position": 10,
            "middle_rail_position": 60,
            "louver_position": None,
        }
    ]

    # The blind comes back: a move it acts on is not reported.
    await _call(hass, COVER_DOMAIN, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 20})
    _reports_in(fake_hub, UID_LIVING, 20)
    await coordinator.async_refresh()
    await _watchdog_done(coordinator, UID_LIVING)
    assert len(events) == 1


async def test_move_watchdog_stops_as_soon_as_the_blind_reports_moving(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The watch waits on the hub's own updates, not a timer, and asks nothing of a blind that moved.

    With the real one-minute timeout in force, it finishes the moment the blind reports in
    partway there: movement towards the goal is proof the command arrived.
    """
    coordinator: NormanCoordinator = init_integration.runtime_data
    await _call(hass, COVER_DOMAIN, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 10})
    task = coordinator._move_watchers[UID_LIVING]
    assert not task.done(), "the command returned while its watch carries on"

    _reports_in(fake_hub, UID_LIVING, 25)
    await coordinator.async_refresh()
    await asyncio.wait_for(task, 1)

    assert len(_moves(fake_hub, UID_LIVING)) == 1
    assert not _status_requests(fake_hub, UID_LIVING)


async def test_a_report_away_from_the_goal_does_not_confirm_the_move(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A blind finishing an earlier move reports in, but not towards this move's goal."""
    coordinator: NormanCoordinator = init_integration.runtime_data
    await _call(hass, COVER_DOMAIN, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 10})
    task = coordinator._move_watchers[UID_LIVING]

    _reports_in(fake_hub, UID_LIVING, 70)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert not task.done(), "still waiting for this move"
    coordinator.async_cancel_move_watch(UID_LIVING)


async def test_move_watchdog_is_quiet_when_the_blind_arrives(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A blind that reaches its target gets no status request and no retry."""
    orig = fake_hub._control

    async def _arrive(method, url, data):  # noqa: ANN001
        body = json.loads(data) if isinstance(data, str | bytes) else data
        if "BottomRailPosition" in body:
            fake_hub.set_position(UID_LIVING, bottom=body["BottomRailPosition"])
        return await orig(method, url, data)

    with (
        patch.object(fake_hub, "_control", _arrive),
        patch("custom_components.norman.coordinator.MOVE_TIMEOUT", 0),
        patch("custom_components.norman.coordinator.MOVE_REPORT_WAIT", 0),
    ):
        fake_hub.mock.clear_requests()
        fake_hub._register()
        await _call(hass, COVER_DOMAIN, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 10})
        await _watchdog_done(init_integration.runtime_data, UID_LIVING)

    assert len(_moves(fake_hub, UID_LIVING)) == 1
    assert not [c for c in fake_hub.control_calls if "StatusRequest" in c]


async def test_a_resend_the_blind_acts_on_ends_the_chase(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The first send is dropped, the resend lands: no further resends, nothing reported."""
    orig = fake_hub._control
    sends = 0

    async def _second_lands(method, url, data):  # noqa: ANN001
        nonlocal sends
        body = json.loads(data) if isinstance(data, str | bytes) else data
        if "BottomRailPosition" in body:
            sends += 1
            if sends == 2:
                _reports_in(fake_hub, UID_LIVING, body["BottomRailPosition"])
        return await orig(method, url, data)

    events = async_capture_events(hass, EVENT_COMMAND_FAILED)
    with (
        patch.object(fake_hub, "_control", _second_lands),
        patch("custom_components.norman.coordinator.MOVE_TIMEOUT", 0),
        patch("custom_components.norman.coordinator.MOVE_REPORT_WAIT", 0),
    ):
        fake_hub.mock.clear_requests()
        fake_hub._register()
        await _call(hass, COVER_DOMAIN, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 10})
        await _watchdog_done(init_integration.runtime_data, UID_LIVING)

    assert len(_moves(fake_hub, UID_LIVING)) == 2
    assert not events


async def test_stop_cancels_the_move_watchdog(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """After a stop there is no target to chase, so the watch is dropped."""
    coordinator: NormanCoordinator = init_integration.runtime_data
    await _call(hass, COVER_DOMAIN, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 10})
    assert UID_LIVING in coordinator._move_watchers

    await _call(hass, COVER_DOMAIN, SERVICE_STOP_COVER)
    await settle(hass)
    assert UID_LIVING not in coordinator._move_watchers
    assert not [c for c in fake_hub.control_calls if "StatusRequest" in c]


def _slider(hass: HomeAssistant, uid: int, rail: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "number", DOMAIN, f"{uid}_{rail}_rail_position"
    )
    assert entity_id
    return entity_id


async def _slide(hass: HomeAssistant, rail: str, value: int) -> None:
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: _slider(hass, UID_LIVING, rail), "value": value},
        blocking=True,
    )


def _rails_sent(fake_hub: FakeHub) -> list[tuple[int, int]]:
    return [
        (c["BottomRailPosition"], c["MiddleRailPosition"]) for c in _moves(fake_hub, UID_LIVING)
    ]


async def test_moves_sent_together_keep_each_other(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Both rails set at once, as a scene does: the second keeps the first's rail.

    Each fills the other rail in with where it is heading. Worked out from the hub's target
    alone, both read the blind as it was (40/60) before either was sent, and the second
    undid the first: the blind ended at 40/70.
    """
    await asyncio.gather(_slide(hass, "bottom", 30), _slide(hass, "middle", 70))
    await hass.async_block_till_done()

    assert _rails_sent(fake_hub) == [(30, 60), (30, 70)]


async def test_a_scene_sets_both_rails(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Home Assistant applies a scene's entities concurrently; both rails still arrive."""
    assert await async_setup_component(hass, "scene", {})
    await hass.async_block_till_done()  # scene.apply comes with a platform loaded after setup
    await hass.services.async_call(
        "scene",
        "apply",
        {
            "entities": {
                _slider(hass, UID_LIVING, "bottom"): "30",
                _slider(hass, UID_LIVING, "middle"): "70",
            }
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    assert _rails_sent(fake_hub)[-1] == (30, 70)


async def test_a_move_right_behind_another_keeps_it(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """One rail and then the other, before the hub has been re-read (this fake never is)."""
    await _slide(hass, "bottom", 30)
    await _slide(hass, "middle", 70)

    assert _rails_sent(fake_hub) == [(30, 60), (30, 70)]


async def test_a_move_that_fails_to_send_is_not_kept(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A move the hub never took is not where the blind is heading."""
    fake_hub.control_exc = aiohttp.ClientError("unreachable")
    with pytest.raises(HomeAssistantError):
        await _slide(hass, "bottom", 30)
    fake_hub.control_exc = None

    await _slide(hass, "middle", 70)
    assert _rails_sent(fake_hub)[-1] == (40, 70)


async def test_a_stop_ends_the_move_in_flight(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """After a stop the blind is wherever it stopped, which only the hub knows."""
    await _slide(hass, "bottom", 30)
    await _call(hass, COVER_DOMAIN, SERVICE_STOP_COVER)

    await _slide(hass, "middle", 70)
    assert _rails_sent(fake_hub)[-1] == (40, 70)


async def test_a_move_the_blind_reports_hands_back_to_the_hub(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Once the blind reports the move, the hub's target counts again -- remote moves included."""
    coordinator: NormanCoordinator = init_integration.runtime_data
    await _slide(hass, "bottom", 30)
    _reports_in(fake_hub, UID_LIVING, 30)
    await coordinator.async_refresh()
    await _watchdog_done(coordinator, UID_LIVING)
    assert coordinator.commanded_rails(UID_LIVING) is None

    # Moved from the Norman remote since.
    _reports_in(fake_hub, UID_LIVING, 50)
    await coordinator.async_refresh()
    await _slide(hass, "middle", 70)
    assert _rails_sent(fake_hub)[-1] == (50, 70)


@pytest.mark.parametrize(
    "press",
    [
        pytest.param(
            lambda hass, entry: hass.services.async_call(
                DOMAIN,
                "room_command",
                {"room": "Living Room", "command": "best_view"},
                blocking=True,
            ),
            id="room preset",
        ),
        pytest.param(
            lambda hass, entry: hass.services.async_call(
                DOMAIN, "room_command", {"command": "best_privacy"}, blocking=True
            ),
            id="hub-wide preset",
        ),
        pytest.param(
            lambda hass, entry: hass.services.async_call(
                "button",
                "press",
                {
                    ATTR_ENTITY_ID: er.async_get(hass).async_get_entity_id(
                        "button", DOMAIN, f"{entry.entry_id}_all_favorite"
                    )
                },
                blocking=True,
            ),
            id="all-blinds button",
        ),
        pytest.param(
            lambda hass, entry: hass.services.async_call(
                "button",
                "press",
                {
                    ATTR_ENTITY_ID: er.async_get(hass).async_get_entity_id(
                        "button", DOMAIN, f"{UID_LIVING}_jog_up"
                    )
                },
                blocking=True,
            ),
            id="jog",
        ),
    ],
)
async def test_a_later_command_ends_the_move_watch(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub, press: Any
) -> None:
    """A preset or jog replaces the move in flight, so the watch must not send it again.

    Left running, the watch saw the blind heading for the preset instead, took it for a move
    that never arrived, and resent the move -- undoing the preset.
    """
    coordinator: NormanCoordinator = init_integration.runtime_data
    await _slide(hass, "bottom", 10)
    assert UID_LIVING in coordinator._move_watchers

    await press(hass, init_integration)
    await hass.async_block_till_done()

    assert UID_LIVING not in coordinator._move_watchers
    assert coordinator.commanded_rails(UID_LIVING) is None


async def test_a_status_request_leaves_the_move_watch_alone(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Asking a blind to report in does not move it, so its move is still in flight."""
    coordinator: NormanCoordinator = init_integration.runtime_data
    await _slide(hass, "bottom", 10)
    await hass.services.async_call(
        "button",
        "press",
        {
            ATTR_ENTITY_ID: er.async_get(hass).async_get_entity_id(
                "button", DOMAIN, f"{UID_LIVING}_request_status"
            )
        },
        blocking=True,
    )

    assert UID_LIVING in coordinator._move_watchers
    assert coordinator.commanded_rails(UID_LIVING) == (10, 60)
    coordinator.async_supersede()


async def test_new_blind_is_added_after_reconnect(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """A blind paired after setup appears once the device list is re-read."""
    assert er.async_get(hass).async_get_entity_id("cover", DOMAIN, "2001") is None

    fake_hub.devices["results"]["RoomList"][0]["GroupList"][0]["PeripheralList"].append(
        {"PeripheralUID": 2001, "PeripheralName": "Hall Drape", "ModuleType": 7}
    )
    fake_hub.status["Peripherals"].append(
        {"PeripheralUID": 2001, "BottomRailPosition": 10, "MiddleRailPosition": 20}
    )

    await notifications.put(None)  # periodic reconnect → device list re-read
    await settle(hass)

    state = hass.states.get(cover_entity_id(hass, 2001))
    assert state is not None
    assert state.attributes["friendly_name"] == "Hall Drape Bottom rail"
    assert state.attributes[ATTR_CURRENT_POSITION] == 10


async def test_blind_dropped_by_hub_becomes_unavailable(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """A peripheral that disappears from the hub's status is unavailable, not stale."""
    fake_hub.status["Peripherals"] = [
        p for p in fake_hub.status["Peripherals"] if p.get("PeripheralUID") != UID_STATUS_ONLY
    ]
    await notifications.put({"PeripheralList": []})
    await settle(hass)

    assert hass.states.get(cover_entity_id(hass, UID_STATUS_ONLY)).state == "unavailable"
    assert hass.states.get(cover_entity_id(hass, UID_LIVING)).state == CoverState.OPEN
