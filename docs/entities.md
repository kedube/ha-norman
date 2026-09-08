# Entities

Per blind the integration creates a **cover** (two for two-rail blinds), a **position slider**
per rail, five **buttons**, and four **diagnostic sensors**, all on one **device**. The hub gets
a device of its own carrying four diagnostic sensors.

| | Per blind | On the hub |
|---|---|---|
| Cover | Bottom rail; Middle rail on two-rail blinds | — |
| Number | Bottom rail position; Middle rail position on two-rail blinds | — |
| Button | Favorite position, Jog up, Jog down, Run to top limit, Run to bottom limit | — |
| Sensor | Battery, Last seen, Signal strength\*, Firmware version\* | MAC address, Time zone, Wi-Fi network, Wi-Fi signal\* |

\* disabled by default; enable from the entity's settings.

## Devices

| Device | Identifiers | Notes |
|---|---|---|
| Hub | `norman` / `hub_<entry id>` | Named as in the Norman app (for example "ShadeAuto Hub"); model and firmware from the hub (`NienMadeHub`, 6.x); configuration URL is the hub's base address; the MAC address is attached as a network connection when it can be resolved (see below). |
| Blind | `norman` / `<PeripheralUID>` | Named after the blind's name in the Norman app; model is the Norman product name where the type has been matched to the app's catalogue ("Cellular Shade (dual rail)" for `ModuleType` 33; single-rail types are still "Single-rail window covering" until matched) with the hub's `ModuleType/ModuleDetail` as model id; `via_device` links it to the hub; `sw_version` is the version the app shows (see [Firmware](#firmware-version)); the serial number is the `PeripheralUID`; the suggested area is the hub's room name. |

The device page therefore mirrors the app's blind details: room (area), battery (sensor),
version, module type (model id), and serial number.

Renaming a blind or the hub in the Norman app renames the device here too (the hub announces
the edit and the integration re-reads the names). A name set in Home Assistant is kept; the
app's name shows underneath it as the device's original name. Room changes update the
*suggested* area only, which Home Assistant applies when a device is first created.

## Cover entities

The hub's `ModuleType` decides what kind of cover a blind gets:

| `ModuleType` | Cover entities | Device class | Features |
|---|---|---|---|
| 33 | two-rail (day/night cellular, top-down/bottom-up, SmartDrape): the **primary** cover, plus a **Middle rail** cover | `blind`, `shade` | primary: open, close, set position, stop, open tilt, close tilt, set tilt position, stop tilt. Middle rail: open, close, set position, stop |
| 32 | single-rail (roller and honeycomb style) | `shade` | open, close, set position, stop |
| other | treated as two-rail; a warning asks for a report | `blind` | as two-rail |

**Two-rail blinds are two covers.** Each is named for the rail it drives: **Bottom rail** and
**Middle rail**, so a blind called "Living Drape" has entities named "Living Drape Bottom rail"
and "Living Drape Middle rail". The middle rail (`cover.<blind>_middle_rail`) is: on a
day/night shade that is the second fabric, on a top-down/bottom-up shade the top rail, and on
a SmartDrape the vane tilt. The integration does not need to know which of those it is: it
drives the rail, and the product decides what the rail means. The primary cover also exposes the middle rail as *tilt*, which
suits drapes; for shades, use the Middle rail cover, whose slider means the same thing it
means in the Norman app. Both read the same hub values, so they never disagree. The
`nudge_position` action works on either; on the Middle rail cover it nudges the middle rail.

Entity ids are derived from the blind's name in the Norman app, prefixed with its area on Home
Assistant 2026.9 and newer (`cover.living_room_living_drape` for a blind called "Living Drape" in
the hub's "Living Room"; older releases and existing installs keep `cover.living_drape`). A
peripheral the hub reports status for but does not list by name gets `Norman <uid>`.

| Property | Source | Notes |
|---|---|---|
| State | bottom rail | `closed` when the position is 0, otherwise `open`; `unknown` if the hub has not reported a position. |
| `current_position` | `BottomRailPosition` | 0 = closed, 100 = open, matching Home Assistant's convention. |
| `current_tilt_position` | `MiddleRailPosition` | Two-rail only. 0–100. On SmartDrape this is the vane tilt; on top-down/bottom-up blinds it is the middle rail. |
| `target_position` (attribute) | `TargetBottomRailPosition` | Where the bottom rail is heading. Equal to `current_position` when idle. |
| `target_tilt` (attribute) | `TargetMiddleRailPosition` | Two-rail only. Where the middle rail is heading. |

### Availability

A cover (and each of its sensors) is **unavailable** when:

- the last refresh of the hub failed (the hub is unreachable), or
- the hub's status no longer lists that peripheral (it was removed or is not responding).

It becomes available again automatically on the next successful refresh.

### Data updates

There is no polling interval. The integration holds a long-poll open to the hub and refreshes
every cover whenever the hub reports a change, including changes made with a remote or the
Norman app. It also refreshes after every command it sends and every time the long-poll is
reconnected. See [docs/NORMAN_API.md](NORMAN_API.md#post-nmv1notification) for the mechanics.

The bundled [dashboard card](dashboard.md) puts all of this on one card, grouped by room;
[`examples/dashboard.yaml`](../examples/dashboard.yaml) is a complete dashboard using it.

## Position sliders

| Entity | Rail | Range |
|---|---|---|
| Bottom rail position | `BottomRailPosition` | 0–100%, in steps of 10 |
| Middle rail position | `MiddleRailPosition` | 0–100%, in steps of 10. Two-rail blinds only. |

These are `number` entities and they read and write exactly what the covers do, so the two
never disagree. They exist because Home Assistant renders a cover as up/stop/down buttons in
most places and keeps its position slider in the more-info dialog, whereas a `number` renders
as a slider wherever you put it — closer to the Norman app, and easier to drive from an
automation or a voice assistant ("set the bedroom shade to 30").

The 10% step is a usability choice, not a hub limit: the hub accepts any whole percentage. For
finer movement use the **Jog** buttons (the motor's own fine-tune) or the
[`nudge_position`](services.md#normannudge_position) action, which takes any step from -100 to
100.

They sit in the device page's **Controls** group beside the covers, so a two-rail blind shows
its two covers and its two sliders together, with the buttons below the divider.

## Buttons

One press is one verb sent to the hub for that blind (see
[docs/NORMAN_API.md](NORMAN_API.md#control-verbs)), followed by a status re-read so the cover
catches up with the motor.

All five are **enabled** but carry Home Assistant's *configuration* entity category. That is a
layout choice rather than a statement about how often they are used: the device page lists
uncategorised entities first, sorted by entity id, so leaving the buttons uncategorised placed
them between a two-rail blind's two covers. With them categorised, the bottom-rail and
middle-rail covers stay side by side at the top of the page and the buttons follow the
divider. Being categorised also keeps them off auto-generated dashboards; add them to a
dashboard by hand if you want them there.

| Button | Hub verb | Notes |
|---|---|---|
| Favorite position | `Favorite: 0` | Moves to the favorite stored in the blind. The verb is confirmed room-wide from the app; the per-blind form is the hub's advertised one and has not been captured yet. If nothing happens on your blinds, open an issue. |
| Jog up / Jog down | `MotorFineTuneToUp` / `…Down: 170` | A small motor step, the same as the app's limit-setup jog. Independent of position targets. |
| Run to top limit / Run to bottom limit | `SetMotorToTopLimit` / `…BottomLimit: 170` | Drives the motor to the limit stored in the blind. Not the same as open/close, which go through the hub's position logic: these can still work when a blind's position tracking has drifted. |

Errors follow the cover convention: a hub error or timeout fails the press with a message
naming the verb and the blind.

### Firmware version

Single-rail blinds report two versions: `FirmwareVersion` (4.1.0.4 on every one seen) and
`RfFirmwareVersion` (0.3.20). The Norman app shows the **Rf** one as the blind's version, so
that is what the device's `sw_version` and the firmware sensor show; both raw values are on
the sensor as the `module_firmware` and `rf_firmware` attributes. Two-rail blinds report only
`FirmwareVersion`, which is shown as is.

## Diagnostic sensors

Each blind also gets these sensors, filed under **Diagnostic** on the device page. They update
on the same push refreshes as the cover and are unavailable under the same conditions.

| Sensor | Source | Notes |
|---|---|---|
| **Battery** | `BatteryVoltage` | A percentage, despite the hub's field name: every hub seen reports 0–100 and its registration calls the feature `ReportBatteryLevel`. Battery device class, so it shows the usual icons and can drive low-battery automations. |
| **Last seen** | `Timestamp` | When the blind last reported to the hub. Accepts epoch seconds, epoch milliseconds, or ISO 8601 from the hub; anything else shows *unknown*. |
| **Signal strength** | `RssiMean` | **Disabled by default.** A unitless radio-quality index from the hub (0 and 34 seen), not dBm. Useful for spotting a blind at the edge of range. |
| **Firmware version** | `RfFirmwareVersion` on single-rail blinds, `FirmwareVersion` otherwise (see [Firmware version](#firmware-version)) | **Disabled by default**: the same value is already on the device page as `sw_version`. Enable it from the entity settings if you want history or automations on it. Carries both raw values as the `module_firmware` and `rf_firmware` attributes. |

Sensor entity ids follow the same pattern as the cover with the sensor name appended, for
example `sensor.living_room_living_drape_battery`. Installs that ran 0.11 keep their existing
`..._battery_voltage` entity id; the entity is migrated in place.

### Hub sensors

The hub device has its own diagnostic sensors:

| Sensor | Source | Default | Notes |
|---|---|---|---|
| MAC address | the local network (ARP), not the hub | enabled | The hub never reports its MAC. It is looked up when the entry loads, which only works when Home Assistant is on the same network segment as the hub; otherwise the sensor is unknown. When found it is also attached to the device as a network connection. |
| Time zone | `TimeZone` in the device list | enabled | The IANA zone set in the Norman app; the hub uses it for its own schedules. |
| Wi-Fi network | `WiFiSSID` in the registration reply | enabled | The network the hub is joined to. Diagnostics downloads still redact it. |
| Wi-Fi signal | `WiFiRSSI` in status | disabled | dBm. |

## Removing a blind

Once the hub stops reporting a blind (it was unpaired or is not responding), its device can be
deleted from **Settings → Devices & services → Norman → the device → ⋮ → Delete**. Blinds the
hub still reports, and the hub device itself, refuse deletion because they would come straight
back on the next refresh.

## Not exposed (yet)

Seen in real hub payloads but not turned into entities, because their meaning or usefulness is
not established: `PacketReceiveRate`, `StallCurrent`, and the hub's `OTA` and `PairingMode`
flags.

Of the hub's control verbs, fine-tune, run-to-limit, and favorite are [buttons](#buttons), and
stop is on the covers. The ones still without an entity are the limit-setting family
(`SetTopLimit`, `CleanTopLimit`, and their bottom and middle equivalents), `Calibration`, and
the unconfirmed `MotorSpeedAdjust`, `ReverseMotorDirection`, `StopSensorSwitch`,
`SmartDialSwitch`, and the `RailSpacing` group. All can be sent with `norman.send_hub_command`;
the limit and calibration ones change how a blind travels, so read
[Hub verbs](services.md#hub-verbs) first. See also
[docs/NORMAN_API.md](NORMAN_API.md#observed-fields).
