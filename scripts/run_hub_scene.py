#!/usr/bin/env python3
"""Inspect or run one hub-stored room scene, checking actual shade positions.

Room and scene indexes are zero-based in GetAllScene order. Normal output contains no
room names, scene names, hub identity, or peripheral identifiers. The default is a dry
run; --execute sends one /control request that may move every shade in the saved scene.

    python3 scripts/run_hub_scene.py Dexatek.local --room-index 2 --scene-index 0
    python3 scripts/run_hub_scene.py Dexatek.local --room-index 2 --scene-index 0 --execute
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from explore_hub import post, status, timestamp

POSITION_FIELDS = ("Position", "BottomRailPosition", "MiddleRailPosition")


def expected_positions(target: dict[str, Any], current: dict[str, Any]) -> dict[str, int]:
    """Use only saved position fields the module actually reports in status."""
    expected: dict[str, int] = {}
    for field in POSITION_FIELDS:
        if field in target and field in current:
            expected[field] = int(target[field])
    if not expected:
        raise ValueError("A scene target has no position field comparable with status")
    return expected


def at_target(current: dict[str, Any], expected: dict[str, int]) -> bool:
    """Allow small rail rounding errors; Shutter Position is discrete."""
    for field, value in expected.items():
        tolerance = 0 if field == "Position" else 3
        if abs(int(current[field]) - value) > tolerance:
            return False
    return True


def changed_outside(
    before: dict[int, dict[str, Any]], after: dict[int, dict[str, Any]], target_uids: set[int]
) -> int:
    """Count non-scene blinds whose reported actual positions changed."""
    return sum(
        any(old.get(field) != after[uid].get(field) for field in POSITION_FIELDS)
        for uid, old in before.items()
        if uid not in target_uids and uid in after
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="hub hostname or IP address")
    parser.add_argument("--room-index", type=int, required=True)
    parser.add_argument("--scene-index", type=int, required=True)
    parser.add_argument("--execute", action="store_true", help="run the scene on the hub")
    parser.add_argument("--timeout", type=int, default=90, help="seconds to check actual positions")
    args = parser.parse_args()
    if args.room_index < 0 or args.scene_index < 0 or args.timeout < 1:
        parser.error("indexes must be nonnegative and timeout must be positive")

    registration = post(args.host, "registration", {"Timestamp": timestamp()})
    if registration.get("Error") not in (0, "0"):
        raise ValueError("registration failed")
    reply = post(
        args.host,
        "GetAllScene",
        {
            "ThingName": registration["ThingName"],
            "TaskID": 1,
            "Timestamp": timestamp(),
        },
    )
    if reply.get("status", {}).get("code") not in (0, "0"):
        raise ValueError("GetAllScene failed")
    rooms = reply["results"]["RoomList"]
    if args.room_index >= len(rooms):
        parser.error(f"--room-index must be less than {len(rooms)}")
    room = rooms[args.room_index]
    scenes = room.get("SceneList", [])
    if args.scene_index >= len(scenes):
        parser.error(f"--scene-index must be less than {len(scenes)} in this room")
    scene = scenes[args.scene_index]
    before = status(args.host)
    targets = scene.get("PeripheralList", [])
    if not targets:
        raise ValueError("Selected scene has no shade targets")
    expected: dict[int, dict[str, int]] = {}
    for target in targets:
        uid = int(target["PeripheralUID"])
        if uid not in before or uid in expected:
            raise ValueError("Scene target is missing or duplicated in status")
        expected[uid] = expected_positions(target, before[uid])

    print(
        json.dumps(
            {
                "phase": "baseline",
                "firmware": registration.get("FirmwareVersion"),
                "room_index": args.room_index,
                "scene_index": args.scene_index,
                "scene_targets": len(expected),
                "already_at_target": sum(
                    at_target(before[uid], positions) for uid, positions in expected.items()
                ),
                "all_blinds": len(before),
            }
        )
    )
    if not args.execute:
        return 0

    response = post(
        args.host,
        "control",
        {
            "RoomID": int(room["RoomID"]),
            "SetToScene": int(scene["SceneID"]),
            "Timestamp": timestamp(),
            "TaskID": int(time.time()) % 10000,
        },
    )
    print(json.dumps({"phase": "acknowledgment", "error": response.get("Error")}))
    if response.get("Error") not in (0, "0"):
        return 1

    started = time.monotonic()
    while True:
        current = status(args.host)
        reached = sum(
            uid in current and at_target(current[uid], positions)
            for uid, positions in expected.items()
        )
        elapsed = round(time.monotonic() - started, 1)
        print(
            json.dumps(
                {
                    "phase": "check",
                    "elapsed_seconds": elapsed,
                    "reached": reached,
                    "scene_targets": len(expected),
                    "outside_position_changes": changed_outside(before, current, set(expected)),
                }
            )
        )
        if reached == len(expected):
            return 0
        if elapsed >= args.timeout:
            return 1
        time.sleep(min(5, args.timeout - elapsed))


if __name__ == "__main__":
    raise SystemExit(main())
