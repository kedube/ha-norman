# Changelog

Notable changes for each tagged release. Versions correspond to git tags and to the
`version` field in `custom_components/norman/manifest.json`. Add entries under
**Unreleased** as part of each change; the release workflow rotates that section into a
version heading and publishes it as the release's Highlights.

## 0.12 — 2026-09-08
- **Stop.** Covers support `stop_cover` (and `stop_cover_tilt` on two-rail blinds), sending the
  hub's `MotorStop` verb exactly as the Norman app does. Confirmed from a packet capture of the
  app.
- **Discovery.** The hub announces itself over mDNS (`_nien_made._tcp.local.`); Home Assistant
  now offers it under Discovered, and an announcement from an already configured hub refreshes
  its stored address, so a DHCP change heals itself.
- **Battery as a percentage.** The hub's `BatteryVoltage` is 0–100; the sensor is now a
  battery-class percentage. Existing `..._battery_voltage` entities are migrated in place.
- **Blind types from the hub.** `ModuleType` 33 is a two-rail cover (position + tilt) and 32 a
  single-rail shade (position only). Unknown types fall back to two-rail with one warning.
- **Hub device details and radio sensors.** The hub device shows its model, firmware, and the
  name from the app, and gets a Wi-Fi signal sensor; each blind gets a signal-strength sensor.
  Both radio sensors are disabled by default.
- **`norman.send_hub_command`** action posts arbitrary fields to the hub's control call for one
  blind and returns the reply. The verbs the Norman app uses (fine-tune, limits, calibration)
  are documented in `docs/services.md` and `docs/NORMAN_API.md`.
- **Diagnostics redaction** now also scrubs the hub's location, Wi-Fi name, time zone, and
  custom name inside raw bodies.
- **Buttons per blind:** Favourite position, Jog up, Jog down, and (disabled by default) Run
  to top limit and Run to bottom limit, sending the verbs captured from the Norman app. The
  favourite verb is confirmed room-wide; its per-blind form is the hub's advertised one.
- **Renames follow the Norman app.** The hub announces edits made in the app (`UpdateTime`
  notifications); the integration re-reads the device list on room, blind, and hub edits and
  updates device names in the registry. Names set in Home Assistant are left alone.
- **Protocol reference** gained "Observed fields", "Control verbs", "Room-wide and hub-wide
  control", "Configuration endpoints used by the app" (schedules, renames), and
  "Discovery (mDNS)" sections from real-hub and Norman-app captures.

## 0.11 — 2026-09-07
- **Timeouts are handled.** A slow or absent hub used to surface as an unexpected error
  with a traceback (aiohttp's timeout is not a `ClientError`); it is now a normal
  connection error everywhere: setup retries, the config flow says "cannot connect", and
  cover actions fail with a clear message.
- **Shared web session.** The integration uses Home Assistant's aiohttp session instead of
  creating (and sometimes leaking) its own.
- **Config flow:** the hub's address is validated before connecting, the hub's own identity
  (`ThingName`) is the entry's unique id so an address change is recognised as the same
  hub, and a **Reconfigure** step changes the address in place.
- **Covers keep the other rail where it is heading.** Commands that touch one rail send the
  other rail's current target (then its current position) instead of assuming 100, and the
  nudge actions are relative to the target so quick repeated nudges add up.
- **Newly paired blinds appear without a restart** (the device list is re-read on every
  notification reconnect), and a blind the hub stops reporting becomes unavailable.
- **Notification stream parser** handles UTF-8 characters split across reads, braces inside
  names, and never grows without bound; the periodic reconnect no longer goes through an
  exception.
- **Logging:** a dropped notification stream is logged once, and its recovery once, instead
  of an error every 15 seconds.
- **Devices:** the hub is a device; blinds link to it via `via_device`; entities use
  `has_entity_name`.
- **Diagnostics** export (hub address redacted) and `services.yaml` / translation entries for
  the nudge actions so they show properly in the action picker.
- **Hub traffic capture.** Every exchange with the hub is recorded below the parsing layer
  (last 50, bodies clipped, plus the last full response per endpoint) and exported by
  diagnostics as `hub_traffic` with the address, ThingName, hub location, Wi-Fi name, time
  zone, and hub name scrubbed inside the raw bodies too. New
  `norman.get_hub_data` action returns the live raw device list and status. Debug logging
  now prints every request and response.
- **Diagnostic sensors** per blind: battery voltage, last seen, and (disabled by default)
  firmware version.
- **Device removal:** a blind the hub no longer reports can be deleted from its device page.
- **Legacy entries are re-keyed** from the typed address to the hub's identity on load, so
  duplicate detection and reconfigure work for installs made before 0.11.
- `hacs.json` declares Home Assistant 2026.3 as the minimum version.
- **Repository:** CI (HACS, hassfest, Ruff, pytest), automated releases on every green push
  to `main`, Dependabot, issue templates, a contributor guide, and reference docs under
  `docs/`. Tests moved out of the shipped integration directory into `tests/` and now cover
  setup, migration, config flow, covers, sensors, actions, the API client, the stream parser,
  the traffic recorder, diagnostics, device removal, and brand serving.
- **Brand icon and logo** (from the Norman wordmark) under `brand/`, served by Home Assistant
  2026.3+ directly, and `icons.json` icons for every action.
- Manifest now points at this repository; version scheme changed to `major.minor`
  (`0.10` continues from the earlier `0.1.0`).

## 0.1.0 — 2025-11-07
- Initial release: local control of Norman blinds via the hub with push updates,
  position and tilt, and the `nudge_position` / `nudge_tilt` actions.
