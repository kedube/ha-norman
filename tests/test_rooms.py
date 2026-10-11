"""Tests for the room devices and the hub-wide controls: one request for many blinds."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import copy
from typing import Any
from unittest.mock import patch

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.number import ATTR_VALUE, SERVICE_SET_VALUE
from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.norman.button import ROOM_BUTTONS
from custom_components.norman.const import (
    DOMAIN,
    HUB_COMMAND_SETTING,
    HUB_COMMAND_TRIGGER,
    MOVE_ATTEMPTS,
    ROOM_MIDDLE_WITHOUT_TWO_RAIL,
)
from custom_components.norman.coordinator import NormanCoordinator, room_identifier

from .conftest import FakeHub, loaded, settle
from .const import (
    SHUTTER_DEVICE,
    SHUTTER_STATUS,
    SMARTDRAPE_DEVICE,
    SMARTDRAPE_STATUS,
    UID_BEDROOM,
    UID_LIVING,
    UID_SHUTTER,
    UID_SMARTDRAPE,
    UID_STATUS_ONLY,
)

# The fake hub's rooms (tests/const.py): Living Room holds the two-rail UID_LIVING (40/60),
# Bedroom the single-rail UID_BEDROOM (0). UID_STATUS_ONLY is in no room.
LIVING_ROOM = 1
BEDROOM = 2
# A second two-rail shade, paired into whichever room a test needs.
UID_SECOND = 1004


def _two_rail(uid: int, name: str, bottom: int, middle: int) -> tuple[dict, dict]:
    """A day/night Cellular Shade's device-list and status records."""
    device = {
        "PeripheralUID": str(uid),
        "PeripheralName": name,
        "ModuleType": "33",
        "ModuleDetail": "3",
    }
    status = {
        "PeripheralUID": uid,
        "ModuleType": 33,
        "ModuleDetail": 3,
        "BottomRailPosition": bottom,
        "MiddleRailPosition": middle,
        "TargetBottomRailPosition": bottom,
        "TargetMiddleRailPosition": middle,
        "Timestamp": 1700000000,
    }
    return device, status


def _pair(fake_hub: FakeHub, room_index: int, device: dict, status: dict) -> None:
    """Pair a blind into the hub's ``room_index``-th room, on a remote channel of its own."""
    groups = fake_hub.devices["results"]["RoomList"][room_index]["GroupList"]
    groups.append(
        {"GroupID": 90 + len(groups), "GroupName": "", "PeripheralList": [copy.deepcopy(device)]}
    )
    fake_hub.status["Peripherals"].append(copy.deepcopy(status))


@pytest.fixture
async def two_in_living_room(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> AsyncGenerator[MockConfigEntry]:
    """The fake hub with a second two-rail shade in the living room, at the same 40/60."""
    _pair(fake_hub, 0, *_two_rail(UID_SECOND, "Living Sheer", bottom=40, middle=60))
    async with loaded(hass, mock_config_entry) as entry:
        yield entry


def _scope_entity(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, room_id: int | None, key: str
) -> str:
    unique_id = (
        f"{entry.entry_id}_{key}" if room_id is None else f"{entry.entry_id}_{room_id}_{key}"
    )
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id, f"no {domain} {unique_id}"
    return entity_id


def _room_slider(hass: HomeAssistant, entry: MockConfigEntry, room_id: int, rail: str) -> str:
    return _scope_entity(hass, entry, NUMBER_DOMAIN, room_id, f"room_{rail}_rail_position")


def _hub_slider(hass: HomeAssistant, entry: MockConfigEntry, rail: str) -> str:
    return _scope_entity(hass, entry, NUMBER_DOMAIN, None, f"all_{rail}_rail_position")


async def _set(hass: HomeAssistant, entity_id: str, value: int) -> None:
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value},
        blocking=True,
    )
    await hass.async_block_till_done()


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()


def _moves(fake_hub: FakeHub) -> list[dict[str, Any]]:
    """Every position move the hub received, without the stamps."""
    return [
        {k: v for k, v in call.items() if k not in ("Timestamp", "TaskID")}
        for call in fake_hub.control_calls
        if "BottomRailPosition" in call
    ]


def _device(hass: HomeAssistant, entry: MockConfigEntry, identifier: str) -> dr.DeviceEntry:
    """Looked up through the entry: identifiers are not unique across entries since 2026.9."""
    for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id):
        if (DOMAIN, identifier) in device.identifiers:
            return device
    raise AssertionError(f"no device {identifier}")


def _room_device(hass: HomeAssistant, entry: MockConfigEntry, room_id: int) -> dr.DeviceEntry:
    return _device(hass, entry, room_identifier(entry, room_id))


async def _watchdogs_done(coordinator: NormanCoordinator, *uids: int) -> None:
    for uid in uids:
        if task := coordinator._move_watchers.get(uid):
            await task
    await coordinator.hass.async_block_till_done()


# --- devices and entities -------------------------------------------------------------------


async def test_every_room_gets_a_device_in_its_area(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A room is a device named as the hub names it, in that area, hanging off the hub.

    In the area, the room's controls sit beside its blinds on the area's page.
    """
    hub = _device(hass, init_integration, f"hub_{init_integration.entry_id}")
    for room_id, name in ((LIVING_ROOM, "Living Room"), (BEDROOM, "Bedroom")):
        device = _room_device(hass, init_integration, room_id)
        assert device.name == name
        assert device.model == "Room"
        assert device.manufacturer == "Norman"
        assert device.via_device_id == hub.id
        assert ar.async_get(hass).async_get_area(device.area_id).name == name


async def test_a_room_gets_a_slider_for_each_rail_its_blinds_have(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The living room's two-rail shade brings both sliders; the bedroom's only a bottom one."""
    registry = er.async_get(hass)
    entry_id = init_integration.entry_id
    assert _room_slider(hass, init_integration, LIVING_ROOM, "bottom")
    assert _room_slider(hass, init_integration, LIVING_ROOM, "middle")
    assert _room_slider(hass, init_integration, BEDROOM, "bottom")
    assert not registry.async_get_entity_id(
        NUMBER_DOMAIN, DOMAIN, f"{entry_id}_{BEDROOM}_room_middle_rail_position"
    )

    state = hass.states.get(_room_slider(hass, init_integration, LIVING_ROOM, "bottom"))
    assert state.attributes["friendly_name"] == "Living Room Bottom rail position"
    assert state.attributes["step"] == 10
    assert float(state.state) == 40


async def test_a_room_gets_every_button(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Laid out as a blind's page: stop with the sliders, moves under config, refresh last."""
    registry = er.async_get(hass)
    for room_id in (LIVING_ROOM, BEDROOM):
        for description in ROOM_BUTTONS:
            entity = registry.async_get(
                _scope_entity(hass, init_integration, BUTTON_DOMAIN, room_id, description.key)
            )
            expected = {
                "room_stop": None,
                "room_refresh": EntityCategory.DIAGNOSTIC,
            }.get(description.key, EntityCategory.CONFIG)
            assert entity.entity_category is expected, description.key
            assert entity.disabled_by is None, description.key
    best = _scope_entity(hass, init_integration, BUTTON_DOMAIN, BEDROOM, "room_best_privacy")
    assert hass.states.get(best).attributes["friendly_name"] == "Bedroom Best privacy"


async def test_the_hub_gets_a_slider_for_every_rail(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """On the hub device, uncategorised: the controls beside All blinds stop."""
    hub = _device(hass, init_integration, f"hub_{init_integration.entry_id}")
    for rail in ("bottom", "middle"):
        entity = er.async_get(hass).async_get(_hub_slider(hass, init_integration, rail))
        assert entity.entity_category is None
        assert entity.device_id == hub.id
    state = hass.states.get(_hub_slider(hass, init_integration, "bottom"))
    assert state.attributes["friendly_name"] == "ShadeAuto Hub All blinds bottom rail position"


async def test_a_room_slider_reads_the_average_of_its_blinds(
    hass: HomeAssistant, two_in_living_room: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """As a cover group reports its members: settled on one value, or between them."""
    slider = _room_slider(hass, two_in_living_room, LIVING_ROOM, "bottom")
    assert float(hass.states.get(slider).state) == 40

    fake_hub.set_position(UID_SECOND, bottom=70)
    await two_in_living_room.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get(slider).state) == 55


# --- room-wide positions --------------------------------------------------------------------


async def test_a_room_moved_together_takes_one_request(
    hass: HomeAssistant, two_in_living_room: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Both shades heading to the same middle rail: one request with the room's RoomID.

    No PeripheralUID: the hub sends the pair to every blind in the room (confirmed on two
    office shades, 2026-10-10). Both rails go -- a room request missing either is refused or
    resets the other.
    """
    await _set(hass, _room_slider(hass, two_in_living_room, LIVING_ROOM, "bottom"), 20)

    assert _moves(fake_hub) == [
        {"RoomID": LIVING_ROOM, "BottomRailPosition": 20, "MiddleRailPosition": 60}
    ]


async def test_a_room_whose_blinds_disagree_is_moved_blind_by_blind(
    hass: HomeAssistant, two_in_living_room: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """One request would drag one shade's middle rail to the other's, so each gets its own.

    Each keeps its own middle rail, as its own slider would.
    """
    fake_hub.set_position(UID_SECOND, middle=80)
    await two_in_living_room.runtime_data.async_refresh()

    await _set(hass, _room_slider(hass, two_in_living_room, LIVING_ROOM, "bottom"), 20)

    assert _moves(fake_hub) == [
        {"PeripheralUID": UID_LIVING, "BottomRailPosition": 20, "MiddleRailPosition": 60},
        {"PeripheralUID": UID_SECOND, "BottomRailPosition": 20, "MiddleRailPosition": 80},
    ]


async def test_a_room_move_carries_the_other_rail_along(
    hass: HomeAssistant, two_in_living_room: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Raising the bottom rails past the middle ones takes the middle rails up too."""
    await _set(hass, _room_slider(hass, two_in_living_room, LIVING_ROOM, "bottom"), 90)
    await _set(hass, _room_slider(hass, two_in_living_room, LIVING_ROOM, "middle"), 30)

    assert _moves(fake_hub) == [
        {"RoomID": LIVING_ROOM, "BottomRailPosition": 90, "MiddleRailPosition": 90},
        # The second move starts from the first, not from the hub's stale 40/60.
        {"RoomID": LIVING_ROOM, "BottomRailPosition": 30, "MiddleRailPosition": 30},
    ]


async def test_a_single_rail_room_sends_a_middle_rail_it_does_not_have(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The hub still needs both fields; the one it gets is what its own presets record."""
    await _set(hass, _room_slider(hass, init_integration, BEDROOM, "bottom"), 50)

    assert _moves(fake_hub) == [
        {
            "RoomID": BEDROOM,
            "BottomRailPosition": 50,
            "MiddleRailPosition": ROOM_MIDDLE_WITHOUT_TWO_RAIL,
        }
    ]


async def test_a_middle_rail_move_leaves_a_single_rail_neighbour_alone(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """The room request reaches the single-rail shade too, so it goes only when harmless.

    With both bottom rails level, the two-rail shade's middle rail moves in one request
    that leaves the single-rail shade where it is. A middle rail lowered past its bottom rail
    takes that bottom rail with it, and one request would take the single-rail shade's down
    too -- so then the two-rail shade is sent its move on its own.
    """
    _pair(fake_hub, 1, *_two_rail(UID_SECOND, "Bedroom Sheer", bottom=0, middle=50))
    async with loaded(hass, mock_config_entry) as entry:
        middle = _room_slider(hass, entry, BEDROOM, "middle")
        await _set(hass, middle, 80)
        await _set(hass, _room_slider(hass, entry, BEDROOM, "bottom"), 30)
        before = len(_moves(fake_hub))
        await _set(hass, middle, 20)

        moves = _moves(fake_hub)
    assert moves[:before] == [
        {"RoomID": BEDROOM, "BottomRailPosition": 0, "MiddleRailPosition": 80},
        {"RoomID": BEDROOM, "BottomRailPosition": 30, "MiddleRailPosition": 80},
    ]
    # The middle rail down to 20 carries the two-rail shade's bottom rail with it, which
    # the single-rail shade, at 30, must not follow.
    assert moves[before:] == [
        {"PeripheralUID": UID_SECOND, "BottomRailPosition": 20, "MiddleRailPosition": 20}
    ]


@pytest.mark.parametrize(
    ("device", "status", "driven"),
    [
        # A drape draws on its bottom rail like a shade, but its middle rail is the vanes,
        # which a room request has not been tried on: each blind is sent its own move.
        (SMARTDRAPE_DEVICE, SMARTDRAPE_STATUS, {UID_LIVING, UID_SMARTDRAPE}),
        # A Shutter has no rails at all, so it is not moved; and a room request would
        # reach it, so the shade beside it is sent its own.
        (SHUTTER_DEVICE, SHUTTER_STATUS, {UID_LIVING}),
    ],
)
async def test_a_room_with_an_untried_product_is_moved_blind_by_blind(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
    device: dict,
    status: dict,
    driven: set[int],
) -> None:
    """Only single- and two-rail shades have had a room-wide position sent to them."""
    fake_hub.add_blind(device, status)
    async with loaded(hass, mock_config_entry) as entry:
        await _set(hass, _room_slider(hass, entry, LIVING_ROOM, "bottom"), 20)

    moves = _moves(fake_hub)
    assert not [move for move in moves if "RoomID" in move]
    assert {move["PeripheralUID"] for move in moves} == driven
    assert UID_SHUTTER not in {move["PeripheralUID"] for move in moves}


async def test_the_hub_slider_moves_every_blind_with_no_address(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """No RoomID and no PeripheralUID: the hub reads an omitted scope as every blind."""
    fake_hub.set_position(UID_STATUS_ONLY, middle=60)  # level with the living room's
    await init_integration.runtime_data.async_refresh()

    await _set(hass, _hub_slider(hass, init_integration, "bottom"), 50)

    assert _moves(fake_hub) == [{"BottomRailPosition": 50, "MiddleRailPosition": 60}]


async def test_a_room_move_is_watched_and_resent_blind_by_blind(
    hass: HomeAssistant, two_in_living_room: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A shade that ignores the room request is chased with a move of its own.

    The hub acked a room restore on 2026-10-10 that one of two shades only carried out when
    its own command was resent; the room's request is not sent again.
    """
    coordinator: NormanCoordinator = two_in_living_room.runtime_data
    with (
        patch("custom_components.norman.coordinator.MOVE_TIMEOUT", 0),
        patch("custom_components.norman.coordinator.MOVE_REPORT_WAIT", 0),
    ):
        await _set(hass, _room_slider(hass, two_in_living_room, LIVING_ROOM, "bottom"), 20)
        await _watchdogs_done(coordinator, UID_LIVING, UID_SECOND)

    moves = _moves(fake_hub)
    assert [move for move in moves if "RoomID" in move] == [moves[0]]
    for uid in (UID_LIVING, UID_SECOND):
        resends = [move for move in moves if move.get("PeripheralUID") == uid]
        assert resends == [
            {"PeripheralUID": uid, "BottomRailPosition": 20, "MiddleRailPosition": 60}
        ] * (MOVE_ATTEMPTS - 1)


async def test_a_blind_move_after_a_room_move_keeps_it(
    hass: HomeAssistant, two_in_living_room: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """One shade's middle rail moved right after the room: its bottom stays at the room's."""
    await _set(hass, _room_slider(hass, two_in_living_room, LIVING_ROOM, "bottom"), 20)
    blind_middle = er.async_get(hass).async_get_entity_id(
        NUMBER_DOMAIN, DOMAIN, f"{UID_LIVING}_middle_rail_position"
    )
    await _set(hass, blind_middle, 70)

    assert _moves(fake_hub)[-1] == {
        "PeripheralUID": UID_LIVING,
        "BottomRailPosition": 20,
        "MiddleRailPosition": 70,
    }


async def test_a_room_move_that_fails_names_the_room_and_is_not_kept(
    hass: HomeAssistant, two_in_living_room: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A room request the hub refused is not where the blinds are heading."""
    coordinator: NormanCoordinator = two_in_living_room.runtime_data
    fake_hub.control_response = {"Error": 9}
    with pytest.raises(
        HomeAssistantError, match=r"Failed to set position \(value: 20\) for Living Room"
    ):
        await _set(hass, _room_slider(hass, two_in_living_room, LIVING_ROOM, "bottom"), 20)
    assert coordinator.commanded_rails(UID_LIVING) is None
    assert coordinator.commanded_rails(UID_SECOND) is None


async def test_a_busy_hub_is_retried_for_a_room_move(
    hass: HomeAssistant, two_in_living_room: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Error 2 is retried as it is for one blind's move."""
    fake_hub.control_responses = [{"Error": 2}, {"Error": 0}]
    with patch("custom_components.norman.api.HUB_BUSY_RETRY_DELAY", 0):
        await _set(hass, _room_slider(hass, two_in_living_room, LIVING_ROOM, "bottom"), 20)

    assert [move.get("RoomID") for move in _moves(fake_hub)] == [LIVING_ROOM, LIVING_ROOM]


# --- room buttons ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("room_stop", {"MotorStop": HUB_COMMAND_TRIGGER}),
        ("room_best_privacy", {"Switch": 0}),
        ("room_best_view", {"Switch": 1}),
        ("room_favorite", {"Favorite": HUB_COMMAND_SETTING}),
        ("room_jog_up", {"MotorFineTuneToUp": HUB_COMMAND_TRIGGER}),
        ("room_jog_down", {"MotorFineTuneToDown": HUB_COMMAND_TRIGGER}),
    ],
)
async def test_room_buttons_send_the_verb_with_the_room(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    key: str,
    expected: dict[str, int],
) -> None:
    """One request with the room's RoomID and nothing narrower, then a status re-read."""
    status_calls = len(fake_hub.calls_to("/status"))
    await _press(hass, _scope_entity(hass, init_integration, BUTTON_DOMAIN, LIVING_ROOM, key))

    call = fake_hub.control_calls[-1]
    assert set(call) == {"Timestamp", "TaskID", "RoomID", *expected}
    assert call["RoomID"] == LIVING_ROOM
    assert {k: call[k] for k in expected} == expected
    assert len(fake_hub.calls_to("/status")) == status_calls + 1


async def test_room_refresh_sweeps_the_room_then_pokes_its_wired_blinds(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """norman.room_command's refresh, as a button: the room sweep, then each single-rail blind."""
    before = len(fake_hub.control_calls)
    await _press(
        hass, _scope_entity(hass, init_integration, BUTTON_DOMAIN, BEDROOM, "room_refresh")
    )

    sweep, *pokes = fake_hub.control_calls[before:]
    assert sweep["ReportBatteryLevel"] == 0 and sweep["RoomID"] == BEDROOM
    assert [poke["PeripheralUID"] for poke in pokes] == [UID_BEDROOM]


async def test_a_room_stop_ends_the_moves_in_that_room_only(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Left running, a watch would take the stopped blind for one that never arrived."""
    coordinator: NormanCoordinator = init_integration.runtime_data
    await coordinator.async_move_blind(UID_LIVING, 10, None)
    await coordinator.async_move_blind(UID_BEDROOM, 90, None)
    assert {UID_LIVING, UID_BEDROOM} <= set(coordinator._move_watchers)

    await _press(
        hass, _scope_entity(hass, init_integration, BUTTON_DOMAIN, LIVING_ROOM, "room_stop")
    )

    assert UID_LIVING not in coordinator._move_watchers
    assert coordinator.commanded_rails(UID_LIVING) is None
    assert UID_BEDROOM in coordinator._move_watchers


async def test_a_room_button_failure_names_the_room(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    fake_hub.control_response = {"Error": 9}
    with pytest.raises(HomeAssistantError, match="Failed to send room_stop to Living Room"):
        await _press(
            hass, _scope_entity(hass, init_integration, BUTTON_DOMAIN, LIVING_ROOM, "room_stop")
        )


# --- rooms coming and going -----------------------------------------------------------------


async def test_a_blind_paired_into_a_room_brings_the_rails_it_has(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """The bedroom gains a middle-rail slider once a two-rail shade joins it."""
    _pair(fake_hub, 1, *_two_rail(UID_SECOND, "Bedroom Sheer", bottom=0, middle=50))
    await notifications.put(None)  # periodic reconnect: the device list is re-read
    await settle(hass)

    assert _room_slider(hass, init_integration, BEDROOM, "middle")


async def test_a_new_room_gets_a_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    device, status = _two_rail(UID_SECOND, "Study Shade", bottom=0, middle=100)
    fake_hub.devices["results"]["RoomList"].append(
        {
            "RoomID": 7,
            "RoomName": "Study",
            "GroupList": [{"GroupID": 1, "GroupName": "", "PeripheralList": [device]}],
        }
    )
    fake_hub.status["Peripherals"].append(status)
    await notifications.put(None)
    await settle(hass)

    assert _room_device(hass, init_integration, 7).name == "Study"
    assert _scope_entity(hass, init_integration, BUTTON_DOMAIN, 7, "room_best_view")


async def test_a_room_renamed_in_the_app_is_renamed_here(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    fake_hub.devices["results"]["RoomList"][1]["RoomName"] = "Guest Room"
    await notifications.put({"UpdateTime": {"room": 1788831865}, "Timestamp": 1})
    await settle(hass)

    assert _room_device(hass, init_integration, BEDROOM).name == "Guest Room"


async def test_an_emptied_room_is_unavailable_and_can_be_deleted(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """A room the hub still reports refuses deletion; once it is gone, it can go."""
    from custom_components.norman import async_remove_config_entry_device

    bedroom = _room_device(hass, init_integration, BEDROOM)
    assert not await async_remove_config_entry_device(hass, init_integration, bedroom)

    fake_hub.devices["results"]["RoomList"].pop(1)
    fake_hub.status["Peripherals"] = [
        p for p in fake_hub.status["Peripherals"] if p.get("PeripheralUID") != UID_BEDROOM
    ]
    await notifications.put({"UpdateTime": {"room": 1788831865}, "Timestamp": 1})
    await settle(hass)

    stop = _scope_entity(hass, init_integration, BUTTON_DOMAIN, BEDROOM, "room_stop")
    assert hass.states.get(stop).state == STATE_UNAVAILABLE
    assert await async_remove_config_entry_device(hass, init_integration, bedroom)
    living = _room_device(hass, init_integration, LIVING_ROOM)
    assert not await async_remove_config_entry_device(hass, init_integration, living)
