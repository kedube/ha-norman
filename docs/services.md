# Actions (services)

Beyond the standard [cover](https://www.home-assistant.io/integrations/cover/) actions
(`cover.open_cover`, `cover.close_cover`, `cover.set_cover_position`, the tilt equivalents),
the integration registers three actions of its own. The two nudge actions move a blind
relative to where it is heading and target one or more `cover` entities from this integration;
`get_hub_data` reads the hub's raw payloads for troubleshooting. All three appear in the
automation editor's action picker.

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

Adjust a cover's tilt by a relative amount. Only offered for covers that support tilt (on the
current hardware, all of them).

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

## `norman.get_hub_data`

Read the hub's raw device list and status, exactly as the hub sends them, and return them as a
response. Not tied to an entity. Meant for bug reports and for mapping new blind types: the
response includes every field, including ones the integration does not understand.

| Field | Required | Meaning |
|---|---|---|
| `config_entry_id` | only with several hubs | Which hub to read. With one hub configured it can be omitted. |

Response:

```yaml
thing_name: NormanHub-ABC123
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

The response is not redacted (it is the live payload, and `thing_name` identifies your hub), so
remove anything you would rather not share before posting it. The diagnostics download applies
that redaction automatically; see the README's [Diagnostics](../README.md#diagnostics).

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
