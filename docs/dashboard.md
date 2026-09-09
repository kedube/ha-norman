# Dashboard card

The integration ships a Lovelace card, **Norman Shades**, that shows every blind grouped by
room with its battery level and a percentage slider per rail.

```
┌──────────────────────────────────────────────────┐
│ ShadeAuto Hub                            🪟 ☀ ⭐  │
│                                                  │
│ MASTER BEDROOM                 ▲ ■ ▼   🪟 ☀ ⭐  │
│ Master_Bedroom_1                         🔋 100% │
│   Bottom rail  ────●──────  60%          ▲ ■ ▼   │
│   Middle rail  ─────────●─  80%          ▲ ■ ▼   │
│ Master_Bedroom_2                         🔋  74% │
│   Bottom rail  ●──────────   0%          ▲ ■ ▼   │
│                                                  │
│ DEN                            ▲ ■ ▼   🪟 ☀ ⭐  │
│ Den_1                                    🔋  35% │
│   Bottom rail  ──────────●  90%          ▲ ■ ▼   │
└──────────────────────────────────────────────────┘
```

The card header is named after your **hub** — the name it has in Home Assistant, which the
integration takes from the Norman app — so two hubs give two distinguishable cards. Set `title`
to override it, or `title: ""` for no heading text at all.

If your card was added before v0.30 it may already have `title: Shades` saved in its config —
the card picker used to supply that automatically. Remove the `title` line to get the hub name. It carries **Best privacy / Best
view / Favorite** for the whole house, and each room heading carries open/stop/close plus the
same three for that room.

[`examples/dashboard.yaml`](../examples/dashboard.yaml) is a minimal dashboard built on this
card. Paste its view into your dashboard's raw configuration editor.

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

Each room heading carries **▲ ■ ▼** of its own, acting on every blind in that room at once —
including the middle rails of two-rail blinds, so "close the bedroom" closes both fabrics. It
is one service call per press, not one per blind.

This is on by default. For plain headings:

```yaml
type: custom:norman-shades-card
hide_room_controls: true
```

The buttons live in the heading, so `hide_room_names: true` removes them too — there is
nowhere left to put them.

These buttons fan out over Home Assistant's cover entities, so **close** puts *both* rails of a
two-rail blind down. That is not the same as the Norman app's **Best Privacy**, which closes the
bottom fabric while opening the sheer middle rail fully — private, but still lit.

### The app's room buttons

Each heading also carries the app's own three, to the right of the open/stop/close. For
headings without them:

```yaml
type: custom:norman-shades-card
hide_room_presets: true
```

| Button | Does |
|---|---|
| Best privacy | Bottom rail to 0, middle rail to 100 |
| Best view | Both rails to 100 |
| Favorite | The room's stored favorite position |

These send the hub's own room verbs through the
[`norman.room_command`](services.md#normanroom_command) action — one request for the room, not
one per blind — so they behave exactly as the app does. Favorite has no Home Assistant
equivalent and is only reachable this way.

### The whole house

The same three buttons sit in the card's own header, where they move **every** blind on the
hub. To leave the header plain:

```yaml
type: custom:norman-shades-card
hide_home_controls: true
```

| Button | Does |
|---|---|
| Best privacy | Every blind: bottom rail to 0, middle rail to 100 |
| Best view | Every blind: both rails to 100 |
| Favorite | Every blind to its own stored favorite |

Like the room presets these go through `norman.room_command`, but with no room at all — the hub
treats a command with no scope as "everything", so it is one request for the house however many
blinds you have. These are the same three buttons the app's own **All Rooms** screen sends.
Because they are the hub's own verbs this is not a fan-out and needs no room-name match.

They deliberately carry the app's names rather than open/close arrows. **Best privacy** is not a
close: it leaves the middle rail fully open, so a two-rail blind ends private but still lit.

All three work on single-rail blinds as well as two-rail ones — a capture of the app driving a
single-rail shade shows it sending the same three verbs unchanged.

There is no house-wide **stop**: the hub's stop is per blind, so it would have to fan out over
every cover, and a stop that lags the blinds it is stopping is worse than none. Use a room's
stop instead.

The header is drawn for these buttons even if you set no title.

The room presets match on the **hub's** room name while the card groups by Home Assistant
**area**. The integration seeds areas from the hub's room names, so they agree out of the box; if
you rename an area, the preset buttons for it will report that the room is unknown, and name the
ones the hub does know. The house buttons carry no room at all, so nothing there can mismatch.

The sliders drive the integration's `number` entities, so they move in the same 10% steps as
those entities and never disagree with the covers. While you drag a thumb the card holds it in
place rather than letting an incoming hub update pull it back, and the percentage it shows is
what you chose until the blind finishes moving.

## Options

Every option is optional; the card works with none of them.

```yaml
type: custom:norman-shades-card
title: Norman Hub          # omit to use the hub's own name
hide_battery: false        # hide the battery readings
hide_room_names: false     # one flat list instead of room headings
hide_room_controls: false  # remove the open/stop/close from each room heading
hide_room_presets: false   # remove the app's Best privacy / Best view / Favorite per room
hide_home_controls: false  # remove the same three buttons for the whole house, in the header
rooms:                     # only these areas, in this order
  - Master Bedroom
  - Den
default_room: Unassigned   # heading for blinds with no area
bottom_label: Bottom rail  # rename the rail rows
middle_label: Middle rail
```

`title`, `hide_battery`, `hide_room_names`, `hide_room_controls`, `hide_room_presets`, and `hide_home_controls` are also available in the card's visual editor.

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
