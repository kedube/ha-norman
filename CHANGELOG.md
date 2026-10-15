# Changelog

Notable changes for each tagged release. Versions correspond to git tags and to the
`version` field in `custom_components/norman/manifest.json`. Add entries under
**Unreleased** as part of each change; the release workflow rotates that section into a
version heading and publishes it as the release's Highlights.

## Unreleased

- **Covers read opening and closing** while the hub has a target their rail has not reached, for
  up to 3½ minutes, so automations, voice assistants and Home Assistant's own cards see a move
  under way, not only Norman Shades.
- **A warning names blinds that share a remote channel.** The hub sends a preset to every blind
  on the channels it is addressed to, so such blinds move together on each one's Best privacy,
  Best view and Favorite.
- **The docs point Gen 1 hub owners to a separate integration**, and advise against using the
  hub from Apple Home and Home Assistant together.
- **Hub behaviour measured on 2026-10-15 is in the API notes:** `GroupID` is a channel bitmask; a
  stopped blind reports where it stopped within 3 s and the hub's target follows; the
  notification request's body is ignored; some blinds report a move only a minute or more after
  making it, unless asked.
- **The docs name the hub this is for:** the Norman Gen 2 Hub, set up with Norman's ShadeAuto
  app.

## 0.88 — 2026-10-15

- **Moving a blind's other rail no longer restarts a stopped move.** Within about 10 s of a stop
  or a jog, moving a two-rail blind's other rail, a SmartDrape's vanes or a room slider sent the
  stopped rail on to where it had been going. The next move after a stop, a jog or a preset now
  reads the hub first, and waits up to 10 s for the blind to report where it stopped.
- **A stop goes ahead of the commands waiting to be sent.** A command whose blinds a stop or a
  newer command takes over while it waits is no longer sent at all: presets, jogs and battery
  reports as well as moves. A stop behind a scene's thirteen queued moves went out after all of
  them, about 21 s later, with every blind started first. A room or hub request that loses some
  of its blinds while it waits now goes to the rest one by one straight away, not after the
  70-second check.
- **Quick shutter louver nudges add up.** Three quick nudges turned the louvers two steps.
- **A blind one point short of where it was sent counts as there.** Sent 25 again from the 24 it
  stopped at, a blind was asked to report in, sent the move twice more and reported as not
  responding.
- **Request status, Refresh blinds and a room's Refresh show the answers sooner.** The read
  straight after the press saw none of them and held back the first answer's read for 10 s; it
  is skipped while the notification stream is up.
- **Command spacing and the sidebar switch apply without reloading the hub.** Turning the sidebar
  entry on or off reloaded the whole hub and cancelled the checks of moves in flight.
- **Discovery no longer contacts a hub already set up at that address** each time Home Assistant
  starts.
- **Deleting a device works while its hub is offline or disabled**, instead of failing with
  "Unknown error".
- **The dashboard card's resource goes with the last hub that is set up**, even when an ignored
  or disabled hub entry remains. Every dashboard load used to ask for the missing file.
- **Saved scenes deleted while Home Assistant was off are removed** even when the hub's first
  device-list read failed and no scenes are left.
- **A second stream outage is logged** after a quiet night: a stream back for a whole cycle with
  nothing moving was still counted as down.
- **Diagnostics** record a notification stream that drops mid-connection, include the hub's
  options, and keep Japanese and Chinese names as written. The hub's MAC address is found when
  it is set up by an IPv6 address.
- **Norman Shades.** Room ▲ ■ ▼ send one command per blind, not one per rail, so a room's stop
  reaches its last two-rail blind about twice as soon. A failed command no longer leaves a blind
  reading "Closing", or its other rail drawn moved. "Not confirmed" shows in the list layout,
  and a blind not confirmed can be sent the position it is drawn at again. A SmartDrape that
  goes unavailable keeps the side it stacks to, and no longer rebuilds the card, closing trays
  and dropping a drag on another blind. Alt, Ctrl and ⌘ arrow-key shortcuts no longer move
  blinds; screen readers hear arrow-key moves at once, and list-layout sliders are named for
  their blinds. The visual editor keeps `title: ""`. A card showing two hubs' blinds is headed
  "Shades", and its presets and ⟳ still name a hub when all of a room's blinds are unavailable.
  The screenshot shows the refresh buttons.

## 0.87 — 2026-10-15

- **Room command descriptions corrected.** The action's help text said `best_privacy` leaves
  the middle rail where it is and `best_view` opens only the bottom rail. `best_privacy` closes
  the bottom rail and fully opens the middle rail, and `best_view` fully opens both. The help
  text also now says that a room `refresh` sends a status request to each blind. Behaviour is
  unchanged.
- **A stop is no longer undone by a move still waiting to be sent.** A room or hub slider that
  moves blinds one at a time skips the blinds a stop or a newer command reaches first. A move,
  preset or scene overtaken while it waited is no longer watched, so it is not sent again after
  the stop. Nor is a move or scene the hub refused as busy tried again once a stop or a newer
  command has taken its blinds over.
- **Stopping a blind no longer makes every Norman entity unavailable for a moment.** A stop that
  landed while a move's check was reading the hub marked the hub's update failed, and Home
  Assistant dropped commands to its entities until the next read.
- **Diagnostics no longer expose the hub's location, name, time zone or address.** The traffic
  log clips long replies, and a clipped device list (any hub with more than a few blinds) kept
  those fields; connection errors kept the hub's address.
- **The notification stream reconnects when the hub stops answering.** A hub that accepted the
  connection but never answered left the integration waiting, with no updates, until restart.
- **Actions need no `config_entry_id` when one hub is set up.** An ignored or disabled entry,
  or a second hub that is not set up, made every action ask for one, and the dashboard card's
  presets failed.
- **Changing the hub's address reloads it once, not twice.** Home Assistant also flagged the
  double reload, and stops accepting it in 2026.12.
- **A reply with a byte that is not UTF-8 is read** instead of failing setup.
- **A blind or room deleted in Home Assistant comes back** if the hub reports it again, without a
  reload. A room that holds only scenes takes the hub's name for it, and is not deleted while
  its scenes exist.
- **Presets read the hub once instead of twice**, and saved scenes are parsed only when the
  hub's device list is read.
- **Dashboard card.** Tiles follow a renamed, disabled or enabled entity without a page reload.
  List-layout sliders keep following the hub after a tap or a scroll, and arrow keys on them
  send one move. Hidden entities are left off the card. The visual editor keeps the focus while
  a title is typed. Arrow-key moves on both rails of a blind are both sent. Rooms with no area
  get no presets, which always failed, and an unpinned card with two hubs sends each preset to
  the right hub. The card no longer scans every entity in Home Assistant on each state change.
- **Refresh from Norman Shades.** Each blind has a **⟳** beside its battery that asks it to
  report in, each room's **⋯** has **Refresh**, and the header has a **⟳** for the whole house.
  Nothing moves, and the battery report that can close shades is not offered. `hide_refresh:
  true` removes them.
- **Norman Shades fixes.** A blind going unavailable mid-drag on a list slider no longer sends
  the half-dragged position. Arrow keys followed by a drag on the same rail send one move, not
  two, and keys pressed during a drag no longer discard it. A dashboard edit redraws the card at
  once instead of leaving it blank. Presets are not sent to a hub that is not set up, and a
  device another integration also has is matched to the right hub. Redraws write only what
  changed, about three times cheaper on a large card.
- **`norman.send_hub_command` takes the blind over.** A move still being checked was sent again
  on top of a verb sent by hand, such as a limit setting or a calibration, and reported as
  failed. A status request still leaves the check running.
- **A wake sweep stops when its hub unloads.** One running across a reload kept sending through
  the old connection, unpaced against the new one.
- **The device list is not re-read on every retry while the notification stream is down.** It
  is read once when the stream drops and again when it returns; status is still read each time.
- **A command cancelled part-way, by an automation restarting, no longer makes every Norman
  entity unavailable** until the next read of the hub.
- **The entry's title follows a hub renamed in the Norman app straight away**, not only at the
  next restart, where it stayed on the old name. A new title no longer reloads the hub.
- **`norman.get_hub_data` returns a device list the hub failed to read**, as it was sent,
  instead of an error.
- **Removing the last hub takes the Norman Shades card off the dashboard resources.**
- **Messages are translated throughout.** Errors no longer carry English phrases such as "set
  position (value: 30)", or button keys, inside a translated sentence; setup and update failures,
  and adding a hub that is already being set up, have messages of their own. The Room field of
  `norman.room_command` now says that leaving it empty addresses the whole hub.

## 0.86 — 2026-10-14

- **Refresh blinds now uses `StatusRequest`.** A single unscoped request brought fresh reports
  from all 13 shades on a live hub within two minutes without moving them. A room refresh sends
  one addressed request per shade because `RoomID` did not constrain `StatusRequest`.
- **The app's battery report is a separate room and hub button.** `ReportBatteryLevel` closed
  both roller and cellular shades in live tests. The button is named **Report battery levels
  (may close shades)**; there is no per-shade form because `PeripheralUID` did not constrain
  the command in an earlier test.

## 0.85 — 2026-10-13

- **Refresh blinds: a caveat, not a change.** On one hub of type 48 roller shades, Refresh
  blinds closed every shade ([#5](https://github.com/kedube/ha-norman/issues/5)), while a status
  request to one of those shades, answered in 2.5 seconds, closed nothing. Refresh blinds sends
  the Norman hub's own report-in request, which moves nothing on cellular shades (verified on
  real hardware), so it stays as it is. What is different on that hub isn't known. Its shades
  also miss some status requests, so connectivity may play a part. If Refresh blinds moves your
  shades, use **Request status** on each shade instead.

## 0.84 — 2026-10-13

- **Scenes in Norman Shades.** Added support for scene groups.

## 0.83 — 2026-10-13

- **Scenes in Norman Shades.** A room's scenes from the Norman app follow its Privacy, View and
  Favorite buttons in the room's ⋯ fold-out, one button each, and run the scene with every blind
  checked afterwards. A room without scenes shows only the three. Scene groups are left out, as
  they act on several rooms.

## 0.82 — 2026-10-13

- **Scenes saved in the Norman app are Home Assistant scenes.** A room scene goes on its room's
  device and a scene group on the hub's, named as in the app. Running one is a single request
  that moves every blind in it to its own stored position, quicker than a Home Assistant scene
  sending one command per blind. Every blind is then checked, and one that never moves is sent
  its stored position on its own. Scenes follow the app as they are added, renamed or deleted;
  the integration never edits them. Diagnostics list them.
- **"Disconnected" is described by the hub's times, not the app's list.** The Connection
  sensor and the wake sweep count a blind as disconnected once the hub has not heard from it
  for 24 hours, the Norman app's own threshold. The docs and the options form said they match
  what the app lists. They don't always, because the app's copy of the last-heard times lags
  the hub's: one evening a phone listed all thirteen blinds as disconnected and a computer
  three, while the hub had heard from every one within the day. Nothing changes in behaviour.

## 0.81 — 2026-10-13

- **Room-wide and hub-wide presets are checked blind by blind.** Best privacy, Best view and
  Favorite for a room or the whole house (the buttons, and `norman.room_command`) go out as
  one request that the hub carries to each blind, and nothing used to check that every blind
  acted on it. Each blind is now checked as if it had been sent the preset on its own: one
  still silent after a minute is asked to report in, and one that never moved is sent the
  preset on its own, up to three sends, then logged and announced with
  `norman_command_failed`. Asking also corrects a blind that moved without the hub hearing
  its report.
- **"Not confirmed" instead of "Closing" for hours.** The hub keeps a blind's old position
  and new target until the blind next reports in. So a blind that missed a command, or
  carried it out without the hub hearing it, read "Closing" in Norman Shades with no end: one
  sat at "Closing · Bottom 100%" for two hours, already closed. Past the 3½ minutes the
  integration spends checking a move, it now reads "Not confirmed", drawn where it was sent
  with the dashed line where the hub last heard it, and offers no Stop.

## 0.80 — 2026-10-13

- **The wake sweep no longer closes roller shades.** It asked every blind on the hub to report
  in, and on a hub of type 48 roller shades that closed every shade each time it ran
  ([#5](https://github.com/kedube/ha-norman/issues/5)). It now asks only the blinds the Norman
  app would list as disconnected (not heard from for 24 hours), as the app does, and sends
  nothing while every blind is connected.
- **Saving the options no longer turns on the wake sweep or polling.** The form filled in 3600
  seconds for the wake sweep and 60 for the poll the first time it was opened, and saved them
  along with whatever else was changed. Both now start at 0, off. An entry that already has
  them keeps its values; if you never chose them, set both to 0 under **Configure**.
- **The poll interval tops out at 300 seconds.** The integration already re-reads every blind
  each time it reconnects to the hub, every 5 minutes, and that restarts the poll's timer, so a
  longer interval never fired. A saved value over 300 now counts as off, which is what it
  amounted to. The poll only shortens how long a missed notification goes unnoticed: it
  re-reads what the hub has stored, so it cannot correct a sleeping blind's position;
  **Request status** or the wake sweep can.
- **Debug logs no longer carry the hub's identity.** The hub's ThingName and location are
  blanked in logged requests and replies, as diagnostics already did, so a debug log can be
  attached to a public issue.
- **Norman Shades in your language.** The page, the dashboard card and its editor, and the
  sidebar entry are translated into German, Spanish, French, Japanese, and Simplified and
  Traditional Chinese. The page and card follow each user's profile language; the sidebar
  entry's title follows the server's language. German now says "Rollo" throughout, as Home
  Assistant does for shades, so **Refresh blinds** reads "Rollos aktualisieren".

## 0.78 — 2026-10-12

- **No more time zone and location repairs.** The hub's location (which also gives it its time
  zone) cannot be changed in the Norman app once the hub is set up, so nothing the repairs
  pointed at could be fixed, and only the hub's own schedules use either. The integration no longer reads the
  hub's schedule list. The time zone sensor still shows unknown while the hub reports none.

## 0.77 — 2026-10-12

- **The hub's entry is named as in the Norman app.** A new entry is still titled
  `Norman Hub (<address>)`, since the hub only gives its name once it is read, but setup now
  retitles it with the hub's name and follows later renames. A title changed in Home Assistant
  is kept, and so is any non-default title when the address is reconfigured.
- **Time zone and location repairs only when a hub schedule needs them.** The Norman app
  cannot set either after the hub's setup, and nothing but the hub's own schedules uses them,
  so a hub without schedules no longer gets a repair it cannot act on. The integration reads
  the hub's schedule list (read-only) to decide, and the repairs now suggest replacing those
  schedules with Home Assistant automations.
- **Repair titles name the hub once.** They read "Lakehouse Shades has no time zone" instead
  of "Norman Hub Lakehouse Shades has no time zone".

## 0.76 — 2026-10-12

- **Rooms the hub cannot name follow their blinds' area.** While the hub cannot read its
  device list, a room whose blinds are all in one area is named after that area and placed
  in it, so a restart or a re-added hub keeps its rooms in place. Home Assistant restores a
  re-added blind's area; a room whose blinds are spread over several areas, or not placed
  yet, keeps its generic name.
- **A repair when the hub loses its time zone or location.** The hub runs its own schedules by
  both, and losing them was silent: Settings → Repairs now warns when the hub reports no time
  zone, one that keeps a different time from Home Assistant's, or no location. Each clears
  itself once the hub reports the setting again. Only whether a location is set is checked;
  the coordinates are not stored.
- **The time zone sensor shows what the hub reports.** It no longer keeps showing an earlier
  zone after the hub stops reporting one.

## 0.75 — 2026-10-12

- **The hub keeps its name when its configuration read fails.** A restart while the hub
  cannot read its device list no longer renames the hub device to the entry title.
- **A device list with no rooms counts as a failed read.** A reply from the hub that reports
  success but carries no `RoomList` is retried instead of renaming every blind and room to
  its generic name.
- **No more "Room <id>" areas.** Setting up while the hub cannot read its device list no
  longer creates an area for each unnamed room; the room's device is left without an area.

## 0.74 — 2026-10-12

- **Shade controls stay available when the hub's configuration read fails.** The integration
  keeps the last good room and name data while updating positions from `status`. After a
  restart it keeps the device and room names already in Home Assistant; a fresh setup uses
  generic names and the room/group IDs in `status`. The configuration read is retried after a
  short delay.
- **Expanded the local API reference.** Direct hub tests confirm saved scene and scene-group
  reads, writes, and activation; the reference also records the observed failure of the hub's
  configuration reader after scene updates and a power cycle. New scripts help inspect hub
  report requests and run a saved scene with actual-position checks.

## 0.72 — 2026-10-11

- **Every room has its own controls, and so does the whole house.** Each of the hub's rooms
  is now a device in its area, with a **Bottom rail position** and **Middle rail position**
  slider (for the rails its blinds have) and **Stop**, **Best privacy**, **Best view**,
  **Favorite position**, **Jog up**, **Jog down** and **Refresh blinds** buttons. The hub's
  device gains **All blinds** bottom and middle rail sliders and **All blinds stop**, **jog
  up** and **jog down**. Each is one request to the hub however many blinds it moves. A room
  slider moves every blind exactly as its own slider would: when the blinds would all be sent
  the same pair, that is one request; when they would not, each is sent its own, so no blind's
  other rail is dragged to a neighbour's. Rooms holding a SmartDrape, PerfectSheer or Shutter
  are moved blind by blind, as the room request has not been tried on them. Every blind a
  slider moves is watched and, if it does not go, sent the move on its own. See
  [Rooms and the whole house](docs/entities.md#rooms-and-the-whole-house).
- **Norman Shades no longer mistakes a room for the hub.** The card titled itself after the
  first Norman device without a cover, which a room device now is too; it now looks for the
  hub's own entities.
- **Confirmed room-wide and hub-wide arbitrary positions on the hub.** A single `RoomID` plus
  `BottomRailPosition` and `MiddleRailPosition` control request moved both office blinds
  to 25/75 and restored them to 0/100. Omitting the address moved two den blinds to 0; a
  third stopped at 18 before all three were restored to 100. The protocol and service docs
  now record these capabilities and which other control scopes remain untested.
- **Direct hub tests also confirmed room and hub stop and jog.** A room stop halted both
  moving office shades, a hub stop halted one, and a hub jog made small changes in office
  and den shades. Single-field room positions are unsafe to infer from per-blind behavior:
  middle-only was rejected, while bottom-only reset the omitted middle target to 0. A
  room restore also needed one per-blind resend despite the hub accepting it. The protocol
  reference records the results and the remaining limits.

## 0.71 — 2026-10-10
- **The example dashboard is gone.** `examples/dashboard.yaml` was a dashboard to paste in by
  hand; Norman Shades is now in the sidebar with nothing to build, and adding it to a dashboard
  is one card from the picker ([docs/dashboard.md](docs/dashboard.md#on-a-dashboard)).

## 0.68 — 2026-10-10
- **Norman Shades is in the sidebar.** Once the integration is set up, **Norman Shades**, every
  blind by room drawn as a window you drag, appears in Home Assistant's sidebar, so there is no
  dashboard to build and no card to add. On a phone it runs edge to edge, with the usual button
  for opening the sidebar. With more than one hub, each gets its own entry showing only its
  blinds. To remove it, turn off **Show Norman Shades in the sidebar** in the integration's
  options. It can still go on a dashboard as a card.
- **On a dashboard, the card can be kept to one hub.** A new `config_entry_id` option, also offered as **Hub**
  in the card's visual editor, shows only that hub's blinds and sends its presets to that hub.
  It is only needed with more than one hub.

## 0.64 — 2026-10-03
- **A blind that ignores every attempt is no longer raised in Repairs.** Giving up on a blind
  after three sends opened a repair issue under Settings, as if something needed fixing; one
  command going unanswered usually does not. It is now only a warning in the log (Settings →
  System → Logs) and the `norman_command_failed` event, which automations can still use to
  notify you. Issues already raised disappear when Home Assistant restarts.
- **Ready for Home Assistant 2026.10.** Schemas are built with probatio, which replaced
  voluptuous in Home Assistant 2026.9 (2026.10 no longer installs voluptuous); earlier releases
  still use voluptuous. The `getmac` requirement is now a minimum version (`>=0.9.5`) rather
  than a pin, since Home Assistant depends on it too.

## 0.63 — 2026-09-30
- **The dashboard card draws Roman shades and PerfectSheers as themselves.** Both used to be
  drawn as a pleated cellular shade. A Roman Shade is now a flat panel with a seam at each
  batten that folds up into a stack of soft folds above its hem as it rises. A PerfectSheer is
  fabric vanes between two sheers that roll up into a cassette; with the shade fully down its
  vanes open with its tilt, showing the view through the sheer between them. Every product the
  hub reports now has its own picture.

## 0.62 — 2026-09-30
- **The dashboard card draws roller shades and SmartDrapes as themselves.** Both used to be
  drawn as a pleated cellular shade. A Roller Shade now hangs plain woven fabric off a roll
  that grows as the shade winds up, with brackets at the ends and a hem bar to drag. A
  SmartDrape is drawn as fabric vanes on a sheer, gathered to the side it stacks to when open
  (left, right or split) and drawn sideways by its leading edge; its vanes turn with its tilt.
  The card tells them apart by the device's model (`ModuleType`/`ModuleDetail`).
- **SmartDrape: new `stack` attribute**, the side the drape gathers to (`left`, `right` or
  `split`), from the hub's `MSDStackType`.

## 0.61 — 2026-09-30
- **Setting both rails at once no longer loses one.** A command that moves one rail sends the
  other where it is heading, and that came from the hub's target alone — which still showed the
  blind as it was until the next status read. A scene setting both rails of a two-rail blind
  (Home Assistant applies its entities at the same moment) always lost the first rail's move,
  and a script setting one rail and then the other lost it whenever the status read after the
  first was held back by the ten-second refresh cooldown. The integration now remembers each
  move it sends until the blind reports it, is stopped, or is sent something else, and fills
  the other rail in from that. SmartDrape and PerfectSheer, whose two values also travel
  together, are fixed the same way.
- **A preset or jog now ends the check on a move still in flight.** Sent while a move's
  watchdog was waiting, a room or hub-wide preset (or a jog) left the check running: it saw
  the blind heading for the preset, took the move for one that never arrived, and sent it
  again — undoing the preset. The check now ends when anything else moves the blind.

## 0.59 — 2026-09-30
- **Every product the Norman app knows is supported.** The app (ShadeAuto 0.8.33) decides from
  a blind's `ModuleType` and `ModuleDetail` what it is and which controls it gets, and the
  integration now follows the same table: Shutter (1), Cellular Shade (32, with 32/3–5 a
  top-down/bottom-up shade on two rails), dual Cellular Shade (33), Roller Shade, Roman Shade
  and PerfectSheer (48 and 49, by detail), and SmartDrape (80). None of them logs the
  unknown-type warning. Types 1 and 49, and the Roman Shade, PerfectSheer and top-down/bottom-up
  details, follow the app alone: nobody has reported one from a hub yet.
- **SmartDrape vanes move to the app's seven stops.** 0.58 treated them as a plain 0–100
  tilt, so "open tilt" sent 100 — which on a SmartDrape closes the vanes the other way. They
  are open at 50 and closed at both ends: the tilt is now how open they are (0, 33, 67, 100),
  and a tilt sent from here is one of the seven values the app sends. A nudge moves at least
  one stop.
- **Shutter: one cover, named Louvers.** Its louvers are the hub's `Position` 0–7; the tilt is
  how open they are, in five steps, and open and close turn them. The dashboard card draws it
  as a plantation shutter whose tilt rod you drag, and a room's Stop leaves it out.
- **PerfectSheer: one `shade` cover**, the shade as position and its vanes as tilt, moving
  independently.
- **Device models carry the app's product names**: type 32 is now "Cellular Shade", and 48 and
  49 are named Roller Shade, Roman Shade or PerfectSheer by detail.
- The `nudge_tilt` step no longer says a negative step "tilts left": positive opens, on every
  product. The API reference no longer claims the hub needs both rails in every move — the app
  sends one on its own — though the integration still sends both.

## 0.58 — 2026-09-30
- **Roller Shades (`ModuleType` 48) are single-rail.** They fell back to two rails, so Best
  privacy and Best view sent to a shade already at that position were judged on a middle rail
  it does not have: the preset always looked missed, was sent twice more, and ended in "did not
  move after 3 attempts" ([#2](https://github.com/kedube/ha-norman/issues/2)). They now get one
  cover and one slider, and a preset they are already at is confirmed quietly.
- **SmartDrape (`ModuleType` 80) is supported.** One `curtain` cover: how far the drape is drawn
  as position, the vanes as tilt. Driven as a two-rail shade, the two carried each other along
  — opening the drape swung its vanes to 100, and tilting the vanes below how far it was drawn
  pulled the drape across. They now move independently. The card draws it as a single shade;
  the vanes are tilted from the more-info dialog.
- **Middle rail entities these blinds no longer have are removed.** The Middle rail cover and
  slider the fallback gave them are deleted at startup rather than left as "no longer
  provided", and the card stops drawing a second fabric on them. Automations that used a
  SmartDrape's Middle rail cover should use its cover's tilt instead.
- Device models now name these products ("Roller Shade", "SmartDrape"), and an unmapped type
  reads "Window covering" rather than "Cellular Shade (dual rail)".

## 0.57 — 2026-09-25
- **A dropped preset is now resent.** Best privacy, Best view and Favorite sent to a single
  blind are checked the way moves are, but the check compared the blind with the hub's target
  *after* asking the blind to report in — and the report-in resets that target to wherever the
  blind is, so a blind that ignored the preset always looked arrived and was never resent. The
  check now keeps the target the hub recorded when it accepted the command.
- **Commands are checked without waiting and resent up to three times.** The check after each
  move or preset runs in the background and listens to the updates the hub already pushes: a
  blind that reports moving ends it with no further requests. A blind still silent after a
  minute is asked to report in and, if it has not moved, sent the command again — now up to
  three sends in all rather than two.
- **A blind that ignores every attempt is flagged.** It raises a repair issue naming the blind,
  which clears itself the next time a command to it is confirmed, and fires a
  `norman_command_failed` event for automations.

## 0.55 — 2026-09-24
- **A two-rail blind's blackout is drawn in the same ivory as a single-rail shade.** The card
  drew it slate grey, which read as a different, darker product; only the light-filtering
  fabric above the middle rail is drawn differently now, see-through so the sky shows.

## 0.54 — 2026-09-24
- **Command spacing raised to 1.6 seconds.** 1.5 s held up over several whole-house runs, but
  longer use still dropped a command from time to time. A thirteen-blind scene now takes about
  21 seconds to go out instead of 20. If you have saved the integration's options before, your
  hub keeps the value it saved: change **Command spacing** under **Configure** to pick this up.
- **Either rail of a two-rail blind can be dragged at any time.** On the card, the two pull
  tabs now sit apart — the middle rail's on the left, the bottom rail's on the right — so both
  can be taken hold of when the rails are together. Before, a fully open blind only ever let
  you pick up the bottom rail. A rail dragged past the other now carries it along instead of
  stopping at it: pull the middle rail down from fully open and the bottom rail comes with it.
- **Moving one rail of a two-rail blind past the other carries the other along.** The middle
  rail hangs above the bottom rail, but a command that moved one rail sent the other back
  unchanged even when the two would cross — "open" on the bottom rail with the middle rail
  half-way asked the hub for a shape the blind cannot make. Now the other rail goes with it in
  the same command: raising the bottom rail above the middle rail raises the middle rail too,
  and lowering the middle rail below the bottom rail lowers the bottom rail. This applies to
  the covers, the tilt commands, the sliders, the nudge actions and the card alike; moves that
  do not cross are unchanged, and single-rail blinds are unaffected.
- **The card draws a two-rail blind's fabrics the right way up.** The light-filtering fabric
  hangs *above* the middle rail and the blackout below it; 0.53 had them the other way round.
  The light-filtering fabric is now drawn see-through, so the sky shows through it by day and
  the night sky after dark. The documentation had the same mix-up and described Best privacy
  as "private, but still lit": it stacks the light-filtering fabric away and draws the
  blackout across the window. Putting both rails down is what leaves the light-filtering fabric
  across it.
- **The card shows each blind's battery percentage** beside its battery icon again, next to the
  blind's status.

## 0.53 — 2026-09-24
- **The dashboard card is redesigned around the shade itself.** Every blind is now a window
  with its shade hanging in it — a cellular shade with a headrail, pleats and a pull tab on
  each rail — laid out in a grid per room. **Drag a pull tab to move that rail**, on single-rail
  and two-rail blinds alike: both the middle and bottom rails of a day/night blind have their
  own tab, and when the two are pressed together the direction you pull decides which one
  moves. On a phone a swipe that does not start on a rail scrolls the page instead, so
  scrolling past the card cannot move a blind. Each rail is also a keyboard slider.
  - A moving blind is drawn where it is going, with a dashed line where it actually is, a
    "Closing · 70%" status and a Stop button on its corner.
  - The light-filtering fabric is drawn translucent and the blackout opaque, and the view
    through the window follows the sun, from day through dusk to night.
  - The header gains a one-line summary (shades open, moving, low batteries); the room presets
    fold out of a **⋯** in each room heading instead of repeating on every row; battery levels
    show as an icon, with the number only when it is low.
  - `hide_picture: true` now gives a compact list with a slider per rail.
  - A configured `rooms:` list now sets the order of the rooms, as documented; it was being
    re-sorted alphabetically.
  - The per-rail open/stop/close buttons are gone: drag a rail to either end to open or close
    it, use the room's buttons for a whole room, or open the blind's details from its name.

## 0.52 — 2026-09-23
- **A refresh no longer floods the hub.** The hub answers a Refresh blinds sweep with one
  notification *per blind* over about half a minute, and every one of them used to trigger a
  full re-read of every blind on the hub — thirteen reads in a burst on the reference hub,
  all competing for the same radio that commands are deliberately paced across. Those reads
  are now batched: the first change is still picked up immediately, and the rest of the burst
  collapses into it. Pressing Refresh blinds, a wake sweep, and a scene that moves the whole
  house are all noticeably quieter on the network, with no change to how fast a single change
  shows up. Reconnecting after an outage still re-reads at once, since that one must not wait.
- **Presets that the blind ignored are now chased reliably.** The watchdog behind Best
  privacy, Best view and Favorite left an entry behind every time it finished, so a blind
  accumulated stale watchdog records for the life of the entry, and pressing a preset twice in
  quick succession could leave the live watchdog untracked — after which a stop could no
  longer cancel it. Both are fixed, and the same fault was present in the move watchdog's
  bookkeeping for a repeated move.
- **Diagnostics downloads stay a sensible size.** The last full response from each hub
  endpoint is kept unclipped on purpose, because a truncated device list is exactly the
  payload a "please support my blind" report needs whole. It had no upper bound at all,
  though, so one malformed oversized response would sit in memory until the integration was
  reloaded. It is now capped generously — far above the real payloads, which are nowhere near
  it — so nothing you would actually report is lost.

## 0.51 — 2026-09-21
- **Command spacing raised to 1.5 seconds.** The gap was first measured by sending thirteen
  commands by hand, where 1.3 s got every blind. Running the same scene through a Home
  Assistant automation kept losing a blind now and then at that setting, so the hand test
  had been the easier case; at 1.5 s several consecutive whole-house runs dropped nothing.
  A whole-house scene takes a few seconds longer and stops silently missing blinds. The
  value remains configurable per hub under **Command spacing**.

## 0.50 — 2026-09-21
- **Diagnostics keep enough history to show the run you are reporting.** The raw traffic
  buffer held 50 exchanges, and a scene covering thirteen blinds produces roughly four times
  the blind count — so the interesting run had already been pushed out of the buffer before
  the download finished, hiding exactly what the report was meant to capture. It now holds
  200, which covers a whole-house scene, its watchdog retries a minute later, and the
  routine traffic around both, while keeping the file small enough to attach to an issue.

## 0.49 — 2026-09-21
- **Whole-house buttons on the hub.** **All blinds best privacy**, **All blinds best view**
  and **All blinds favorite position** on the hub device, matching the Norman app's own All
  Rooms screen. Each is a single request that the hub fans out over its own radio, so they
  are not thirteen paced commands and finish far sooner than moving each blind in turn.
  Verified on hardware with every blind staged at 50/50 first, single-rail blinds included.

## 0.48 — 2026-09-21
- **Scenes no longer silently lose blinds.** The hub has one radio and transmits to blinds
  one at a time. A Best Privacy script that fired all thirteen blinds in the same second had
  the hub acknowledge every one with `Error 0`, store every target — and eleven of the
  thirteen never moved, having missed their transmission. Nothing in the reply distinguishes
  that from success. Commands are now queued and sent one at a time with a measured gap
  between them, so a scene covering several blinds reaches all of them. A burst takes longer
  to dispatch, which is the trade for it actually working.
- **Command spacing option.** The gap is a per-hub setting (**Command spacing**, 0.3 to 5
  seconds) rather than a fixed constant, since hubs differ in blind count, range and radio
  environment. Raise it if blinds still miss a command sent alongside others; lower it to
  make large scenes finish sooner.

## 0.47 — 2026-09-19
- **Wake a quiet blind.** A battery blind's radio sleeps between commands and the hub stops
  hearing from it; its battery, last-seen and position go stale, and the Norman app lists it
  as "Disconnect" with a refresh button. That refresh is now in Home Assistant, captured from
  the app on 2026-09-18 and confirmed against its network library: a **Request status** button
  on every blind (`StatusRequest: 0`, the blind answered within five seconds each time) and a
  **Refresh blinds** button on the hub (`ReportBatteryLevel: 0`, every battery blind reports
  in over about half a minute). `norman.room_command` gains `refresh` for one room. Nothing
  moves; the answers arrive as the hub's own notifications.
- **Connection sensor.** Each blind gets a connectivity binary sensor that turns off once
  the hub has not heard from it for 24 hours — the app's own "Disconnect" rule, read from its
  code — and on again the moment it reports in. It does not affect availability: a quiet blind
  still takes commands. It is the cue for an automation to press Request status.
- **Busy hub retried.** Every move sent while the hub was sweeping its blinds after a refresh
  came back with the hub's `Error 2`, and the same moves succeeded a minute later. A move that
  gets that code is now retried up to three times, five seconds apart, before it fails.
- **Last seen is a liveness time.** The hub's per-blind `Timestamp` moves whenever the blind
  reports in, not only when its state changes; the docs and the availability note said
  otherwise and now do not.
- **Ignored moves are chased.** A blind can accept a move and not go, and the hub then
  reports the old position with the new target until the blind next reports in (one sat
  like that for twelve minutes in the capture). Sixty seconds after every move the
  integration now checks that the blind confirmed the target; if not, it asks the blind to
  report in and, if the report shows it never moved, sends the move once more. A stop
  cancels the watch.
- **Refresh reaches wired blinds too.** The hub-wide sweep never woke the wired (single-rail)
  blinds, but a per-blind status request did, so Refresh blinds and `room_command: refresh`
  now follow the sweep with one request per wired blind in scope.
- **Wake sweep option.** A second interval next to the poll in the integration's options.
  Every interval it has every blind report in, the way the refresh button does, which
  refreshes the hub's own cache; the poll only re-reads it, and the capture showed that
  cache wrong for blinds that had gone quiet. Off by default; ten minutes to a day.
- **Pairing window on the hub.** A **Start pairing** button opens the hub's ten-minute
  pairing window (the app's own request) and a **Pairing mode** sensor shows while it is
  open. Pairing itself still happens at the blind and in the app.

## 0.41 — 2026-09-14
- **The card now draws each blind as a window.** Every blind gets a picture of itself — the
  frame, the head rail, and the fabric hanging down to wherever the hub says each rail is —
  which you move by **dragging**: press anywhere on the picture and the nearest rail follows
  your finger, with the position sent when you let go. A press without movement sends nothing,
  so a mis-tap cannot move a blind. On a two-rail blind both fabrics are drawn, the sheer cell
  above the middle rail and the blackout cell below it, and the two rails cannot be dragged
  past each other because the blind cannot make that shape either. While a rail travels, a
  dashed line marks where it is heading. The position bars and **▲ ■ ▼** pills are unchanged
  and sit below the picture, so the keyboard and screen-reader paths are exactly as they were.
  `hide_picture: true` (also in the visual editor) goes back to bars alone. The picture is
  drawn in CSS rather than from embedded images, so it follows your theme, stays sharp on any
  screen, and scales with the card.
- **The two fabrics are drawn the way the blind is built.** On a two-rail blind the blackout
  cell hangs from the head rail to the middle rail and the sheer hangs from the middle rail to
  the bottom rail — so **Best privacy** (bottom 0, middle 100) draws the *sheer* across the
  window, private but still bright, and a fully closed blind draws the *blackout*. The sheer is
  translucent and warmer than the blackout, so which part of the window is passing more light
  is visible at a glance rather than something you work out from two percentages. The materials
  themselves follow the card this one is modelled on.
- **The window is lit and the shade is what blocks it.** The opening behind the fabric is
  bright and the fabric is darker than it, matching the card this one is modelled on: open is a
  bright window, closed is grey slats over it. Earlier versions had this the other way round,
  which is why the picture never quite looked right however much the fabric was tuned. The
  frame's jambs and sill now use the reference's own proportions too.

## 0.40 — 2026-09-10
- **Fixed the options dialog failing to open.** Choosing **Configure** returned "Config flow
  could not be loaded: 500 Internal Server Error". The poll-interval field paired its selector
  with a plain validation function, and the frontend fetches the form's schema over the
  websocket API, which can only serialize selectors and a few known validators — so building
  the form raised before it could be shown. The range is now expressed by the selector alone
  and the one rule it cannot state ("0, or 10 to 3600") is checked when the form is submitted.
  A test serializes the schema through the same call the websocket API uses, which is what
  the existing options tests missed by driving the flow directly.
- **Polling is now off by default.** It was introduced in 0.39 set to 60 seconds for everyone.
  Push covers most installs on its own, so the poll is now opt-in for the case that needs it —
  a battery blind whose radio sleeps and whose position therefore goes stale. Existing entries
  keep whatever they have configured; entries that never configured it stop polling. The form
  suggests 60 seconds when you switch it on.

## 0.39 — 2026-09-10
- **A sleeping blind no longer reports a stale position.** The hub only pushes a notification
  when it hears from a blind, and a battery blind's radio sleeps to save power — the Norman app
  shows those as "Disconnect", though a command still wakes them and works. With updates driven
  purely by push, a blind that moved while asleep kept serving its last known position
  indefinitely, so `is_closed` answered about the past and automations that check state before
  acting ("close it if it isn't closed") silently did the wrong thing. `status` is now also
  re-read every 60 seconds, which corrects the position whether or not the hub says anything.
- **The poll interval is configurable.** The integration gained a **Configure** button:
  10-3600 seconds, or **0 to turn polling off** and go back to relying purely on the hub's
  notifications. Changing it reloads the entry. A value between 1 and 9 is rejected by the
  form rather than quietly replaced by the default, so the page cannot show a number that is
  not the one in force.

## 0.28 — 2026-09-09
- **Clearer attribution.** The README now states that roughly 80% of the original code has been
  rewritten and which parts are new, and a `NOTICE` file records the Apache-2.0 attribution to
  Keito Uchiyama's `keito/home-assistant-norman` properly. A test keeps the credit from being
  lost in a future edit.
- **Screenshots in the documentation.** The README leads with the card, and shows the
  integration page after setup and a blind's device page; `docs/entities.md` gains the blind and
  hub device pages; `docs/dashboard.md` replaces its ASCII sketch of the card with the real
  thing. All four are downscaled from the original Retina captures (4.3 MB → 1.3 MB), since HACS
  clones this repository onto every install. Tests check that every referenced image exists, has
  alt text, and stays under 600 KB.
- **The card has been redesigned around Home Assistant's own tile idiom.** Each rail is now a
  self-labelled bar — name on the left, percentage on the right, a fill behind them — with one
  segmented ▲ ■ ▼ pill, instead of a native browser slider flanked by a label, a value and three
  loose icon buttons. The app's presets are labelled chips (Privacy · View · Favorite) rather
  than three bare icons, at both the room and the house. A room's blinds sit in one rounded
  group. Every control is 32 px for touch, and control rows wrap beneath their heading on a
  phone rather than squeezing the name out.
- **A moving blind now says so.** A blind takes up to 30 s to travel and the hub reports where
  it *is* the whole way, so a press used to look ignored. The bar now shows "40% → 80%", a
  ghost marker at the target, and lights the stop button until the two numbers meet — all from
  the `target_position` attribute the covers already exposed.
- **The card's heading follows the hub once the device registry loads**, rather than being
  fixed at first render. A configured `title` always wins, whatever it says; remove it to get
  the hub name. Cards added from the picker before v0.30 have `title: "Shades"` saved in their
  config, so those need the title removed once.
- **The card names your hub in its header** instead of saying "Shades". Two hubs now give two
  cards you can tell apart. An explicit `title` still wins, `title: ""` gives a blank heading,
  and "Shades" remains the fallback when no hub device can be found. The heading also follows a
  hub rename rather than being fixed at first render.
- **Fixed a blocking file read on the event loop.** `frontend.py` read `manifest.json` at import
  time to get the card's version. Home Assistant instruments `Path.read_text` precisely to catch
  that, and this module is imported on the event loop when a user downloads diagnostics. The
  version now comes from Home Assistant's loader, which has already parsed and cached the same
  manifest, so there is no disk access at all. A test walks the module's AST to keep it that way.
- **A failing scheduled CI run now opens an issue.** The weekly run exists to catch a new Home
  Assistant release breaking the integration from the outside, but a red scheduled run notifies
  nobody. It now files one issue per outage (commenting on it rather than opening another if it
  keeps failing), and only for the schedule.
- **A malformed hub payload no longer takes every blind offline.** Where the hub sends a list
  of objects, `_process_data` assumed it got one: a string, a scalar, or a list of non-objects
  in any of the four nesting levels raised `AttributeError` out of the coordinator, which Home
  Assistant catches only by logging a stack trace and marking **every** entity unavailable —
  for what may be one bad record among twenty. Unreadable records are now skipped and the rest
  of the house keeps working.
- **The notification listener now survives an unexpected error.** It caught only connection
  drops, so anything else escaped its loop and ended the task for good. Because there is no
  polling fallback, that left the integration loaded and apparently healthy while it silently
  stopped updating forever. It now logs and retries, like a dropped connection.
- **`strict-typing` complete (quality scale, Platinum).** The integration now checks clean
  under mypy, and a CI job keeps it that way.
- **Replaced an `assert` in the config flow** with an explicit abort: `python -O` strips
  asserts, which would have produced an entry titled "Norman Hub (None)".
- **Corrected the protocol reference on concurrency.** It claimed the integration never has two
  hub requests in flight; `PARALLEL_UPDATES = 0` and the background listener mean it can.
- **The card's checks now run in CI.** `scripts/check_card.mjs` executes the card against a
  realistic `hass` object, and nothing ran it automatically — 800 lines of JavaScript were
  verified only when someone remembered to. It is now a CI job alongside ruff and pytest.
- **New guards against the documentation going stale**: `docs/entities.md` is checked against
  the entity descriptions that actually exist (names, counts, and which entities are disabled
  by default), and every card option the editor exposes must appear in `docs/dashboard.md`.
- **Removed two unused constants**, `HUB_CMD_TO_TOP_LIMIT` and `HUB_CMD_TO_BOTTOM_LIMIT`, left
  behind when the run-to-limit buttons were dropped. A comment records why they are absent.
- **Fixed the card mistaking another sensor for the battery.** The battery was matched on
  either its translation key *or* an entity id ending in `_battery`, unlike every other
  entity, which only falls back to the id when the key is missing. A Norman sensor a user had
  renamed to end in `_battery` could therefore displace the real reading. Now guarded like
  the rest, with a regression test.
- **The app's Best privacy / Best view / Favorite buttons now ship on by default**, per room and
  for the whole house. They were opt-in behind `room_presets` / `home_controls`, which meant a
  fresh card showed neither and you had to find a YAML key to get them. Opting out is now
  `hide_room_presets: true` / `hide_home_controls: true`, matching `hide_room_controls`.
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
  [docs/dashboard.md](docs/dashboard.md).

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
