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
- **Gold:** complete. Discovery is via mDNS (`_nien_made._tcp.local.`, confirmed from a
  capture of the Norman app); the announcement has no TXT record, so the flow reads the hub's
  identity over HTTP before offering or updating it. Every error the integration raises
  carries a translation key (`exceptions` in `strings.json`), so `exception-translations` is
  done, and so is the rest of Gold.
- **Platinum:** complete. The integration is annotated throughout and `mypy` reports no issues;
  a CI job runs it on every push so it stays that way. Note that Platinum formally requires the
  *dependencies* to be typed too, which does not apply here: the only runtime requirement is
  `getmac`, and the hub client is part of this repository rather than a third-party library.

## Deliberate deviations

- **Entity unique ids are the hub's peripheral id alone**, not prefixed with the hub's
  identity. Prefixing would be more correct for multi-hub setups, but changing unique ids
  regenerates entity ids for every existing install and breaks automations. It is left as-is
  until a migration is worth the disruption.
- **`PARALLEL_UPDATES = 0`.** Entities are push-updated, and the hub queues commands (it
  echoes a per-request `TaskID`), so command calls are not serialised.

## What "done" means for the tests

`test-coverage` is marked done on the basis that every code path with behaviour has a test:
setup/unload/retry and both unique-id migrations, all three config-flow steps (user, zeroconf
discovery, reconfigure) and every error, every cover command and both nudge actions including
clamping and target-following, the per-rail sliders, the verb buttons, the diagnostic sensors
and their timestamp parsing, the `get_hub_data` and `send_hub_command` actions, device removal,
the notification listener's reconnect, rename-following, and logging behaviour, the stream
parser's edge cases, the traffic recorder's bounds and scrubbing, diagnostics, brand image
serving, the endpoint prober's read-only guarantee, and the release scripts.
`tests/test_repo_consistency.py` additionally pins hand-edited metadata (translations,
exception keys, the observed-field catalogue, `services.yaml`, `icons.json`, brand image sizes,
docs links) against the code. Coverage is not measured numerically in CI; the suite is intentionally behaviour-
driven (a fake hub on `aioclient_mock`) rather than line-driven.
