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
shades, SmartDrape, PerfectSheer and Shutter); single-rail shades are skipped.

| Field | Required | Range | Meaning |
|---|---|---|---|
| `step` | yes | -100 … 100 | Positive opens. On a two-rail blind it moves the middle rail; on a SmartDrape, PerfectSheer or Shutter it opens the vanes or louvers. A SmartDrape's vanes and a Shutter's louvers move in stops, and any step moves at least one. |

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
matter how many blinds the room holds — the same request the app sends. Each room's device has
the same four as buttons ([Rooms and the whole house](entities.md#rooms-and-the-whole-house));
this action is for naming the room in a script.

| Field | Required | Values | Meaning |
|---|---|---|---|
| `room` | no | a room name | As the **hub** knows it (the Norman app's room name), matched case-insensitively. Not the Home Assistant area, which may have been renamed. **Omit it to address every blind on the hub.** |
| `command` | yes | `best_privacy`, `best_view`, `favorite`, `refresh` | Which of the app's buttons to press. |
| `config_entry_id` | no | | Which hub, when more than one is set up. |

| Command | Sends | Effect |
|---|---|---|
| `best_privacy` | `{"Switch": 0, "RoomID": …}` | Bottom rail to **0**, middle rail to **100**. On a day/night shade that draws the blackout, which hangs below the middle rail, across the window, with the light-filtering sheer above it stacked fully open. |
| `best_view` | `{"Switch": 1, "RoomID": …}` | Both rails to **100** — fully open. |
| `favorite` | `{"Favorite": 0, "RoomID": …}` | Sends the room to its stored favorite position — the same one the physical remote's favorite button uses. Home Assistant's cover actions have no equivalent; the room's own **Favorite position** button sends the same request. |
| `refresh` | `{"ReportBatteryLevel": 0, "RoomID": …}` | Asks every blind in the room to **report in** — battery, position and last-seen — the same request the app's refresh sends on its device & battery status screen. Nothing moves. On hardware all three blinds in a room answered within five seconds; hub-wide, every battery blind over about half a minute. The hub-wide sweep skips wired (single-rail) blinds, so each of those in scope gets its own `StatusRequest` afterwards. The answers arrive as the hub's own notifications, so the entities follow a few seconds after the call returns. The **Request status** button does this for one blind and **Refresh blinds** on the hub for all of them (see [docs/entities.md](entities.md#hub-buttons)). |

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

All four commands work without a room — the first three are what the app's **All Rooms** screen sends, and `refresh` without a room is its refresh button.

`Switch` sets both rails to fixed positions; it is not a relative move.

### A whole room to any position

Each room has its own **Bottom rail position** and **Middle rail position** sliders, and the
hub has **All blinds** ones ([Rooms and the whole house](entities.md#rooms-and-the-whole-house)).
They are `number` entities, so `number.set_value` drives them:

```yaml
action: number.set_value
target:
  entity_id: number.office_office_bottom_rail_position
data:
  value: 40
```

That moves the bottom rail of every blind in the office to 40 and leaves each one's middle rail
where it was going. When the blinds are already moving together — after a preset, or an
earlier room move — it is **one** request to the hub, a `/control` payload with `RoomID` and
both rail fields, the form a [live test](NORMAN_API.md#post-nmv1control) confirmed; when they
are not, each blind is sent its own move so no middle rail is dragged to a neighbour's. Every
blind moved is checked afterwards and sent its move again if it did not go: the hub accepting a
room request is not proof that every blind carried it out. Stop and jog for a room are its
**Stop**, **Jog up** and **Jog down** buttons; for the house, the hub's **All blinds** ones.

Two positions at once — say bottom 25 and middle 75 for the whole room — are two
`number.set_value` calls, or a scene holding both sliders; the second starts from the first.

Home Assistant can also target the room's **area** with the standard cover action, which sends
each blind its own command:

```yaml
action: cover.set_cover_position
target:
  area_id: den
data:
  position: 40
```

The commands go out one at a time, [Command spacing](options.md#command-spacing) apart (1.6 s by
default), so a room takes a few seconds to go out; that pacing is what keeps the hub from
dropping them.

- **Two-rail blinds move both rails.** The area holds each blind's Bottom rail cover *and* its
  Middle rail cover, so both rails go to 40, leaving the light-filtering fabric across the top
  of the window. To move only the bottom rails, list those covers instead:

  ```yaml
  action: cover.set_cover_position
  target:
    entity_id:
      - cover.den_den_1_bottom_rail
      - cover.den_den_2_bottom_rail
  data:
    position: 40
  ```

- **Shutters are skipped.** Their louvers take only tilt, so add a
  `cover.set_cover_tilt_position` for them.
- **Every cover in the area moves,** including ones from other integrations.

For a position a room goes to often, save it as each blind's favorite in the Norman app instead:
`command: favorite` then sends the whole room there in **one** request to the hub, with no
spacing.

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
| `{SetMotorToTopLimit: 170}` / `{SetMotorToBottomLimit: 170}` | Drive toward the stored limit **while held** — the app repeats it every ~0.3 s inside its Shade Limit Setting screen. One call is a single pulse, so there is no button for it. | yes |
| `{Favorite: 0}` | Go to the favorite position. The **Favorite position** button. Note the app addresses this by `RoomID` + `GroupID`, not `PeripheralUID` — pass those in `fields` to match it, or use [`norman.room_command`](#normanroom_command). | yes |
| `{FindTop: 0}` | Re-sync to the top; the app sends it when entering and leaving limit setup. | yes |
| `{SetTopLimit: 0}` / `{SetBottomLimit: 0}` | Store the **current** position as that limit. | changes the blind's travel |
| `{CleanTopLimit: 0}` / `{CleanBottomLimit: 0}` | Clear a stored limit. | changes the blind's travel |
| `{Calibration: 0}` | Run the motor's calibration. | changes the blind's travel |
| `{StatusRequest: 0}` | Ask this blind to report in; nothing moves. The **Request status** button. | yes |

`Switch` and `Favorite` are confirmed at blind, room, and hub scope. For one blind the app
uses `RoomID` + `GroupID`; the Best privacy, Best view, and Favorite buttons already send
those forms. `ReportBatteryLevel` refreshes a room or the whole hub, while `StatusRequest`
refreshes one blind. This action always fills in `PeripheralUID`, so use
[`norman.room_command`](#normanroom_command) for room or hub presets and refresh. Arbitrary
room and hub positions are confirmed in the raw API but have no integration action yet. The
rest of the vocabulary (`MotorSpeedAdjust`, `ReverseMotorDirection`, and others; see
[docs/NORMAN_API.md](NORMAN_API.md#control-verbs))
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
