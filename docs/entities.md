# Entities

The integration creates one **cover** entity (two for two-rail blinds), five **buttons**,
and four **diagnostic sensors** per peripheral the hub reports, plus one **device** per blind
and one for the hub itself (with its own Wi-Fi signal sensor).

## Devices

| Device | Identifiers | Notes |
|---|---|---|
| Hub | `norman` / `hub_<entry id>` | Named as in the Norman app (for example "ShadeAuto Hub"); model and firmware from the hub (`NienMadeHub`, 6.x); configuration URL is the hub's base address. |
| Blind | `norman` / `<PeripheralUID>` | Named after the blind's name in the Norman app; model is "Two-rail window covering" or "Single-rail window covering" with the hub's `ModuleType/ModuleDetail` as model id; `via_device` links it to the hub; `sw_version` is the version the app shows (see [Firmware](#firmware-version)); the serial number is the `PeripheralUID`; the suggested area is the hub's room name. |

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
| 33 | two-rail (day/night, top-down/bottom-up, SmartDrape): the **primary** cover, plus a **Middle rail** cover | `blind`, `shade` | primary: open, close, set position, stop, open tilt, close tilt, set tilt position, stop tilt. Middle rail: open, close, set position, stop |
| 32 | single-rail (roller and honeycomb style) | `shade` | open, close, set position, stop |
| other | treated as two-rail; a warning asks for a report | `blind` | as two-rail |

**Two-rail blinds are two covers.** The primary cover (named after the device) is the bottom
rail. The **Middle rail** cover (`cover.<blind>_middle_rail`) is the middle rail: on a
day/night shade that is the second fabric, on a top-down/bottom-up shade the top rail, and on
a SmartDrape the vane tilt. The primary cover also exposes the middle rail as *tilt*, which
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

## Buttons

One press is one verb sent to the hub for that blind (see
[docs/NORMAN_API.md](NORMAN_API.md#control-verbs)), followed by a status re-read so the cover
catches up with the motor.

| Button | Hub verb | Notes |
|---|---|---|
| Favourite position | `Favorite: 0` | Moves to the favourite stored in the blind. The verb is confirmed room-wide from the app; the per-blind form is the hub's advertised one and has not been captured yet. If nothing happens on your blinds, open an issue. |
| Jog up / Jog down | `MotorFineTuneToUp` / `…Down: 170` | A small motor step, the same as the app's limit-setup jog. Independent of position targets. |
| Run to top limit / Run to bottom limit | `SetMotorToTopLimit` / `…BottomLimit: 170` | Drives the motor to the limit stored in the blind. Not the same as open/close, which go through the hub's position logic: these can still work when a blind's position tracking has drifted. Categorised as configuration, so they appear in the device page's configuration section rather than on the cover card. |

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
| **Firmware version** | `FirmwareVersion` | **Disabled by default**: the same value is already on the device page as `sw_version`. Enable it from the entity settings if you want history or automations on it. |

The hub device has one sensor of its own, **Wi-Fi signal** (`WiFiRSSI`, dBm, signal-strength
device class), also disabled by default.

Sensor entity ids follow the same pattern as the cover with the sensor name appended, for
example `sensor.living_room_living_drape_battery`. Installs that ran 0.11 keep their existing
`..._battery_voltage` entity id; the entity is migrated in place.

## Removing a blind

Once the hub stops reporting a blind (it was unpaired or is not responding), its device can be
deleted from **Settings → Devices & services → Norman → the device → ⋮ → Delete**. Blinds the
hub still reports, and the hub device itself, refuse deletion because they would come straight
back on the next refresh.

## Not exposed (yet)

Seen in real hub payloads but not turned into entities, because their meaning or usefulness is
not established: `PacketReceiveRate`, `StallCurrent`, `RfFirmwareVersion` (kept in diagnostics),
and the hub's `OTA` and `PairingMode` flags. The hub's other control verbs (fine-tune up/down, run
to a limit, set/clear limits, calibrate, and unconfirmed ones such as `Favorite` and
`MotorSpeedAdjust`) can be sent with `norman.send_hub_command` but have no button or number
entity yet. See [docs/NORMAN_API.md](NORMAN_API.md#observed-fields) and
[docs/services.md](services.md#hub-verbs).
