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

HUB_LATITUDE = "42.657582"
HUB_SSID = "HomeNet_IoT"

# Registration echoes hub identity and network details as well as a peripheral summary
HUB_MODEL = "NienMadeHub"
HUB_FIRMWARE = "6.1.25"

REGISTRATION_RESPONSE: dict[str, Any] = {
    "Error": 0,
    "ThingName": HUB_THING_NAME,
    "Model": HUB_MODEL,
    "FirmwareVersion": HUB_FIRMWARE,
    "WiFiSSID": HUB_SSID,
}

_DEVICES: dict[str, Any] = {
    "status": {"code": 0},
    "results": {
        "ThingName": HUB_THING_NAME,
        "CustomDeviceName": "ShadeAuto Hub",
        "TimeZone": "America/New_York",
        "GeoLoc": {"Latitude": HUB_LATITUDE, "Longitude": "-70.676380"},
        "NetworkID": "42076",
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
                                "ModuleType": "33",
                                "ModuleDetail": "3",
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
                                "PeripheralName": "Bedroom Shade",
                                "ModuleType": "32",
                                "ModuleDetail": "2",
                            },
                            {"PeripheralUID": "not-a-number", "PeripheralName": "Junk"},
                            {"PeripheralName": "No UID"},
                        ],
                    }
                ],
            },
        ],
    },
}

_STATUS: dict[str, Any] = {
    "Error": 0,
    "WiFiRSSI": -53,
    "OTA": 0,
    "PairingMode": 0,
    "Peripherals": [
        {
            "PeripheralUID": UID_LIVING,
            "ModuleType": 33,
            "ModuleDetail": 3,
            "BottomRailPosition": 40,
            "MiddleRailPosition": 60,
            "TargetBottomRailPosition": 40,
            "TargetMiddleRailPosition": 60,
            "BatteryVoltage": 73,
            "RssiMean": 34,
            "StallCurrent": 4100,
            "FirmwareVersion": "0.5.3.8",
            "Timestamp": 1700000000,
        },
        {
            "PeripheralUID": UID_BEDROOM,
            "ModuleType": 32,
            "ModuleDetail": 2,
            "BottomRailPosition": 0,
            "MiddleRailPosition": 0,
            "TargetBottomRailPosition": 0,
            "TargetMiddleRailPosition": 0,
            "BatteryVoltage": 11,
            "RssiMean": 0,
            "FirmwareVersion": "4.1.0.4",
            "RfFirmwareVersion": "0.3.20",
        },
        {
            "PeripheralUID": UID_STATUS_ONLY,
            "BottomRailPosition": 100,
            "MiddleRailPosition": 0,
        },
        {"PeripheralUID": None, "BottomRailPosition": 1},
    ],
}


# The two products reported in issue #2, as its get_hub_data output showed them. Neither is
# in the default payloads; tests that want them pair them with FakeHub.add_blind.
UID_ROLLER = 53479
UID_SMARTDRAPE = 13702

ROLLER_DEVICE: dict[str, Any] = {
    "PeripheralUID": str(UID_ROLLER),
    "PeripheralName": "Playroom",
    "ModuleType": "48",
    "ModuleDetail": "1",
}
# Closed by the previous night's Best Privacy. Switch records a middle-rail target of 100 for
# every blind, and this shade has no middle rail to reach it with: it reads 0 throughout.
ROLLER_STATUS: dict[str, Any] = {
    "PeripheralUID": UID_ROLLER,
    "ModuleType": 48,
    "ModuleDetail": 1,
    "BottomRailPosition": 0,
    "MiddleRailPosition": 0,
    "TargetBottomRailPosition": 0,
    "TargetMiddleRailPosition": 100,
    "FirmwareVersion": "2.4.1",
    "Timestamp": 1700000000,
}

SMARTDRAPE_DEVICE: dict[str, Any] = {
    "PeripheralUID": str(UID_SMARTDRAPE),
    "PeripheralName": "Living Room",
    "ModuleType": "80",
    "ModuleDetail": "1",
    "MSDStackType": "left",
}
SMARTDRAPE_STATUS: dict[str, Any] = {
    "ModuleType": 80,
    "PeripheralUID": UID_SMARTDRAPE,
    "ModuleDetail": 1,
    "TargetBottomRailPosition": 0,
    "TargetMiddleRailPosition": 100,
    "BottomRailPosition": 0,
    "MiddleRailPosition": 100,
    "MsdStatus": 0,
    "FirmwareVersion": "0.2.3",
    "Timestamp": 1700000000,
}


# The rest of the Norman app's module table (ShadeAuto 0.8.33). None of these has been seen
# from a hub yet: the records are built from the fields the app's parsers read, so they pin
# the integration to the app rather than to a capture.
UID_SHUTTER = 3001
UID_ROMAN = 3002
UID_SHEER = 3003
UID_ROLLER_MRS2 = 3004
UID_TDBU = 3005


def _device(uid: int, name: str, module_type: int, module_detail: int) -> dict[str, Any]:
    return {
        "PeripheralUID": str(uid),
        "PeripheralName": name,
        "ModuleType": str(module_type),
        "ModuleDetail": str(module_detail),
    }


def _rails(uid: int, module_type: int, module_detail: int, bottom: int, middle: int) -> dict:
    return {
        "PeripheralUID": uid,
        "ModuleType": module_type,
        "ModuleDetail": module_detail,
        "BottomRailPosition": bottom,
        "MiddleRailPosition": middle,
        "TargetBottomRailPosition": bottom,
        "TargetMiddleRailPosition": middle,
        "Timestamp": 1700000000,
    }


# Louvers fully closed: Position 7.
SHUTTER_DEVICE = _device(UID_SHUTTER, "Study Shutter", 1, 1)
SHUTTER_STATUS: dict[str, Any] = {
    "PeripheralUID": UID_SHUTTER,
    "ModuleType": 1,
    "ModuleDetail": 1,
    "Position": 7,
    "TargetPosition": 7,
    "Angle": 0,
    "BatteryVoltage": 80,
    "FirmwareVersion": "1.0.0",
    "Timestamp": 1700000000,
}
ROMAN_DEVICE = _device(UID_ROMAN, "Den Roman", 48, 2)
ROMAN_STATUS = _rails(UID_ROMAN, 48, 2, bottom=60, middle=0)
SHEER_DEVICE = _device(UID_SHEER, "Hall Sheer", 49, 3)
SHEER_STATUS = {**_rails(UID_SHEER, 49, 3, bottom=0, middle=40), "Mrs2Status": 0}
ROLLER_MRS2_DEVICE = _device(UID_ROLLER_MRS2, "Office Roller", 49, 1)
ROLLER_MRS2_STATUS = {**_rails(UID_ROLLER_MRS2, 49, 1, bottom=100, middle=0), "Mrs2Status": 0}
TDBU_DEVICE = _device(UID_TDBU, "Nursery", 32, 4)
TDBU_STATUS = _rails(UID_TDBU, 32, 4, bottom=30, middle=80)

# Every product the app knows beyond the reference hub's two, as (device, status) pairs.
EVERY_NEW_PRODUCT: tuple[tuple[dict[str, Any], dict[str, Any]], ...] = (
    (ROLLER_DEVICE, ROLLER_STATUS),
    (SMARTDRAPE_DEVICE, SMARTDRAPE_STATUS),
    (SHUTTER_DEVICE, SHUTTER_STATUS),
    (ROMAN_DEVICE, ROMAN_STATUS),
    (SHEER_DEVICE, SHEER_STATUS),
    (ROLLER_MRS2_DEVICE, ROLLER_MRS2_STATUS),
    (TDBU_DEVICE, TDBU_STATUS),
)


def devices_payload() -> dict[str, Any]:
    """A fresh copy of the GetAllPeripheral response."""
    return copy.deepcopy(_DEVICES)


def status_payload() -> dict[str, Any]:
    """A fresh copy of the status response."""
    return copy.deepcopy(_STATUS)
