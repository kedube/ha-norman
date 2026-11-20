# Contributing

Thanks for helping improve the Norman Home Assistant integration.

## Development setup

1. Fork the repository and create a feature branch.
2. Create a virtual environment with **Python 3.14** (Home Assistant 2026.9+ requires it).
3. Install test dependencies:

```bash
pip install -r requirements_test.txt
```

4. Run the test suite:

```bash
pytest -q
```

## Running the CI checks locally

CI runs seven jobs; the two hosted actions (HACS validation and hassfest) cannot be reproduced
without Docker, the rest can. Running these before pushing avoids a round-trip:

```bash
ruff check .                                         # lint
ruff format --check .                                # formatting (run `ruff format .` to fix)
mypy custom_components/norman --ignore-missing-imports  # types
pytest -q                                            # Python test suite
node scripts/check_card.mjs                          # the card, under Node
node scripts/check_layout.mjs                        # the card's layout, in a real browser
```

The layout check needs Google Chrome or Chromium: it finds one on the `PATH` or in the usual
macOS place, or at `CHROME_PATH`. Add `--screenshots <dir>` to keep a picture of every view it
measures.

Formatting is enforced, so run `ruff format .` before committing rather than hand-aligning code.

## Project layout

- `custom_components/norman/` contains the integration code:
  - `api.py` — the hub client and the notification stream parser. Every request goes through
    `_async_request`, which is where transport and protocol errors are normalised.
  - `coordinator.py` — reads the hub, runs the notification listener loop, keeps the device
    registry in step, and sends the room, scene and blind commands.
  - `parsing.py` — turns the hub's device list and status into `NormanPeripheralData` and its
    saved scenes into `NormanScene`: pure functions, no Home Assistant state.
  - `moves.py` — where each blind is heading and making sure a command arrived: the move
    records, the claims that keep a queued command from undoing a newer one, the move
    watchdog, and the rail arithmetic every move shares. Mixed into the coordinator.
  - `entity.py` — the base entity (device info, availability), the `NormanRailMixin` that
    holds the both-rails-in-every-command rule, and the dynamic-add helper every platform
    uses. A platform that moves a blind should use the mixin rather than calling the API
    directly, so the rail-fill logic stays in one place.
  - `cover.py` — the cover entities (one per rail) and the two nudge actions.
  - `number.py` — the per-rail position sliders.
  - `button.py` — the per-blind hub verbs (favorite, jog, run to limit).
  - `sensor.py` — the diagnostic sensors (battery, last seen, signal, firmware) and the
    hub's own (MAC address, time zone, Wi-Fi network and signal).
  - `config_flow.py` — user, zeroconf discovery, and reconfigure steps.
  - `services.py` — the integration-level `room_command`, `get_hub_data` and
    `send_hub_command` actions; the nudge actions live with the covers.
  - `frontend.py` — serves `www/`, adds the Norman Shades sidebar panel for each hub whose
    option is on, and registers the card as a dashboard resource, repointing stale entries after
    an upgrade. Every failure here is logged and swallowed: none of it may block setup.
  - `www/norman-shades-card.js` — the card itself. Plain custom elements, no build step, so
    the file that ships is the file that runs. It reads entities through the registry rather
    than taking a configured list, so a new blind appears without editing the dashboard. The
    card's JS is not executed by the test suite; `tests/test_repo_consistency.py` pins its
    structure (picker registration, element names) and `tests/test_frontend.py` covers
    serving and resource registration.
  - `www/norman-strings.js` — the card's words in every language, shared with the panel. Both
    import it at their own `?v=` stamp, never with a plain relative import: `/norman/` is
    served with long-lived cache headers, so an unstamped URL could pair an upgraded card with
    the previous release's words.
  - `www/norman-panel.js` — the sidebar panel. It hosts the card full screen, passes it Home
    Assistant's `narrow` and the panel's config (`config_entry_id`, with several hubs), and
    keeps clear of a phone's safe areas itself (it registers with `handle_safe_area`). With
    the view option on it also holds the view's stage (the colours behind the page), loads the
    view and hands it to the card.
  - `www/norman-view.js` — the view from the sidebar page's windows: which photograph shows
    for the weather and the sun, the sun's and the moon's positions, where each window looks
    (a room's windows share one strip of the photograph), the page's colours, and the WebGL 2
    pass that sets the photograph's own sky and water moving and draws rain, snow, the moon,
    shooting stars and birds over it, in every window at once. It falls back to the still
    photograph wherever it cannot draw. Loaded by the panel only when the view is on; it
    defines no element.
  - `www/norman-birds.js` — the bird models, **generated** from the
    [Light Control card](https://github.com/kedube/ha-light-control)'s `src/house/birds.ts` by
    `scripts/build_birds.mjs`. Change the birds in that card and build again, not here.
  - `www/view/` — the view's photographs, built by `scripts/build_view.py` from the table in
    `scripts/view/scenes.toml`: for each scene the strip of the photograph the windows look
    out on, two wide by one high and small, and the same part of its map of sky and water,
    plus `scenes.json`, their index. Only CC0 and public-domain photographs can ship; `NOTICE`
    credits each author. They are most of what the view adds to an install, which
    `tests/test_repo_consistency.py` pins at 1 MB.
  - `diagnostics.py` — the export, including the raw `hub_traffic` capture.
- `tests/` contains the pytest suite. Integration tests drive the real code against a fake hub
  registered on `aioclient_mock` (`tests/conftest.py`), so request payloads and error handling
  are exercised for real. `tests/test_repo_consistency.py` pins hand-edited metadata
  (translations, exception translation keys, the observed-field catalogue, `services.yaml`,
  `icons.json`, brand image sizes, manifest links, docs links) that otherwise drifts.
- `.github/scripts/` contains the release helpers (version bump, changelog rotation, release
  notes), covered by `tests/test_release_scripts.py`.
- `docs/` contains the user and contributor reference split out of the README. Keep the README
  as the narrative landing page (install → configure → what you get → troubleshoot) and put
  detail here:
  - [`docs/dashboard.md`](docs/dashboard.md) — Norman Shades, and the card's options on a
    dashboard.
  - [`docs/entities.md`](docs/entities.md) — entities, devices, attributes, availability.
  - [`docs/services.md`](docs/services.md) — all five actions, and the hub verbs `send_hub_command` can send.
  - [`docs/NORMAN_API.md`](docs/NORMAN_API.md) — the hub protocol. Read it before changing
    `api.py` or `coordinator.py`.
- `scripts/check_card.mjs` runs the card and its sidebar panel under Node against a realistic `hass`
  object (`node scripts/check_card.mjs`). The card reads the **frontend** entity registry,
  which does not carry `unique_id` — only `translation_key` and a handful of display fields —
  so a wrong field name there fails silently rather than erroring. Run it after touching
  `www/norman-shades-card.js`; CI runs it in the Card job, and `tests/test_repo_consistency.py`
  pins the same contract.
- `scripts/check_layout.mjs` opens the card and the sidebar panel in a real browser, served from
  `scripts/layout/harness.html` against a fake Home Assistant, at a phone's and a desktop's
  size with touch, a notch and reduced motion emulated, and measures what they draw: nothing
  past the screen's edges, finger-sized targets, rooms side by side on a wide screen, the
  header staying put. `check_card.mjs` uses stand-ins for the DOM and cannot see any of that.
  Run it after touching the card's styles; CI runs it in the Layout job. Its browser has no
  graphics chip there, so with the view on it measures the windows drawn still;
  `node scripts/check_layout.mjs --serve` serves the same page for a browser of your own,
  where the view moves, with no Home Assistant running.
- `scripts/build_view.py` builds the view's photographs (`fetch`, `masks`, `cut`, `index`; its
  docstring says what each step needs), and `scripts/build_birds.mjs` its birds.
- `blueprints/automation/norman/` holds the automation blueprints the README offers.
  `tests/test_blueprints.py` sets each one up as an automation and drives it.
- `custom_components/norman/translations/` holds one file per language. `en.json` is the
  source of truth and must match `strings.json` exactly. Japanese and both Chinese files use
  the vocabulary of the Norman app itself (its language tables ship unencrypted in the app
  bundle; Norman calls the middle rail 中樑 / ミッドレール, a favourite 我的最愛 / お気に入り,
  and so on), so a user reading the app and Home Assistant side by side sees the same terms.
  German, French, and Spanish have no Norman reference vocabulary and were written for this
  integration; corrections from native speakers are welcome. Every file must contain every
  key in `en.json`: `tests/test_repo_consistency.py` fails otherwise. Errors raised by the
  integration are translated too, under `exceptions`; raise them with a `translation_key`
  rather than an English string.
- `scripts/probe_hub_endpoints.py` looks for hub endpoints nobody has documented. It sends an
  identity-only body (`ThingName`, `TaskID`, `Timestamp`) and refuses by name to send anything
  that looks like a write. This is a name-based safeguard, not proof that an unknown endpoint
  is free of side effects:

  ```console
  python3 scripts/probe_hub_endpoints.py <hub-ip>
  ```

  Anything it marks UNDOCUMENTED belongs in `docs/NORMAN_API.md`. To find undocumented
  *fields* rather than endpoints, turn on debug logging and leave it running: the coordinator
  reports every field outside the catalogue in `const.py`, once per name.

  `scripts/explore_hub.py` compares all blind states before and after one `StatusRequest`,
  `ReportBatteryLevel`, or per-blind `RequestModuleInfo`. It prints a dry-run summary by default;
  `--observe-only` measures background reports, and `--execute` sends the selected command.
  Use the [direct hub test workflow](docs/NORMAN_API.md#direct-hub-capability-tests) to interpret
  the result; an `Error: 0` acknowledgement alone is not evidence that blinds acted.

  `scripts/run_hub_scene.py` reads a saved room scene and reports its target count without
  printing names or IDs. With `--execute`, it sends `RoomID` plus `SetToScene` and checks
  actual positions and changes outside the scene. It also defaults to a dry run.

  `tests/test_repo_consistency.py` checks that every relative Markdown link resolves to a real
  file and heading.
- `hacs.json` and `manifest.json` contain release and integration metadata.
- `custom_components/norman/brand/` holds the icon (`icon.png` 256×256, `icon@2x.png` 512×512:
  the brass "N" monogram) and logo (`logo.png` / `logo@2x.png`: the full wordmark, 256 / 512 px
  tall). Since Home Assistant 2026.3 the core `brands` component serves these straight from the
  integration directory (the [Brands Proxy API](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api)),
  so there is nothing to submit anywhere; the `home-assistant/brands` repository no longer takes
  custom-integration images. Only `icon.png` is mandatory: HA falls back along
  `logo → icon`, `@2x → normal`, `dark_* → light`, so add `dark_icon.png` etc. only if the brass
  artwork ever needs a dark-mode variant. `tests/test_repo_consistency.py` checks the sizes and
  that HA actually serves the icon.

## Adding support for another Norman product

Every `ModuleType` the Norman app knows is mapped (1, 32, 33, 48, 49, 80; see the cover-type
table in `docs/NORMAN_API.md`), four of them from the app alone. Anything else is treated as
two-rail with a warning. To map another product, or confirm one of the app-only ones:

1. Get the raw hub payloads with the product paired: run the `norman.get_hub_data` action
   from Developer tools, or take a [diagnostics export](README.md#diagnostics) and read
   `hub_traffic.latest_raw`. Note the peripheral's `ModuleType` and `ModuleDetail` and how its
   rails behave when it moves.
2. Add the `ModuleType` to `MODULE_TYPE_COVER_TYPES` in `const.py` — or, where one type covers
   several products, the pair to `MODULE_DETAIL_COVER_TYPES` — adding a cover type constant if
   none of the existing ones fits.
3. If it needs new behaviour, add an entity class in `cover.py` (subclass `NormanCoverBase`)
   and register it in `COVER_CLASSES`. Add its product name to `MODULE_TYPE_MODELS` (or
   `MODULE_DETAIL_MODELS`) in `entity.py`.
4. Add the payload to `tests/const.py` (and to `EVERY_NEW_PRODUCT` there) and cover the new
   behaviour in `tests/test_products.py`.
   Only a two-rail type gets middle-rail entities; a type that used to fall back to two-rail
   has its old ones deleted at startup (`async_remove_entity` in `entity.py`).
5. Update the **Supported devices** table in the README and the type tables in
   `docs/entities.md` and `docs/NORMAN_API.md`.

## Pull requests

Please keep pull requests focused and include:

- a clear summary of the change
- tests for behavior changes when practical
- updated documentation when setup, behavior, or actions change
- a line under **Unreleased** in [CHANGELOG.md](CHANGELOG.md); the release workflow turns it into
  the release's Highlights

If you are fixing a bug, linking the issue in the pull request description is helpful.

## Reporting issues

Please use the GitHub issue templates for bug reports and feature requests. When possible, include:

- Home Assistant version
- integration version
- installation method
- the blind type
- relevant logs, and a diagnostics export for anything involving blind state

## Notes

- Do not commit diagnostics exports or logs containing addresses from your own network.
- The `main` branch is intended to stay stable and should be updated through pull requests.
- A push to `main` runs CI and nothing else. To release, run **Actions → Release → Run
  workflow**. It checks that CI passed on `main`'s latest commit, bumps the manifest version in
  `custom_components/norman/manifest.json` using `major.minor` format (two-digit minor, e.g.
  `0.11`), commits that bump, creates a matching git tag, and publishes a GitHub release whose
  notes are the rotated **Unreleased** changelog section plus the commit list. `bump: minor` is
  the default; use `bump: major` for a breaking change, or `bump: none` to publish the current
  manifest version again (for example, if creating the release failed after the bump was
  pushed).
