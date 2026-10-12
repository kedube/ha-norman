# Norman Hub local API reference

This is the contributor reference for the hub protocol the integration speaks. It is
reverse-engineered from direct hub tests, app traffic, and inspection of the installed
ShadeAuto app's network library. Field names are reproduced exactly as the hub sends them.
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
  - [Waking a blind](#waking-a-blind)
  - [Pairing mode](#pairing-mode)
  - [POST /NM/v1/notification](#post-nmv1notification)
- [Known endpoint surface](#known-endpoint-surface)
- [Configuration endpoints](#configuration-endpoints)
- [Open questions and coverage workflow](#open-questions-and-coverage-workflow)
  - [Direct hub capability tests](#direct-hub-capability-tests)
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
it is on the same network; app traffic established many [control verbs](#control-verbs),
while direct hub tests established additional scopes and the [discovery](#discovery-mdns)
record was checked with mDNS browsing.

## Discovery (mDNS)

The hub announces itself with multicast DNS, which is what the integration's zeroconf discovery
(`"zeroconf": ["_nien_made._tcp.local."]` in the manifest) listens for:

| Record | Value |
|---|---|
| Service type | `_nien_made._tcp.local.` |
| Instance | `NienMadeLocal._nien_made._tcp.local.` |
| Target host | `Dexatek.local.` (Dexatek is the hub's ODM), port `10123`, A and AAAA records |
| TXT | `thing_name`, `multicast_group`, `multicast_port` on the hub checked 2026-10-11; an earlier capture had no TXT fields |

The config flow calls `registration` on the discovered address to validate it and get the
`ThingName`, whether or not a TXT identity is present. It then decides whether the hub is new
(offer it) or known (refresh its stored address). The app itself resolves the instance name
with a unicast SRV query rather than browsing.

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
  [Cover types](#cover-types) for the values mapped so far. Contributions that record
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
| `MiddleRailPosition` | 0–100; the second fabric on a day/night shade, the top rail on top-down/bottom-up, the vanes on a PerfectSheer (0 closed, 100 open) or a SmartDrape (seven stops, open at 50); always 0 on a single-rail blind | the **Middle rail** cover's position, and the primary cover's `current_tilt_position` |
| `TargetBottomRailPosition` | where the bottom rail is heading | `target_position` attribute |
| `TargetMiddleRailPosition` | where the middle rail is heading | `target_tilt` attribute |
| `Position`, `TargetPosition` | a Shutter's louvers, 0–7, and where they are heading | the Shutter's `current_tilt_position` / `target_tilt`, and `louver_position` |
| `BatteryVoltage` | a **percentage**, 0–100, despite the field name (see [Observed fields](#observed-fields)) | **Battery** sensor |
| `RssiMean` | radio quality, unitless (0 or 34 seen) | opt-in **Signal strength** sensor |
| `FirmwareVersion` | blind firmware | device `sw_version` and the opt-in **Firmware version** sensor, except when `RfFirmwareVersion` is also present, which is shown instead (only single-rail blinds have been seen to report both) |
| `Timestamp` | last update; epoch seconds (as a number, or a string on some payloads) | **Last seen** sensor |

Positions are coerced to integers and clamped to 0–100; an unusable value becomes `None`,
which the entity reports as an unknown position. A peripheral that appears here but not in
`GetAllPeripheral` still gets a full set of entities (covers, sliders, buttons, sensors), named `Norman <uid>`, with its cover type taken from `ModuleType`.

### POST /NM/v1/control

Moves a covering. The hub accepts either rail on its own — the Norman app's group screen sends
`MiddleRailPosition` alone, and its per-blind screen a single-rail blind's
`BottomRailPosition` alone — but the integration **always sends both**, filling the untouched
rail with where it is heading: the last move sent from here while that move is in flight,
otherwise the hub's target (falling back to its current position, then to 100). The move is
recorded before it waits its turn to be sent, so two commands in a row — or at once, as a scene
sends them — keep each other's rail instead of each sending the other back to where it was;
the hub's target would still show the blind before both. That is what
lets it carry a two-rail shade's other rail along in the same request (below). It works in both
directions: moving the bottom rail sends the middle rail's current target back with it, and
moving the middle rail — whether through the **Middle rail** cover, the middle-rail slider, or
a tilt command — sends the bottom rail's back. A capture therefore always shows both fields,
even when the user touched only one.

A **Shutter** (`ModuleType` 1) has no rails. Its louvers are one field, `Position` 0–7 (7 shut,
3 horizontal, 0 turned fully the other way), sent alone: `{"PeripheralUID": …, "Position": 3}`.
That is what the app's network library builds for a Shutter; it has not been sent to a real
one from here. The app's library can also send `Position1` / `Position2` (and read their
`Target…` counterparts), a pair for split-panel shutters that no product in the app uses yet.

On a two-rail blind the middle rail hangs above the bottom rail, so the rail sent back is
**carried along** when the move would pass it: raising the bottom rail above the middle rail
sends the middle rail up to the same position, and lowering the middle rail below the bottom
rail sends the bottom rail down with it. Both go in the one request, so the hub is never
asked for a shape the blind cannot make. Single-rail blinds are unaffected.

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

**Room-wide position moves work too.** On 2026-10-10, a single `/control` request with
`RoomID` and both rail fields, but no `PeripheralUID` or `GroupID`, moved both two-rail blinds
in the Office room. `{"RoomID": 29550, "BottomRailPosition": 25, "MiddleRailPosition": 100}`
sent both bottom rails from 0 to 25 (one reported 24); a second request with bottom 25 and
middle 75 brought both blinds to 25/75. A third request with bottom 0 and middle 100 restored
both to their starting positions. All three replies had `Error: 0`, and no blind outside Office
changed position during the first move. The hub exposed each target immediately, while actual
positions arrived about 10 seconds later. This room-wide form has not been seen from the
ShadeAuto app; it was tested directly against the hub.

**Hub-wide position moves also work without any address field.** On 2026-10-10,
`{"BottomRailPosition": 0, "MiddleRailPosition": 100}` with no `RoomID`, `GroupID`, or
`PeripheralUID` returned `Error: 0` and set the bottom-rail target to 0 on all three
previously open single-rail Den shades. Two reached 0; the third reported stopping at 18.
Separate per-blind moves returned all three to their original 100, and a final `status` read
matched the starting positions of all 13 blinds on the hub. The partial move means the reply
and target alone are not proof that every blind reaches the requested position. The ShadeAuto
app has not been seen sending this hub-wide position form either.

`GroupID` is the blind's **address within its room** — the button (1, 2, 4, ...) a paired
Norman remote uses for it. The same value repeats across rooms, so it is only meaningful with
`RoomID`, and the pair `(RoomID, GroupID)` is **unique per blind** (verified across every blind
on the reference hub).

That pair is how the `Switch` and `Favorite` verbs address a single blind. They are **not**
addressed by `PeripheralUID`: sending `{"Switch": 1, "RoomID": 29550, "GroupID": 1}` moved only
the group-1 blind in that room and left group 2 untouched. The app sends `PeripheralUID`
alongside as well, but the room/group pair is what selects the target — which is why an earlier
test of `{"Favorite": 0, "PeripheralUID": …}` alone appeared to do nothing.

The app also sends `RoomID` and `GroupID` with every move; the hub accepts moves without them,
so the integration does not send them with one blind's move (a `RoomID` without
`PeripheralUID` is the room-wide move above). For a single-rail blind (`ModuleType` 32) the app sends
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
| `SetMotorToTopLimit` | 170 | Drive toward the stored top limit **while held**: the app sends it every ~0.3 s for as long as its OPEN control is pressed, only inside the Shade Limit Setting screen. Not a one-shot move, so it has no button; `send_hub_command` can send it. |
| `SetMotorToBottomLimit` | 170 | The same, downward. Also hold-to-run, also no button. |
| `MotorFineTuneToUp` | 170 | Jog up one small step. Sent as discrete taps (the capture shows single sends as well as short bursts as the user nudges a rail), unlike the run-to-limit verbs' steady ~0.3 s repeat while held — which is why this one suits a button. The app uses `PeripheralUID`; direct tests also confirmed room and hub scope. **Used** (Jog up button). |
| `MotorFineTuneToDown` | 170 | Jog down a small step. **Used** (Jog down button). |
| `FindTop` | 0 | Sent when opening the limit-setting screen and again when leaving it; presumably re-syncs the motor to its top. |
| `SetTopLimit` / `SetBottomLimit` | 0 | Store the current position as that limit. |
| `CleanTopLimit` / `CleanBottomLimit` | 0 | Clear the stored limit (the app sends this right before setting a new one). |
| `Calibration` | 0 | Run the motor's calibration. |
| `StatusRequest` | 0 | Ask **one blind** to report in (with `PeripheralUID`). Nothing moves; the blind's `Timestamp` in `status` moves and the hub pushes a `PeripheralList` notification for it. Answered within 5 s on every try. **Used** (Request status button). See [Waking a blind](#waking-a-blind). |
| `ReportBatteryLevel` | 0 | Ask every blind on the hub (no scope field) or in a room (`RoomID`) to report in. The app's refresh button. Despite the name the answer carries position and last-seen too. **Used** (Refresh blinds button, `room_command: refresh`). |

```json
{"PeripheralUID": 58850, "Timestamp": 1788828922, "TaskID": 43620, "MotorStop": 170}
```

```json
{"PeripheralUID": 58850, "MotorStop": 170, "Error": 0, "TaskID": 43620, "RequestTimestamp": 1788828922, "Timestamp": 1788828922530}
```

The registration reply lists more verbs per blind than the app was seen to use (`Favorite`,
`MotorSpeedAdjust`, `ReverseMotorDirection`, `Switch`, `RailSpacing…`, `SmartDialSwitch`,
`CleanRfPairing`, `CleanAllPosition`, `CleanErrorCode`, `ConfigToScene`,
`SetToScene`, `SetMiddleLimit`, `CleanMiddleLimit`, `StopSensorSwitch`). Their values there
(`170` or `259` for motor verbs, `0`/`1` for settings) are consistent with the same convention,
but they are unconfirmed. `norman.send_hub_command` can send any of them; the limit, direction,
and clean verbs change how a blind behaves and may need a physical recalibration to undo.

`RequestModuleInfo: 0` is advertised by both module types 32 and 33 and was tested directly
with `PeripheralUID` on one of each on 2026-10-11. Both requests returned `Error: 0` and echoed
the verb, with no extra module-information fields in the synchronous reply. Each addressed
blind reported a newer `Timestamp` within 10 s; no other blind reported and no position or
target changed during the watch. It therefore works as a per-blind report request on these
products, but what additional module information it may retrieve is still unknown.

### Room-wide and hub-wide control

The `Switch` and `Favorite` verbs work **without** `PeripheralUID`, addressing every blind in
a room or on the hub in one request. Both scopes are captured from the app: the **room** forms
come from a room screen, and the **hub-wide** forms from the **All Rooms** header on its main page
(`Hub_Main_Page_Header_All_Rooms`), which offers the same three buttons for the whole house.
The position fields also accept room-wide and hub-wide scopes, as tested above, though neither
form has been captured from the app.

| Control fields | One blind | One room | Whole hub |
|---|---|---|---|
| `BottomRailPosition` + `MiddleRailPosition` | Confirmed | Confirmed on the two Office dual-rail blinds | Confirmed fan-out on the three Den single-rail blinds; one stopped short |
| One rail field alone | Captured from the app | Middle-only returned `Error: 2`; bottom-only was accepted but set the middle target to 0 | Middle-only returned `Error: 2`; bottom-only not tested |
| `Switch` / `Favorite` | Captured from the app and confirmed | Confirmed | Confirmed |
| `MotorStop` | Captured from the app | Stopped both moving Office shades | Stopped one moving Office shade; simultaneous motors in multiple rooms not tested |
| `MotorFineTuneToUp` / `MotorFineTuneToDown` | Captured from the app | Small position changes on both Office shades | Small position changes in Office and Den; all 13 blinds reported in |
| `StatusRequest` / `ReportBatteryLevel` | `StatusRequest` confirmed; `ReportBatteryLevel` with only `PeripheralUID` appears to cause a broader sweep | `ReportBatteryLevel` confirmed; `StatusRequest` with room or room/group fields appears to cause a broader sweep | `ReportBatteryLevel` confirmed; unscoped `StatusRequest` was acknowledged and six of 13 blinds reported within 30 s |
| Saved scene `SetToScene` | Not tested | Confirmed with `RoomID` and numeric `SceneID` as the `SetToScene` value | Not tested |
| Shutter `Position` (0–7) | Built by the app's library; no live Shutter test here | Not tested | Not tested |

The current hub has cellular shades only (module types 32 and 33). The position result does
not establish how a room or hub-wide command would affect a SmartDrape, PerfectSheer, or
Shutter. An `Error: 0` reply and a changed target also do not guarantee every motor completes
its move, as the Den test shows.

**A missing rail field is not preserved at broader scopes.** A room request containing only
`MiddleRailPosition: 75` returned `Error: 2` six times, while a two-field request to the same
room succeeded. The hub-wide middle-only form also returned `Error: 2`. A room request with
only `BottomRailPosition: 0` returned `Error: 0` but set both Office shades' *middle* targets
to 0, even though they had been at 100. An explicit two-field request restored them. Use both
rail fields for room or hub-wide position moves; the hub-wide bottom-only form was not tested.

**Stop and jog also accept broader scopes.** From about 25/75, room-scoped fine-tune taps
produced small position changes on both Office shades. A room-scoped `MotorStop: 170` stopped
the pair at bottom 48 and 49 while they were heading for 100. An unscoped `MotorStop: 170`
stopped one moving Office shade at 26 instead of 100. Two unscoped
`MotorFineTuneToDown: 170` taps shifted the staged Office shade from 25/75 to 24/74 and all
three Den shades from bottom 100 to 99; all 13 blinds' last-seen timestamps advanced. All
were returned to their starting positions. The unscoped stop test had only one motor moving,
so stopping several rooms at once remains unverified.

The hub acknowledged a later room position restore and stored both Office targets, but one
shade did not move until its position command was resent individually. Multi-blind commands
need an actual-position check and a recovery path; `Error: 0` is only acceptance by the hub.

The integration's room and **All blinds** position sliders work within these limits
(`NormanCoordinator.async_move_room`). Every room request carries both rail fields. It is sent
only when every blind in scope is a single- or two-rail shade (`ROOM_POSITION_TYPES`) and
would be sent the same pair by its own slider anyway; otherwise each blind is sent its own move,
paced. Each blind moved is then watched like any single move, and the recovery is that
blind's own position command, never the room request again.

The hub-wide form is simply the bare verb with **no scope field at all** — no `RoomID`, no
all-rooms marker: `{"Switch": 0}`, `{"Switch": 1}`, `{"Favorite": 0}`. An omitted scope means
"everything", not "nothing".

Hub-wide `Favorite` moved every two-rail blind to its stored 0/50. The four single-rail blinds
did not move in that capture, but they were already sitting at bottom 100 when it fired, so it
said nothing either way about them. **Settled since**, by staging all thirteen blinds at 50/50
first and then sending each of the three hub-wide verbs: every blind moved, the single-rail
ones going to 50% on `Favorite`. Best Privacy's bottom 0 / middle 100 was confirmed at this
scope too.

A later per-blind capture of a **single-rail** shade settles it: the app sends all three verbs
to it in exactly the same form as to a two-rail blind, addressed by `RoomID` + `GroupID`.

```
{"TaskID": 60730, "RoomID": 3961, "GroupID": 1, "Favorite": 0}
{"TaskID": 60731, "RoomID": 3961, "GroupID": 1, "Switch": 0}
{"TaskID": 60732, "RoomID": 3961, "GroupID": 1, "Switch": 1}
```

So none of the three verbs is conditioned on rail count, at any scope. On a single-rail blind
`Switch` has only the bottom rail to set; the middle-rail half of the command is simply moot.

| Body (plus `Timestamp`, `TaskID`) | Effect |
|---|---|
| `{"Switch": 1}` | open every blind on the hub (both rails to 100) -- **verified** |
| `{"Switch": 0}` | close every blind on the hub (bottom to 0, middle to 100) -- **verified** |
| `{"Favorite": 0}` | send every blind on the hub to its stored favorite -- **verified** |
| `{"Switch": 1, "RoomID": 29550}` / `{"Switch": 0, "RoomID": 29550}` | open / close every blind in the room |
| `{"Favorite": 0, "RoomID": 24973}` | send every blind in the room to its stored favorite position |

`Switch` sets **both** rails, to a fixed pair of positions per direction -- it is not a
relative or bottom-only move. Verified by staging a two-rail blind at 60/60 and 40/40 and
watching the targets it produced:

| App button | Body | Target it sets (two-rail) |
|---|---|---|
| Best Privacy | `{"Switch": 0, "RoomID": …}` | bottom **0**, middle **100** |
| Best View | `{"Switch": 1, "RoomID": …}` | bottom **100**, middle **100** |
| Remote Favorite | `{"Favorite": 0, "RoomID": …}` | the blind's stored favorite (0/50 on the reference hub) |

"Best Privacy" therefore means the middle rail fully up and the bottom rail fully down: on a
day/night shade the light-filtering sheer, which hangs above the middle rail, is stacked away
and the blackout below it covers the window. Reading this from a capture alone is misleading -- a room that is already at middle
100 shows no middle movement, which is what made an earlier revision of this document claim
`Switch` left the middle rail untouched. Stage a blind away from both rails' end positions
before drawing conclusions.

`norman.room_command` and each room's buttons send these three, and the hub's three **All
blinds** buttons send the hub-wide form. The hub echoes `Switch` / `Favorite` and `RoomID`.

**`Switch` and `Favorite` take three scopes, selected by which address fields are present:**

| Scope | Address fields | Sent by |
|---|---|---|
| One blind | `RoomID` + `GroupID` (+ `PeripheralUID`, which the app includes) | a blind's own buttons |
| One room | `RoomID` | a room screen |
| Every blind | none | the **All Rooms** screen |

All three were captured from the app. Note that `PeripheralUID` alone is **not** an address for
these verbs: `{"Favorite": 0, "PeripheralUID": …}` does move the blind (the hub appears to fall
back to it), but the app never sends that form, and it is not what selects the target when the
room/group pair is present.

**Beware when testing this: the reply says nothing about movement.** The hub answers
`Error: 0` immediately and echoes the field, and then `status` keeps reporting the *old*
position — target included — for as long as the blind takes to travel. On a large shade that
is around **30 seconds**. A test that watches for 15 or 20 seconds will conclude the command
did nothing. Neither the reply nor the status read distinguishes "refused" from "moving"; only
waiting long enough does. Per-blind open/close stays with the cover entities, since Home
Assistant's own groups and areas already fan those out across both rails.

### Waking a blind

Captured on 2026-09-18 from the app's **device & battery status** screen (its
`SSLowBatteryAndDisconnectViewController`, which lists blinds the hub has not heard from
and offers a refresh button), then confirmed by reading the app's network library
(`DKIoTClient.framework`), which builds three requests for it:

| App builder | Body (plus `Timestamp`, `TaskID`) | Scope |
|---|---|---|
| `CreateNormanPeripheralRequestStatus` | `{"PeripheralUID": X, "StatusRequest": 0}` | one blind |
| `CreateNormanRoomRequestPeripheralBatteryLevel` | `{"RoomID": R, "ReportBatteryLevel": 0}` | one room |
| `CreateNormanHubRequestPeripheralBatteryLevel` | `{"ReportBatteryLevel": 0}` | every blind |

All three carry the value `0` — the same literal the library uses for `FindTop` and
`Favorite`, while `MotorStop` gets `170` — and the hub echoes the verb back with `Error: 0`.
The refresh button sends the hub-wide form; the other two were verified by sending them.

What happens next is visible in `status`: each blind's `Timestamp` is **when the hub last
heard from it**, and it moves when a blind reports in with nothing changed, so it is a
liveness signal rather than a last-change time. Timings on the reference hub:

- **Per blind** (`StatusRequest`): the blind's `Timestamp` moved within **5 s**, on every try,
  including a blind that had ignored the hub-wide sweep.
- **Per room** (`ReportBatteryLevel` + `RoomID`): all three blinds in the room within **5 s**.
- **Hub-wide** (`ReportBatteryLevel`): the hub polls the battery (type 33) blinds one after
  another; seven of nine had reported within ~30 s, and the remaining two only on a later
  try. The four type 32 blinds (`RssiMean` 34, wired) did not respond to the sweep at all —
  but a per-blind `StatusRequest` to one of them was answered in 4 s, so the integration
  follows every sweep with one request per type 32 blind.

Direct tests on 2026-10-11 found that `StatusRequest` does **not** appear to use the same scope
rules as `ReportBatteryLevel`. With `PeripheralUID`, its one target reported within **10 s**
and no other blind reported during a 60 s watch. With `RoomID` alone, neither blind in the
selected room reported within 10 s, but both had reported by 30 s and ten blinds outside the
room had reported by 60 s. With `RoomID` + `GroupID`, the selected blind reported by 30 s and
nine outside it by 60 s. An unscoped request was acknowledged and six of 13 blinds reported
within 30 s. Every request returned `Error: 0`; no positions changed.

These results suggest that omitting `PeripheralUID` may turn `StatusRequest` into a hub-wide
report-in sweep, even when room/group fields are present. They do not prove which specific
request caused each report: in no-command 60 s comparisons, two to four blinds outside the
selected room reported, while neither blind in that room did. The existing
`ReportBatteryLevel` room form is the confirmed way to refresh a room.

The converse scope also behaves unexpectedly. In a quiet no-command minute on 2026-10-11,
none of 13 blinds reported. Sending `ReportBatteryLevel: 0` with one `PeripheralUID` returned
`Error: 0`; eight blinds, including the addressed one, reported within 60 s. All eight had
changes in reported position and target fields, consistent with a stale hub cache being
corrected during a broad report-in. No physical motor movement was verified. Use
`StatusRequest` to refresh a single blind; an accepted `ReportBatteryLevel` with a UID is not
evidence that it was scoped to that blind.

Each report arrives as a `{"Status": …, "PeripheralList": [uid]}` notification, so a client
holding the notification stream sees them without polling. The app taps the button several
times in a row; nothing suggests that is needed.

**Error 2.** Every position `control` sent during the sweep window that followed three
refresh taps (21:59:02–21:59:42, twelve commands to eleven blinds) answered
`{"Error": 2}` with the fields echoed, and the same commands a minute later answered `0`. A
`StatusRequest` sent mid-sweep answered `0`, so 2 is not a blanket "busy". It is the only
code the hub has ever returned for a move; the integration retries a move that gets it
(`HUB_BUSY_RETRIES` × `HUB_BUSY_RETRY_DELAY`) before failing.

The app's **"Disconnect"** label is time-based: `isDisconnectPeripheral:withHub:` compares
now against the blind's last-heard time and flags it past **86400 s** (24 h). The
integration's connection binary sensor applies the same threshold.

**Why reporting in matters: the hub's cache can be wrong.** In the same session the hub had
reported every type 33 blind's `MiddleRailPosition` as 100 for the preceding hour; when the
blinds reported in, several read 0 (nothing had moved). And a blind that accepts a move and
does not go leaves the hub reporting the old position with the *new target* indefinitely:
blind 8399 answered a move to middle 100 with `Error: 0` at 22:00:00 and `status` then
showed `MiddleRailPosition: 0, TargetMiddleRailPosition: 100` until a room-wide
`ReportBatteryLevel` at 22:12:10 had it report in, at which point the target snapped to 0.
Neither `status` nor the notification stream reveals either case on their own. The
integration's move watchdog (a `StatusRequest` 60 s after any move the blind has not
reported, then a resend if it still has not moved, up to three sends) and its optional wake
sweep exist for exactly these two. The report-in also **overwrites the target** with the
blind's actual position, so a check that compares position with target after asking the blind
to report in always passes; the watchdog keeps the target it read when the command was sent.

### Pairing mode

`{"PairingMode": 5}` on `control`, with no scope field, opens the hub's pairing window. The
hub echoes it with `Error: 0` and `status` reports `PairingMode: 5` from then on — for
exactly ten minutes on 2026-09-18 (22:08:47 → 22:18:48), after which it reads `0` again.
The same request was refused with `Error: 8` a few minutes earlier, while the hub was
sweeping its blinds after a refresh, and with `Error: 10` in an earlier capture. The app
also sends `{"SearchForPeripheral": 0}` (answered `0`) around it; the rest of its pairing
flow (`discoverPeripheralWithRoomId`, `remoteControlPair` in its library) has not been
captured. `PairingMode` reads `4` in the registration reply regardless. The integration
exposes the window as a hub button and a binary sensor and nothing more.

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

## Known endpoint surface

Twenty local paths are known on the reference hub (firmware 6.1.25). The integration calls
five; fifteen more were captured from the app or tested directly. The hub returned **HTTP 404**
for the other names tried, and `scripts/probe_hub_endpoints.py` found two scene reads among 43
read candidates. That scan tests candidate names, not every possible path or request body. It
does not establish that the local API is complete, even for this firmware.

| Path suffix under `/NM/v1/` | Evidence | Integration |
|---|---|---|
| `registration`, `GetAllPeripheral`, `status`, `control`, `notification` | app traffic and direct use | used |
| `GetAllSchedule`, `AddSchedule`, `DeleteSchedule` | app traffic | not used |
| `UpdateRoom`, `UpdatePeripheral`, `UpdateDeviceInfo`, `GetDeviceInfo` | app traffic | not used |
| `GetAllScene`, `GetAllSceneGroup` | direct read probe; one saved scene now observed in `GetAllScene` | not used |
| `AddScene`, `UpdateScene`, `DeleteScene`, `AddSceneGroup`, `UpdateSceneGroup`, `DeleteSceneGroup` | direct create/update/read/delete tests with disposable records | not used |

The principal integration gaps are:

| Hub capability | Direct evidence | Integration today |
|---|---|---|
| Saved room scenes | Read, create, update, delete, and activate tested on this hub | No scene discovery, entity, or dedicated action; a caller can supply the confirmed `RoomID`/`SetToScene` body through `send_hub_command` |
| Saved scene groups | Read, create, update, delete, and cross-room activation tested; one motor missed the group command | No scene-group model or dedicated action; a raw `SceneGroupID` control call is possible, without per-member completion checks |
| Hub schedules | Read, create, and delete observed in app traffic | Not modelled; Home Assistant automations remain the intended scheduler |
| Names and room styling | `UpdateRoom`, `UpdatePeripheral`, and `UpdateDeviceInfo` observed in app traffic | Reads names and styling where useful, but does not offer these writes |
| Device information | `GetDeviceInfo` observed in app traffic | Gets hub identity from `registration` and the tree instead |

This table counts **dedicated integration support**, not every body a caller could send with
the raw command action. Scene and scene-group activation would need member-level status
checks before being treated as reliable actions.

An independent [hub-binary string listing](https://community.home-assistant.io/t/norman-tdbu-blind-control/705405?page=2)
also names two paths not yet tested on firmware 6.1.25:
`UpdatePeripheralGroupName` and `UpdateSchedule`. These remain
**candidates**; their bodies and behavior have not been confirmed on the hub. The listing
has 22 paths in total, including all 20 in the table. Its firmware version was not reported.
The installed ShadeAuto 0.8.33 library has builders that suggest
`{RoomID, GroupID, GroupName}` for group renaming and
`{ScheduleID, ScheduleEnable, Conditions, Executions}` for schedule updates, in addition
to `ThingName`. Neither body was sent to the hub during this exploration, so the mapping
to those two candidate paths and their effects are unverified.

The app may reach other paths in screens or workflows that have not been captured. A feature
visible in the app is not by itself evidence of a *local* endpoint: check its destination in
a capture before adding it to this list.

## Configuration endpoints

These were captured from the Norman app or found by probing, and are documented for
completeness; the integration does not call any of them. All take `ThingName`, `Timestamp`, and `TaskID` in the body and
answer in the `{"status": {"code", "error"}, "results": {…}}` shape. The captured writes
were followed by an `UpdateTime` notification (above), and the app re-read the matching list.

| Endpoint | Body (besides the common fields) | Effect |
|---|---|---|
| `GetAllSchedule` | — | `results.ScheduleList`: every schedule stored **on the hub**. |
| `GetAllScene` | — | `results.RoomList`: `[{RoomID, SceneList}]`, one entry per room. One saved scene observed on 2026-10-11. Found by probing, not seen from the app. |
| `GetAllSceneGroup` | — | `results.SceneGroupList`; tested with a disposable two-scene group, then empty after cleanup. Found by probing. |
| `AddScene` | `RoomID`, `SceneID`, `SceneName`, `Icon`, `Color`, `Sorting`, `PeripheralList` | Creates a room scene. Tested with one shade and a numeric-string scene ID supplied by the client; `status.code: 0`, then present in `GetAllScene`. |
| `UpdateScene` | `RoomID`, `SceneList: [full scene object]` | A full object with a changed name returned `status.code: 0` and the new name appeared in `GetAllScene`. A partial rename object returned `status.code: 1` and had no effect. |
| `DeleteScene` | `RoomID`, `SceneID` | Removes a scene. Tested on the disposable one; `status.code: 0`, then absent from `GetAllScene`. |
| `AddSceneGroup` | `SceneGroupName`, `SceneList: [{RoomID, SceneID}]`, `Sorting`, `Icon`, `Color` | Creates a group of room scenes. Tested with two scenes in separate rooms; the reply assigned a UUID-string `SceneGroupID`, and the group appeared in `GetAllSceneGroup`. |
| `UpdateSceneGroup` | `SceneGroupList: [full group object]` | A full object with a changed name returned `status.code: 0` and the new name appeared in `GetAllSceneGroup`. |
| `DeleteSceneGroup` | `SceneGroupID` | Removes a group. Tested on the disposable one; `status.code: 0`, then absent from `GetAllSceneGroup`. |
| `AddSchedule` | `Conditions`, `Executions`, `ScheduleEnable` | Creates a schedule; the reply carries the hub-assigned `ScheduleID` (a UUID). |
| `DeleteSchedule` | `ScheduleID` | Removes one. |
| `UpdateRoom` | `RoomList: [{RoomID, RoomName, Icon, Color, Sorting}]` (all strings) | Renames / restyles rooms. |
| `UpdatePeripheral` | `RoomID`, `GroupID`, `PeripheralList: [{PeripheralUID, PeripheralName, Sorting}]` (strings) | Renames blinds. |
| `UpdateDeviceInfo` | `CustomDeviceName` | Renames the hub. |
| `GetDeviceInfo` | — | `results.CustomDeviceName` (and `ThingName`). |

A newly saved room scene on firmware 6.1.25 produced this shape in `GetAllScene`. The same
scene object also appeared under the matching room's `SceneList` in `GetAllPeripheral`.
Identifiers and the name below are placeholders; the position and module values are from the
observed response. **Every value inside the scene and its targets was a string**, including
IDs and positions:

```json
{
  "RoomID": "12345",
  "SceneList": [{
    "SceneID": "1",
    "SceneName": "Example",
    "Icon": "<icon>",
    "Color": "",
    "Sorting": "1",
    "PeripheralList": [
      {"PeripheralUID": "1001", "Position": "0", "BottomRailPosition": "0", "MiddleRailPosition": "100", "ModuleType": "33", "ModuleDetail": "<detail>"},
      {"PeripheralUID": "1002", "Position": "0", "BottomRailPosition": "0", "MiddleRailPosition": "100", "ModuleType": "33", "ModuleDetail": "<detail>"}
    ]
  }]
}
```

The two listed UIDs belonged to blinds in that room, and their saved rail positions matched
`status` when read. `Position` was present as `"0"` even though these type-33 blinds have
no `Position` in their live `status` entries. This is one example, not a guarantee that every
scene is confined to its room or has exactly these target fields.

The disposable scene write used the same six fields per `PeripheralList` target shown above:
`PeripheralUID`, `Position`, `BottomRailPosition`, `MiddleRailPosition`, `ModuleType`, and
`ModuleDetail`, all as strings. `AddScene` echoed the supplied scene object in `results`.
`AddSceneGroup` returned its new UUID-string `SceneGroupID`; a subsequent `GetAllSceneGroup`
returned `SceneGroupName`, `SceneGroupID`, `Icon`, `Color`, `Sorting`, and a `SceneList` of
`{RoomID, SceneID, SceneName}` objects. A second one-scene group also appeared in
`GetAllPeripheral` under `results.SceneGroupList`, but its item had only `RoomID` and
`SceneID`; treat `SceneName` as optional in that list. The delete requests returned success,
and the records disappeared on the next read. These are tested request forms, not proof that
every field is required or every alternative value is accepted.

`UpdateScene` succeeded with the complete saved scene object in `SceneList`, changing
`SceneName` while retaining `SceneID`, `Icon`, `Color`, `Sorting`, and `PeripheralList`.
A shorter entry containing only `SceneID`, `SceneName`, `Icon`, and `Color` returned
`status.code: 1` (`"Request process fail."`) and left the name unchanged.
`UpdateSceneGroup` likewise succeeded with the complete saved group object in
`SceneGroupList`, changing `SceneGroupName` while retaining `SceneGroupID`, `SceneList`,
`Sorting`, `Icon`, and `Color`. Both updates were checked with fresh reads and their
disposable records were removed afterward. These observations do not establish whether
all unchanged fields are required, only that the full-object forms work.

**Post-write read failure on the reference hub:** after the full-object update tests and
cleanup, repeated valid `GetAllPeripheral` requests returned
`{"status": {"code": 1, "error": "Request process fail."}}` with no `RoomList`.
`registration`, `status` (all 13 blinds), `GetAllScene` (the original scene),
`GetAllSceneGroup` (empty), and `GetAllSchedule` (empty) still answered normally.
`GetAllPeripheral` had succeeded after the earlier add/delete tests, but the exact write
that led to this failure is not isolated. An accepted empty `UpdateSceneGroup` request did
not restore it. Further configuration writes were stopped. A power cycle did **not** restore
`GetAllPeripheral`: it still returns code 1 after startup. `GetDeviceInfo` also returns code
1. `GetAllScene` now returns an empty `RoomList`, so the user's previously saved scene is no
longer visible through that read. `registration` and `status` still show the same 13 blind IDs;
all reported actual positions match the saved pretest baseline, and status still carries six
distinct `RoomID` values. The configuration store may be damaged or inaccessible; the cause
and the scene's persistence are not yet known. No additional configuration writes should be
sent to this hub until it is recovered.

#### Run a saved scene

The installed ShadeAuto 0.8.33 `DKIoTClient.framework` has a
`CreateNormanHub:setToSceneControl:withRoomId:taskIdentifier:` builder. Its control body
sets `RoomID` and a `SetToScene` field whose **numeric value is the saved `SceneID`**.
This was tested directly on firmware 6.1.25, with `SceneID: "1"` in the read reply:

```json
{"RoomID": 12345, "SetToScene": 1, "Timestamp": 1700000000, "TaskID": 8200}
```

`POST /NM/v1/control` answered `Error: 0` and echoed `RoomID` and `SetToScene`. Before
the call, the two scene blinds were moved from their saved bottom/middle positions of
`0/100` to approximately `25/75`. Immediately after the call, both targets read `0/100`;
by the next five-second status check, **both actual positions** read `0/100`. No position
changed among the other eleven blinds, and a final `status` read matched all 13 blinds'
starting positions. This confirms scene activation by the hub on this room and product
type, not merely acceptance of the request.

`scripts/run_hub_scene.py` repeats this check using room and scene indexes from
`GetAllScene`. It defaults to a dry run and requires `--execute` to send the command;
it checks actual positions for every scene target and reports observed changes outside the
scene. Stage at least one target away from its saved position to verify physical movement.

Do not confuse this use of `SetToScene: 1` with the per-blind registration vocabulary,
which advertises `SetToScene: 287`; the latter's behavior is untested. The app library
also builds a control body with `SceneGroupID` for running a scene group. A direct test
used the UUID-string ID assigned by `AddSceneGroup`:

```json
{"SceneGroupID": "<group UUID>", "Timestamp": 1700000000, "TaskID": 8800}
```

The hub returned `Error: 0` and echoed `SceneGroupID`. The group contained three blinds
across two rooms; one blind in each room had been staged away from its saved scene position.
The group call changed their targets to the saved positions, and the shade in the original
scene moved back. **The staged shade in the disposable scene did not move back within
90 seconds**, although its target changed. Seven `PeripheralList` notifications arrived;
all mentioned only the group's three blinds, and one listed all three. No other blind's
actual position changed. A separate per-blind position command restored the missed shade.
This establishes that group activation is accepted and can fan out across rooms, but one
successful acknowledgment did not complete every member's move. Group activation needs
per-blind completion checks and a recovery path. The disposable group and scene were then
deleted; a final read found only the user's original scene, no groups, and all 13 blinds at
their pretest positions.

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

## Open questions and coverage workflow

Known gaps between the hub and the integration include hub-stored scenes and schedules, and
configuration writes. Gaps in the **protocol reference** include group activation reliability,
schedule updates, group renaming, the rest of pairing, control-field and scope combinations, and
products absent from the reference hub.
Norman's [ShadeAuto manual](https://normanusa.com/app/uploads/2024/01/ShadeAuto-Manual.pdf)
shows scene creation and activation, multiple scenes, group renaming, firmware updates, and
device setup; it does not specify which of those use the local API. App captures reveal request
shapes the app uses, but they cannot bound what the hub accepts: room-wide and hub-wide position
moves were found by sending `/control` forms the app has not been seen sending. Start from the
direct hub results already recorded above; capture the app only when a particular missing body
shape cannot be established from hub reads, controlled tests, or available handler code.
The 2026-10-11 read baseline on the reference hub confirmed firmware 6.1.25, 13 blinds in six
rooms, and empty schedule, scene, and scene-group lists. A scene was then created. A
disposable second scene and scene group were tested and removed. After the configuration
read failure and power cycle, `GetAllScene` returns no rooms; the original scene needs a
recovery check before treating it as present or permanently lost.

| Question | Best evidence to collect |
|---|---|
| Which scene update caused `GetAllPeripheral` to fail? | A hub restart did not restore the read. Determine whether the configuration store can be recovered without further writes; then, on a separate test hub, run one full-object update at a time and check `GetAllPeripheral` immediately after each write and deletion. A successful update reply and changed name did not establish later read health. |
| When does a scene group drop a member's move? | Repeat controlled group activation with blinds staged in two rooms, collecting each member's actual position and report-in after the command. Compare the radio pacing and recovery behavior with separate room scene calls. One three-blind group call left a staged member unmoved. |
| How does a schedule change after creation? | Read `GetAllSchedule` and inspect the candidate `UpdateSchedule` handler or a controlled enable/disable operation; compare stored state before and after. |
| How does group renaming work? | Inspect candidate `UpdatePeripheralGroupName`, then verify its effect with `GetAllPeripheral` on a test group. |
| What is the rest of pairing? | Record `registration`, `status`, and peripheral lists before and after a controlled pairing test; identify the `SearchForPeripheral` command's reply and notifications. Inspect handler code first where available. |
| How do other products behave? | Collect redacted `registration`, `GetAllPeripheral`, `status`, and notifications from hubs with Shutter, Roman, PerfectSheer, MRS2, and SmartDrape products. Record `ModuleType`/`ModuleDetail`, firmware, and actual movement for each command. |
| Are there more local paths? | Compare path strings from a matching hub binary with this table, then probe additional plausible `Get*` names. Repeat on other hub firmware versions. A 404 for a guessed name is only negative evidence for that name and firmware. |

### Direct hub capability tests

Treat `/control` as a matrix of **address scope** and **command fields**, rather than a fixed
list of app buttons. Four address forms have been observed for at least one command:
`PeripheralUID`, `RoomID` plus `GroupID`, `RoomID` alone, and no address (whole hub). Cross
those with the field families
below, recording accepted requests, actual behavior, and product/firmware differences. The
[room-wide and hub-wide control table](#room-wide-and-hub-wide-control) is the current partial
matrix; a blank or "not tested" cell is an experiment to run, not evidence of rejection.

For the report-in rows, `scripts/explore_hub.py` runs one command with an explicit scope and
compares **all** blind timestamps and positions at chosen intervals. It defaults to a dry run,
allows `StatusRequest`, `ReportBatteryLevel`, and per-blind `RequestModuleInfo`, and prints no
hub or blind identifiers in normal output.
Use `--observe-only` for a no-command comparison, then `--execute` for one controlled request:

```sh
python3 scripts/explore_hub.py Dexatek.local --verb StatusRequest --scope room --room-index 1 --observe-only
python3 scripts/explore_hub.py Dexatek.local --verb StatusRequest --scope room --room-index 1 --execute
```

| Field family | Examples | Open behavior questions |
|---|---|---|
| Positions | both rails, either rail alone, Shutter `Position` | Which scopes and module types accept each form? Does an omitted rail reset its target? |
| Presets and motion | `Switch`, `Favorite`, `MotorStop`, fine-tune verbs | Does each scope reach every intended blind? What happens when two motors are already moving? |
| Report-in | `StatusRequest`, `ReportBatteryLevel` | Which scopes wake which module types, and how long do replies take? |
| Advertised settings | verbs in each blind's `registration` record | Which fields are supported by each product, and what values or prerequisites do they require? Capture app behavior or inspect handler logic before testing writes that change calibration or pairing. |

For a reversible test, save full `status` and `GetAllPeripheral` snapshots first. Send one
request with known affected blinds, wait for the hub's radio and physical movement, then read
`status` for **every** blind: `Error: 0` and a changed target do not prove delivery. Record
request, reply, notifications, final positions, hub firmware, and module types. Restore the
starting positions with individually checked moves. Test field omission and alternate scopes
separately; the observed room-only bottom-rail request unexpectedly changed middle-rail
targets, while middle-only returned `Error: 2`. Space commands as described under
[Control commands are paced](#control-commands-are-paced).

For each app experiment, save a **before snapshot**, perform one action, save the request and
reply and any `notification` events, then take an **after snapshot**. A capture can be decoded
with `scripts/parse_hub_capture.py`; `norman.get_hub_data` or a diagnostics export supplies the
current read payloads. Capture on the app device or at a router/AP mirror that sees its
traffic to the hub; a laptop simply connected to the same LAN usually cannot see it. The
parser accepts classic pcap with IPv4, so convert pcapng first. Scrub identifiers and names
before sharing. The endpoint probe's
`--json` output contains only a 400-character response sample, so it cannot establish a full
response schema; retain a separately redacted full reply for newly discovered reads.

Document each confirmed operation with its method/path, required and optional body fields,
response and error shape, notification side effects, scope (blind, room, hub), app and hub
versions, product type, and whether it was observed from the app or tested on hardware. Keep
untested values and inferred meanings marked as such. Start with candidate read probes; test
writes that alter limits, pairing, firmware, or network settings only on hardware prepared for that
change. Even a successful `/control` reply needs a later state check to establish its effect.

## Observed fields

Everything below comes from captures of a real hub (`NienMadeHub`, firmware 6.1.25, 13 blinds
of two types). Only the fields marked **used** are read by the integration; the rest are kept
verbatim in the diagnostics capture and are candidates for future features.

This list is also **executable**: the `KNOWN_HUB_FIELDS`, `KNOWN_PERIPHERAL_FIELDS`,
`KNOWN_SCENE_FIELDS`, `KNOWN_SCENE_TARGET_FIELDS`, `KNOWN_SCENE_GROUP_FIELDS`, and
`KNOWN_SCENE_GROUP_ITEM_FIELDS` sets in `const.py` hold the same names.
The coordinator checks hub, peripheral, saved scene, and scene-group objects in `GetAllPeripheral` and
logs an unrecognized field at debug level, once per name. So a firmware update that adds a
field in one of these objects announces itself in the log rather than being silently dropped.
`tests/test_repo_consistency.py` checks the lists against this table, so a field
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
| `TimeZone` | GetAllPeripheral | `America/New_York` | **used** (time zone sensor, time zone repair); redacted in diagnostics |
| `GeoLoc` (`Latitude`/`Longitude`) | registration, GetAllPeripheral | | **used** only to check that both coordinates are set (location repair); the values are not stored; redacted |
| `NetworkID` | registration, GetAllPeripheral | | not used; redacted |
| `PairingMode` | registration (`4`), status (`0` / `5`) | `5` | **used** (pairing-mode sensor): `5` in status while the hub's ten-minute pairing window is open, see [Pairing mode](#pairing-mode). |
| `OTA`, `DeviceType`, `FirmwareId`, `FirmwareCode`, `TotalSegment`/`Segment`, `CleanPairing` | registration, status | `0`, `48` | not used. `OTA` was `1` in one registration reply while status said `0`. |
| `StatusRequest`, `ReportBatteryLevel` | registration (`0`) | `0` | The hub's own report-in verbs, listed the same way a blind lists its command vocabulary. **Used** as `control` verbs (see [Waking a blind](#waking-a-blind)); the registration field itself is not read. |
| `SceneGroupList`, rooms' `SceneList` | GetAllPeripheral | `[]` or saved scene objects | not used |
| rooms' `Icon`, `Color`, `Sorting`; groups' `Sorting` | GetAllPeripheral | `"3"` | not used |
| `RequestTimestamp` / `Timestamp` | every reply | seconds / milliseconds | not used |

### Saved scene

These fields were observed in one room scene in `GetAllPeripheral` and `GetAllScene`.

| Field | Where | Observed value | Used |
|---|---|---|---|
| `SceneID`, `SceneName` | room's `SceneList` | numeric string, user-chosen string | not used |
| `Icon`, `Color`, `Sorting` | scene | strings; `Color` was empty | not used |
| `PeripheralList` | scene | two target objects | not used |
| `PeripheralUID`, `ModuleType`, `ModuleDetail` | each target | strings | not used |
| `Position`, `BottomRailPosition`, `MiddleRailPosition` | each target | `"0"`, `"0"`, `"100"` | not used |

### Saved scene group

These fields were observed with disposable groups in `GetAllSceneGroup` and
`GetAllPeripheral`.

| Field | Where | Observed value | Used |
|---|---|---|---|
| `SceneGroupID`, `SceneGroupName` | `SceneGroupList` item | UUID string, user-chosen string | not used |
| `Icon`, `Color`, `Sorting` | group | strings | not used |
| `SceneList` | group | one or two room-scene references | not used |
| `RoomID`, `SceneID`, optional `SceneName` | each reference | strings | not used |

### Per peripheral

| Field | Where | Example | Used |
|---|---|---|---|
| `PeripheralUID`, `PeripheralName`, `RoomID`, `GroupID` | GetAllPeripheral (strings), status (ints) | | **used**. `PeripheralUID` is also exposed as the device's serial number: no other per-blind identifier appears in any payload, so it is the best candidate for the app's "Serial Number" |
| `ModuleType` / `ModuleDetail` | both | `33`/`3`, `32`/`2`, `48`/`1`, `80`/`1` | **used** (cover type; see below) |
| `BottomRailPosition`, `MiddleRailPosition`, `Target…` | status | 0–100 | **used** |
| `BatteryVoltage` | status | `5` … `100` | **used** as a **percentage** (battery sensor) |
| `RssiMean` | status | `0`, `34` | **used** (signal-strength sensor, unitless) |
| `FirmwareVersion` | status | `0.5.3.8`, `4.1.0.4` | **used**; on type 33 it is the version the app shows |
| `RfFirmwareVersion` | status (type 32 only) | `0.3.20` | **used**: this is the version the Norman app shows for single-rail blinds (Den_1: app 0.3.20, `FirmwareVersion` 4.1.0.4), so it takes precedence for the device's version |
| `Timestamp` | status | epoch seconds | **used** (last-seen sensor, connection sensor). When the hub last **heard from** the blind: it moves when a blind reports in with nothing changed, not only on a state change. |
| `MSDStackType` | GetAllPeripheral (type 80 only) | `"left"` | the SmartDrape cover's `stack` attribute: the side it gathers to when open. Only `"left"` has been seen from a hub; the app numbers the sides 1 left, 2 split, 3 right, so `"right"`, `"split"` and the numbers are read too. |
| `MsdStatus` | status (type 80 only) | `0` | not used; only `0` has been seen |
| `Position`, `TargetPosition` | status (type 1, from the app) | `0`–`7` | **used**: a Shutter's louvers (7 shut, 3 horizontal). Known from the app's parsers, not yet seen from a hub. |
| `Position1`, `Position2`, `TargetPosition1`, `TargetPosition2` | status (from the app) | | not used. A split-panel pair the app's library can read and send; no product in ShadeAuto 0.8.33 shows controls for it. |
| `Angle` | status (from the app) | | not used. Read by the app's library alongside the louvers; its meaning is unknown. |
| `Mrs2Status` | status (type 49, from the app) | | not used; the MRS2 roller's counterpart of `MsdStatus`. |
| `PacketReceiveRate` | status | `0` | not used. Has been `0` on every blind in every capture, including blinds that are plainly reachable, so it is either unimplemented in this firmware or counts something the hub never populates. |
| `StallCurrent` | status (type 33 only) | `4100`, `1240` | not used. Despite the name it reads as a **stall threshold, not a measurement**: the current draw at which the motor decides it has hit an obstruction (or a limit) and stops. It does not vary during travel -- it holds one value through a full open and close, in both directions, and at rest. It is not fixed per blind either: two blinds read `4100` in captures a day apart and `1240` afterwards, with no setting changed in the app, so the motor appears to adapt it. A **falling** value on one blind is therefore the interesting signal (a motor deciding it needs less force to call something a stall), not the absolute number. Both blinds that changed are in one room, and one of them (`58850`) is the blind a `Calibration` was run against the day before -- so calibration, or the limit-setting around it, is the likeliest cause. Unconfirmed: the other blind was not calibrated. Not exposed as an entity while its meaning rests on a single observation. |
| `Switch`, `MotorStop`, `Favorite`, `Calibration`, `ConfigToScene`, `SetToScene`, `SetMotorToTopLimit`, `SetMotorToBottomLimit`, `MotorFineTuneToUp`, `MotorFineTuneToDown`, `SetTopLimit`, `CleanTopLimit`, `SetBottomLimit`, `CleanBottomLimit`, `SetMiddleLimit`, `CleanMiddleLimit`, `MotorSpeedAdjust`, `ReverseMotorDirection`, `StopSensorSwitch`, `FindTop`, `RailSpacing`, `RailSpacingDefault`, `RailSpacingIncrease`, `RailSpacingDecrease`, `SmartDialSwitch`, `CleanRfPairing`, `CleanAllPosition`, `CleanErrorCode`, `RequestModuleInfo` | registration only | `170`, `259`, `0`, `1` | The per-blind **command vocabulary**; the value shown is the one to send. `MotorStop` is **used** (stop). See [Control verbs](#control-verbs) for the ones confirmed from the app. The list differs by type: only type 33 advertises `StallCurrent`, `CleanRfPairing`, `CleanAllPosition`, `MotorSpeedAdjust`, `ReverseMotorDirection`, `FindTop`, and the `RailSpacing` family (`RailSpacing: 10`); only type 32 advertises `RfFirmwareVersion`, `SetMiddleLimit`/`CleanMiddleLimit`, `CleanErrorCode`, and `SmartDialSwitch`. Both list `Switch`, `Favorite`, `Calibration`, `ConfigToScene`/`SetToScene` (`287`), `CleanAllScene`, `StopSensorSwitch`, and the top/bottom limit and fine-tune verbs. |

### Cover types

| `ModuleType`/`ModuleDetail` | App name (code) | Seen | Behaviour | Integration |
|---|---|---|---|---|
| 1 | Shutter (MS4) | app only | louvers as `Position` 0–7; no rails | one `shutter` cover, Louvers: tilt = how open, open/close turn them; no sliders |
| 32 / 2 | Cellular Shade (MCS) | reference hub, 4.1.0.4 + `RfFirmwareVersion` | middle rail always 0, target 0 | single-rail cover, position only; one position slider |
| 32 / 0 | Cellular Shade (MCS) | app only | the app shows one slider | as 32/2 |
| 32 / 3–5 | Cellular Shade (MCS) | app only | the app shows two sliders: a top-down/bottom-up shade | as 33 |
| 33 / 3 | Cellular Shade (DMCS; Japanese "twin, up/down") | reference hub, 0.5.3.x, has `StallCurrent` | middle rail tracks 0–100 (50 when half); day/night cellular shades | primary cover (bottom rail, middle as tilt) + Middle rail cover; two position sliders |
| 33 / 4–5 | Cellular Shade (DMCS) | app only | the app accepts them like 33/3 | as 33/3 |
| 48 / 1 | Roller Shade (MRS1) | issue [#2](https://github.com/kedube/ha-norman/issues/2), 2.4.1 | only the bottom rail moves; the middle rail reads 0, but `Switch` still records a middle-rail target | single-rail cover, position only; one position slider |
| 48 / 2 | Roman Shade (MRS1) | app only | one slider | as 48/1 |
| 48 / 3 | PerfectSheer (MRS1) | app only | two sliders: the shade, and its vanes on the middle rail (0 closed, 100 open), drawn only while the shade is down | one `shade` cover, shade as position and vanes as tilt, independent; one position slider |
| 49 / 1–3 | as 48 (MRS2), with `Mrs2Status` | app only | a second generation of the roller module | as 48 |
| 80 / 1 | SmartDrape (MSD) | issue [#2](https://github.com/kedube/ha-norman/issues/2), 0.2.3, with `MSDStackType` / `MsdStatus` | bottom rail = how far the drape is drawn; middle rail = vanes in seven stops (0, 17, 33, 50, 66, 83, 100), open at 50 and closed at both ends | one `curtain` cover, draw as position and vane openness as tilt, independent; one position slider |
| other | — | | | two-rail by default, warning logged once |

ShadeAuto 0.8.33 knows exactly these six `ModuleType`s: its firmware-update list, its device
details page ("Module Type": MS4, MCS, DMCS, MRS1, MRS2, "MDS"), its pairing list and the
sliders it shows each product all switch on them, and anything else it calls "Unknown". The
ModuleDetail splits are the app's too: it names the roller family by detail (1 Roller Shade,
2 Roman Shade, 3 PerfectSheer) and gives 32/3–5, 33, 48/3 and 80 two sliders.

A single-rail product left on the two-rail default misreports presets as failed. `Switch`
records a middle-rail target of 100 for Best privacy and Best view on every blind, and a blind
with no middle rail keeps reporting 0 — so one that is already at the preset never matches its
target, and the move watchdog asks it to report in, resends the preset twice, and gives up.
That is how type 48 was found.

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
| GetAllPeripheral and configuration endpoints | `"status": {"code": 0}` | `"status": {"code": <non-zero>, "error": "<message>"}` |

**Observed error codes.** Three non-zero `Error` values have been captured, all on `/control`,
all with HTTP 200 and the fields echoed back, so the code is the only signal of failure:

| Code | Seen on | Circumstances |
|---|---|---|
| `2` | a position move | while the hub was sweeping its blinds after the app's refresh (see [Waking a blind](#waking-a-blind)); the same moves succeeded a minute later. The integration retries a move that gets it. |
| `8` | `{"PairingMode": 5}` | 2026-09-18, during the same sweep window; the identical request ten minutes later was accepted and opened the window (see [Pairing mode](#pairing-mode)) |
| `10` | `{"PairingMode": 5}` | an earlier capture, same situation |

No mapping of codes to meanings exists; treat any other non-zero value as "the hub refused
this" and surface it verbatim.

**`Error: 0` means the hub accepted the command, not that a blind carried it out.** The hub
answers `0` and echoes the fields back for a command it then fails to deliver over the radio,
and it stores the new `TargetBottomRailPosition` either way. The only evidence that a blind
acted is its **position** converging on that target in a later `status` read — which can take
30–60 s, and may never happen if the transmission was missed (see
[Control commands are paced](#control-commands-are-paced)).

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
button press ──► control (Switch / Favorite by room+group, or jog by uid) ──► status (refresh)
                  (Switch / Favorite are then watched, and resent once if the blind never moved)
room / hub slider ──► control (both positions, RoomID or no address; or one per blind) ──► status
                  (each blind is then watched, and sent its own move if it never moved)
room / hub button ──► control (verb, RoomID or no address) ──► status (refresh)
get_hub_data action ──► GetAllPeripheral + status (redacted, returned as the response)
send_hub_command action ──► control (caller's fields) ──► status
mDNS announcement ──► config flow ──► registration (identity) ──► offer, or refresh the address
```

If `GetAllPeripheral` fails while `status` still works, the coordinator keeps its last good
room/name tree and continues updating positions. On a fresh setup without a cached tree it
creates generic `Norman <uid>` devices from `status`, preserving room and group IDs when
`status` supplies them. It retries the tree read after at least 60 seconds on a subsequent
refresh and applies the names when it recovers. This fallback was added after the reference
hub's configuration reader stayed broken across a power cycle; it does not repair the hub's
configuration store or make saved scenes available.

The hub's **MAC address is not in any payload**: no endpoint reports it. It is resolved from
the local ARP table when the entry loads, so it is only available when Home Assistant shares a
network segment with the hub. Do not go looking for it in a capture.

The rail sliders (`number`) and the covers share one code path, so both send the same
both-rails `control` call; a room's and the hub's sliders work each blind's move out the same
way. The buttons — a blind's, a room's and the hub's — are the only place the integration sends
a [control verb](#control-verbs) other than `MotorStop` without the user reaching for
`send_hub_command`.

`status` can also be re-read on a timer (off by default; see the poll interval option), which
catches changes the hub never pushed -- it only notifies when it hears from a blind, and a
battery blind's radio sleeps (the Norman app shows such a blind as "Disconnect" after a day of
silence). The report-in verbs ([Waking a blind](#waking-a-blind)) end that on demand. If the
notification stream cannot be established at all the integration still works for commands, and
each command's follow-up `status` call keeps the state fresh, but external changes (remote,
app) will not be reflected until the stream comes back or the next poll, if one is set. The listener logs one error when the stream drops and one info line when it recovers.

**`GetAllPeripheral` is cached; `status` is not.** A refresh re-reads `status` every time but
only calls `GetAllPeripheral` when the cached device list has been invalidated, which happens
on the first refresh, on any listener reconnect (deliberate cycle or dropped stream), and on an
`UpdateTime` notification naming `room`, `peripheral`, or `device`. That split matters when
reading a capture: `status` is the hot path and carries positions and battery, while the
heavier structural payload — names, rooms, module types, firmware — is fetched rarely. A
`schedule` update does not invalidate anything, since schedules are not modelled.

### Control commands are paced

**The hub has one radio, and it drops commands sent faster than it can transmit them.** A
script that sent Best Privacy to all thirteen blinds at once (diagnostics of 2026-09-21,
every request stamped with the same `Timestamp`) had the hub serialise the HTTP replies
~333 ms apart, answer every one with `Error: 0`, and store every blind's target — and
**eleven of the thirteen blinds never moved**. They never heard the command: the hub
transmitted while their acknowledgement windows overlapped, and nothing in the protocol
reports that. Resending does not help, because a resent burst collides the same way.

The gap was measured on the reference hub by sending the same thirteen commands with a
fixed delay between them: at 1.0–1.2 s a few blinds still missed, and at **1.3 s all
thirteen responded**. The same scene driven from a Home Assistant automation kept losing a
blind occasionally at 1.3 s, so the hand test was the easier case; at **1.5 s** several
consecutive whole-house runs dropped nothing, but longer use at 1.5 s still lost a command from
time to time, so the shipped default is **1.6 s**.

So `_async_control` holds an `asyncio.Lock` and spaces every `/control` send by the entry's
command-spacing option (const.py, `DEFAULT_CONTROL_INTERVAL`, 1.6 s), measured from the end
of the previous send so that a slow hub reply counts towards the gap rather than adding to
it. Concurrent callers queue rather than collide; thirteen commands take ~21 s to dispatch.

Only `/control` is gated. `status` reads, `GetAllPeripheral` and the notification stream are
unaffected and still run concurrently, so the UI stays responsive while a batch drains.

Requests otherwise share one aiohttp session and `PARALLEL_UPDATES = 0` on every platform, so
Home Assistant does not serialise entity commands itself and the notification listener's
refreshes run alongside them. The hub echoes a per-request `TaskID`, which suggests it queues
HTTP work rather than assuming one caller — the acks were never the problem, the radio was.

**If you are writing another client, pace your control calls.** The `Error: 0` reply is not
evidence that a blind heard anything; see [Error conventions](#error-conventions).

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
