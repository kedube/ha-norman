# Norman Hub local API reference

This is the contributor reference for the hub protocol the integration speaks. It is
reverse-engineered from observing a Norman Hub on a local network; nothing here comes from
vendor documentation or vendor code. Field names are reproduced exactly as the hub sends them.
Where a field's meaning is inferred rather than confirmed, the text says so.

Read this before changing anything in [`api.py`](../custom_components/norman/api.py) or
[`coordinator.py`](../custom_components/norman/coordinator.py).

## Contents

- [Transport](#transport)
- [Endpoints](#endpoints)
  - [POST /NM/v1/registration](#post-nmv1registration)
  - [POST /NM/v1/GetAllPeripheral](#post-nmv1getallperipheral)
  - [POST /NM/v1/status](#post-nmv1status)
  - [POST /NM/v1/control](#post-nmv1control)
  - [POST /NM/v1/notification](#post-nmv1notification)
- [Error conventions](#error-conventions)
- [How the integration uses the endpoints](#how-the-integration-uses-the-endpoints)
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
- `ModuleType` / `ModuleDetail` presumably identify the kind of covering. Only SmartDrape has
  been mapped so far, so every peripheral is treated as a two-rail blind. Contributions that
  record which values correspond to which products are welcome (open an issue with a
  diagnostics export).
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
      "BatteryVoltage": 12.4,
      "FirmwareVersion": "1.2.3",
      "Timestamp": "1700000000"
    }
  ]
}
```

| Field | Meaning | Exposed as |
|---|---|---|
| `BottomRailPosition` | 0 = closed, 100 = open | cover `current_position` |
| `MiddleRailPosition` | 0–100; the tilt on SmartDrape, the middle rail on top-down/bottom-up blinds | cover `current_tilt_position` |
| `TargetBottomRailPosition` | where the bottom rail is heading | `target_position` attribute |
| `TargetMiddleRailPosition` | where the middle rail is heading | `target_tilt` attribute |
| `BatteryVoltage` | volts (not a percentage) | **Battery voltage** sensor |
| `FirmwareVersion` | blind firmware | device `sw_version` and the opt-in **Firmware version** sensor |
| `Timestamp` | last update; epoch seconds as a string observed | **Last seen** sensor |

Positions are coerced to integers and clamped to 0–100; an unusable value becomes `None`,
which the entity reports as an unknown position. A peripheral that appears here but not in
`GetAllPeripheral` still gets a cover entity, named `Norman <uid>`.

### POST /NM/v1/control

Moves a covering. The call **always takes both rails**; there is no way to move one and leave
the other untouched, so the integration fills the untouched rail with its current target
(falling back to its current position, then to 100). That is why `open_cover` on a
SmartDrape sends the current tilt back along with the new position.

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

The hub acknowledges immediately; the blind then moves and the new position arrives through
the notification stream and the next `status` call.

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

## Error conventions

The hub uses two different shapes:

| Endpoint | Success | Failure |
|---|---|---|
| registration, status, control | `"Error": 0` | `"Error": <non-zero int>` |
| GetAllPeripheral | `"status": {"code": 0}` | `"status": {"code": <non-zero>, "error": "<message>"}` |

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
setup ──► registration ──► GetAllPeripheral ──► status ──► entities created
                                                   ▲
notification stream ──(any object with PeripheralList)──┘  (refresh)
periodic reconnect (300 s) / disconnect (15 s) ──► GetAllPeripheral + status
cover action ──► control ──► status (request_refresh)
get_hub_data action ──► GetAllPeripheral + status (raw, returned as the response)
```

There is no polling interval. If the notification stream cannot be established at all the
integration still works for commands, and each command's follow-up `status` call keeps the
state fresh, but external changes (remote, app) will not be reflected until the stream comes
back. The listener logs one error when the stream drops and one info line when it recovers.

## Capturing traffic

`NormanApiClient.traffic` is a `TrafficRecorder`: every request/response pair and every
notification-stream chunk is appended to a ring buffer (50 entries, bodies clipped to 16 KiB)
before any parsing happens, and the last complete response per endpoint is kept whole in
`latest_raw`. The diagnostics export publishes it as `hub_traffic` with the host and
`ThingName` scrubbed. The `norman.get_hub_data` action returns live `GetAllPeripheral` and
`status` payloads for the same purpose. When someone reports a new blind type, ask for either
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
- Diagnostics exports redact the hub address and ThingName. Positions and blind names are
  included because they are what bug reports need.
