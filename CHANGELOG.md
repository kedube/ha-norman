# Changelog

Notable changes for each tagged release. Versions correspond to git tags and to the
`version` field in `custom_components/norman/manifest.json`. Add entries under
**Unreleased** as part of each change; the release workflow rotates that section into a
version heading and publishes it as the release's Highlights.

## 0.28 — 2026-09-09
- **The card's whole-house buttons now carry the app's names.** `home_controls` already sent
  Best privacy / Best view / Favorite, but presented them as open/close arrows — misleading,
  since Best privacy leaves the middle rail fully open rather than putting both fabrics down.
  They now match the room buttons in name, icon and order.
- **Confirmed all three room/house verbs work on single-rail blinds.** A per-blind capture of a
  single-rail shade shows the app sending `Switch 0`, `Switch 1` and `Favorite` to it in the
  same `RoomID` + `GroupID` form it uses for two-rail blinds.

## 0.27 — 2026-09-09
- **Per-blind Best privacy and Best view buttons**, completing the set alongside Favorite
  position and matching the three the Norman app offers.
- **Removed the Run to top limit / Run to bottom limit buttons.** They were the wrong shape for
  the verb: the app sends `SetMotorToTopLimit` every ~0.3 s for as long as its OPEN control is
  *held*, and only inside the Shade Limit Setting screen — a single press is one pulse of a
  hold-to-run signal, not a move. Best view and Best privacy reach the same end positions
  through the hub's own verb, so the buttons were also redundant. `send_hub_command` can still
  send the raw verbs.
- **Corrected how `Switch` and `Favorite` address a single blind.** They take `RoomID` +
  `GroupID`, not `PeripheralUID`: a capture of the app's per-blind buttons shows `GroupID: 1`
  moving only the group-1 blind in that room and leaving group 2 untouched. `(RoomID, GroupID)`
  is unique per blind on the hub. `GroupID` had been documented as a remote-control grouping
  the integration exposes nothing for; it is in fact the per-blind address. All three buttons
  now send the app's own payload.

## 0.26 — 2026-09-09
- **House-wide control.** `norman.room_command` now takes an optional `room`: omit it and the
  verb goes to every blind on the hub in a single request. All three commands work this way —
  captured from the app's own **All Rooms** screen, where the payload turns out to be the bare
  verb with no scope field at all. The card gained a matching `home_controls` option putting
  open, close and favorite in its header. Hub-wide favorite reaches only two-rail blinds;
  single-rail ones have no stored favorite.
- **New card option: `room_presets`.** Adds the Norman app's own three room buttons — Best
  privacy, Best view, Favorite — to each room heading, sending the hub's room verbs through
  `norman.room_command`. This reaches positions the card's own controls cannot: Best privacy is
  bottom rail 0 with the middle rail fully open (private, but still lit), where the card's close
  puts both rails down; and Favorite has no Home Assistant equivalent at all. Off by default,
  because it matches the hub's room name while the card groups by Home Assistant area.
- **Protocol reference corrected: `Switch` sets *both* rails.** It was documented as driving
  the bottom rail only. Verified on hardware by staging a two-rail blind at 60/60 and 40/40:
  `Switch: 0` targets bottom 0 / middle 100, and `Switch: 1` targets both 100. The earlier
  reading came from a capture in which the middle rail already sat at 100, so it appeared not
  to move — the reason the doc now says to stage a blind away from its end positions before
  concluding anything about a verb.
- **The per-blind Favorite position button is confirmed working.** It had been documented as an
  unverified extrapolation since the Norman app only ever sends `Favorite` room-wide. Tested
  against a real hub from two different starting positions: `{"Favorite": 0, "PeripheralUID": …}`
  moves that blind alone to its stored favorite. Also documented the reason it is easy to
  mistake for a no-op: the hub answers `Error: 0` immediately and then keeps reporting the old
  position, target included, for the whole ~30 seconds a large shade takes to travel.
- **Protocol reference:** audited against all four packet captures.
  - `StallCurrent` was documented as always `4100`, and is not. It reads as a stall *threshold*
    — the draw at which the motor decides it has hit an obstruction and stops — rather than a
    measurement: it holds one value through a full open and close and at rest. Two blinds moved
    from `4100` to `1240` between captures a day apart with no setting changed, one of them the
    blind a `Calibration` had been run against, which is the likeliest cause.
  - Documented the only non-zero error the hub has ever returned — `Error: 10`, for a
    `PairingMode` request it would not accept — and that the HTTP status stays 200, so the code
    is the only signal.
  - Explained `GroupID`: it is the blind's remote-control button group, meaningful only with
    `RoomID`, not a Home Assistant grouping.
  - Noted that `PacketReceiveRate` has been `0` on every blind in every capture.

## 0.24 — 2026-09-09
- **New action: `norman.room_command`.** Runs the Norman app's own room buttons —
  `best_privacy`, `best_view`, `favorite` — against every blind in a room, in a single request
  to the hub rather than one per blind. `favorite` has no Home Assistant equivalent, so this is
  the only way to send a room to its stored favorite position. Captured from the app and
  confirmed against a real hub; see
  [docs/services.md](docs/services.md#normanroom_command).
- **Protocol reference corrected:** `Switch` drives the **bottom rail only** and leaves the
  middle rail untouched — the doc previously said it moved both rails to 100. That is precisely
  what makes the app's "Best Privacy" work on a day/night shade: the bottom fabric closes while
  the sheer middle stays open. The three app buttons are now documented with the bodies they
  send and the movement observed.
- `scripts/parse_hub_capture.py` reassembles a packet capture of the hub into readable
  request/response pairs, for decoding verbs the integration does not yet know.
- **Whole-room control on the card.** Each room heading carries its own open/stop/close, moving
  every blind in that room at once — including the middle rails of two-rail blinds, so closing a
  room closes both fabrics. One service call per press rather than one per blind. **On by
  default**; set `hide_room_controls: true` (or use the visual editor) for plain headings.

## 0.22 — 2026-09-08
- **Fixed: the dashboard card found no middle rails and no batteries.** It identified entities
  by `unique_id`, which the *frontend* entity registry never sends — `_as_display_dict` carries
  only entity id, platform, area, device, icon, `translation_key` and a few flags. Reading a
  field that is not there fails silently, so two-rail blinds showed a single slider (and the one
  they showed was the middle rail mislabelled as the bottom), and the battery icon was never
  built. Entities are now matched on `translation_key`, with an entity-id fallback. The battery
  also gained a hover and screen-reader label, so its percentage cannot be mistaken for a rail
  position. Added `scripts/check_card.mjs`, which runs the card under Node against a realistic
  `hass` object, plus Python guards that pin the contract in CI.
- **Fixed: the card's open/stop/close only ever moved the bottom rail.** The buttons sat in the
  blind's header and were hardcoded to the bottom-rail cover, so a two-rail blind had a middle
  rail slider but no way to open or stop that rail — and pressing the buttons moved the bottom
  rail instead. Each rail now carries its own **▲ ■ ▼**, targeting that rail's own cover, and
  they are disabled when the blind is unavailable.

## 0.20 — 2026-09-08
- **Protocol reference:** audited against the code and corrected throughout.
  - The flow diagram showed only "cover action" for hub writes; the rail sliders and the five
    buttons take the same path, and the buttons are the only in-integration sender of the jog
    and run-to-limit verbs.
  - `get_hub_data` was described as returning raw payloads — it redacts them — and the
    diagnostics redaction was described as the host and `ThingName` when it covers ten keys.
  - The error table listed only `"Error": 0` as success; the client also accepts `"0"`, an
    absent field, and any `succ…` string. The notification stream's `"Success."` acknowledgement
    was credited to the one code path that never sees it, and errors on that endpoint raise
    `NormanConnectionError` rather than `NormanApiError`.
  - The firmware rule is "`RfFirmwareVersion` when present", not "on single-rail blinds".
  - Documented that the hub's MAC is not in any payload (it comes from ARP), that
    `GetAllPeripheral` is cached while `status` is not, that requests are sequential, and that
    the both-rails rule applies in both directions.
  - Added the two missing sections to the table of contents.
- **Documentation:** corrected the supported-devices claims. The integration was described as
  tested only on SmartDrape, which understated it — motorized cellular shades (single-rail and
  day/night) are what it runs on day to day, with SmartDrape the covering the tilt behaviour was
  originally worked out on. Reworded to say what is actually tested, and to make clear that the
  two `ModuleType` codes describe how many rails a motor has rather than any specific Norman
  product, so any bottom-rail covering should work.
- **The card reports its own version.** It reads the version from the `?v=` stamp on the URL
  the integration registers, so there is no version constant in the JavaScript to fall behind
  `manifest.json`, and it prints the build it actually loaded to the browser console. A
  diagnostics download now compares the registered version against the integration's
  (`version_matches`), which makes a browser running a cached older card obvious instead of
  something to diagnose by eye. See
  [docs/dashboard.md](docs/dashboard.md#checking-which-version-you-are-running).
  A release-process test bumps the manifest with the real workflow script and asserts the
  card's resource URL follows, so the automatic version bump on push can never leave the
  card stamped with the previous release.

## 0.19 — 2026-09-08
- **Dashboard card.** A **Norman Shades** Lovelace card, shipped with the integration and
  registered automatically: blinds grouped by room, each with its battery level and a
  percentage slider per rail in steps of 10. It reads the entity registry rather than a
  configured list, so newly paired blinds appear on their own. See
  [docs/dashboard.md](docs/dashboard.md), and
  [examples/dashboard.yaml](examples/dashboard.yaml) for a complete three-view dashboard to
  copy from — the card on its own, a per-room layout, and the same blinds built from Home
  Assistant's own cards.

## 0.18 — 2026-09-08
- **Documentation:** the README gained an **Upgrading** section (HACS and manual steps, what is
  preserved across an upgrade, and what to expect when a release adds or renames entities), and
  the whole doc set was audited against the code. Corrected: a mangled entity table in the
  README, a stale "battery is volts" claim and status example in the protocol reference, a
  leftover line saying the hub had one sensor when it has four, a firmware-sensor row that
  named the wrong field for single-rail blinds, several places still saying favorite and
  jog "have no entity yet" (they have been buttons since 0.12) including the action's own
  user-facing description in all seven languages, a claim that the limit verbs had never been
  seen from the app when they were captured from it, an outdated module list in the
  contributing guide, an incomplete test inventory, and a self-contradictory quality-scale
  line.

## 0.17 — 2026-09-08
- **Covers are named for their rail.** The primary cover is now "<blind> Bottom rail" rather
  than taking the device's name, so a two-rail blind's two covers read as a pair. Existing
  entity ids are unchanged; only the display name moves.
- **Position sliders sit with the covers.** The rail sliders are no longer in the
  configuration category, so the device page's Controls group holds both covers and both
  sliders.
- **Position sliders.** Each rail gets a `number` entity, 0–100% in steps of 10, that reads and
  writes the same hub values as the cover. Home Assistant hides a cover's position slider in
  its more-info dialog; these render as sliders wherever you place them, and take a plain
  percentage from an automation or a voice assistant.
- **Device pages group the two covers together.** On a two-rail blind the bottom-rail and
  middle-rail covers now sit next to each other at the top of the device page, with every
  button below the divider. The buttons gained the configuration entity category to achieve
  this; they remain enabled, but no longer appear on auto-generated dashboards.

## 0.16 — 2026-09-08

Version bump only; no user-facing changes.

## 0.15 — 2026-09-08
- **Two-rail blinds are two covers.** Day/night and top-down/bottom-up shades have a second
  fabric on the middle rail and the app shows two sliders; a single cover hid it behind a
  tilt control. Each two-rail blind now also has a **Middle rail** cover with its own
  position and stop. The primary cover keeps its tilt for drapes.
- **Firmware version matches the app.** Single-rail blinds report two versions and the app
  shows `RfFirmwareVersion`; the device and firmware sensor now show that one (Den_1: 0.3.20,
  not 4.1.0.4), with both raw values as sensor attributes.
- **Serial number** on each blind's device page (the hub's `PeripheralUID`).
- **Translations:** Japanese, Traditional and Simplified Chinese (using the Norman app's own
  vocabulary), German, French, and Spanish, for the config flow, actions, entity names, and
  error messages.
- **Translated errors.** Every error the integration raises now carries a translation key
  (`exception-translations` on the quality scale is done).
- **Product names from Norman's catalogue.** `ModuleType` 33 devices are now "Cellular Shade
  (dual rail)", the app's own product name for dual-rail (day/night, top-down/bottom-up)
  cellular shades. Single-rail types keep a descriptive name until they are matched.
- **Hub diagnostics:** MAC address, time zone, and Wi-Fi network sensors on the hub device.
  The hub never reports its MAC, so it is resolved from the local network (new `getmac`
  requirement) and attached to the device as a network connection when found.

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
- **Undocumented hub fields are reported.** The integration knows every field real hubs have
  been seen to send; anything else is logged once per name at debug level, so a firmware
  update or an unmapped product surfaces instead of being silently dropped.
- **Endpoint prober** (`scripts/probe_hub_endpoints.py`) finds hub endpoints nobody has
  documented. It is read-only by construction. Running it mapped the hub's complete endpoint
  surface and found two undocumented scene reads (`GetAllScene`, `GetAllSceneGroup`).
- **Buttons per blind:** Favorite position, Jog up, Jog down, Run to top limit, and Run to
  bottom limit, sending the verbs captured from the Norman app. The limit pair is categorised
  as configuration; it drives the motor to its stored limit, which can still work when a
  blind's position tracking has drifted. The favorite verb is confirmed room-wide; its
  per-blind form is the hub's advertised one.
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
