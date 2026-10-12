#!/usr/bin/env python3
"""Compare all blind states around one non-motor Norman hub command.

This runner is intentionally limited to ``StatusRequest``, ``ReportBatteryLevel``, and
per-blind ``RequestModuleInfo``. None is advertised as a motor command. It never sends a
control request without ``--execute``.
Blind and room selections use zero-based indexes from GetAllPeripheral so normal output can
describe an experiment without printing names, room IDs, or peripheral UIDs.

Examples:

    python3 scripts/explore_hub.py Dexatek.local --verb StatusRequest --scope room --room-index 1
    python3 scripts/explore_hub.py Dexatek.local --verb StatusRequest --scope room --room-index 1 --execute
    python3 scripts/explore_hub.py Dexatek.local --verb StatusRequest --scope room --room-index 1 --observe-only
    python3 scripts/explore_hub.py Dexatek.local --verb StatusRequest --scope group --room-index 1 --blind-index 0 --execute
    python3 scripts/explore_hub.py Dexatek.local --verb ReportBatteryLevel --scope blind --room-index 1 --blind-index 0 --execute
    python3 scripts/explore_hub.py Dexatek.local --verb RequestModuleInfo --scope blind --room-index 1 --blind-index 0 --execute

The script records an HTTP acknowledgement separately from actual blind reports. An advanced
peripheral Timestamp means the hub heard from that blind; it does not prove the tested
request caused the report if other clients are active.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any
import urllib.error
import urllib.request

PORT = 10123
TIMEOUT = 10
VERBS = ("StatusRequest", "ReportBatteryLevel", "RequestModuleInfo")
CURRENT_POSITION_FIELDS = (
    "BottomRailPosition",
    "MiddleRailPosition",
    "Position",
)
TARGET_POSITION_FIELDS = (
    "TargetBottomRailPosition",
    "TargetMiddleRailPosition",
    "TargetPosition",
)


def post(host: str, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Send one JSON request and require a JSON object reply."""
    request = urllib.request.Request(  # noqa: S310 - local hub chosen by the operator
        f"http://{host}:{PORT}/NM/v1/{endpoint}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError(f"{endpoint} returned {type(data).__name__}, expected an object")
    return data


def timestamp() -> int:
    """Return the hub's expected seconds-scale timestamp."""
    return int(time.time())


def status(host: str) -> dict[int, dict[str, Any]]:
    """Read status, indexed by UID internally; identifiers are never printed."""
    data = post(host, "status", {"Timestamp": timestamp()})
    if data.get("Error") not in (0, "0", None):
        raise ValueError(f"status returned Error {data['Error']}")
    blinds: dict[int, dict[str, Any]] = {}
    for item in data.get("Peripherals", []):
        if not isinstance(item, dict):
            continue
        try:
            blinds[int(item["PeripheralUID"])] = item
        except (KeyError, TypeError, ValueError):
            continue
    return blinds


def room_blinds(room: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the room's group tree in its hub-provided order."""
    return [
        blind
        for group in room.get("GroupList", [])
        for blind in group.get("PeripheralList", [])
        if isinstance(blind, dict) and blind.get("PeripheralUID") is not None
    ]


def compare(
    before: dict[int, dict[str, Any]],
    after: dict[int, dict[str, Any]],
    targets: set[int],
) -> dict[str, int]:
    """Summarize all status changes without exposing identifiers."""
    reported: set[int] = set()
    moved: set[int] = set()
    target_changed: set[int] = set()
    for uid in before.keys() & after.keys():
        old, new = before[uid], after[uid]
        try:
            if int(new.get("Timestamp", 0)) > int(old.get("Timestamp", 0)):
                reported.add(uid)
        except (TypeError, ValueError):
            pass
        if any(old.get(key) != new.get(key) for key in CURRENT_POSITION_FIELDS):
            moved.add(uid)
        if any(old.get(key) != new.get(key) for key in TARGET_POSITION_FIELDS):
            target_changed.add(uid)
    return {
        "reported_in_scope": len(reported & targets),
        "reported_outside_scope": len(reported - targets),
        "position_changed_in_scope": len(moved & targets),
        "position_changed_outside_scope": len(moved - targets),
        "target_changed_in_scope": len(target_changed & targets),
        "target_changed_outside_scope": len(target_changed - targets),
        "missing_from_status": len(before.keys() - after.keys()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="hub IP address or hostname")
    parser.add_argument("--verb", required=True, choices=VERBS)
    parser.add_argument("--scope", required=True, choices=("blind", "group", "room", "hub"))
    parser.add_argument("--room-index", type=int, help="zero-based index in GetAllPeripheral")
    parser.add_argument("--blind-index", type=int, help="zero-based index within the room")
    parser.add_argument("--check", type=int, action="append", help="seconds after send; repeatable")
    parser.add_argument(
        "--execute", action="store_true", help="send the selected non-motor command"
    )
    parser.add_argument(
        "--observe-only", action="store_true", help="measure background reports without a command"
    )
    args = parser.parse_args()

    if args.execute and args.observe_only:
        parser.error("--execute and --observe-only cannot be combined")
    if args.verb == "RequestModuleInfo" and args.scope != "blind":
        parser.error("RequestModuleInfo is limited to one PeripheralUID")

    if args.scope != "hub" and args.room_index is None:
        parser.error("--room-index is required for blind, group, and room scope")
    if args.scope in ("blind", "group") and args.blind_index is None:
        parser.error("--blind-index is required for blind and group scope")
    if args.scope not in ("blind", "group") and args.blind_index is not None:
        parser.error("--blind-index is only valid for blind and group scope")
    if args.scope == "hub" and args.room_index is not None:
        parser.error("--room-index is not valid for hub scope")
    checks = args.check or [10, 30]
    if any(check <= 0 for check in checks) or checks != sorted(set(checks)):
        parser.error("--check values must be positive, unique, and increasing")

    try:
        registration = post(args.host, "registration", {"Timestamp": timestamp()})
        if registration.get("Error") not in (0, "0", None):
            raise ValueError(f"registration returned Error {registration['Error']}")
        tree = post(
            args.host,
            "GetAllPeripheral",
            {
                "ThingName": registration["ThingName"],
                "TaskID": 1,
                "Timestamp": timestamp(),
            },
        )
        tree_status = tree.get("status", {})
        if isinstance(tree_status, dict) and tree_status.get("code") not in (0, "0", None):
            raise ValueError(f"GetAllPeripheral returned code {tree_status['code']}")
        result = tree.get("results", {})
        if not isinstance(result, dict):
            raise ValueError("GetAllPeripheral has no results object")
        rooms = result.get("RoomList", [])
        if not isinstance(rooms, list):
            raise ValueError("GetAllPeripheral has no RoomList")
        before = status(args.host)

        address: dict[str, int] = {}
        if args.scope == "hub":
            targets = set(before)
        else:
            if args.room_index < 0 or args.room_index >= len(rooms):
                parser.error(f"--room-index must be between 0 and {len(rooms) - 1}")
            room = rooms[args.room_index]
            blinds = room_blinds(room)
            if args.scope == "room":
                targets = {int(blind["PeripheralUID"]) for blind in blinds}
                address["RoomID"] = int(room["RoomID"])
            else:
                if args.blind_index < 0 or args.blind_index >= len(blinds):
                    parser.error(f"--blind-index must be between 0 and {len(blinds) - 1}")
                uid = int(blinds[args.blind_index]["PeripheralUID"])
                targets = {uid}
                if args.scope == "blind":
                    address["PeripheralUID"] = uid
                else:
                    group = next(
                        group
                        for group in room["GroupList"]
                        if any(
                            int(blind["PeripheralUID"]) == uid
                            for blind in group.get("PeripheralList", [])
                        )
                    )
                    targets = {
                        int(blind["PeripheralUID"])
                        for blind in group.get("PeripheralList", [])
                        if blind.get("PeripheralUID") is not None
                    }
                    address.update(
                        {"RoomID": int(room["RoomID"]), "GroupID": int(group["GroupID"])}
                    )
        if not targets or not targets <= set(before):
            raise ValueError("selected blinds are absent from status; refusing the experiment")
        if args.verb == "RequestModuleInfo":
            advertised = next(
                (
                    blind.get("RequestModuleInfo")
                    for blind in registration.get("Peripherals", [])
                    if int(blind.get("PeripheralUID", -1)) in targets
                ),
                None,
            )
            if advertised != 0:
                raise ValueError("selected blind does not advertise RequestModuleInfo: 0")

        print(
            json.dumps(
                {
                    "firmware": registration.get("FirmwareVersion"),
                    "blind_count": len(before),
                    "room_count": len(rooms),
                    "verb": args.verb,
                    "scope": args.scope,
                    "room_index": args.room_index,
                    "blind_index": args.blind_index,
                    "target_count": len(targets),
                    "mode": "execute"
                    if args.execute
                    else "observe"
                    if args.observe_only
                    else "dry_run",
                }
            ),
            flush=True,
        )
        if not args.execute and not args.observe_only:
            return 0

        sent_at = time.monotonic()
        if args.execute:
            reply = post(
                args.host,
                "control",
                {
                    "Timestamp": timestamp(),
                    "TaskID": int(time.time() * 1000) % 10000,
                    args.verb: 0,
                    **address,
                },
            )
            print(
                json.dumps(
                    {
                        "ack_error": reply.get("Error"),
                        "echoed_verb": reply.get(args.verb),
                        "response_keys": sorted(
                            set(reply)
                            - {
                                "ThingName",
                                "PeripheralUID",
                                "RoomID",
                                "GroupID",
                                "Timestamp",
                                "RequestTimestamp",
                                "TaskID",
                            }
                        ),
                    }
                ),
                flush=True,
            )
        else:
            print(json.dumps({"ack_error": None, "note": "no control request sent"}), flush=True)
        for check in checks:
            time.sleep(max(0, sent_at + check - time.monotonic()))
            after = status(args.host)
            print(
                json.dumps({"after_seconds": check, **compare(before, after, targets)}), flush=True
            )
    except (OSError, ValueError, KeyError, urllib.error.URLError) as err:
        parser.exit(1, f"experiment failed: {err}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
