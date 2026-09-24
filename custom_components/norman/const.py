"""Constants for the Norman integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "norman"
MANUFACTURER = "Norman"

# Platforms
PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.COVER,
    Platform.NUMBER,
    Platform.SENSOR,
]

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

# The wake sweep: have every blind report in on a timer, the way the Norman app's refresh
# does (hub-wide ReportBatteryLevel, plus a StatusRequest to each wired blind, which the
# hub-wide sweep skips). The poll above only re-reads the hub's *cache*, and the capture of
# 2026-09-18 showed that cache being wrong for a blind that had gone quiet -- middle rails
# the hub reported at 100 read 0 once the blinds reported in. The sweep refreshes the cache
# itself: positions, battery and last-seen become what the blind says now. Off by default;
# the floor keeps a sweep from waking battery blinds more than a few times an hour.
WAKE_DISABLED = 0
DEFAULT_WAKE_INTERVAL = WAKE_DISABLED
MIN_WAKE_INTERVAL = 600
MAX_WAKE_INTERVAL = 86400
SUGGESTED_WAKE_INTERVAL = 3600
CONF_WAKE_INTERVAL = "wake_interval"

# The move watchdog. A blind that ignores a move leaves the hub reporting the old position
# with the new target -- indefinitely, until the blind next reports in (blind 8399 sat at
# middle 0 / target 100 for twelve minutes on 2026-09-18 after answering the move with
# Error 0). So after a move, if the blind has not confirmed the target within MOVE_TIMEOUT,
# it is asked to report in; if the report shows it never moved, the move is sent once more.
# A large shade takes ~30 s to travel end to end, so the timeout leaves a margin over that.
MOVE_TIMEOUT = 60.0
MOVE_REPORT_WAIT = 10.0

# Minimum gap between two `control` sends. The hub has one radio and transmits to blinds
# one at a time: a Best Privacy script that fired all thirteen blinds in the same second
# (diagnostics of 2026-09-21, every request stamped 1790018526) had the hub serialise them
# ~333 ms apart, ack every one with Error 0, store every target -- and eleven of thirteen
# blinds never moved, having missed their transmission. Pacing the sends fixes it. The
# threshold was measured on the reference hub twice, and the two tests disagreed: sending
# the thirteen commands by hand, 1.0-1.2 s still lost a few and 1.3 s got them all; but the
# same house running the scene through a Home Assistant automation kept losing a blind now
# and then at 1.3 s, so the hand test was the easier case. At 1.5 s several consecutive
# whole-house runs dropped nothing, which is where the default sits. 1.4 s may well be
# enough -- the floor was not bisected past 1.3 -- but a tenth of a second per blind buys
# no useful time against a failure mode that is silent when it happens.
# Sends are serialised by a lock and spaced by this gap, so a burst of commands takes
# (n * this) seconds to dispatch rather than colliding. Hubs differ -- more blinds, longer
# range, a different radio environment -- so this is the default for a user-configurable
# option rather than a fixed constant.
DEFAULT_CONTROL_INTERVAL = 1.5
# Bounds offered in the options flow. The floor is the hub's own observed serialisation rate
# (~333 ms), below which pacing cannot help; the ceiling keeps a mistyped value from making a
# whole-house scene take minutes -- at 5 s, thirteen blinds already take over a minute. A
# value outside the range falls back to the default.
MIN_CONTROL_INTERVAL = 0.3
MAX_CONTROL_INTERVAL = 5.0
CONF_CONTROL_INTERVAL = "control_interval"

# Pairing. `{"PairingMode": 5}` on control opens the hub's pairing window; status then
# reports `PairingMode: 5` for ten minutes (22:08:47 to 22:18:48 on 2026-09-18) and 0 after.
# The hub refused it with Error 8 while sweeping its blinds, and with Error 10 in an
# earlier capture. The rest of the app's pairing flow (SearchForPeripheral, room discovery,
# remote pairing) is not modelled: only the window is exposed.
HUB_CMD_PAIRING_MODE = "PairingMode"
HUB_PAIRING_START = 5

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
# Each command produces about four exchanges -- the control call, the notification it
# provokes, and the status reads that follow -- so a scene covering a whole house produces
# four times the blind count, and the commands are paced seconds apart on top of that. At 50
# a thirteen-blind scene overflowed the buffer before the user could download it, hiding the
# very run they were trying to report (2026-09-21). 200 holds a thirteen-blind scene, its
# watchdog retries a minute later, and the routine traffic around both, for a report of
# roughly half a megabyte -- the point past which a diagnostics file stops being something
# a user can attach to an issue.
TRAFFIC_MAX_EXCHANGES = 200
TRAFFIC_BODY_LIMIT = 16 * 1024
# Separate, much larger limit for the last full response per endpoint. Those are kept
# unclipped on purpose -- a truncated GetAllPeripheral is exactly the payload a "please
# support my blind" report needs in full -- so the 16 KB body limit must not apply. They
# still need *a* bound: the endpoint count is fixed and small (five), so the worst case here
# is five times this, and 256 KB comfortably holds the largest real payload (a thirteen-blind
# GetAllPeripheral runs about 55 KB) without letting a malformed multi-megabyte body sit in
# memory for the life of the entry.
TRAFFIC_LATEST_RAW_LIMIT = 256 * 1024

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
# The two "report in" verbs, captured from the app's device & battery status screen on
# 2026-09-18 and confirmed against its network library (DKIoTClient.framework builds both
# with the same value-0 literal it uses for FindTop and Favorite):
#   {"StatusRequest": 0, "PeripheralUID": X}  -- one blind; it answered within 5 s each time
#   {"ReportBatteryLevel": 0}                  -- every battery blind on the hub (the app's
#                                                refresh button); ~30 s for all to report
#   {"ReportBatteryLevel": 0, "RoomID": R}     -- one room; all three blinds in 5 s
# Neither moves anything. A blind that reports in updates its `Timestamp` in `status` and the
# hub pushes a PeripheralList notification for it, which is how the coordinator learns of it.
# See docs/NORMAN_API.md, "Waking a blind".
HUB_CMD_REQUEST_STATUS = "StatusRequest"
HUB_CMD_REPORT_BATTERY = "ReportBatteryLevel"

# Error 2 on a position command. Observed on 2026-09-18: every move sent while the hub was
# sweeping its blinds after three refresh taps (a ~50 s window) answered Error 2, and the
# identical moves a minute later answered 0. A StatusRequest sent mid-sweep still answered 0,
# so it is not a blanket "busy" -- but it is the only code the hub has ever returned for a
# move, and waiting cured it. A move is therefore retried a few times, spaced out, before the
# error reaches the user. Diagnostics record every attempt.
HUB_ERROR_BUSY = 2
HUB_BUSY_RETRIES = 3
HUB_BUSY_RETRY_DELAY = 5.0

# The Norman app lists a blind under "Disconnect" when the hub has not heard from it for
# 86400 s (the constant in its isDisconnectPeripheral:withHub: check). The connection
# binary sensor uses the same rule so Home Assistant and the app agree.
UNRESPONSIVE_AFTER = timedelta(hours=24)

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
# what makes "best privacy" meaningful on a day/night shade -- the middle rail goes fully up,
# stacking away the light-filtering sheer that hangs above it, and the bottom rail fully down,
# drawing the blackout below it across the window. Verified on hardware.
ROOM_COMMANDS: dict[str, dict[str, int]] = {
    "best_privacy": {"Switch": 0},
    "best_view": {"Switch": 1},
    "favorite": {"Favorite": HUB_COMMAND_SETTING},
    # Asks every blind in the room to report in (battery, position, last seen). Nothing
    # moves. Verified room-wide and hub-wide on 2026-09-18.
    "refresh": {HUB_CMD_REPORT_BATTERY: HUB_COMMAND_SETTING},
}

# All four verbs work with no RoomID at all, addressing every blind on the hub. This is what
# the app's "All Rooms" screen sends, captured from it: the bare verb with no scope field.
# None of the three is conditioned on rail count: a per-blind capture of a single-rail shade
# shows the app sending Switch 0, Switch 1 and Favorite to it unchanged.
HUB_WIDE_COMMANDS: frozenset[str] = frozenset(ROOM_COMMANDS)
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_PERIPHERAL_UID = "peripheral_uid"
ATTR_FIELDS = "fields"
