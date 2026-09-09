# Dashboard card

The integration ships a Lovelace card, **Norman Shades**, that shows every blind grouped by
room with its battery level and a percentage slider per rail.

```
┌────────────────────────────────────────────┐
│ Shades                                     │
│                                            │
│ MASTER BEDROOM                             │
│ Master_Bedroom_1                   🔋 100% │
│   Bottom rail  ────●──────  60%    ▲ ■ ▼   │
│   Middle rail  ─────────●─  80%    ▲ ■ ▼   │
│ Master_Bedroom_2                   🔋  74% │
│   Bottom rail  ●──────────   0%    ▲ ■ ▼   │
│                                            │
│ DEN                                        │
│ Den_1                              🔋  35% │
│   Bottom rail  ──────────●  90%    ▲ ■ ▼   │
└────────────────────────────────────────────┘
```

[`examples/dashboard.yaml`](../examples/dashboard.yaml) is a complete three-view dashboard
built on this card — the whole house on one card, a per-room layout, and the same blinds using
only built-in cards. Paste a view from it into your dashboard's raw configuration editor.

## Adding it

The integration serves the card and registers it as a dashboard resource on its own, so there
is nothing to install. After setting up the integration (and one Home Assistant restart, if you
had just installed the integration itself):

1. Open the dashboard you want it on and enter edit mode.
2. **Add card**, then search for **Norman Shades**.
3. Save. There is nothing to configure; the card finds your blinds by itself.

In **YAML mode** dashboards the resource list is not writable by an integration, so add it
once under your `resources:` as a JavaScript module — the log line at startup names the exact
URL, which is `/norman/norman-shades-card.js?v=<integration version>`.

## What it shows

Blinds are grouped by their Home Assistant **area**, which the integration seeds from the
hub's own room names, so the grouping matches the Norman app out of the box. Moving a blind to
a different area in Home Assistant moves it on the card.

| Element | Notes |
|---|---|
| Room heading | The area name. Blinds with no area are grouped under "Unassigned". |
| Blind name | Click it to open the usual more-info dialog. |
| Battery | From the blind's battery sensor, with the icon following the level. Amber below 30%, red below 15%. |
| Bottom rail | Position slider, 0–100% in steps of 10, with **▲ ■ ▼** (open, stop, close) for that rail. |
| Middle rail | The same row again, on two-rail blinds (day/night, top-down/bottom-up) only. Each rail's controls act on that rail alone. |

A blind the hub has stopped reporting is dimmed and its sliders are disabled.

### Whole-room control

`room_controls: true` puts **▲ ■ ▼** in each room heading, acting on every blind in that room
at once — including the middle rails of two-rail blinds, so "close the bedroom" closes both
fabrics. It is one service call per press, not one per blind.

```yaml
type: custom:norman-shades-card
room_controls: true
```

It is off by default, and it needs the room headings: with `hide_room_names: true` there is
nowhere to put the buttons, so nothing is added. The hub has its own room-wide command, but it
is not reachable from a dashboard card and only drives both rails fully open or closed; going
through Home Assistant's cover service reaches every rail and works the same way as the
per-rail buttons.

The sliders drive the integration's `number` entities, so they move in the same 10% steps as
those entities and never disagree with the covers. While you drag a thumb the card holds it in
place rather than letting an incoming hub update pull it back, and the percentage it shows is
what you chose until the blind finishes moving.

## Options

Every option is optional; the card works with none of them.

```yaml
type: custom:norman-shades-card
title: Shades              # omit for no header
hide_battery: false        # hide the battery readings
hide_room_names: false     # one flat list instead of room headings
room_controls: false       # add open/stop/close to each room heading
rooms:                     # only these areas, in this order
  - Master Bedroom
  - Den
default_room: Unassigned   # heading for blinds with no area
bottom_label: Bottom rail  # rename the rail rows
middle_label: Middle rail
```

`title`, `hide_battery`, `hide_room_names`, and `room_controls` are also available in the card's visual editor.

## Using the built-in cards instead

The card is a convenience, not a requirement — everything it does is available from Home
Assistant's own cards, since the integration exposes plain covers, numbers, buttons, and
sensors. A tile card with a position feature gives one blind a slider:

```yaml
type: tile
entity: cover.living_drape_bottom_rail
features:
  - type: cover-open-close
  - type: cover-position
```

And the rail sliders are ordinary `number` entities, so they work in any card that takes one:

```yaml
type: entities
entities:
  - number.living_drape_bottom_rail_position
  - number.living_drape_middle_rail_position
  - sensor.living_drape_battery
```

## Checking which version you are running

The card takes its version from the URL the integration registers it at, so it always reports
the build the browser actually loaded rather than a number compiled into the file. On load it
prints one line to the browser console (⌥⌘I, or F12, then Console):

```
 NORMAN-SHADES-CARD  v0.19
```

That should match the **Version** shown on the Norman entry under **Settings → Devices &
services**. If it is lower, the browser is running a cached copy — hard-refresh the page. If
it says `unknown`, the resource was added by hand without the `?v=` stamp; the card still
works, but it can no longer be cache-busted on upgrade, so re-register it with the stamp.

A [diagnostics download](../README.md#diagnostics) reports the same comparison under
`frontend`, as `integration_version`, `registered_versions`, and a `version_matches` flag —
useful when attaching to an issue, since it does not depend on the reporter's browser.

## Troubleshooting

**The card is not in the "Add card" list.** Hard-refresh the browser (⇧ and reload) — the
resource is registered at startup, and a tab open from before will not have it. If it is still
missing, check the log for `Registered the Norman shades card` and look under
**Settings → Dashboards → ⋮ → Resources** for `/norman/norman-shades-card.js`.

**"Custom element doesn't exist".** The browser has an older copy cached, or two resource
entries point at the card. The integration repoints stale entries on every start, so a restart
plus a hard refresh usually clears it. A [diagnostics download](../README.md#diagnostics)
reports the version the card should be and what Lovelace actually has registered, under
`frontend`.

**A blind is missing from the card.** The card lists blinds that have a Norman cover entity
which is not hidden or disabled. Check the blind's entities on its device page.
