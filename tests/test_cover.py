"""Tests for the cover entities and the nudge services."""

from __future__ import annotations

import asyncio
from typing import Any

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
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.norman.const import DOMAIN

from .conftest import FakeHub, cover_entity_id, settle
from .const import UID_BEDROOM, UID_LIVING, UID_STATUS_ONLY

ALL_FEATURES = (
    CoverEntityFeature.OPEN
    | CoverEntityFeature.CLOSE
    | CoverEntityFeature.SET_POSITION
    | CoverEntityFeature.OPEN_TILT
    | CoverEntityFeature.CLOSE_TILT
    | CoverEntityFeature.SET_TILT_POSITION
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
    assert state.attributes["friendly_name"] == "Living Drape"

    assert hass.states.get(cover_entity_id(hass, UID_BEDROOM)).state == CoverState.CLOSED

    status_only = hass.states.get(cover_entity_id(hass, UID_STATUS_ONLY))
    assert status_only.state == CoverState.OPEN
    assert status_only.attributes[ATTR_CURRENT_POSITION] == 100
    assert status_only.attributes["target_position"] is None


@pytest.mark.parametrize(
    ("service", "data", "expected"),
    [
        (SERVICE_OPEN_COVER, {}, (100, 60)),
        (SERVICE_CLOSE_COVER, {}, (0, 60)),
        (SERVICE_SET_COVER_POSITION, {ATTR_POSITION: 25}, (25, 60)),
        (SERVICE_OPEN_COVER_TILT, {}, (40, 100)),
        (SERVICE_CLOSE_COVER_TILT, {}, (40, 0)),
        (SERVICE_SET_COVER_TILT_POSITION, {ATTR_TILT_POSITION: 33}, (40, 33)),
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
    """Every command sends both rails; the untouched one keeps its current target."""
    status_calls = len(fake_hub.calls_to("/status"))

    await _call(hass, COVER_DOMAIN, service, **data)

    assert _last_control(fake_hub) == (UID_LIVING, *expected)
    # A refresh follows the command so the state catches up with the hub
    assert len(fake_hub.calls_to("/status")) == status_calls + 1


async def test_commands_follow_the_target_while_moving(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Mid-move, the untouched rail is sent where it is heading, not where it is now."""
    fake_hub.set_position(UID_LIVING, target_bottom=80, target_middle=10)
    await notifications.put({"PeripheralList": []})
    await settle(hass)

    await _call(hass, COVER_DOMAIN, SERVICE_OPEN_COVER_TILT)
    assert _last_control(fake_hub) == (UID_LIVING, 80, 100)

    await _call(hass, COVER_DOMAIN, SERVICE_CLOSE_COVER)
    assert _last_control(fake_hub) == (UID_LIVING, 0, 10)


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
        ("nudge_position", 100, (100, 60)),
        ("nudge_position", -100, (0, 60)),
        ("nudge_tilt", 30, (40, 90)),
        ("nudge_tilt", -100, (40, 0)),
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
    fake_hub.set_position(UID_LIVING, target_bottom=80)
    await notifications.put({"PeripheralList": []})
    await settle(hass)

    await _call(hass, DOMAIN, "nudge_position", step=5)
    assert _last_control(fake_hub) == (UID_LIVING, 85, 60)


@pytest.mark.parametrize("step", [101, -101, "lots"])
async def test_nudge_rejects_out_of_range_steps(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub, step: Any
) -> None:
    """The service schema validates the step before anything reaches the hub."""
    with pytest.raises(Exception, match="step"):
        await _call(hass, DOMAIN, "nudge_position", step=step)
    assert fake_hub.control_calls == []


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
    assert state.attributes["friendly_name"] == "Hall Drape"
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
