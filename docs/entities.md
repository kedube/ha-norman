# Entities

The integration creates one **cover** entity and three **diagnostic sensors** per peripheral
the hub reports, plus one **device** per blind and one for the hub itself.

## Devices

| Device | Identifiers | Notes |
|---|---|---|
| Hub | `norman` / `hub_<entry id>` | Manufacturer Norman, model Hub. Its configuration URL is the hub's base address. |
| Blind | `norman` / `<PeripheralUID>` | Named after the blind's name in the Norman app; `via_device` links it to the hub; `sw_version` is the blind firmware; the suggested area is the hub's room name. |

## Cover entities

Entity ids are derived from the blind's name in the Norman app, prefixed with its area on Home
Assistant 2026.9 and newer (`cover.living_room_living_drape` for a blind called "Living Drape" in
the hub's "Living Room"; older releases and existing installs keep `cover.living_drape`). A
peripheral the hub reports status for but does not list by name gets `Norman <uid>`.

| Property | Source | Notes |
|---|---|---|
| State | bottom rail | `closed` when the position is 0, otherwise `open`; `unknown` if the hub has not reported a position. |
| `current_position` | `BottomRailPosition` | 0 = closed, 100 = open, matching Home Assistant's convention. |
| `current_tilt_position` | `MiddleRailPosition` | 0–100. On SmartDrape this is the vane tilt; on top-down/bottom-up blinds it is the middle rail. |
| `target_position` (attribute) | `TargetBottomRailPosition` | Where the bottom rail is heading. Equal to `current_position` when idle. |
| `target_tilt` (attribute) | `TargetMiddleRailPosition` | Where the middle rail is heading. |
| Device class | — | `blind` |
| Supported features | — | open, close, set position, open tilt, close tilt, set tilt position |

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

## Diagnostic sensors

Each blind also gets these sensors, filed under **Diagnostic** on the device page. They update
on the same push refreshes as the cover and are unavailable under the same conditions.

| Sensor | Source | Notes |
|---|---|---|
| **Battery voltage** | `BatteryVoltage` | Volts, not a percentage. The voltage-to-charge curve differs per motor, so no battery-level sensor is offered; watch for the value trending down and automate on a threshold that suits your blinds. |
| **Last seen** | `Timestamp` | When the blind last reported to the hub. Accepts epoch seconds, epoch milliseconds, or ISO 8601 from the hub; anything else shows *unknown*. |
| **Firmware version** | `FirmwareVersion` | **Disabled by default**: the same value is already on the device page as `sw_version`. Enable it from the entity settings if you want history or automations on it. |

Sensor entity ids follow the same pattern as the cover with the sensor name appended, for
example `sensor.living_room_living_drape_battery_voltage`.

## Removing a blind

Once the hub stops reporting a blind (it was unpaired or is not responding), its device can be
deleted from **Settings → Devices & services → Norman → the device → ⋮ → Delete**. Blinds the
hub still reports, and the hub device itself, refuse deletion because they would come straight
back on the next refresh.

## Not exposed (yet)

- `ModuleType` / `ModuleDetail` — presumably the product type; only SmartDrape has been
  identified so far. Visible in the [diagnostics export](../README.md#diagnostics) and in the
  `norman.get_hub_data` response (see [docs/services.md](services.md#normanget_hub_data)).
