# Norman Hub local API reference

This is the contributor reference for the hub protocol the integration speaks. It is
reverse-engineered from observing a Norman Hub on a local network; nothing here comes from
vendor documentation or vendor code. Field names are reproduced exactly as the hub sends them.
Where a field's meaning is inferred rather than confirmed, the text says so.

Read this before changing anything in [`api.py`](../custom_components/norman/api.py) or
[`coordinator.py`](../custom_components/norman/coordinator.py).

## Contents

- [Transport](#transport)
- [Discovery (mDNS)](#discovery-mdns)
- [Endpoints](#endpoints)
  - [POST /NM/v1/registration](#post-nmv1registration)
  - [POST /NM/v1/GetAllPeripheral](#post-nmv1getallperipheral)
  - [POST /NM/v1/status](#post-nmv1status)
  - [POST /NM/v1/control](#post-nmv1control)
  - [Control verbs](#control-verbs)
  - [Room-wide and hub-wide control](#room-wide-and-hub-wide-control)
  - [POST /NM/v1/notification](#post-nmv1notification)
- [The complete endpoint surface](#the-complete-endpoint-surface)
- [Configuration endpoints used by the app](#configuration-endpoints-used-by-the-app)
- [Observed fields](#observed-fields)
- [Error conventions](#error-conventions)
- [How the integration uses the endpoints](#how-the-integration-uses-the-endpoints)
- [Capturing traffic](#capturing-traffic)
- [Security notes](#security-notes)

## Transport

| Property | Value |
|---|---|
| Scheme | plain `http://` (no TLS) |
| Port | `10123` (fixed; `HUB_PORT` in `const.py`) |
| Method | every endpoint is `POST` with a JSON body |
| Authentication | none |
| Timeouts | 10 s per request (`REQUEST_TIMEOUT`); the notification stream has no total timeout |

Every request body carries `"Timestamp": <unix seconds>`. Command-style requests also carry
`"TaskID": <int>`; the hub appears to echo it and the integration simply uses an incrementing
counter modulo 10000. No response has ever been observed to depend on the value.

The Norman app (`User-Agent: SmartShutter/0.8.32`) speaks exactly this protocol to the hub when
it is on the same network; a packet capture of the app is how the [control verbs](#control-verbs)
and the [discovery](#discovery-mdns) record below were confirmed.

## Discovery (mDNS)

The hub announces itself with multicast DNS, which is what the integration's zeroconf discovery
(`"zeroconf": ["_nien_made._tcp.local."]` in the manifest) listens for:

| Record | Value |
|---|---|
| Service type | `_nien_made._tcp.local.` |
| Instance | `NienMadeLocal._nien_made._tcp.local.` |
| Target host | `Dexatek.local.` (Dexatek is the hub's ODM), port `10123`, A and AAAA records |
| TXT | none |

Because there is no TXT record, the announcement carries no identity: the config flow calls
`registration` on the discovered address to get the `ThingName`, and only then decides whether
the hub is new (offer it) or known (refresh its stored address). The app itself resolves the
instance name with a unicast SRV query rather than browsing.

## Endpoints

### POST /NM/v1/registration

Announces the client and returns the hub's identity. Called once per client before
`GetAllPeripheral` (which needs the `ThingName`), and by the config flow to validate the
address the user typed.

Request:

```json
{"Timestamp": 1700000000}
```

Response:

```json
{"Error": 0, "ThingName": "NormanHub-ABC123"}
```

`ThingName` is a stable identifier for the hub (it looks like an AWS IoT thing name). The
config flow uses it as the config entry's unique id so the same hub is recognised even when its
IP address changes; if it is missing the host is used instead.

The real reply is much larger than the example: hub-level `Model`, `FirmwareVersion`,
`FirmwareId`, `FirmwareCode`, `DeviceType`, `WiFiSSID`, `PairingMode`, `CleanPairing`,
`StatusRequest`, `ReportBatteryLevel`, `OTA`, `TotalSegment`/`Segment`, and a `Peripherals`
list that, per blind, carries every **verb the blind supports with the value to send** (see
[Control verbs](#control-verbs)) alongside placeholder state (`RssiMean: 255`,
`StallCurrent: 65535`, `BatteryVoltage: 100`, empty `FirmwareVersion`). The app sends an empty
body (`{}`) when it re-registers; the hub answers the same way.

### POST /NM/v1/GetAllPeripheral

Returns the hub's room / group / peripheral tree with names and module types. Requires the
`ThingName` from registration.

Request:

```json
{"ThingName": "NormanHub-ABC123", "TaskID": 17, "Timestamp": 1700000000}
```

Response (trimmed to the fields the integration reads):

```json
{
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
                "PeripheralUID": 1001,
                "PeripheralName": "Living Drape",
                "ModuleType": 7,
                "ModuleDetail": 2
              }
            ]
          }
        ]
      }
    ]
  }
}
```

Notes:

- `PeripheralUID` has been seen both as an integer and as a numeric string; the integration
  coerces it to `int` so the two payloads line up. Entries with a missing or non-numeric UID
  are skipped.
- `ModuleType` / `ModuleDetail` identify the kind of covering; see
  [Cover types](#cover-types) for the two values mapped so far. Contributions that record
  which values correspond to which products are welcome (open an issue with a diagnostics
  export).
- Errors for this endpoint are reported under `status.code` / `status.error`, not `Error`
  (see [Error conventions](#error-conventions)).

### POST /NM/v1/status

Returns the live state of every peripheral. This is the lightweight call the integration
makes on every refresh.

Request:

```json
{"Timestamp": 1700000000}
```

Response:

```json
{
  "Error": 0,
  "Peripherals": [
    {
      "PeripheralUID": 1001,
      "BottomRailPosition": 40,
      "MiddleRailPosition": 60,
      "TargetBottomRailPosition": 40,
      "TargetMiddleRailPosition": 60,
      "BatteryVoltage": 73,
      "RssiMean": 34,
      "FirmwareVersion": "0.5.3.8",
      "Timestamp": 1700000000
    }
  ]
}
```

| Field | Meaning | Exposed as |
|---|---|---|
| `BottomRailPosition` | 0 = closed, 100 = open | cover `current_position` |
| `MiddleRailPosition` | 0–100; the second fabric on a day/night shade, the top rail on top-down/bottom-up, the vane tilt on SmartDrape | the **Middle rail** cover's position, and the primary cover's `current_tilt_position` |
| `TargetBottomRailPosition` | where the bottom rail is heading | `target_position` attribute |
| `TargetMiddleRailPosition` | where the middle rail is heading | `target_tilt` attribute |
| `BatteryVoltage` | a **percentage**, 0–100, despite the field name (see [Observed fields](#observed-fields)) | **Battery** sensor |
| `RssiMean` | radio quality, unitless (0 or 34 seen) | opt-in **Signal strength** sensor |
| `FirmwareVersion` | blind firmware | device `sw_version` and the opt-in **Firmware version** sensor, except when `RfFirmwareVersion` is also present, which is shown instead (only single-rail blinds have been seen to report both) |
| `Timestamp` | last update; epoch seconds (as a number, or a string on some payloads) | **Last seen** sensor |

Positions are coerced to integers and clamped to 0–100; an unusable value becomes `None`,
which the entity reports as an unknown position. A peripheral that appears here but not in
`GetAllPeripheral` still gets a full set of entities (covers, sliders, buttons, sensors), named `Norman <uid>`, with its cover type taken from `ModuleType`.

### POST /NM/v1/control

Moves a covering. The call **always takes both rails**; there is no way to move one and leave
the other untouched, so the integration fills the untouched rail with its current target
(falling back to its current position, then to 100). It works in both directions: moving the
bottom rail sends the middle rail's current target back with it, and moving the middle rail —
whether through the **Middle rail** cover, the middle-rail slider, or a tilt command — sends the
bottom rail's back. A capture therefore always shows both fields, even when the user touched
only one.

Request:

```json
{
  "PeripheralUID": 1001,
  "Timestamp": 1700000000,
  "TaskID": 18,
  "BottomRailPosition": 100,
  "MiddleRailPosition": 60
}
```

Response:

```json
{"Error": 0}
```

The hub acknowledges immediately, echoing the fields it accepted (`PeripheralUID`, both
positions, `TaskID`, `RequestTimestamp`) plus its own millisecond `Timestamp`. The blind then
moves and the new position arrives through the notification stream and the next `status` call.

The app also sends `RoomID` and `GroupID` with every move; the hub accepts moves without them,
so the integration does not send them. For a single-rail blind (`ModuleType` 32) the app sends
`BottomRailPosition` only and the hub's echo reports `MiddleRailPosition: 0`; the integration
sends both rails for every type, which the hub accepts equally.

An **empty** body is accepted too: the app POSTs `/control` with no body every 5 seconds while
open and gets `{"Error": 0, "TaskID": 0, "RequestTimestamp": 0, "Timestamp": ...}` back. It
looks like a keep-alive or "is the hub there" probe; the integration has no need for it.

### Control verbs

Everything other than a position move is a **verb field** on the same `control` call, one per
request, alongside `PeripheralUID`, `Timestamp`, and `TaskID`. The value is `170` (0xAA) for
verbs that make the motor do something now, and `0` for verbs that store or clear a setting.
The hub echoes the verb back in its reply with `"Error": 0`; a rejected verb has not been
observed. All of the following were captured from the Norman app:

| Verb | Value | What the app does with it |
|---|---|---|
| `MotorStop` | 170 | Stop the motor where it is. **Used** by the integration for `stop_cover` and `stop_cover_tilt` (one motor, one stop). |
| `SetMotorToTopLimit` | 170 | Run to the stored top limit. The app repeats it several times per second while the button is held. **Used** (Run to top limit button). |
| `SetMotorToBottomLimit` | 170 | Run to the stored bottom limit; same repeat pattern. **Used** (Run to bottom limit button). |
| `MotorFineTuneToUp` | 170 | Jog up a small step (limit-setting screen). **Used** (Jog up button). |
| `MotorFineTuneToDown` | 170 | Jog down a small step. **Used** (Jog down button). |
| `FindTop` | 0 | Sent when opening the limit-setting screen and again when leaving it; presumably re-syncs the motor to its top. |
| `SetTopLimit` / `SetBottomLimit` | 0 | Store the current position as that limit. |
| `CleanTopLimit` / `CleanBottomLimit` | 0 | Clear the stored limit (the app sends this right before setting a new one). |
| `Calibration` | 0 | Run the motor's calibration. |

```json
{"PeripheralUID": 58850, "Timestamp": 1788828922, "TaskID": 43620, "MotorStop": 170}
```

```json
{"PeripheralUID": 58850, "MotorStop": 170, "Error": 0, "TaskID": 43620, "RequestTimestamp": 1788828922, "Timestamp": 1788828922530}
```

The registration reply lists more verbs per blind than the app was seen to use (`Favorite`,
`MotorSpeedAdjust`, `ReverseMotorDirection`, `Switch`, `RailSpacing…`, `SmartDialSwitch`,
`CleanRfPairing`, `CleanAllPosition`, `CleanErrorCode`, `RequestModuleInfo`, `ConfigToScene`,
`SetToScene`, `SetMiddleLimit`, `CleanMiddleLimit`, `StopSensorSwitch`). Their values there
(`170` or `259` for motor verbs, `0`/`1` for settings) are consistent with the same convention,
but they are unconfirmed. `norman.send_hub_command` can send any of them; the limit, direction,
and clean verbs change how a blind behaves and may need a physical recalibration to undo.

### Room-wide and hub-wide control

Two verbs work **without** `PeripheralUID`, addressing every blind in a room or on the hub in
one request. Both were captured from the app and confirmed in the following `status` reads,
where every target in scope changed:

| Body (plus `Timestamp`, `TaskID`) | Effect |
|---|---|
| `{"Switch": 1}` | open every blind on the hub (both rails to 100) |
| `{"Switch": 0}` | close every blind on the hub |
| `{"Switch": 1, "RoomID": 29550}` / `{"Switch": 0, "RoomID": 29550}` | open / close every blind in the room |
| `{"Favorite": 0, "RoomID": 24973}` | send every blind in the room to its stored favorite position |

The hub echoes `Switch` / `Favorite` and `RoomID`. `Switch` and `Favorite` are also listed per
blind in the registration reply, so the per-blind forms `{"Switch": 1, "PeripheralUID": …}`
and `{"Favorite": 0, "PeripheralUID": …}` are the obvious extrapolation, but neither has been
captured. The integration sends the per-blind `Favorite` form from the Favorite position
button (unverified until someone reports it moving a blind) and leaves `Switch` alone: Home
Assistant's own cover groups and areas already fan out open/close.

### POST /NM/v1/notification

A long-poll. The hub keeps the response open and writes a bare JSON object every time a
peripheral's state changes (including changes made with a remote or the Norman app). There is
no framing between objects: no newline, no length prefix.

Request: empty body.

Response stream, as observed:

```text
{"Error":0}{"PeripheralList":[{"PeripheralUID":1001, ...}]}{"PeripheralList":[...]}...
```

- The first object is an acknowledgement without `PeripheralList`; the integration skips any
  object that lacks that key.
- The integration does **not** read positions out of the notification. It treats each one as
  a wake-up and calls `status`, which is authoritative and covers every peripheral.
- Besides state changes the stream carries **structure changes** made in the app:
  `{"UpdateTime": {"room": <s>}, "Timestamp": <ms>}` after a room is renamed or re-iconed,
  `{"UpdateTime": {"peripheral": …}}` after a blind is renamed, `{"UpdateTime": {"device": …}}`
  after the hub is renamed, and `{"UpdateTime": {"schedule": …}}` after a schedule is added or
  deleted. The integration re-reads `GetAllPeripheral` on the first three (so names follow the
  app) and treats the fourth as a plain refresh.
- The app opens this stream at launch as well, alongside its own `status` polls after every
  command.
- Long-lived connections have been seen to go quiet, so the integration closes and reopens the
  stream every `NOTIF_MAX_DURATION` (300 s). Because the hub gives no explicit end-of-stream
  signal, an unexpected EOF is treated as a disconnect and retried after `RECONNECT_INTERVAL`
  (15 s). On every reconnect the device list is re-read, which is how newly paired blinds
  appear without a restart.
- Parsing is done by `JsonStreamParser` in `api.py`: an incremental UTF-8 decoder (a multi-byte
  character can be split across two reads) feeding a scanner that tracks string and escape
  state, so braces inside names and nested objects do not break framing. Unparseable segments
  are logged at debug level and skipped; an object that never closes is discarded once the
  buffer exceeds `NOTIF_MAX_BUFFER` (64 KiB).

## The complete endpoint surface

Eleven endpoints are known: the five the integration uses, and six more the app uses or a
probe found. The hub answers **HTTP 404** for any other path, which makes probing reliable —
`scripts/probe_hub_endpoints.py` sends an identity-only body to a list of candidate names and
reports which answer (it refuses, by name, to send anything that could write). Running it
against the reference hub with 43 candidates found exactly two undocumented endpoints, both
scene reads, so the surface below is believed complete for firmware 6.1.25.

```
registration  GetAllPeripheral  status  control  notification      (the integration)
GetAllSchedule  AddSchedule  DeleteSchedule                        (schedules, app only)
UpdateRoom  UpdatePeripheral  UpdateDeviceInfo  GetDeviceInfo      (names, app only)
GetAllScene  GetAllSceneGroup                                      (found by probing)
```

## Configuration endpoints used by the app

These were captured from the Norman app or found by probing, and are documented for
completeness; the integration does not call any of them. All take `ThingName`, `Timestamp`, and `TaskID` in the body and
answer in the `{"status": {"code", "error"}, "results": {…}}` shape, echoing what was written.
Each write is followed by an `UpdateTime` notification (above) and the app re-reads the
matching list.

| Endpoint | Body (besides the common fields) | Effect |
|---|---|---|
| `GetAllSchedule` | — | `results.ScheduleList`: every schedule stored **on the hub**. |
| `GetAllScene` | — | `results.RoomList`: `[{RoomID, SceneList}]`, one entry per room. Empty on every room of the reference hub, so a scene's shape is still unknown. Found by probing, not seen from the app. |
| `GetAllSceneGroup` | — | `results.SceneGroupList`, empty on the reference hub. Found by probing. |
| `AddSchedule` | `Conditions`, `Executions`, `ScheduleEnable` | Creates a schedule; the reply carries the hub-assigned `ScheduleID` (a UUID). |
| `DeleteSchedule` | `ScheduleID` | Removes one. |
| `UpdateRoom` | `RoomList: [{RoomID, RoomName, Icon, Color, Sorting}]` (all strings) | Renames / restyles rooms. |
| `UpdatePeripheral` | `RoomID`, `GroupID`, `PeripheralList: [{PeripheralUID, PeripheralName, Sorting}]` (strings) | Renames blinds. |
| `UpdateDeviceInfo` | `CustomDeviceName` | Renames the hub. |
| `GetDeviceInfo` | — | `results.CustomDeviceName` (and `ThingName`). |

A schedule as the hub stores it:

```json
{
  "ScheduleID": "08f08a0d-cbfe-4db0-b418-094f99bcf883",
  "Conditions": {"Days": [1, 2, 3, 4, 5], "SunriseOffsetMin": 15},
  "Executions": {"RoomIdList": [{"RoomID": "24973", "Switch": "1"}]},
  "ScheduleEnable": true
}
```

`Conditions` is `Days` (1 = Monday … 7 = Sunday) plus one of `Time: [hour, minute]`,
`SunriseOffsetMin`, or `SunsetOffsetMin` (the hub knows its location from `GeoLoc`).
`Executions` is any of `RoomIdList` (room + `Switch` open/close), `SceneIdList`, and
`SceneGroupIdList`; the app sends the unused lists empty. Schedules are deliberately not
exposed by the integration: Home Assistant automations cover the same ground with far more
flexibility, and a schedule on the hub would fight them.

## Observed fields

Everything below comes from captures of a real hub (`NienMadeHub`, firmware 6.1.25, 13 blinds
of two types). Only the fields marked **used** are read by the integration; the rest are kept
verbatim in the diagnostics capture and are candidates for future features.

This list is also **executable**: `KNOWN_HUB_FIELDS` and `KNOWN_PERIPHERAL_FIELDS` in
`const.py` hold the same names, and the coordinator logs (at debug level, once per name) any
field the hub sends that is missing from them. So a firmware update that adds a field, or a
product nobody has captured, announces itself in the log rather than being silently dropped.
`tests/test_repo_consistency.py` checks the two lists against each other, so a field
documented here must be catalogued and vice versa.

### Hub level

| Field | Where | Example | Used |
|---|---|---|---|
| `Model` | registration | `NienMadeHub` | **used** (hub device model) |
| `FirmwareVersion` | registration | `6.1.25` | **used** (hub device firmware) |
| `ThingName` | registration, GetAllPeripheral | hub identity | **used** (config entry unique id); redacted |
| `CustomDeviceName` | GetAllPeripheral | `ShadeAuto Hub` | **used** (hub device name); redacted |
| `WiFiRSSI` | status | `-53` | **used** (Wi-Fi signal sensor) |
| `WiFiSSID` | registration | | **used** (Wi-Fi network sensor); redacted in diagnostics |
| `TimeZone` | GetAllPeripheral | `America/New_York` | **used** (time zone sensor); redacted in diagnostics |
| `GeoLoc` (`Latitude`/`Longitude`), `NetworkID` | registration, GetAllPeripheral | | not used; redacted |
| `OTA`, `PairingMode`, `DeviceType`, `FirmwareId`, `FirmwareCode`, `TotalSegment`/`Segment`, `CleanPairing`, `StatusRequest`, `ReportBatteryLevel` | registration, status | `0`, `4`, `48` | not used. `PairingMode` reads `4` in registration and `0` in status; `OTA` was `1` in one registration reply while status said `0`. |
| `SceneGroupList`, rooms' `SceneList` | GetAllPeripheral | `[]` | not used |
| rooms' `Icon`, `Color`, `Sorting`; groups' `Sorting` | GetAllPeripheral | `"3"` | not used |
| `RequestTimestamp` / `Timestamp` | every reply | seconds / milliseconds | not used |

### Per peripheral

| Field | Where | Example | Used |
|---|---|---|---|
| `PeripheralUID`, `PeripheralName`, `RoomID`, `GroupID` | GetAllPeripheral (strings), status (ints) | | **used**. `PeripheralUID` is also exposed as the device's serial number: no other per-blind identifier appears in any payload, so it is the best candidate for the app's "Serial Number" |
| `ModuleType` / `ModuleDetail` | both | `33`/`3`, `32`/`2` | **used** (cover type; see below) |
| `BottomRailPosition`, `MiddleRailPosition`, `Target…` | status | 0–100 | **used** |
| `BatteryVoltage` | status | `5` … `100` | **used** as a **percentage** (battery sensor) |
| `RssiMean` | status | `0`, `34` | **used** (signal-strength sensor, unitless) |
| `FirmwareVersion` | status | `0.5.3.8`, `4.1.0.4` | **used**; on type 33 it is the version the app shows |
| `RfFirmwareVersion` | status (type 32 only) | `0.3.20` | **used**: this is the version the Norman app shows for single-rail blinds (Den_1: app 0.3.20, `FirmwareVersion` 4.1.0.4), so it takes precedence for the device's version |
| `Timestamp` | status | epoch seconds | **used** (last-seen sensor) |
| `PacketReceiveRate` | status | `0` | not used |
| `StallCurrent` | status (type 33 only) | `4100` | not used |
| `Switch`, `MotorStop`, `Favorite`, `Calibration`, `ConfigToScene`, `SetToScene`, `SetMotorToTopLimit`, `SetMotorToBottomLimit`, `MotorFineTuneToUp`, `MotorFineTuneToDown`, `SetTopLimit`, `CleanTopLimit`, `SetBottomLimit`, `CleanBottomLimit`, `SetMiddleLimit`, `CleanMiddleLimit`, `MotorSpeedAdjust`, `ReverseMotorDirection`, `StopSensorSwitch`, `FindTop`, `RailSpacing`, `RailSpacingDefault`, `RailSpacingIncrease`, `RailSpacingDecrease`, `SmartDialSwitch`, `CleanRfPairing`, `CleanAllPosition`, `CleanErrorCode`, `RequestModuleInfo` | registration only | `170`, `259`, `0`, `1` | The per-blind **command vocabulary**; the value shown is the one to send. `MotorStop` is **used** (stop). See [Control verbs](#control-verbs) for the ones confirmed from the app. The list differs by type: only type 33 advertises `StallCurrent`, `CleanRfPairing`, `CleanAllPosition`, `MotorSpeedAdjust`, `ReverseMotorDirection`, `FindTop`, and the `RailSpacing` family (`RailSpacing: 10`); only type 32 advertises `RfFirmwareVersion`, `SetMiddleLimit`/`CleanMiddleLimit`, `CleanErrorCode`, and `SmartDialSwitch`. Both list `Switch`, `Favorite`, `Calibration`, `ConfigToScene`/`SetToScene` (`287`), `CleanAllScene`, `StopSensorSwitch`, and the top/bottom limit and fine-tune verbs. |

### Cover types

| `ModuleType`/`ModuleDetail` | Firmware seen | Behaviour | Integration |
|---|---|---|---|
| 33 / 3 | 0.5.3.x, has `StallCurrent` | middle rail tracks 0–100 (50 when half); the reference hub's are day/night cellular shades | primary cover (bottom rail, middle as tilt) + Middle rail cover; two position sliders |
| 32 / 2 | 4.1.0.4 + `RfFirmwareVersion` | middle rail always 0, target 0 | single-rail cover, position only; one position slider |
| other | | | two-rail by default, warning logged once |

### Notification stream, as observed

- First object: `{"Error": "Success."}` — note the **string** value; `_raise_on_error_code`
  accepts it.
- Then, per change: `{"Status": 1788827049448, "PeripheralList": [58850]}` — `PeripheralList`
  is a list of **ids**, not objects, and `Status` is a millisecond timestamp.
- A control call produced a notification within the same second and another when the move
  finished, about eight seconds later. Each hub call answered in 3–11 ms.

## Error conventions

The hub uses two different shapes:

| Endpoint | Success | Failure |
|---|---|---|
| registration, status, control | `"Error": 0` | `"Error": <non-zero int>` |
| GetAllPeripheral | `"status": {"code": 0}` | `"status": {"code": <non-zero>, "error": "<message>"}` |

`_raise_on_error_code` accepts four spellings of success on the `Error` endpoints: `0`, the
string `"0"`, an absent or `null` field, and any string beginning with `succ`
(case-insensitive). Be equally permissive in new code — the hub demonstrably uses more than one
spelling, and this list is only what has been observed.

The notification stream is the exception: its opening `{"Error": "Success."}` acknowledgement
never reaches `_raise_on_error_code` at all, because the listener yields only objects carrying
`PeripheralList` or `UpdateTime` and drops everything else. An error *on that endpoint* surfaces
as a `NormanConnectionError` (HTTP >= 400, or the hub closing the stream), not a
`NormanApiError` — the one place the rule below does not hold.

The client maps everything to two exceptions:

- `NormanConnectionError` — the hub could not be reached: connection refused, DNS failure,
  or a timeout. Note that aiohttp raises a bare `TimeoutError` for its total timeout, which is
  **not** a `ClientError`; `_async_request` catches it explicitly.
- `NormanApiError` — the hub answered, but with an HTTP error status, a body that is not
  JSON, a body that is not a JSON object, or a non-zero error code.

Both derive from `HomeAssistantError`, so they can be raised straight out of a service call
after the entity wraps them with context.

## How the integration uses the endpoints

```text
setup ──► registration ──► GetAllPeripheral ──► status ──► entities created ──► card served
                                                   ▲
notification stream ──(PeripheralList, or UpdateTime: schedule)──┘  (refresh)
notification stream ──(UpdateTime: room / peripheral / device)──► GetAllPeripheral + status
                                                                  (names pushed to devices)
periodic reconnect (300 s) / disconnect (15 s) ──► GetAllPeripheral + status
cover / number action ──► control (both positions) ──► status (request_refresh)
cover stop ──► control (MotorStop) ──► status (request_refresh)
button press ──► control (Favorite / jog / run-to-limit verb) ──► status (request_refresh)
get_hub_data action ──► GetAllPeripheral + status (redacted, returned as the response)
send_hub_command action ──► control (caller's fields) ──► status
mDNS announcement ──► config flow ──► registration (identity) ──► offer, or refresh the address
```

The hub's **MAC address is not in any payload**: no endpoint reports it. It is resolved from
the local ARP table when the entry loads, so it is only available when Home Assistant shares a
network segment with the hub. Do not go looking for it in a capture.

The rail sliders (`number`) and the covers share one code path, so both send the same
both-rails `control` call. The five buttons are the only place the integration sends a
[control verb](#control-verbs) other than `MotorStop` without the user reaching for
`send_hub_command`.

There is no polling interval. If the notification stream cannot be established at all the
integration still works for commands, and each command's follow-up `status` call keeps the
state fresh, but external changes (remote, app) will not be reflected until the stream comes
back. The listener logs one error when the stream drops and one info line when it recovers.

**`GetAllPeripheral` is cached; `status` is not.** A refresh re-reads `status` every time but
only calls `GetAllPeripheral` when the cached device list has been invalidated, which happens
on the first refresh, on any listener reconnect (deliberate cycle or dropped stream), and on an
`UpdateTime` notification naming `room`, `peripheral`, or `device`. That split matters when
reading a capture: `status` is the hot path and carries positions and battery, while the
heavier structural payload — names, rooms, module types, firmware — is fetched rarely. A
`schedule` update does not invalidate anything, since schedules are not modelled.

All requests are issued sequentially on one session; the integration never has two hub requests
in flight, and it takes no lock, so nothing here says whether the hub tolerates concurrency.

## Capturing traffic

`NormanApiClient.traffic` is a `TrafficRecorder`: every request/response pair and every
notification-stream chunk is appended to a ring buffer (50 entries, bodies clipped to 16 KiB)
before any parsing happens, and the last complete response per endpoint is kept whole in
`latest_raw`. The diagnostics export publishes it as `hub_traffic`, redacted: the host, the config entry's
unique id, and every key in `SENSITIVE_HUB_KEYS` (`ThingName`, `GeoLoc`, `Latitude`,
`Longitude`, `WiFiSSID`, `NetworkID`, `TimeZone`, `CustomDeviceName`) are removed by key inside
JSON bodies, and the host and `ThingName` are additionally replaced by value anywhere they
appear in text. The export also carries a `frontend` block with the card's expected and
registered versions. The `norman.get_hub_data` action returns live `GetAllPeripheral` and
`status` payloads for the same purpose, with the same sensitive keys removed. When someone reports a new blind type, ask for either
of these; the parsed model in `NormanPeripheralData` drops unknown fields and is not enough.

Debug logging (`custom_components.norman.api: debug`) prints every exchange with the body
truncated to 500 characters.

## Security notes

- The protocol has no authentication and no encryption. Anyone on the same network segment can
  move blinds and read state. Keep the hub on a trusted LAN or VLAN; the integration cannot
  add security the device does not have.
- The integration only ever connects *to* the hub; it opens no listening ports.
- The host is validated as an IP address or hostname before use and the URL is built with
  `yarl` (so a value like `hub/../x` or `hub:80` cannot redirect requests elsewhere).
- Diagnostics exports redact the hub address, the entry's unique id, and the hub's identity,
  location, Wi-Fi SSID, time zone and custom name (`SENSITIVE_HUB_KEYS`). The hub's own name is
  redacted; **blind** names and positions are not, because they are what bug reports need.
