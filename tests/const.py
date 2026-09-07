"""Constants and payload builders for Norman tests.

The payloads mirror what a real hub returns (see docs/NORMAN_API.md), trimmed to the
fields the integration reads.
"""

from __future__ import annotations

import copy
from typing import Any

from homeassistant.const import CONF_HOST

HUB_HOST = "192.168.1.50"
HUB_URL = f"http://{HUB_HOST}:10123"
HUB_THING_NAME = "NormanHub-ABC123"

MOCK_CONFIG: dict[str, str] = {CONF_HOST: HUB_HOST}

# Peripheral ids used throughout the suite
UID_LIVING = 1001
UID_BEDROOM = 1002
UID_STATUS_ONLY = 1003  # reported by /status but absent from GetAllPeripheral

_DEVICES: dict[str, Any] = {
    "status": {"code": 0},
    "results": {
        "RoomList": [
            {
                "RoomID": 1,
                "RoomName": "Living Room",
                "GroupList": [
                    {
                        "GroupID": 10,
                        "GroupName": "Windows",
                        "PeripheralList": [
                            {
                                "PeripheralUID": UID_LIVING,
                                "PeripheralName": "Living Drape",
                                "ModuleType": 7,
                                "ModuleDetail": 2,
                            }
                        ],
                    }
                ],
            },
            {
                "RoomID": 2,
                "RoomName": "Bedroom",
                "GroupList": [
                    {
                        "GroupID": 20,
                        "GroupName": "",
                        "PeripheralList": [
                            {
                                "PeripheralUID": str(UID_BEDROOM),
                                "PeripheralName": "Bedroom Drape",
                                "ModuleType": 7,
                            },
                            {"PeripheralUID": "not-a-number", "PeripheralName": "Junk"},
                            {"PeripheralName": "No UID"},
                        ],
                    }
                ],
            },
        ]
    },
}

_STATUS: dict[str, Any] = {
    "Error": 0,
    "Peripherals": [
        {
            "PeripheralUID": UID_LIVING,
            "BottomRailPosition": 40,
            "MiddleRailPosition": 60,
            "TargetBottomRailPosition": 40,
            "TargetMiddleRailPosition": 60,
            "BatteryVoltage": 12.4,
            "FirmwareVersion": "1.2.3",
            "Timestamp": "1700000000",
        },
        {
            "PeripheralUID": UID_BEDROOM,
            "BottomRailPosition": 0,
            "MiddleRailPosition": 100,
            "TargetBottomRailPosition": 0,
            "TargetMiddleRailPosition": 100,
            "BatteryVoltage": 11.9,
            "FirmwareVersion": "1.2.3",
        },
        {
            "PeripheralUID": UID_STATUS_ONLY,
            "BottomRailPosition": 100,
            "MiddleRailPosition": 0,
        },
        {"PeripheralUID": None, "BottomRailPosition": 1},
    ],
}


def devices_payload() -> dict[str, Any]:
    """A fresh copy of the GetAllPeripheral response."""
    return copy.deepcopy(_DEVICES)


def status_payload() -> dict[str, Any]:
    """A fresh copy of the status response."""
    return copy.deepcopy(_STATUS)
