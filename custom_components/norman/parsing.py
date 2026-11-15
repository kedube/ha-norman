"""Turn the hub's payloads into the integration's models.

Pure functions, with no Home Assistant state: the coordinator reads ``GetAllPeripheral`` and
``status`` and hands them here (``parse_devices``, ``parse_scenes``). The hub's payloads are
reverse-engineered and unvalidated, so every reader here skips what it cannot read rather than
raising (``dicts``, ``parse_int``).
"""

from __future__ import annotations

from typing import Any

from .const import (
    DEFAULT_COVER_TYPE,
    MODULE_DETAIL_COVER_TYPES,
    MODULE_TYPE_COVER_TYPES,
    MSD_STACK_SIDES,
    SHUTTER_CLOSED,
)
from .models import (
    NormanDevices,
    NormanPeripheralData,
    NormanScene,
    NormanSceneGroup,
    NormanSceneTarget,
    scene_key,
)


def cover_type(module_type: int | None, module_detail: int | None = None) -> str:
    """The cover type for a ModuleType/ModuleDetail, defaulting when the type is unknown."""
    if module_type is None:
        return DEFAULT_COVER_TYPE
    if module_detail is not None and (module_type, module_detail) in MODULE_DETAIL_COVER_TYPES:
        return MODULE_DETAIL_COVER_TYPES[(module_type, module_detail)]
    return MODULE_TYPE_COVER_TYPES.get(module_type, DEFAULT_COVER_TYPE)


def parse_devices(device_info: dict[str, Any], status_data: dict[str, Any]) -> NormanDevices:
    """Combine ``GetAllPeripheral`` (names, rooms, groups) and ``status`` (positions) by blind.

    A blind that ``status`` reports but the device list does not (or that arrives while the
    device list is unreadable) gets a placeholder named after its id.
    """
    devices: NormanDevices = {}

    # Process device information (names, room, group)
    results = device_info.get("results")
    room_list = results.get("RoomList") if isinstance(results, dict) else None
    for room in dicts(room_list):
        room_id = room.get("RoomID")
        room_name = room.get("RoomName", "")

        for group in dicts(room.get("GroupList")):
            group_id = group.get("GroupID")
            group_name = group.get("GroupName", "")

            for peripheral in dicts(group.get("PeripheralList")):
                peripheral_uid = parse_uid(peripheral.get("PeripheralUID"))
                if peripheral_uid is None:
                    continue

                module_type = parse_int(peripheral.get("ModuleType"))
                module_detail = parse_int(peripheral.get("ModuleDetail"))
                devices[peripheral_uid] = NormanPeripheralData(
                    id=peripheral_uid,
                    name=peripheral.get("PeripheralName") or f"Norman {peripheral_uid}",
                    type=cover_type(module_type, module_detail),
                    room_id=parse_int(room_id),
                    room_name=room_name,
                    group_id=parse_int(group_id),
                    group_name=group_name,
                    module_type=module_type,
                    module_detail=module_detail,
                    stack=parse_stack(peripheral.get("MSDStackType")),
                )

    # Add status information
    for peripheral in dicts(status_data.get("Peripherals")):
        peripheral_uid = parse_uid(peripheral.get("PeripheralUID"))
        if peripheral_uid is None:
            continue

        if peripheral_uid not in devices:
            # Create minimal device if not found in device_info
            module_type = parse_int(peripheral.get("ModuleType"))
            module_detail = parse_int(peripheral.get("ModuleDetail"))
            devices[peripheral_uid] = NormanPeripheralData(
                id=peripheral_uid,
                name=f"Norman {peripheral_uid}",
                type=cover_type(module_type, module_detail),
                room_id=parse_int(peripheral.get("RoomID")),
                group_id=parse_int(peripheral.get("GroupID")),
                module_type=module_type,
                module_detail=module_detail,
            )

        device = devices[peripheral_uid]
        device.bottom_rail_position = parse_position(peripheral.get("BottomRailPosition"))
        device.middle_rail_position = parse_position(peripheral.get("MiddleRailPosition"))
        device.target_bottom_rail_position = parse_position(
            peripheral.get("TargetBottomRailPosition")
        )
        device.target_middle_rail_position = parse_position(
            peripheral.get("TargetMiddleRailPosition")
        )
        device.position = parse_louvers(peripheral.get("Position"))
        device.target_position = parse_louvers(peripheral.get("TargetPosition"))
        # Despite its name the field is a 0-100 level on every hub seen so far
        device.battery_level = parse_position(peripheral.get("BatteryVoltage"))
        device.signal_strength = parse_int(peripheral.get("RssiMean"))
        device.firmware_version = peripheral.get("FirmwareVersion") or None
        device.rf_firmware_version = peripheral.get("RfFirmwareVersion") or None
        device.last_update = peripheral.get("Timestamp")

    return devices


def dicts(raw: Any) -> list[dict[str, Any]]:
    """The dict entries of ``raw``, or an empty list if it is not a list of dicts.

    The hub's payloads are reverse-engineered and unvalidated, so a firmware change (or a
    partial write) can put a string, a null, or a scalar where a list of objects belongs.
    Reaching ``.get()`` on one of those raises AttributeError out of the coordinator's update,
    which Home Assistant catches -- but only by logging a stack trace and marking EVERY
    entity on the hub unavailable, for what may be one malformed record among twenty.
    Skipping what cannot be read keeps the rest of the house working, and matches the
    isinstance guards the coordinator's unknown-field logging applies to the same structures.
    """
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def parse_scenes(
    device_info: dict[str, Any],
) -> tuple[dict[str, NormanScene], dict[str, NormanSceneGroup]]:
    """The scenes and scene groups saved on the hub, from ``GetAllPeripheral``.

    Each room's ``SceneList`` holds its scenes, each sending some of the room's blinds to
    stored positions, and ``SceneGroupList`` holds groups of room scenes. The hub stores
    every value in them as a string, ids and positions included (docs/NORMAN_API.md). A
    scene whose id is not a number is left out, since ``SetToScene`` takes the id as one,
    and so is a group without an id. A missing name is left empty: the scene entity is then
    called what its kind is called, translated.
    """
    results = device_info.get("results")
    if not isinstance(results, dict):
        return {}, {}
    scenes: dict[str, NormanScene] = {}
    for room in dicts(results.get("RoomList")):
        room_id = parse_int(room.get("RoomID"))
        if room_id is None:
            continue
        for raw in dicts(room.get("SceneList")):
            scene_id = parse_int(raw.get("SceneID"))
            if scene_id is None:
                continue
            targets: dict[int, NormanSceneTarget] = {}
            for target in dicts(raw.get("PeripheralList")):
                device_id = parse_uid(target.get("PeripheralUID"))
                if device_id is None:
                    continue
                targets[device_id] = NormanSceneTarget(
                    bottom=parse_position(target.get("BottomRailPosition")),
                    middle=parse_position(target.get("MiddleRailPosition")),
                    position=parse_louvers(target.get("Position")),
                )
            scene = NormanScene(
                room_id=room_id,
                scene_id=scene_id,
                name=str(raw.get("SceneName") or ""),
                targets=targets,
                room_name=str(room.get("RoomName") or ""),
            )
            scenes[scene.key] = scene
    groups: dict[str, NormanSceneGroup] = {}
    for raw in dicts(results.get("SceneGroupList")):
        group_id = raw.get("SceneGroupID")
        if not isinstance(group_id, str) or not group_id:
            continue
        members = []
        for item in dicts(raw.get("SceneList")):
            room_id = parse_int(item.get("RoomID"))
            scene_id = parse_int(item.get("SceneID"))
            if room_id is not None and scene_id is not None:
                members.append(scene_key(room_id, scene_id))
        groups[group_id] = NormanSceneGroup(
            group_id=group_id,
            name=str(raw.get("SceneGroupName") or ""),
            scene_keys=members,
        )
    return scenes, groups


def parse_int(raw: Any) -> int | None:
    """Coerce a value the hub sends as int in one payload and str in another.

    ``bool`` is rejected explicitly: it is an ``int`` subclass, so a stray ``true`` would
    otherwise become 1 and read as a real id or position.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# A PeripheralUID parses exactly like any other hub int; the alias keeps the call sites
# reading as what they are without a second identical implementation to keep in step.
parse_uid = parse_int


def parse_position(raw: Any) -> int | None:
    """Coerce a rail position to an int clamped to 0-100, or None if unusable."""
    value = parse_int(raw)
    return None if value is None else max(0, min(100, value))


def parse_stack(raw: Any) -> str | None:
    """A SmartDrape's stack side from ``MSDStackType``, by name or the app's number."""
    if raw is None:
        return None
    return MSD_STACK_SIDES.get(str(raw).strip().lower())


def parse_louvers(raw: Any) -> int | None:
    """Coerce a Shutter's louver position to an int clamped to 0-7, or None if unusable."""
    value = parse_int(raw)
    return None if value is None else max(0, min(SHUTTER_CLOSED, value))
