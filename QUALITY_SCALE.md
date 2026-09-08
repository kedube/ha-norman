# Quality Scale Target

`manifest.json` declares `"quality_scale": "custom"`. That is the only accurate value
available: Home Assistant's loader hardcodes every custom integration to `custom` at runtime
regardless of what the manifest says, so declaring `silver` here would pass hassfest and still
be ignored. The tiered scales are reserved for integrations merged into core.

The Silver *rules* remain the engineering target — they are a good checklist whether or not
the badge is claimable — and `custom_components/norman/quality_scale.yaml` tracks them on that
basis. This page explains the status of the ones that are not simply "done".

## Current status

- **Bronze:** complete. Brand images ship inside the integration (`brand/`), which Home
  Assistant 2026.3+ serves itself; the central brands repository no longer accepts custom
  integrations.
- **Silver:** complete. `reauthentication-flow` is exempt because the hub has no
  authentication; `docs-configuration-parameters` because there is no options flow.
- **Gold:** mostly done. Discovery is via mDNS (`_nien_made._tcp.local.`, confirmed from a
  capture of the Norman app); the announcement has no TXT record, so the flow reads the hub's
  identity over HTTP before offering or updating it. Every error the integration raises
  carries a translation key (`exceptions` in `strings.json`), so `exception-translations` is
  done. Open item:
  - (none at Gold) — action errors are plain English strings rather than
    translation keys.
- **Platinum:** `strict-typing` is not enforced (no mypy run in CI).

## Deliberate deviations

- **Entity unique ids are the hub's peripheral id alone**, not prefixed with the hub's
  identity. Prefixing would be more correct for multi-hub setups, but changing unique ids
  regenerates entity ids for every existing install and breaks automations. It is left as-is
  until a migration is worth the disruption.
- **`PARALLEL_UPDATES = 0`.** Entities are push-updated, and the hub queues commands (it
  echoes a per-request `TaskID`), so command calls are not serialised.

## What "done" means for the tests

`test-coverage` is marked done on the basis that every code path with behaviour has a test:
setup/unload/retry and the legacy unique-id migration, both config-flow steps and every error,
every cover command and both nudge actions including clamping and target-following, the
diagnostic sensors and their timestamp parsing, the `get_hub_data` action, device removal, the
notification listener's reconnect and logging behaviour, the stream parser's edge cases, the
traffic recorder's bounds and scrubbing, diagnostics, brand image serving, and the release
scripts. Coverage is not measured numerically in CI; the suite is intentionally behaviour-
driven (a fake hub on `aioclient_mock`) rather than line-driven.
