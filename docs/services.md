# Actions (services)

Beyond the standard [cover](https://www.home-assistant.io/integrations/cover/) actions
(`cover.open_cover`, `cover.close_cover`, `cover.set_cover_position`, `cover.stop_cover`, and
the tilt equivalents), the integration registers four actions of its own. The two nudge actions
move a blind relative to where it is heading and target one or more `cover` entities from this
integration; `get_hub_data` reads the hub's raw payloads for troubleshooting; `send_hub_command`
sends the hub verbs that have no entity of their own. All four appear in the automation
editor's action picker.

Several verbs that once needed `send_hub_command` now have entities — favorite position, jog up
and down, and run to either limit are [buttons](entities.md#buttons), and stop is on the covers
— so reach for the action only for what is left under [Hub verbs](#hub-verbs).

## `norman.nudge_position`

Move a cover by a relative amount.

| Field | Required | Range | Meaning |
|---|---|---|---|
| `step` | yes | -100 … 100 | Positive opens, negative closes. |

The step is applied to where the cover is **heading** (its `target_position`), not just where
it is, so two quick nudges add up instead of both being measured from a stale position. The
result is clamped to 0–100.

```yaml
action: norman.nudge_position
target:
  entity_id: cover.living_drape
data:
  step: -10
```

## `norman.nudge_tilt`

Adjust a cover's tilt by a relative amount. Only acts on covers that support tilt (two-rail
products); single-rail shades are skipped.

| Field | Required | Range | Meaning |
|---|---|---|---|
| `step` | yes | -100 … 100 | Direction depends on the blind. On SmartDrape, negative tilts left. |

Like `nudge_position`, the step is relative to the current tilt target and clamped.

```yaml
action: norman.nudge_tilt
target:
  entity_id: cover.living_drape
data:
  step: 25
```

## `norman.room_command`

Run one of the Norman app's own **room** buttons against every blind in a room. The hub
accepts `RoomID` in place of `PeripheralUID` for these verbs, so this is a single request no
matter how many blinds the room holds — the same request the app sends.

| Field | Required | Values | Meaning |
|---|---|---|---|
| `room` | no | a room name | As the **hub** knows it (the Norman app's room name), matched case-insensitively. Not the Home Assistant area, which may have been renamed. **Omit it to address every blind on the hub.** |
| `command` | yes | `best_privacy`, `best_view`, `favorite` | Which of the app's buttons to press. |
| `config_entry_id` | no | | Which hub, when more than one is set up. |

| Command | Sends | Effect |
|---|---|---|
| `best_privacy` | `{"Switch": 0, "RoomID": …}` | Bottom rail to **0**, middle rail to **100**. On a day/night shade that is the point: the room is private behind the closed fabric, but the sheer middle is fully open so it still lets light in. |
| `best_view` | `{"Switch": 1, "RoomID": …}` | Both rails to **100** — fully open. |
| `favorite` | `{"Favorite": 0, "RoomID": …}` | Sends the room to its stored favorite position — the same one the physical remote's favorite button uses. Home Assistant has no equivalent, so this action is the only way to reach it for a whole room. |

```yaml
action: norman.room_command
data:
  room: Office
  command: best_privacy
```

Leave `room` out and the same verb goes to the whole hub — the hub reads a command with no
scope as every blind:

```yaml
action: norman.room_command
data:
  command: best_view      # every blind in the house, in one request
```

All three commands work without a room — this is what the app's **All Rooms** screen sends.
Note that hub-wide `favorite` reaches only two-rail blinds: single-rail ones have no stored
favorite and stay where they are.

`Switch` sets both rails to fixed positions; it is not a relative move and there is no
room-wide way to reach an arbitrary percentage. For that, use the cover entities (or the card's
room controls, which fan out across every rail).

## `norman.get_hub_data`

Read the hub's raw device list and status, exactly as the hub sends them, and return them as a
response. Not tied to an entity. Meant for bug reports and for mapping new blind types: the
response includes every field, including ones the integration does not understand.

| Field | Required | Meaning |
|---|---|---|
| `config_entry_id` | only with several hubs | Which hub to read. With one hub configured it can be omitted. |

Response:

```yaml
devices:      # the GetAllPeripheral payload (rooms → groups → peripherals)
  status: {code: 0}
  results: {RoomList: [...]}
status:       # the status payload (positions, targets, battery, firmware per peripheral)
  Error: 0
  Peripherals: [...]
```

From **Developer tools → Actions**, pick *Norman: Get hub data*, run it, and copy the response.
In a script:

```yaml
action: norman.get_hub_data
response_variable: hub
```

The hub's identity, location (`GeoLoc`), Wi-Fi name, time zone, and custom name are blanked in
the response, the same as in a diagnostics download; everything about the blinds is left as the
hub sent it. Skim it before posting all the same, since the hub may send fields nobody has seen
yet. See the README's [Diagnostics](../README.md#diagnostics).

## `norman.send_hub_command`

**Advanced.** POST arbitrary fields to the hub's control endpoint for one blind and return the
hub's reply. `PeripheralUID`, `Timestamp`, and `TaskID` are filled in; your fields are merged on
top. The blind will do whatever the hub makes of the fields, so use it deliberately. The verbs
the Norman app is known to send are listed under [Hub verbs](#hub-verbs).

| Field | Required | Meaning |
|---|---|---|
| `peripheral_uid` | yes | The blind's id: the cover entity's unique id, or `PeripheralUID` in `get_hub_data`. |
| `fields` | yes | A flat object of extra fields (numbers, strings, booleans). |
| `config_entry_id` | only with several hubs | Which hub. |

```yaml
action: norman.send_hub_command
data:
  peripheral_uid: 58850
  fields:
    MotorFineTuneToUp: 170
response_variable: reply
```

A refresh follows every call so the covers pick up whatever moved. A non-zero `Error` in the
reply fails the action with the code.

### Hub verbs

A verb is one extra field per call. `170` means "do it now" for motor verbs; `0` stores or
clears a setting. These were captured from the Norman app, so they are known to work:

| `fields` | Effect | Safe to try? |
|---|---|---|
| `{MotorStop: 170}` | Stop the motor. This is what `cover.stop_cover` sends. | yes |
| `{MotorFineTuneToUp: 170}` / `{MotorFineTuneToDown: 170}` | Jog a small step up or down. The **Jog** buttons. | yes |
| `{SetMotorToTopLimit: 170}` / `{SetMotorToBottomLimit: 170}` | Run to the stored top or bottom limit. The **Run to … limit** buttons. | yes |
| `{Favorite: 0}` | Go to the favorite position. The **Favorite position** button; confirmed both per-blind and room-wide. | yes |
| `{FindTop: 0}` | Re-sync to the top; the app sends it when entering and leaving limit setup. | yes |
| `{SetTopLimit: 0}` / `{SetBottomLimit: 0}` | Store the **current** position as that limit. | changes the blind's travel |
| `{CleanTopLimit: 0}` / `{CleanBottomLimit: 0}` | Clear a stored limit. | changes the blind's travel |
| `{Calibration: 0}` | Run the motor's calibration. | changes the blind's travel |

Two more verbs are confirmed only in their **room-wide** form, which this action cannot send
because it always addresses one blind: `{Switch: 1}` / `{Switch: 0}` opens or closes every
blind in a room (or on the hub), and `{Favorite: 0}` sends a room to its favorite positions.
The per-blind `Switch` form has not been captured; the per-blind `Favorite` form is what the
the Favorite position button sends. The rest of the vocabulary (`MotorSpeedAdjust`,
`ReverseMotorDirection`, and others; see [docs/NORMAN_API.md](NORMAN_API.md#control-verbs))
has not been seen from the app at all. If you confirm one, open an issue with the fields and
the reply so it can get a proper entity.

## Errors

If the hub rejects a command or cannot be reached, the action fails with an error that names
the cover and the reason (for example `Failed to set position (value: 10) for Living Drape:
Timed out talking to Norman hub at 192.168.1.50`). Automations can catch this with
`continue_on_error`.

## Behaviour to know about

- The hub's control call always takes **both** rails, so every action sends the untouched
  rail back unchanged (its current target, or current position). See
  [docs/NORMAN_API.md](NORMAN_API.md#post-nmv1control).
- After each command the integration re-reads the hub's status. The blind reports its
  position as it moves, so `current_position` catches up over a few seconds.
- `cover.stop_cover` and `cover.stop_cover_tilt` send the same motor stop, because the hub has
  one stop per blind, not one per rail. After a stop the hub's target positions are wherever the
  blind ended up, so a following nudge is relative to that.
