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

CI runs four jobs; the two hosted actions (HACS validation and hassfest) cannot be reproduced
without Docker, the other two can. Running these before pushing avoids a round-trip:

```bash
ruff check .              # lint
ruff format --check .     # formatting (enforced -- run `ruff format .` to fix)
pytest -q                 # Python test suite
```

Formatting is enforced, so run `ruff format .` before committing rather than hand-aligning code.

## Project layout

- `custom_components/norman/` contains the integration code:
  - `api.py` — the hub client and the notification stream parser. Every request goes through
    `_async_request`, which is where transport and protocol errors are normalised.
  - `coordinator.py` — merges the hub's device list and status into `NormanPeripheralData`
    and runs the notification listener loop.
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
  - `services.py` — the integration-level `get_hub_data` and `send_hub_command` actions; the
    nudge actions live with the covers.
  - `frontend.py` — serves `www/` and registers the Lovelace card as a dashboard resource,
    repointing stale entries after an upgrade. Every failure here is logged and swallowed:
    the card is a convenience and must never block setup.
  - `www/norman-shades-card.js` — the card itself. Plain custom elements, no build step, so
    the file that ships is the file that runs. It reads entities through the registry rather
    than taking a configured list, so a new blind appears without editing the dashboard. The
    card's JS is not executed by the test suite; `tests/test_repo_consistency.py` pins its
    structure (picker registration, element names) and `tests/test_frontend.py` covers
    serving and resource registration.
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
  - [`docs/dashboard.md`](docs/dashboard.md) — the bundled card and its options, with a
    worked dashboard in [`examples/dashboard.yaml`](examples/dashboard.yaml).
  - [`docs/entities.md`](docs/entities.md) — entities, devices, attributes, availability.
  - [`docs/services.md`](docs/services.md) — all four actions, and the hub verbs `send_hub_command` can send.
  - [`docs/NORMAN_API.md`](docs/NORMAN_API.md) — the hub protocol. Read it before changing
    `api.py` or `coordinator.py`.
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
  that could write, so it cannot move a blind:

  ```console
  python3 scripts/probe_hub_endpoints.py <hub-ip>
  ```

  Anything it marks UNDOCUMENTED belongs in `docs/NORMAN_API.md`. To find undocumented
  *fields* rather than endpoints, turn on debug logging and leave it running: the coordinator
  reports every field outside the catalogue in `const.py`, once per name.

  `tests/test_repo_consistency.py` checks that every relative Markdown link resolves to a real
  file and heading, and that the README stays under 500 lines — if that trips, move the newest
  reference material into `docs/` rather than raising the limit.
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

Two `ModuleType` values are mapped (33 two-rail, 32 single-rail); anything else is treated as
two-rail with a warning. To map another product:

1. Get the raw hub payloads with the product paired: run the `norman.get_hub_data` action
   from Developer tools, or take a [diagnostics export](README.md#diagnostics) and read
   `hub_traffic.latest_raw`. Note the peripheral's `ModuleType` and `ModuleDetail` and how its
   rails behave when it moves.
2. Add the `ModuleType` to `MODULE_TYPE_COVER_TYPES` in `const.py`, adding a cover type
   constant if neither existing one fits.
3. If it needs new behaviour, add an entity class in `cover.py` (subclass `NormanCoverBase`)
   and register it in `COVER_CLASSES`; add a model name in `entity.py`.
4. Add the payload to `tests/const.py` and cover the new behaviour in `tests/test_cover.py`.
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
- Successful pushes to `main` automatically bump the manifest version in
  `custom_components/norman/manifest.json` using `major.minor` format (two-digit minor, e.g.
  `0.11`), commit that bump, create a matching git tag, and publish a GitHub release whose notes
  are the rotated **Unreleased** changelog section plus the commit list. A breaking change can
  be released as a major bump by running the **Release** workflow manually with `bump: major`.
