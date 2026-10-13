"""Tests for the scenes saved on the hub."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import patch

from homeassistant.components.scene import DOMAIN as SCENE_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.norman.const import DOMAIN, MOVE_ATTEMPTS
from custom_components.norman.coordinator import (
    NormanCoordinator,
    _parse_scenes,
    hub_identifier,
    room_identifier,
)
from custom_components.norman.diagnostics import async_get_config_entry_diagnostics
from custom_components.norman.models import NormanSceneTarget

from .conftest import FakeHub, loaded, settle
from .const import UID_BEDROOM, UID_LIVING

LIVING_ROOM = 1
BEDROOM = 2
GROUP_ID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"


def _target(uid: int, bottom: int, middle: int, module_type: int) -> dict[str, str]:
    """One blind in a saved scene, every value a string as the hub stores it."""
    return {
        "PeripheralUID": str(uid),
        "Position": "0",
        "BottomRailPosition": str(bottom),
        "MiddleRailPosition": str(middle),
        "ModuleType": str(module_type),
        "ModuleDetail": "3",
    }


def _scene(scene_id: str, name: str, *targets: dict[str, str]) -> dict[str, Any]:
    return {
        "SceneID": scene_id,
        "SceneName": name,
        "Icon": "life_8",
        "Color": "",
        "Sorting": "1",
        "PeripheralList": list(targets),
    }


def _save_scenes(fake_hub: FakeHub) -> None:
    """A scene in each room -- both numbered 1, as the hub numbers them per room -- and a
    group of the two."""
    rooms = fake_hub.devices["results"]["RoomList"]
    rooms[0]["SceneList"] = [_scene("1", "Evening", _target(UID_LIVING, 0, 90, 33))]
    rooms[1]["SceneList"] = [_scene("1", "Night", _target(UID_BEDROOM, 100, 0, 32))]
    fake_hub.devices["results"]["SceneGroupList"] = [
        {
            "SceneGroupID": GROUP_ID,
            "SceneGroupName": "Bedtime",
            "Icon": "",
            "Color": "",
            "Sorting": "1",
            "SceneList": [
                {"RoomID": "1", "SceneID": "1", "SceneName": "Evening"},
                {"RoomID": "2", "SceneID": "1"},
            ],
        }
    ]


@pytest.fixture
async def with_scenes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> AsyncGenerator[MockConfigEntry]:
    """The fake hub with two room scenes and a scene group saved on it."""
    _save_scenes(fake_hub)
    async with loaded(hass, mock_config_entry) as entry:
        yield entry


def _entity_id(hass: HomeAssistant, entry: MockConfigEntry, unique_suffix: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        SCENE_DOMAIN, DOMAIN, f"{entry.entry_id}_{unique_suffix}"
    )
    assert entity_id is not None, unique_suffix
    return entity_id


async def _run(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(
        SCENE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


def _stripped(call: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in call.items() if k not in ("Timestamp", "TaskID")}


# --- reading ---------------------------------------------------------------------------------


def test_scenes_are_parsed_from_the_strings_the_hub_stores() -> None:
    """Ids and positions arrive as strings; a scene or group that cannot be run is left out."""
    tree = {
        "results": {
            "RoomList": [
                {
                    "RoomID": "29550",
                    "SceneList": [
                        _scene("1", "Home Assistant", _target(15981, 0, 90, 33)),
                        _scene("x", "No number"),
                        "not a scene",
                    ],
                }
            ],
            "SceneGroupList": [
                {"SceneGroupName": "No id", "SceneList": []},
                {"SceneGroupID": GROUP_ID, "SceneList": [{"RoomID": "29550", "SceneID": "1"}]},
            ],
        }
    }
    scenes, groups = _parse_scenes(tree)

    assert list(scenes) == ["29550_1"]
    scene = scenes["29550_1"]
    assert (scene.room_id, scene.scene_id, scene.name) == (29550, 1, "Home Assistant")
    assert scene.targets == {15981: NormanSceneTarget(bottom=0, middle=90, position=0)}
    assert list(groups) == [GROUP_ID]
    assert groups[GROUP_ID].scene_keys == ["29550_1"]
    assert groups[GROUP_ID].name == "Scene group"


async def test_room_scenes_go_on_their_rooms_and_groups_on_the_hub(
    hass: HomeAssistant, with_scenes: MockConfigEntry
) -> None:
    """A room scene sits with its room's presets; a group spans rooms, so it is the hub's."""
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    expected = {
        f"{LIVING_ROOM}_scene_1": room_identifier(with_scenes, LIVING_ROOM),
        f"{BEDROOM}_scene_1": room_identifier(with_scenes, BEDROOM),
        f"scene_group_{GROUP_ID}": hub_identifier(with_scenes),
    }
    for suffix, identifier in expected.items():
        entity = entities.async_get(_entity_id(hass, with_scenes, suffix))
        assert entity is not None and entity.device_id is not None
        device = devices.async_get(entity.device_id)
        assert device is not None and (DOMAIN, identifier) in device.identifiers, suffix

    evening = hass.states.get(_entity_id(hass, with_scenes, f"{LIVING_ROOM}_scene_1"))
    assert evening.attributes["friendly_name"] == "Living Room Evening"
    group = hass.states.get(_entity_id(hass, with_scenes, f"scene_group_{GROUP_ID}"))
    assert group.attributes["friendly_name"].endswith("Bedtime")


async def test_a_hub_without_scenes_has_none(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    assert not hass.states.async_entity_ids(SCENE_DOMAIN)


# --- running -------------------------------------------------------------------------------


async def test_a_room_scene_runs_in_one_request(
    hass: HomeAssistant, with_scenes: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The app's own request, with the scene's id as a number; each blind is then watched."""
    coordinator: NormanCoordinator = with_scenes.runtime_data
    before = len(fake_hub.control_calls)

    await _run(hass, _entity_id(hass, with_scenes, f"{LIVING_ROOM}_scene_1"))

    sent = [_stripped(call) for call in fake_hub.control_calls[before:]]
    assert sent == [{"RoomID": LIVING_ROOM, "SetToScene": 1}]
    # Recorded where the scene sends the blind, so a command right behind it keeps the
    # scene's other rail, and watched until the blind reports it went.
    assert coordinator.commanded_rails(UID_LIVING) == (0, 90)
    assert UID_LIVING in coordinator._move_watchers
    assert UID_BEDROOM not in coordinator._move_watchers


async def test_a_blind_that_misses_a_scene_is_sent_its_own_position(
    hass: HomeAssistant,
    with_scenes: MockConfigEntry,
    fake_hub: FakeHub,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Not the scene again: the position the scene stored for that one blind."""
    coordinator: NormanCoordinator = with_scenes.runtime_data
    with (
        patch("custom_components.norman.coordinator.MOVE_TIMEOUT", 0),
        patch("custom_components.norman.coordinator.MOVE_REPORT_WAIT", 0),
    ):
        await _run(hass, _entity_id(hass, with_scenes, f"{LIVING_ROOM}_scene_1"))
        if task := coordinator._move_watchers.get(UID_LIVING):
            await task
        await hass.async_block_till_done()

    sent = [_stripped(call) for call in fake_hub.control_calls]
    assert [call for call in sent if "SetToScene" in call] == [
        {"RoomID": LIVING_ROOM, "SetToScene": 1}
    ]
    resent = [call for call in sent if "BottomRailPosition" in call]
    assert resent == [
        {"PeripheralUID": UID_LIVING, "BottomRailPosition": 0, "MiddleRailPosition": 90}
    ] * (MOVE_ATTEMPTS - 1)
    assert f"Living Drape did not move after {MOVE_ATTEMPTS} attempts" in caplog.text


async def test_a_blind_already_at_the_scene_is_left_alone(
    hass: HomeAssistant, with_scenes: MockConfigEntry, fake_hub: FakeHub
) -> None:
    coordinator: NormanCoordinator = with_scenes.runtime_data
    fake_hub.set_position(UID_LIVING, bottom=0, middle=90)
    await coordinator.async_refresh()

    with (
        patch("custom_components.norman.coordinator.MOVE_TIMEOUT", 0),
        patch("custom_components.norman.coordinator.MOVE_REPORT_WAIT", 0),
    ):
        await _run(hass, _entity_id(hass, with_scenes, f"{LIVING_ROOM}_scene_1"))
        if task := coordinator._move_watchers.get(UID_LIVING):
            await task
        await hass.async_block_till_done()

    assert [_stripped(call) for call in fake_hub.control_calls] == [
        {"RoomID": LIVING_ROOM, "SetToScene": 1}
    ]


async def test_a_scene_group_runs_in_one_request_and_watches_every_member(
    hass: HomeAssistant, with_scenes: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """In its one test a group left a member unmoved, so every member blind is watched."""
    coordinator: NormanCoordinator = with_scenes.runtime_data
    before = len(fake_hub.control_calls)

    await _run(hass, _entity_id(hass, with_scenes, f"scene_group_{GROUP_ID}"))

    sent = [_stripped(call) for call in fake_hub.control_calls[before:]]
    assert sent == [{"SceneGroupID": GROUP_ID}], "no RoomID: the group is the scope"
    assert {UID_LIVING, UID_BEDROOM} <= set(coordinator._move_watchers)
    assert coordinator.commanded_rails(UID_LIVING) == (0, 90)
    assert coordinator.commanded_rails(UID_BEDROOM)[0] == 100


async def test_a_scene_the_hub_rejects_names_the_scene(
    hass: HomeAssistant, with_scenes: MockConfigEntry, fake_hub: FakeHub
) -> None:
    coordinator: NormanCoordinator = with_scenes.runtime_data
    fake_hub.control_response = {"Error": 9}
    with pytest.raises(HomeAssistantError, match="Failed to run the scene Evening"):
        await _run(hass, _entity_id(hass, with_scenes, f"{LIVING_ROOM}_scene_1"))
    assert coordinator.commanded_rails(UID_LIVING) is None, "a refused scene is not kept"
    assert UID_LIVING not in coordinator._move_watchers


async def test_a_scene_replaces_a_move_in_flight(
    hass: HomeAssistant, with_scenes: MockConfigEntry
) -> None:
    """Left running, the old move's watch would undo the scene."""
    coordinator: NormanCoordinator = with_scenes.runtime_data
    await coordinator.async_move_blind(UID_LIVING, 70, None)
    move_watch = coordinator._move_watchers[UID_LIVING]

    await _run(hass, _entity_id(hass, with_scenes, f"{LIVING_ROOM}_scene_1"))
    await hass.async_block_till_done()

    assert move_watch.cancelled()
    assert coordinator.commanded_rails(UID_LIVING) == (0, 90)


# --- following the app ----------------------------------------------------------------------


async def test_scenes_follow_the_app(
    hass: HomeAssistant,
    with_scenes: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """A rename, a new scene and a deleted one all follow the next read of the device list."""
    rooms = fake_hub.devices["results"]["RoomList"]
    rooms[0]["SceneList"][0]["SceneName"] = "Movie night"
    rooms[0]["SceneList"].append(_scene("2", "Morning", _target(UID_LIVING, 100, 100, 33)))
    rooms[1]["SceneList"] = []
    await notifications.put({"UpdateTime": {"scene": 1}, "Timestamp": 1})
    await settle(hass)

    renamed = hass.states.get(_entity_id(hass, with_scenes, f"{LIVING_ROOM}_scene_1"))
    assert renamed.attributes["friendly_name"] == "Living Room Movie night"
    assert hass.states.get(_entity_id(hass, with_scenes, f"{LIVING_ROOM}_scene_2"))
    assert (
        er.async_get(hass).async_get_entity_id(
            SCENE_DOMAIN, DOMAIN, f"{with_scenes.entry_id}_{BEDROOM}_scene_1"
        )
        is None
    )


async def test_scenes_outlast_an_unreadable_device_list(
    hass: HomeAssistant,
    with_scenes: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """The hub has gone through spells of failing to read its configuration; the scenes stay."""
    fake_hub.devices = {"status": {"code": 1, "error": "Request process fail."}}
    await notifications.put({"UpdateTime": {"room": 1}, "Timestamp": 1})
    await settle(hass)

    state = hass.states.get(_entity_id(hass, with_scenes, f"{LIVING_ROOM}_scene_1"))
    assert state.state != STATE_UNAVAILABLE


async def test_a_scene_deleted_while_home_assistant_was_off_is_removed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    mock_config_entry.add_to_hass(hass)
    stale = er.async_get(hass).async_get_or_create(
        SCENE_DOMAIN,
        DOMAIN,
        f"{mock_config_entry.entry_id}_{LIVING_ROOM}_scene_5",
        config_entry=mock_config_entry,
    )
    async with loaded(hass, mock_config_entry):
        assert er.async_get(hass).async_get(stale.entity_id) is None


async def test_diagnostics_include_the_scenes(
    hass: HomeAssistant, with_scenes: MockConfigEntry
) -> None:
    diagnostics = await async_get_config_entry_diagnostics(hass, with_scenes)
    assert diagnostics["scenes"]["1_1"]["targets"][str(UID_LIVING)] == {
        "bottom": 0,
        "middle": 90,
        "position": 0,
    }
    assert diagnostics["scene_groups"][GROUP_ID]["scene_keys"] == ["1_1", "2_1"]
