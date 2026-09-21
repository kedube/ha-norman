# Options

**Settings → Devices & services → Norman → ⋮ → Configure.** All three options are per hub, and
changing any of them reloads the entry.

| Option | Default | Range | What it does |
|---|---|---|---|
| Poll interval | 0 (off) | 10–3600 s | Re-reads every blind's position from the hub on a timer. |
| Wake sweep interval | 0 (off) | 600–86400 s | Has every blind report in, refreshing the hub's own cache. |
| Command spacing | 1.5 s | 0.3–5 s | Seconds to leave between commands sent to the hub. |

## Poll interval

Updates are normally pushed by the hub over its notification stream, so polling is off by
default. It is a safety net for changes the hub never announces — most often a blind that moved
while its radio was asleep. The poll re-reads the hub's **cache**; it does not ask the blinds
anything, so a position the hub itself has wrong stays wrong until a wake sweep.

## Wake sweep interval

Has every blind report in — battery, position, last seen — the way the Norman app's refresh
button does. Unlike the poll, this refreshes the hub's cache rather than re-reading it, so it
is what corrects a position the hub has wrong. It wakes battery blinds, so the floor is ten
minutes; a few times an hour is plenty.

## Command spacing

**The hub has one radio, and it drops commands sent faster than it can transmit them.** A
script that sent Best Privacy to all thirteen blinds at once had every command accepted and
acknowledged — and eleven of the thirteen blinds never moved, because they never heard theirs.
Nothing in the protocol reports this: the hub answers `Error: 0` and stores the new target
either way. Resending does not help, because a resent burst collides the same way.

So commands are queued and sent one at a time, this many seconds apart. A scene covering every
blind takes a few seconds to go out rather than arriving in one unusable burst — thirteen
blinds at the 1.5 s default take about 20 seconds. Only commands are spaced; status reads and
the push stream are unaffected, so the interface stays responsive while a batch drains.

**When to change it.** The default was measured on a hub with thirteen blinds, and the two
ways of measuring it disagreed. Sending the thirteen commands by hand, 1.0–1.2 s still lost a
few and 1.3 s got them all; running the same scene through a Home Assistant automation kept
dropping a blind now and then at 1.3 s. At **1.5 s** several consecutive whole-house runs
dropped nothing, so that is the default — with a little margin deliberately left in, since the
failure is silent when it happens. Hubs differ — more blinds, longer distances, a noisier
radio environment — so:

- **Raise it** if blinds still miss commands that were sent alongside others. Try 2 s, then
  2.5 s. A blind that misses even when commanded on its own is a range problem, not a spacing
  one, and raising this will not help.
- **Lower it** only if large scenes feel slow *and* every blind is reliably acting on them.
  Below the 0.3 s floor there is no point: that is roughly the rate the hub serialises at
  anyway.

If you also drive the hub from your own scripts or `curl`, pace those the same way — the
integration can only space the commands it sends itself.

For the capture and diagnostics behind all of this, see
[NORMAN_API.md](NORMAN_API.md#control-commands-are-paced).
