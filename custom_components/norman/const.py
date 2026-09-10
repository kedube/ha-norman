"""Constants for the Norman integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "norman"
MANUFACTURER = "Norman"

# Platforms
PLATFORMS = [Platform.BUTTON, Platform.COVER, Platform.NUMBER, Platform.SENSOR]

# The hub speaks plain HTTP on a fixed port on the local network; there is no TLS and no
# authentication in the vendor protocol (see docs/NORMAN_API.md).
HUB_PORT = 10123

# Per-request timeout for the short command/status endpoints, in seconds.
REQUEST_TIMEOUT = 10

# How often to re-read `status` even when the hub has pushed nothing.
#
# Off by default. The hub pushes state changes over the notification long-poll, which is
# the primary update path and is enough for most installs; polling only earns its keep when
# a battery blind's radio sleeps. The hub then stops hearing from it (the Norman app shows
# "Disconnect") and sends no notification, so the cached position can go stale while the
# blind is in fact reachable -- a command still wakes it and works. A stale position makes
# `is_closed` answer about the past, which silently breaks automations that check state
# before acting ("close it if it isn't closed"). Anyone seeing that can switch polling on;
# `status` is the hub's lightweight, uncached call (docs/NORMAN_API.md), so the cost is one
# small local request per interval.
POLL_DISABLED = 0
DEFAULT_POLL_INTERVAL = POLL_DISABLED
# Bounds offered in the options flow, either side of POLL_DISABLED. The floor keeps a
# misconfigured entry from hammering a hub that answers `status` synchronously; the ceiling
# is the point past which a poll stops being a useful safety net. A value outside this range
# (other than 0) falls back to the default.
MIN_POLL_INTERVAL = 10
MAX_POLL_INTERVAL = 3600
# What the options form offers when polling has never been configured, so that switching it
# on is one click rather than a guess.
SUGGESTED_POLL_INTERVAL = 60
CONF_POLL_INTERVAL = "poll_interval"

# Seconds to wait after the notification stream drops before reconnecting.
RECONNECT_INTERVAL = 15
# Max seconds to hold a single notification long-poll open before cycling it. The hub
# silently stops delivering events on very old connections, so they are recycled.
NOTIF_MAX_DURATION = 300

# Bytes read per chunk from the notification stream.
READ_CHUNK_SIZE = 1024
# Upper bound on buffered, not-yet-parsed notification bytes. A hub that never closes a JSON
# object would otherwise grow the buffer without limit.
NOTIF_MAX_BUFFER = 64 * 1024

# Raw hub traffic kept for diagnostics: number of exchanges and max bytes per body.
TRAFFIC_MAX_EXCHANGES = 50
TRAFFIC_BODY_LIMIT = 16 * 1024

# Keys the hub sends that identify the home or network rather than a blind. Redacted from
# diagnostics and from the get_hub_data response wherever they appear, including inside raw
# bodies. Seen in real captures: GeoLoc carries the hub's latitude/longitude; WiFiSSID the
# network name; ThingName and NetworkID identify the hub; CustomDeviceName is user-chosen.
# Every field the hub has been observed to send, so anything outside these sets is new (a
# firmware change, or a product nobody has captured). Logged once each at debug level by the
# coordinator; see docs/NORMAN_API.md, "Observed fields". Membership here does NOT mean the
# integration reads a field, only that its existence is accounted for.
KNOWN_HUB_FIELDS = frozenset(
    {
        # identity and firmware
        "ThingName",
        "Model",
        "FirmwareVersion",
        "FirmwareId",
        "FirmwareCode",
        "DeviceType",
        "CustomDeviceName",
        # network and location
        "WiFiSSID",
        "WiFiRSSI",
        "NetworkID",
        "TimeZone",
        "GeoLoc",
        # state and housekeeping
        "OTA",
        "PairingMode",
        "CleanPairing",
        "StatusRequest",
        "ReportBatteryLevel",
        "TotalSegment",
        "Segment",
        "Error",
        "Timestamp",
        "RequestTimestamp",
        "TaskID",
        # nested inside GeoLoc / RoomList entries
        "Latitude",
        "Longitude",
        "Icon",
        "Color",
        # payload containers
        "Peripherals",
        "RoomList",
        "SceneGroupList",
        "SceneList",
        "ScheduleList",
        "status",
        "results",
    }
)

KNOWN_PERIPHERAL_FIELDS = frozenset(
    {
        # identity and placement
        "PeripheralUID",
        "PeripheralName",
        "RoomID",
        "GroupID",
        "GroupList",
        "PeripheralList",
        "RoomName",
        "GroupName",
        "Sorting",
        "ModuleType",
        "ModuleDetail",
        # state
        "BottomRailPosition",
        "MiddleRailPosition",
        "TargetBottomRailPosition",
        "TargetMiddleRailPosition",
        "BatteryVoltage",
        "RssiMean",
        "PacketReceiveRate",
        "StallCurrent",
        "FirmwareVersion",
        "RfFirmwareVersion",
        "Timestamp",
        # the command vocabulary advertised by registration
        "RequestModuleInfo",
        "Switch",
        "MotorStop",
        "Favorite",
        "Calibration",
        "ConfigToScene",
        "SetToScene",
        "CleanAllScene",
        "SetMotorToTopLimit",
        "SetMotorToBottomLimit",
        "MotorFineTuneToUp",
        "MotorFineTuneToDown",
        "SetTopLimit",
        "CleanTopLimit",
        "SetBottomLimit",
        "CleanBottomLimit",
        "SetMiddleLimit",
        "CleanMiddleLimit",
        "CleanRfPairing",
        "CleanAllPosition",
        "CleanErrorCode",
        "MotorSpeedAdjust",
        "ReverseMotorDirection",
        "StopSensorSwitch",
        "SmartDialSwitch",
        "FindTop",
        "RailSpacing",
        "RailSpacingDefault",
        "RailSpacingIncrease",
        "RailSpacingDecrease",
    }
)

SENSITIVE_HUB_KEYS = frozenset(
    {
        "ThingName",
        "GeoLoc",
        "Latitude",
        "Longitude",
        "WiFiSSID",
        "NetworkID",
        "TimeZone",
        "CustomDeviceName",
    }
)

# Cover types, derived from the hub's ModuleType. Observed on real hubs:
#   33 (ModuleDetail 3): two rails, the middle rail tracks 0-100 -> position + tilt
#   32 (ModuleDetail 2): middle rail always 0 -> single rail, position only
# Unknown types fall back to two-rail -- the safer default, since a two-rail blind driven as
# single-rail would leave its middle rail unreachable -- and are logged once so the owner can
# report the hub payload. Nothing here is product-specific: the codes describe how many rails
# the motor has, not which Norman covering it is.
# Motor verbs are fields on the control call; the Norman app sends 170 (0xAA) as the value
# of every "do it now" verb (MotorStop, MotorFineTuneToUp/Down, SetMotorToTopLimit, ...) and 0
# for configuration verbs (FindTop, SetTopLimit, Calibration, ...). Captured from the app.
HUB_COMMAND_TRIGGER = 170
HUB_COMMAND_SETTING = 0
HUB_CMD_STOP = "MotorStop"
HUB_CMD_JOG_UP = "MotorFineTuneToUp"
HUB_CMD_JOG_DOWN = "MotorFineTuneToDown"
# SetMotorToTopLimit / SetMotorToBottomLimit deliberately have no constant here. They are
# hold-to-run signals, not one-shot moves (the app repeats them every ~0.3 s while its
# control is held), so nothing in the integration sends them; send_hub_command takes the
# raw verb name for anyone who wants to. See docs/NORMAN_API.md, "Control verbs".
# Confirmed in both forms against a real hub: {"Favorite": 0, "PeripheralUID": ...} moves one
# blind to its stored favorite, and the RoomID form moves a whole room. Note the hub answers
# Error 0 and keeps reporting the old position while the blind travels (~30 s on a large
# shade), so a command that looks ignored may simply still be running.
HUB_CMD_FAVORITE = "Favorite"
# Switch is the open/close verb behind the app's Best View / Best Privacy buttons. It is
# addressed by RoomID (a room), RoomID + GroupID (one blind), or nothing at all (the whole
# hub) -- never by PeripheralUID alone. It sets BOTH rails: close is bottom 0 / middle 100.
HUB_CMD_SWITCH = "Switch"
HUB_SWITCH_OPEN = 1
HUB_SWITCH_CLOSE = 0

COVER_TYPE_TWO_RAIL = "two_rail"
COVER_TYPE_SINGLE_RAIL = "single_rail"
MODULE_TYPE_COVER_TYPES: dict[int, str] = {
    32: COVER_TYPE_SINGLE_RAIL,
    33: COVER_TYPE_TWO_RAIL,
}
DEFAULT_COVER_TYPE = COVER_TYPE_TWO_RAIL

ATTR_TARGET_POSITION = "target_position"
ATTR_TARGET_TILT = "target_tilt"
ATTR_STEP = "step"

SERVICE_NUDGE_POSITION = "nudge_position"
SERVICE_NUDGE_TILT = "nudge_tilt"
SERVICE_GET_HUB_DATA = "get_hub_data"
SERVICE_SEND_HUB_COMMAND = "send_hub_command"
SERVICE_ROOM_COMMAND = "room_command"
ATTR_ROOM = "room"
ATTR_COMMAND = "command"

# The room-wide commands the Norman app's room screen offers, and the control fields each
# sends. Captured from the app (docs/NORMAN_API.md, "Room-wide and hub-wide control"):
# Switch sets BOTH rails to a fixed pair: 0 -> bottom 0 / middle 100, 1 -> both 100. That is
# what makes "best privacy" meaningful on a day/night shade -- the bottom fabric closes while
# the sheer middle opens fully, so the room is private but still lit. Verified on hardware.
ROOM_COMMANDS: dict[str, dict[str, int]] = {
    "best_privacy": {"Switch": 0},
    "best_view": {"Switch": 1},
    "favorite": {"Favorite": HUB_COMMAND_SETTING},
}

# All three verbs work with no RoomID at all, addressing every blind on the hub. This is what
# the app's "All Rooms" screen sends, captured from it: the bare verb with no scope field.
# None of the three is conditioned on rail count: a per-blind capture of a single-rail shade
# shows the app sending Switch 0, Switch 1 and Favorite to it unchanged.
HUB_WIDE_COMMANDS: frozenset[str] = frozenset(ROOM_COMMANDS)
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_PERIPHERAL_UID = "peripheral_uid"
ATTR_FIELDS = "fields"
