# Options

**Settings → Devices & services → Norman → ⋮ → Configure.** All six options are per hub, and
each takes effect straight away, without a reload.

| Option | Default | Range | What it does |
|---|---|---|---|
| Command spacing | 1.6 s | 0.3–5 s | Seconds to leave between commands sent to the hub. |
| Show Norman Shades in the sidebar | on | on / off | Puts Norman Shades in Home Assistant's sidebar. |
| View from the windows | Big Sur coast | Big Sur coast / Lake Tahoe / None | The photograph the sidebar page's windows look out on. |
| Moving view | on | on / off | Sets that photograph moving. |
| Show the weather | on | on / off | Shows the temperature, conditions and forecast at the top of that page. |
| Weather for the view | empty | a weather entity | The weather the view follows and the page shows. |

## Command spacing

**The hub has one radio, and it drops commands sent faster than it can transmit them.** A
script that sent Best Privacy to all thirteen blinds at once had every command accepted and
acknowledged — and eleven of the thirteen blinds never moved, because they never heard theirs.
Nothing in the protocol reports this: the hub answers `Error: 0` and stores the new target
either way. Resending does not help, because a resent burst collides the same way.

So commands are queued and sent one at a time, this many seconds apart. A scene covering every
blind takes a few seconds to go out rather than arriving in one unusable burst — thirteen
blinds at the 1.6 s default take about 21 seconds. Only commands are spaced; status reads and
the push stream are unaffected, so the interface stays responsive while a batch drains.

**When to change it.** The default was measured on a hub with thirteen blinds, and the two
ways of measuring it disagreed. Sending the thirteen commands by hand, 1.0–1.2 s still lost a
few and 1.3 s got them all; running the same scene through a Home Assistant automation kept
dropping a blind now and then at 1.3 s. At **1.5 s** several consecutive whole-house runs
dropped nothing, but longer use still lost a command from time to time, so the default is
**1.6 s** — with a little margin deliberately left in, since the failure is silent when it
happens. Hubs differ — more blinds, longer distances, a noisier
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

## Show Norman Shades in the sidebar

Puts [Norman Shades](dashboard.md) in Home Assistant's sidebar. It is on by default, including
for hubs set up before the option existed. Turn it off to remove the entry; Norman Shades can
still [go on a dashboard](dashboard.md#on-a-dashboard) as a card. With more than one hub, each
hub's switch controls its own entry.

## View from the windows

The photograph the windows on the sidebar page look out on
([the view](dashboard.md#the-view-from-the-windows)): the **Big Sur coast** or **Lake Tahoe**,
each a set of photographs for every part of the day and every kind of weather. A room's windows
share one view, and the page behind the rooms takes its colors, deep in Home Assistant's dark
theme and pale in its light one. It is on, at the coast, by default, including for hubs set up
before the option existed. Choose **None** for the plain page, drawn as a dashboard card is;
either way the page follows Home Assistant's light or dark theme. With more than one hub, each
hub's page has its own view.

The option only changes the sidebar page. A card on a dashboard always draws its own sky.

The photographs are CC0 or in the public domain, so the page carries no credit. The
repository's [`NOTICE`](../NOTICE) file credits each photographer, and this option's description
in the form links to it.

## Moving view

Sets the photograph in the windows moving: its clouds and water drift, rain and snow fall,
stars twinkle, and birds, a moon and shooting stars cross the sky. Turn it off to show the
photograph still, which asks less of a phone or an old tablet. It is shown still as well on a
device set to reduce motion, and in a browser without WebGL 2, whatever this is set to.

## Show the weather

Shows the weather at the top of the sidebar page, under the hub's name: the temperature and
conditions, and the forecast beside them, or under them on a phone. The forecast is now and the
hours ahead, each with its weather, its temperature and, at 30% or more, its chance of rain or
snow ([the forecast](dashboard.md#the-view-from-the-windows)); a weather entity that forecasts
only by the day shows the days ahead instead. All of it is the
[weather entity's](#weather-for-the-view). Turn it off to leave the weather off the page: under
the hub's name there are then only the house's counts, how many shades are open or moving and
any low batteries, and the page asks Home Assistant for no forecast at all. The photograph in
the windows still follows the weather either way.

With the view set to **None** the page shows no weather, whatever this is set to.

## Weather for the view

The weather entity the view follows: rain shows the photograph of rain, with rain falling. The
page also shows that entity's temperature and conditions under the hub's name, and its
forecast beside them ([Show the weather](#show-the-weather)). Leave it empty
and the page uses Home Assistant's own forecast (`weather.forecast_home`, or `weather.home`),
or failing that the first weather entity there is. With no weather entity at all, the view
follows the sun alone and the page shows no weather.

## Polling and wake sweeps

Earlier releases had two more options here, both off by default: a **poll interval** and a
**wake sweep interval**. Neither is needed. The hub pushes every change it hears of, and the
integration re-reads every blind each time it reconnects to the hub, every 5 minutes, so a
notification that goes missing leaves a blind out of date for 5 minutes at most. A hub that had
either set keeps working as before, without them.

To re-read the hub more often, use Home Assistant's own way to
[poll on a schedule](https://www.home-assistant.io/common-tasks/general/#defining-a-custom-polling-interval):
an automation that calls `homeassistant.update_entity` for one of a hub's covers re-reads every
blind on that hub. A re-read only reads what the hub has stored, though; to have blinds report
in, an automation can press a blind's **Request status**, or **Refresh blinds** on a room or
the hub ([Buttons](entities.md#buttons)).
