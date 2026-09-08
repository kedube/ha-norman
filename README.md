# Norman smart blinds for Home Assistant

A custom Home Assistant integration for [Norman](https://www.normanshutters.com/) motorized
window coverings. It talks to the **Norman Hub directly on your local network** — nothing goes
through the cloud — and it is **push-based**: when a blind moves, whether from Home Assistant,
a remote, or the Norman app, Home Assistant sees the change within a second or two.

> ⚠️ This is an **unofficial** integration, reverse-engineered from the hub's local API. It is
> not affiliated with or endorsed by Norman. The protocol has no vendor documentation and could
> change in a hub firmware update. Use at your own risk; it may void your warranty.

[![CI](https://github.com/kedube/ha-norman/actions/workflows/ci.yml/badge.svg)](https://github.com/kedube/ha-norman/actions/workflows/ci.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![Release](https://img.shields.io/github/v/release/kedube/ha-norman?sort=semver)](https://github.com/kedube/ha-norman/releases)

## Contents

- [Installation](#installation)
- [Configuration](#configuration)
  - [Changing the hub address](#changing-the-hub-address)
  - [Removing the integration](#removing-the-integration)
- [What it provides](#what-it-provides)
  - [Entities](#entities)
  - [Actions](#actions)
  - [Automation ideas](#automation-ideas)
- [How it works](#how-it-works)
- [Supported devices](#supported-devices)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)
- [Diagnostics](#diagnostics)
- [Development](#development)
- [Disclaimers](#disclaimers)

**Reference docs** (split out of this README to keep it browsable):

| Document | Contents |
|---|---|
| [docs/entities.md](docs/entities.md) | Every entity, device, attribute, and availability rule |
| [docs/services.md](docs/services.md) | The `nudge_position` and `nudge_tilt` actions |
| [docs/NORMAN_API.md](docs/NORMAN_API.md) | The hub's local API, for contributors |

## Installation

> Requirements:
>
> - A Norman Hub on the same network as Home Assistant, reachable on TCP port 10123.
> - Home Assistant 2026.3 or newer (`hacs.json` declares this minimum; it is what the
>   bundled brand icon needs). The test suite runs against 2026.9.

### Method 1: HACS custom repository

1. In Home Assistant, open **HACS**.
2. Open the menu in the top-right corner (**⋮**) and select **Custom repositories**.
3. Paste this repository's URL: `https://github.com/kedube/ha-norman`
4. Set the category to **Integration** and click **Add**.
5. Search for **Norman** in HACS, open it, and click **Download**.
6. Restart Home Assistant.

After restart, add the integration from Home Assistant:

[![Open your Home Assistant instance and start setting up a new Norman integration instance.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=norman)

### Method 2: Manual installation

1. Copy `custom_components/norman` into your Home Assistant `config/custom_components` directory.
2. Restart Home Assistant.
3. Add the integration from **Settings > Devices & services > Add integration**.

## Configuration

The only setting is the hub's address, and usually Home Assistant finds it for you.

**Discovered.** The hub announces itself on the local network, so once the integration is
installed a **Norman Hub (address)** card appears under **Settings → Devices & services →
Discovered**. Click **Add**, confirm, and Home Assistant contacts the hub, reads its identity,
and creates one cover entity per blind, named as in the Norman app. Discovery needs Home
Assistant and the hub on the same network segment (mDNS does not cross routers or most VLANs).

**By address.** If nothing is discovered:

1. Add the integration (see [Installation](#installation)).
2. Enter the hub's **IP address or hostname** (no port, no `http://`). Look in your router's
   client list for a device named after the hub (its hostname is `Dexatek`), or check the Norman
   app's hub settings.
3. Submit.

The hub identifies itself by a stable name, so re-adding the same hub by a different address
updates the existing entry instead of creating a duplicate, and a discovered announcement from a
hub that is already set up refreshes its stored address rather than offering it again. That
makes a DHCP address change self-healing; a **fixed address** (a DHCP reservation) in your router
is still the simplest setup. Entries created by versions before 0.11 are re-keyed to the hub's
name automatically on their next load. Several hubs can be added, each as its own entry.

### Changing the hub address

Open **Settings → Devices & services → Norman → ⋮ → Reconfigure** and enter the new address.
The integration checks that the address belongs to the *same* hub before switching, so entities
and automations are unaffected.

### Removing the integration

Open **Settings → Devices & services → Norman → ⋮ → Delete**. The hub keeps no record of Home
Assistant, so nothing needs to be cleaned up on the hub side. If you installed through HACS,
remove the download there too.

## What it provides

### Entities

One [cover](https://www.home-assistant.io/integrations/cover/) entity per blind with position
and **stop**, and for two-rail blinds (day/night, top-down/bottom-up) a second **Middle rail**
cover for the other fabric, plus diagnostic sensors and a device for each blind and for the
hub. All position values are 0–100, with 0 closed and 100 open, as everywhere else in Home
Assistant.

| Entity property | Meaning |
|---|---|
| `current_position` | Bottom rail: 0 closed, 100 open |
| `current_tilt_position` | Middle rail as tilt (for drapes; shades use the Middle rail cover instead): 0–100 |
| `target_position`, `target_tilt` (attributes) | Where each rail is heading while the blind moves |

Each blind also has **buttons** for its favourite position, jog up, jog down, and run to top
or bottom limit, plus diagnostic sensors for **battery** (percent),
**last seen**, and, disabled by default, **signal strength** and **firmware version**; the hub
has a **Wi-Fi signal** sensor, also disabled by default. Full detail, including availability
rules, is in [docs/entities.md](docs/entities.md).

### Actions

Alongside the standard cover actions, the integration provides two relative-move actions for
automations and buttons, and one troubleshooting action:

- `norman.nudge_position` — move by `step` (positive opens, negative closes).
- `norman.nudge_tilt` — tilt by `step` (direction depends on the blind; on SmartDrape,
  negative tilts left).
- `norman.get_hub_data` — returns the hub's raw device list and status as a response, for
  bug reports and for adding support for new blind types.
- `norman.send_hub_command` — advanced: sends arbitrary fields to the hub's control call for
  one blind. The verbs the Norman app uses (fine-tune, run to a limit, set or clear limits,
  calibrate) are documented and can be sent this way; they have no entity of their own yet.

The nudges are relative to where the blind is **heading**, so repeated presses add up, and both
clamp to 0–100. See [docs/services.md](docs/services.md).

### Automation ideas

Close the drapes at sunset, keeping whatever tilt they have:

```yaml
triggers:
  - trigger: sun
    event: sunset
actions:
  - action: cover.close_cover
    target:
      entity_id: cover.living_drape
```

A dashboard button that nudges the tilt a little at a time:

```yaml
type: button
name: Tilt left
tap_action:
  action: perform-action
  perform_action: norman.nudge_tilt
  target:
    entity_id: cover.living_drape
  data:
    step: -10
```

Notify if a blind stops responding:

```yaml
triggers:
  - trigger: state
    entity_id: cover.living_drape
    to: unavailable
    for: "00:10:00"
actions:
  - action: notify.notify
    data:
      message: The living room drape has been unreachable for 10 minutes.
```

## How it works

- **Local only.** Every request goes to the hub's HTTP API on port 10123 of your LAN. The
  integration never contacts Norman's servers and opens no listening ports.
- **Push updates.** The integration holds a long-poll connection open to the hub. Whenever a
  blind's state changes, the hub sends a notification and the integration re-reads the status of
  every blind. There is no polling interval.
- **Reconnects.** The long-poll is recycled every 5 minutes (old connections go quiet), and
  re-established 15 seconds after any drop. Every reconnect re-reads the list of blinds, so a
  blind paired after setup shows up without a restart.
- **Renames follow the app.** The hub also announces edits made in the Norman app; renaming a
  blind, a room, or the hub there updates the matching device name in Home Assistant within a
  second. A name you set in Home Assistant yourself is kept.
- **Commands.** Each move is sent to the hub, then the status is re-read so the entity reflects
  the blind as it moves. The hub's move command always takes *both* rails, so the untouched rail
  is sent back at its current target. Stop sends the hub's motor-stop verb, the same one the
  Norman app's stop button sends.
- **Discovery.** The hub announces itself over mDNS; Home Assistant offers it, and re-announcements
  from a known hub update its address.

The protocol itself is described in [docs/NORMAN_API.md](docs/NORMAN_API.md).

## Supported devices

| Device | Hub `ModuleType` | Exposed as |
|---|---|---|
| Norman Hub (`NienMadeHub`, firmware 6.x) | — | Required. The integration only talks to the hub. |
| Two-rail coverings (day/night, top-down/bottom-up, SmartDrape) | 33 | Two covers: the primary (bottom rail, with the middle rail also as tilt) and a **Middle rail** shade for the second fabric. Tested on day/night shades. |
| Single-rail coverings (roller and honeycomb style) | 32 | Cover with position only, `shade` device class. Tested on a real hub. |
| Anything else | other | Treated as two-rail, and a warning asks you to report the type. |

The type comes from the hub's `ModuleType`. If your blind shows the warning, or behaves
differently from its type, run the `norman.get_hub_data` action and attach the response to an
issue; the mapping is a one-line change.

## Known limitations

- **No authentication on the hub.** That is the vendor protocol, not a choice of this
  integration: anyone on the LAN can control the blinds. Keep the hub on a trusted network.
- **Only two blind types are mapped**; see [Supported devices](#supported-devices).
- **No speed, direction, or limit-setting entities.** The hub has verbs for these; the
  limit-setting ones can be sent with `send_hub_command` (see
  [docs/services.md](docs/services.md#hub-verbs)), the rest have not been seen from the app.
- **Favourite position is an extrapolation.** The app only sends it room-wide; the per-blind
  button uses the form the hub advertises. Report it if it does nothing.
- **Hub schedules are not exposed.** The hub stores its own sunrise/sunset and clock schedules;
  the integration neither shows nor edits them, since Home Assistant automations do the same
  job with more flexibility. Delete hub schedules that would fight your automations.
- **Entity unique ids are per hub only.** The blind's id from the hub is used as-is, so two hubs
  that happen to reuse an id would collide. This has not been observed in practice.
- **Opening/closing state** is not reported; the cover shows `open`/`closed` from its position
  and exposes the target as an attribute instead.

## Troubleshooting

**Setup fails with "Failed to connect to the Norman Hub".**
Home Assistant could not reach the address on port 10123 within 10 seconds. Check the address
in your router, make sure Home Assistant and the hub are on the same network (or that the route
and firewall allow the connection), and try `curl -X POST http://<hub-ip>:10123/NM/v1/status`
from a machine on the same network; a JSON reply means the hub is reachable.

**A blind or feature the integration does not support.**
Turn on [debug logging](#debug-logging) and leave it for a day. Any field your hub sends that
this integration has never seen is logged once with its value, which is usually all that is
needed to add support. Attach those lines, or a `norman.get_hub_data` response, to an issue.

**Setup fails with "Invalid response received from the Norman Hub".**
Something answered on that address, but not with the hub's protocol (a different device, or an
error from the hub itself). Double-check the address. If it is the hub, enable
[debug logging](#debug-logging) and open an issue with the log.

**Setup fails with "Enter a valid IP address or hostname".**
Enter just the address: `192.168.1.50` or `norman-hub.local`, without `http://`, a port, or a
path.

**All covers show *unavailable*.**
The last status read from the hub failed. The integration retries on its own: the log will show
one error when the hub goes away and one info line when it is back. If the hub is powered and
reachable but this persists, restart the hub.

**A change made with the remote or the app takes a long time to show up.**
The push channel is down and the integration is running on command-time refreshes only. Look
for `Notification listener disconnected` in the log. It reconnects every 15 seconds; if the
message keeps repeating at debug level, the hub is refusing the long-poll — a hub restart
usually clears it.

**A blind I just paired does not appear.**
It appears on the next reconnect of the push channel (at most 5 minutes). Reloading the
integration forces it immediately.

**A blind I removed from the hub is still listed.**
Its entities go unavailable; delete the device from its device page (⋮ → Delete). The delete
option is refused while the hub still reports the blind.

**A blind logs "unknown ModuleType".**
The hub reports a product type the integration has not seen. It is treated as a two-rail blind,
which may give it a tilt control that does nothing. Run `norman.get_hub_data` and open an issue
with the response and what the product is.

**Open/close moves the tilt too (or vice versa).**
The hub has no single-rail command, so the integration sends the untouched rail's current
target along with the change. If the hub reports no target and no position for that rail, it
falls back to 100 (open). A [diagnostics export](#diagnostics) shows what the hub reports.

**The hub's address changed.**
Use [Reconfigure](#changing-the-hub-address).

## Diagnostics

The integration supports Home Assistant's diagnostics export: **Settings → Devices &
services → Norman → ⋮ → Download diagnostics**. It contains:

- the last-known state of every blind (names, positions, targets, battery voltage, firmware)
  and whether the last refresh succeeded;
- **`hub_traffic`**: a capture of the communication with the hub, taken below the parsing
  layer. `latest_raw` holds the last complete response from each endpoint (so the full device
  list and status are always there, including fields the integration does not understand), and
  `exchanges` holds the most recent 50 requests, responses, and notification-stream chunks with
  timestamps, HTTP status, duration, and any error.

The hub's address, identity (`ThingName`), location (`GeoLoc`), Wi-Fi network name, time zone,
custom hub name, and network id are redacted everywhere, including inside the raw bodies; real
hubs do send all of these. Everything else is blind state. Because the raw capture may contain fields nobody has
seen yet, skim it before posting; then attach it to the issue. Reproduce the problem shortly
before downloading, since the capture is the last 50 exchanges and is not kept across restarts.

### Capturing a specific problem

1. Reproduce it: move the blind with the remote or the app, send the command that misbehaves,
   or wait for the state that looks wrong.
2. Download diagnostics straight away, before other activity pushes the exchanges out.
3. For an unsupported blind type, the `norman.get_hub_data` action is quicker: run it from
   **Developer tools → Actions** and paste the response into the issue. It returns the live
   raw device list and status.

### Debug logging

**Option 1 — no restart, temporary.** From **Settings → Devices & services → Norman → ⋮ →
Enable debug logging**. Reproduce the problem, then choose **Disable debug logging** to
download the captured log.

**Option 2 — `configuration.yaml`, persistent.** Add a `logger:` block and restart:

```yaml
# configuration.yaml
logger:
  default: warning
  logs:
    custom_components.norman: debug
```

Debug output includes every notification the hub sends and the reasons for each reconnect. It
contains blind ids and positions but no credentials (the hub has none). Turn it back off after
capturing what you need; it is verbose while blinds are moving.

## Development

This repository is structured as a HACS-compatible custom integration repository:

- integration code under `custom_components/norman`
- metadata in `custom_components/norman/manifest.json` and `hacs.json`
- translations in `custom_components/norman/translations/`
- brand images (icon and logo) in `custom_components/norman/brand/`, which Home Assistant
  2026.3+ serves itself for the integrations list and device pages
- a pytest suite under `tests/` that drives the integration against a fake hub at the HTTP
  level (setup, unique-id migration, config flow, covers, sensors, actions, the notification
  stream, the traffic recorder, diagnostics, device removal, brand image serving) and pins repo
  metadata (translations, `services.yaml`, `icons.json`, brand image sizes, docs links) so it
  cannot drift
- GitHub Actions for HACS validation, `hassfest`, Ruff, and pytest ([ci.yml](.github/workflows/ci.yml))
- an automated release on every green push to `main` ([release.yml](.github/workflows/release.yml))
- issue templates, a [contributing guide](CONTRIBUTING.md), a [changelog](CHANGELOG.md), and a
  documented [quality-scale target](QUALITY_SCALE.md)

Version history: each push to `main` publishes a tagged release with generated notes — see the
[Releases page](https://github.com/kedube/ha-norman/releases). The installed version appears in
`manifest.json` and under **Settings → Devices & services → Norman**.

## Disclaimers

For interoperability; no vendor code is included. This project is unaffiliated with Norman.
Use at your own risk; it may void your warranty.

Originally written by [Keito Uchiyama](https://github.com/keito); see the
[license](LICENSE).
