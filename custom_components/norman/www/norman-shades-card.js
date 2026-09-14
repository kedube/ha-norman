/**
 * Norman shades card.
 *
 * Groups every Norman blind by room. Each blind is drawn as a window with its fabric
 * hanging in it -- draggable, and showing where every rail actually is -- above a percentage
 * slider per rail in 10% steps, with the blind's battery level alongside. Written as a plain
 * custom element with no build step and no external dependencies, so the file that ships is
 * the file that runs.
 *
 * The window is drawn in CSS: the slats are a repeating gradient and the geometry is in
 * percent, so the picture themes itself, stays crisp at any pixel density, scales with the
 * card, and handles however many rails a blind has. (The card this one takes its shape from
 * uses three embedded PNGs for the same job, which is why its travel height is fixed.)
 *
 * Discovery is automatic: the card finds Norman cover entities through the entity registry
 * (via the hass object's `entities` map) and groups them by the area Home Assistant has each
 * device in, which the integration seeds from the hub's own room names. Nothing has to be
 * listed in the card configuration.
 */

// The integration stamps its release version onto the resource URL as ?v= (the cache-bust),
// so the card reports exactly which build the browser actually loaded rather than a constant
// that can silently drift from manifest.json. "unknown" means the resource was added by hand
// without the stamp -- which is also the state a stale browser cache leaves behind.
const CARD_VERSION = new URL(import.meta.url).searchParams.get("v") || "unknown";

const STEP = 10;
// The headbox depth, as a percentage of the picture's height. Shared between the CSS token
// --n-head and the drawing arithmetic: the fabric hangs from the bottom of the headbox, so
// if these two disagree the fabric detaches from it. Keep them equal.
const SHADE_HEAD_PCT = 9;
const DOMAIN = "norman";

// Entities are identified by their translation key, which the entity registry sends to the
// frontend as `tk`. NOT by unique_id: the registry's display payload
// (EntityRegistryEntry._as_display_dict in homeassistant/helpers/entity_registry.py) carries
// only entity_id, platform, area/device/labels, icon, translation_key and a few flags --
// `unique_id` is never sent, so reading it yields undefined for every entity.
const KEY_BOTTOM_RAIL = "bottom_rail";
const KEY_MIDDLE_RAIL = "middle_rail";
const KEY_BOTTOM_POSITION = "bottom_rail_position";
const KEY_MIDDLE_POSITION = "middle_rail_position";
const KEY_BATTERY = "battery_level";

// The Norman app's three presets, as chips. The short label is what is printed; the
// title is the full name, used for the tooltip and for assistive technology.
const PRESETS = [
  { command: "best_privacy", icon: "mdi:blinds-horizontal", label: "Privacy", title: "Best privacy" },
  { command: "best_view", icon: "mdi:weather-sunny", label: "View", title: "Best view" },
  { command: "favorite", icon: "mdi:star", label: "Favorite", title: "Favorite" },
];

const clampToStep = (value) => {
  const clamped = Math.max(0, Math.min(100, Number(value) || 0));
  return Math.round(clamped / STEP) * STEP;
};

const batteryIcon = (level) => {
  if (level === null || level === undefined || Number.isNaN(level)) return "mdi:battery-unknown";
  const rounded = Math.round(level / 10) * 10;
  if (rounded >= 100) return "mdi:battery";
  if (rounded <= 0) return "mdi:battery-outline";
  return `mdi:battery-${rounded}`;
};

const batteryClass = (level) => {
  if (level === null || level === undefined || Number.isNaN(level)) return "unknown";
  if (level <= 15) return "critical";
  if (level <= 30) return "low";
  return "ok";
};

class NormanShadesCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("norman-shades-card-editor");
  }

  static getStubConfig() {
    // No title: the card then names the hub itself. Baking in "Shades" here would mean
    // every card added from the picker carried a hardcoded title the user had to clear.
    return { type: "custom:norman-shades-card" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._rendered = false;
    // Sliders the user is currently dragging. While a thumb is held, incoming state
    // updates must not yank it back to the hub's value, which lags the drag by a second
    // or two. Keyed by entity id.
    this._dragging = new Set();
    // Values written optimistically, so the label reads what the user chose immediately
    // rather than waiting for the hub to confirm. Cleared when the state catches up.
    this._pending = new Map();
    // The header's text node, when the header is drawn (see _update).
    this._headerText = null;
  }

  setConfig(config) {
    this._config = config || {};
    this._rendered = false;
    if (this.shadowRoot) this.shadowRoot.innerHTML = "";
  }

  getCardSize() {
    const blinds = this._hass ? this._collectBlinds().length : 3;
    return Math.max(3, blinds + 1);
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    } else {
      this._update();
    }
  }

  /**
   * Every Norman blind visible to this dashboard, assembled from its entities.
   *
   * A blind is identified by its device id, so the bottom rail, middle rail, sliders and
   * battery sensor are grouped even though their entity ids are independent.
   */
  _collectBlinds() {
    const hass = this._hass;
    if (!hass) return [];

    const registry = hass.entities || {};
    const devices = hass.devices || {};
    const areas = hass.areas || {};
    const blinds = new Map();

    const blindFor = (deviceId, fallbackName) => {
      if (!blinds.has(deviceId)) {
        const device = devices[deviceId] || {};
        const area = areas[device.area_id] || {};
        blinds.set(deviceId, {
          deviceId,
          name: device.name_by_user || device.name || fallbackName,
          room: area.name || this._config.default_room || "Unassigned",
          bottomCover: null,
          middleCover: null,
          bottomNumber: null,
          middleNumber: null,
          battery: null,
        });
      }
      return blinds.get(deviceId);
    };

    for (const [entityId, entry] of Object.entries(registry)) {
      if (entry.platform !== DOMAIN || !entry.device_id) continue;
      if (entry.hidden_by || entry.disabled_by) continue;

      const [domain] = entityId.split(".");
      // `translation_key` is the reliable discriminator; fall back to the entity id's
      // suffix for anything that somehow lacks one (a user-renamed entity keeps its key,
      // so this is belt-and-braces rather than a common path).
      const key = entry.translation_key || "";
      const idEndsWith = (suffix) => entityId.endsWith(suffix);
      const blind = blindFor(entry.device_id, entityId);

      if (domain === "cover") {
        if (key === KEY_MIDDLE_RAIL || (!key && idEndsWith("_middle_rail"))) {
          blind.middleCover = entityId;
        } else if (key === KEY_BOTTOM_RAIL || !key) {
          blind.bottomCover = entityId;
        }
      } else if (domain === "number") {
        if (key === KEY_MIDDLE_POSITION || (!key && idEndsWith("_middle_rail_position"))) {
          blind.middleNumber = entityId;
        } else if (key === KEY_BOTTOM_POSITION || (!key && idEndsWith("_bottom_rail_position"))) {
          blind.bottomNumber = entityId;
        }
      } else if (
        domain === "sensor" &&
        (key === KEY_BATTERY || (!key && idEndsWith("_battery")))
      ) {
        // The `!key` guard matters here as much as on the rails: without it, any Norman
        // sensor whose entity id happens to end in "_battery" is claimed as the battery
        // even when its translation key says otherwise (a user-renamed entity keeps its
        // key, so the key is the authority and the id is only a fallback).
        blind.battery = entityId;
      }
    }

    // A device with no cover is the hub, not a blind.
    return [...blinds.values()].filter((blind) => blind.bottomCover);
  }

  /**
   * The hub's name, as Home Assistant has it.
   *
   * The hub is the one Norman device with entities but no cover -- it carries the MAC
   * address, Wi-Fi and time-zone sensors. Its name is what the user set in Home Assistant,
   * falling back to the name the integration took from the Norman app, so the card header
   * reads as their hub rather than a generic word. `name_by_user` wins, matching how Home
   * Assistant shows the device everywhere else.
   *
   * Returns null when there is no hub to name (no Norman devices at all, or every Norman
   * device has a cover), so the caller can fall back rather than print "null".
   */
  /**
   * The heading to show: the configured title, else the hub's name.
   *
   * A configured `title` always wins, whatever it says -- including `""` for a blank
   * heading. With no title the header names the hub, so a house with two hubs gets two
   * cards you can tell apart; "Shades" is only the fallback for when no hub device can be
   * found (an install with no Norman devices yet, or before the registry has loaded).
   *
   * Note that cards added from the picker before v0.30 have `title: "Shades"` saved in
   * their dashboard config, because `getStubConfig()` used to supply it. Those keep saying
   * "Shades" until the title is removed -- the card cannot tell a saved default from a
   * deliberate choice, and second-guessing a configured title is worse than honouring one.
   */
  _headingText() {
    const configured = this._config.title;
    return configured !== undefined ? configured : (this._hubName() ?? "Shades");
  }

  _hubName() {
    const hass = this._hass;
    if (!hass) return null;

    const registry = hass.entities || {};
    const devices = hass.devices || {};
    const withCovers = new Set();
    const norman = new Set();

    for (const [entityId, entry] of Object.entries(registry)) {
      if (entry.platform !== DOMAIN || !entry.device_id) continue;
      norman.add(entry.device_id);
      if (entityId.startsWith("cover.")) withCovers.add(entry.device_id);
    }

    for (const deviceId of norman) {
      if (withCovers.has(deviceId)) continue;
      const device = devices[deviceId];
      const name = device && (device.name_by_user || device.name);
      if (name) return name;
    }
    return null;
  }

  _roomsOf(blinds) {
    const filter = this._config.rooms;
    const rooms = new Map();
    for (const blind of blinds) {
      if (Array.isArray(filter) && filter.length && !filter.includes(blind.room)) continue;
      if (!rooms.has(blind.room)) rooms.set(blind.room, []);
      rooms.get(blind.room).push(blind);
    }
    for (const list of rooms.values()) {
      list.sort((a, b) => a.name.localeCompare(b.name));
    }
    return [...rooms.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }

  _numberOf(entityId) {
    const state = this._hass.states[entityId];
    if (!state || state.state === "unknown" || state.state === "unavailable") return null;
    const value = Number(state.state);
    return Number.isNaN(value) ? null : value;
  }

  /** A rail's displayed position: the pending write while one is in flight, else the state. */
  _railValue(rail) {
    if (this._pending.has(rail.numberId)) return this._pending.get(rail.numberId);
    const fromNumber = rail.numberId ? this._numberOf(rail.numberId) : null;
    if (fromNumber !== null) return fromNumber;
    const cover = this._hass.states[rail.coverId];
    const position = cover?.attributes?.current_position;
    return position === undefined || position === null ? null : Number(position);
  }

  _railsOf(blind) {
    const rails = [
      {
        key: "bottom",
        label: this._config.bottom_label || "Bottom rail",
        coverId: blind.bottomCover,
        numberId: blind.bottomNumber,
      },
    ];
    if (blind.middleCover || blind.middleNumber) {
      rails.push({
        key: "middle",
        label: this._config.middle_label || "Middle rail",
        coverId: blind.middleCover,
        numberId: blind.middleNumber,
      });
    }
    return rails;
  }

  _isUnavailable(blind) {
    const state = this._hass.states[blind.bottomCover];
    return !state || state.state === "unavailable";
  }

  _render() {
    const style = document.createElement("style");
    style.textContent = `
      /* Colour tokens. Home Assistant exposes the RGB triplets of its palette, which is
         what lets the fills and tints here be translucent -- so they sit correctly on any
         theme, light or dark, rather than assuming a white card. */
      :host {
        --n-fg-rgb: var(--rgb-primary-text-color, 33, 33, 33);
        --n-accent-rgb: var(--rgb-primary-color, 3, 169, 244);
        --n-bg-rgb: var(--rgb-card-background-color, 255, 255, 255);
        --n-radius: 10px;
        --n-control: 32px;
        /* The shade picture, matching the card this one is modelled on.
           ----------------------------------------------------------------------------
           Its three PNGs were decoded to get these values rather than guessed at:

             slat (1x6px):  rgb 188 -> 245 top to bottom, a translucent dark line at the
                            top edge. A LIGHT grey fabric, lit from below.
             rail (137x7):  rgb 248/237/224/232/243/222/193 -- a pale extrusion.
             frame:         off-white, rgb 229 at the top, 232 at the sill, 204 in the
                            headbox -- and the window interior is fully TRANSPARENT.

           That last point is the one I had wrong: the opening is not painted. It is a
           hole, so the card shows through it, and what reads as "light" is simply the
           absence of fabric. A tinted "glass" fill fights the fabric instead of
           contrasting with it. --n-daylight therefore stays very close to the card's
           own background, and only darkens enough to be legible. */
        --n-daylight: linear-gradient(
          to bottom,
          rgba(var(--n-fg-rgb), 0.1),
          rgba(var(--n-fg-rgb), 0.03) 45%,
          rgba(var(--n-fg-rgb), 0.07)
        );
        /* Fabric, frame and hardware are fixed near-whites, as in the original: a blind is
           the colour it is, and a blind rendered as a tint of the text colour inverts in a
           dark theme -- a closed blind would read lighter than its opening, which is the
           one mistake this picture must never make. */
        --n-slat-top: #bcbcbc;
        --n-slat-bottom: #f5f5f5;
        --n-frame: #e0e0e0;
        --n-frame-edge: #b4b4b4;
        --n-head-face: #cccccc;
        --n-rail-face: #ececec;
        --n-head: 9%;
        --n-rail: 7px;
      }
      ha-card { padding: 4px 0 8px; }

      /* Header: the hub's name, and the app's three whole-house presets. */
      .header {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 6px 12px;
        font-size: var(--ha-card-header-font-size, 22px);
        font-weight: var(--ha-card-header-font-weight, 500);
        color: var(--ha-card-header-color, var(--primary-text-color));
        padding: 12px 16px 6px;
      }
      .header-text {
        flex: 1 1 140px;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      /* Room: an uppercase heading with its controls; the blinds sit in a rounded group
         beneath it so a room reads as one object, not a run of hairlines. */
      .room { padding: 8px 12px 4px; }
      .room-name {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 6px 10px;
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--secondary-text-color);
        padding: 4px 4px 8px;
      }
      .room-name-text {
        flex: 1 1 120px;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .group {
        border-radius: var(--n-radius);
        background: rgba(var(--n-fg-rgb), 0.04);
        overflow: hidden;
      }

      /* Blind: name and battery on one line, then one bar per rail. */
      .blind { padding: 10px 12px 12px; }
      .blind + .blind { border-top: 1px solid rgba(var(--n-fg-rgb), 0.08); }
      .blind.unavailable { opacity: 0.5; }
      .blind-head {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
      }
      .blind-name {
        flex: 1;
        min-width: 0;
        font-weight: 500;
        cursor: pointer;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .blind-name:hover { text-decoration: underline; }
      .battery {
        display: inline-flex;
        align-items: center;
        gap: 2px;
        font-size: 0.8rem;
        color: var(--secondary-text-color);
        white-space: nowrap;
        cursor: pointer;
      }
      .battery ha-icon { --mdc-icon-size: 18px; }
      .battery.low { color: var(--warning-color, #ff9800); }
      .battery.critical { color: var(--error-color, #f44336); }

      /* The shade picture.
         ------------------------------------------------------------------------------
         A blind is drawn as a window: a frame, and fabric hanging from the head down to
         each rail. Geometry is in PERCENT of the frame, never pixels, so the picture
         scales with the card and a phone gets a smaller shade rather than a clipped one.

         Two rails, drawn as two stacked bands. On a day/night cellular shade the middle
         rail is the join between the two fabrics, so the band above it is the sheer
         (light-filtering) cell and the band below it is the blackout cell; on a
         top-down/bottom-up blind the same two bands read as the top and bottom halves.
         Both are honest about the one thing that is always true: where each rail is.

         Every band's top and height is written by one function (_drawShade), so the
         fabric and its rail can never disagree about where the rail is. */
      .shade {
        position: relative;
        width: 100%;
        aspect-ratio: var(--n-shade-aspect, 4 / 3);
        border-radius: 4px;
        overflow: hidden;
        background: var(--n-daylight);
        cursor: ns-resize;
        touch-action: none;
        -webkit-user-select: none;
        user-select: none;
      }
      .shade.disabled { cursor: not-allowed; }
      .shade:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }

      /* The frame, drawn over everything as an inset ring plus a sill.
         A ring rather than a border: the fabric runs the full width beneath it, so the
         reveal overlaps the fabric's edges the way a real frame overlaps a blind. */
      .shade-frame {
        position: absolute;
        inset: 0;
        border-radius: 3px;
        pointer-events: none;
        z-index: 5;
        /* An off-white frame with a darker outer edge, as in the reference: a broad reveal
           the fabric runs behind, not a dark outline drawn on top of it. */
        box-shadow:
          inset 0 0 0 1px var(--n-frame-edge),
          inset 0 0 0 6px var(--n-frame),
          inset 0 0 0 7px rgba(0, 0, 0, 0.12);
      }
      /* The sill: a deeper bottom member, so the window sits on something. */
      .shade-frame::after {
        content: "";
        position: absolute;
        left: 0; right: 0; bottom: 0;
        height: 8%;
        min-height: 7px;
        background: linear-gradient(to bottom, var(--n-frame) 70%, var(--n-frame-edge));
        border-top: 1px solid var(--n-frame-edge);
      }

      /* The headbox the fabric rolls out of: a solid member with its own lip and a
         shadow cast onto the fabric below, which is what reads as depth. */
      .shade-head {
        position: absolute;
        top: 0; left: 0; right: 0;
        height: var(--n-head);
        min-height: 7px;
        z-index: 4;
        background: linear-gradient(
          to bottom,
          #ededed,
          var(--n-head-face) 60%,
          #c2c2c2
        );
        border-bottom: 1px solid var(--n-frame-edge);
        box-shadow:
          inset 0 1px 0 rgba(255, 255, 255, 0.9),
          0 2px 5px -2px rgba(0, 0, 0, 0.4);
      }

      /* Fabric. The slats are a repeating gradient rather than a tiled bitmap: it themes
         with the card, stays crisp at any pixel density, and costs no bytes. The period
         is in px so the cells stay a constant size as the shade scales. */
      .shade-band {
        position: absolute;
        left: 0; right: 0;
        transition: top 0.3s ease, height 0.3s ease;
        z-index: 1;
      }
      /* Fabric shades a cell at a time: each cell is lit at the top and shadowed where it
         meets the next, which is what makes a stack of cells look like fabric rather than
         like stripes. A fine vertical wash across the width adds the slack a hanging
         fabric has. The 6px period is fixed in px so cells stay a constant size as the
         picture scales; the background is pinned to the bottom so the cells stay put as a
         band grows rather than sliding under the rail. */
      /* Fabric, as a 6px slat: a translucent dark line at the top edge of each slat,
         then a ramp from 188 to 245 grey. This is the decoded reference tile expressed as
         a gradient, so the cells stay a constant size as the picture scales.

         The two cells differ in OPACITY, not just tone, because that is the physical
         difference: on a day/night shade the upper cell is the light-filtering fabric and
         the lower one is the blackout fabric. The upper cell is therefore drawn
         semi-transparent, so the opening behind it shows through and it visibly passes
         more light than the section below it -- which is exactly what the blind does, and
         what makes "Best privacy" legible at a glance. */
      .shade-band {
        background-image: repeating-linear-gradient(
          to bottom,
          rgba(0, 0, 0, 0.14) 0 1px,
          var(--n-slat-top) 1px 2px,
          #cacaca 2px 3px,
          #e3e3e3 3px 4px,
          #ececec 4px 5px,
          var(--n-slat-bottom) 5px 6px
        );
        background-position: bottom;
      }
      /* The light-filtering (sheer) cell.
         The upper section of a day/night shade passes noticeably more light than the
         blackout section below it -- that is the entire point of the product, and the
         reason "Best privacy" (bottom closed, sheer open) is a useful preset. So the two
         cells are separated by three reinforcing cues, not one:
           - opacity: the sheer is translucent, so the opening shows through it;
           - a warm daylight wash over the sheer, as light coming through fabric;
           - lighter, more widely spaced slat shadows, as a thinner weave.
         Three cues because any one of them alone is a subtle tonal shift that disappears
         on a phone, in bright sun, or for anyone with low contrast vision. */
      .shade-band.sheer {
        opacity: 0.72;
        background-image:
          linear-gradient(rgba(255, 248, 224, 0.55), rgba(255, 250, 235, 0.35)),
          repeating-linear-gradient(
            to bottom,
            rgba(0, 0, 0, 0.07) 0 1px,
            #e8e8e8 1px 3px,
            #f2f2f2 3px 5px,
            var(--n-slat-bottom) 5px 6px
          );
      }
      /* The blackout cell: opaque, and clearly deeper so the join is unmistakable. */
      .shade-band.blackout { opacity: 1; }
      .shade-band.blackout::after {
        content: "";
        position: absolute;
        inset: 0;
        background: rgba(40, 44, 52, 0.2);
      }

      /* A rail is an extruded bar: lit along its top edge, dark along its bottom, with a
         shadow cast onto whatever is beneath it. The bottom rail hangs BELOW its position
         (the fabric ends where the rail begins); the middle rail straddles the join between
         the two fabrics, so it is centred on its position instead. */
      .shade-rail {
        position: absolute;
        left: 0; right: 0;
        height: var(--n-rail);
        border-radius: 1px;
        background: linear-gradient(
          to bottom,
          #f8f8f8,
          #e0e0e0 35%,
          var(--n-rail-face) 65%,
          #dedede 85%,
          #c1c1c1
        );
        border-top: 1px solid rgba(255, 255, 255, 0.9);
        box-shadow: 0 2px 4px -1px rgba(0, 0, 0, 0.4);
        transition: top 0.3s ease;
        z-index: 3;
      }
      /* The grip: a shallow channel along the rail, as on the real bottom rail. */
      .shade-rail::after {
        content: "";
        position: absolute;
        left: 18%;
        right: 18%;
        top: 50%;
        height: 1px;
        margin-top: -0.5px;
        border-radius: 1px;
        background: rgba(0, 0, 0, 0.12);
      }
      /* The middle rail sits between two fabrics of similar tone, so unlike the bottom
         rail it has no dark opening behind it to read against. A hairline top and bottom
         is what separates it from the cells either side. */
      .shade-rail.middle {
        margin-top: calc(var(--n-rail) / -2);
        height: calc(var(--n-rail) - 1px);
        box-shadow:
          0 0 0 1px rgba(0, 0, 0, 0.28),
          0 2px 4px -1px rgba(0, 0, 0, 0.4);
        background: linear-gradient(
          to bottom,
          #f4f4f4,
          #dcdcdc 45%,
          #c8c8c8
        );
      }

      /* While a rail is held, nothing animates: the fabric must track the finger 1:1. */
      .shade.dragging .shade-band,
      .shade.dragging .shade-rail { transition: none; }

      /* Where a rail is heading while it travels, as a dashed line. */
      .shade-target {
        position: absolute;
        left: 0; right: 0;
        height: 0;
        border-top: 2px dashed var(--primary-color);
        opacity: 0;
        transition: opacity 0.25s ease, top 0.3s ease;
        z-index: 2;
      }
      .shade-target.showing { opacity: 0.8; }

      /* Per-rail readout. Pinned to the top-right of the glass, where the fabric is only
         ever in the way when the blind is almost fully closed -- and reversed out on a
         scrim so it stays readable against fabric or glass either way. */
      .shade-readouts {
        position: absolute;
        top: calc(var(--n-head) + 5px);
        right: 6px;
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 2px;
        pointer-events: none;
        z-index: 4;
      }
      .shade-readout {
        font-size: 0.7rem;
        line-height: 1.45;
        font-variant-numeric: tabular-nums;
        color: var(--primary-text-color);
        background: rgba(var(--n-bg-rgb), 0.78);
        border-radius: 3px;
        padding: 0 5px;
        white-space: nowrap;
        backdrop-filter: blur(2px);
      }
      .shade-readout.moving { color: var(--primary-color); font-weight: 500; }

      /* Rail: the controls under the picture, one row per rail. */
      /* The bar is kept as the accessible control: a real range input, visually hidden
         over the picture is not possible (the picture is the control), so it sits in the
         rail row below where it is still reachable by keyboard and screen reader. */
      .rail {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .rail + .rail { margin-top: 6px; }
      .bar {
        position: relative;
        flex: 1;
        min-width: 0;
        height: var(--n-control);
        border-radius: 8px;
        background: rgba(var(--n-fg-rgb), 0.08);
        overflow: hidden;
      }
      .bar:focus-within { outline: 2px solid var(--primary-color); outline-offset: 1px; }
      .bar.disabled { cursor: not-allowed; }
      .bar-fill {
        position: absolute;
        top: 0; bottom: 0; left: 0;
        width: 0;
        background: rgba(var(--n-accent-rgb), 0.35);
        transition: width 0.25s ease;
      }
      /* The handle: a short vertical bar at the fill's edge, as on a tile card. */
      .bar-fill::after {
        content: "";
        position: absolute;
        right: 0; top: 6px; bottom: 6px;
        width: 3px;
        border-radius: 2px;
        background: var(--primary-color);
      }
      /* Where the blind is heading while it travels; the fill catches up over ~30 s. */
      .bar-target {
        position: absolute;
        top: 4px; bottom: 4px;
        width: 2px;
        margin-left: -1px;
        border-radius: 1px;
        background: var(--primary-color);
        opacity: 0;
        transition: opacity 0.25s ease;
      }
      .bar.moving .bar-target { opacity: 0.55; }
      .bar-label, .bar-value {
        position: absolute;
        top: 0; bottom: 0;
        display: flex;
        align-items: center;
        pointer-events: none;
        font-size: 0.8rem;
        white-space: nowrap;
      }
      .bar-label { left: 10px; color: var(--secondary-text-color); }
      .bar-value {
        right: 10px;
        font-variant-numeric: tabular-nums;
        font-weight: 500;
      }
      .bar.moving .bar-value { color: var(--primary-color); }
      .bar input[type="range"] {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        margin: 0;
        opacity: 0;
        cursor: pointer;
      }
      .bar input[type="range"]:disabled { cursor: not-allowed; }

      /* A segmented pill: one control with three parts, not three loose buttons. */
      .pill {
        display: inline-flex;
        flex: none;
        border-radius: 999px;
        background: rgba(var(--n-fg-rgb), 0.06);
      }
      .pill ha-icon-button {
        --mdc-icon-button-size: var(--n-control);
        --mdc-icon-size: 18px;
        color: var(--primary-text-color);
      }
      .pill ha-icon-button[disabled] { opacity: 0.35; }
      .pill ha-icon-button.active { color: var(--primary-color); }

      /* A labelled chip, for the app's presets: the word says what the icon cannot. */
      .chips { display: inline-flex; flex: none; gap: 6px; }
      .chip {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        height: var(--n-control);
        padding: 0 11px 0 9px;
        border: 1px solid rgba(var(--n-fg-rgb), 0.16);
        border-radius: 999px;
        background: transparent;
        color: var(--primary-text-color);
        font: inherit;
        font-size: 0.78rem;
        font-weight: 500;
        letter-spacing: normal;
        text-transform: none;
        line-height: 1;
        cursor: pointer;
      }
      .chip ha-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); }
      .chip:hover { background: rgba(var(--n-accent-rgb), 0.08); border-color: transparent; }
      .chip:hover ha-icon { color: var(--primary-color); }
      .chip:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }

      /* Controls sit at the right of their heading and wrap beneath it when the width
         runs out, keeping the name legible on a phone. */
      .controls {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        margin-left: auto;
      }
      .empty { padding: 16px; color: var(--secondary-text-color); }
    `;

    const card = document.createElement("ha-card");
    card.appendChild(style);

    // The header doubles as the house-wide control row, which is on by default. It needs
    // somewhere to live, so it is drawn even when no title is configured.
    //
    // With no configured title the header names the HUB rather than saying "Shades": a
    // house with two hubs gets two cards, and "Shades" twice tells the user nothing about
    // which is which. See _headingText for why a saved "Shades" counts as unset.
    const title = this._headingText();
    if (title || !this._config.hide_home_controls) {
      const header = document.createElement("div");
      header.className = "header";

      const text = document.createElement("span");
      text.className = "header-text";
      text.textContent = title;
      // Kept so the heading can follow a hub rename, or fill in once the device registry
      // has loaded -- _render() runs once, but the hub's name can arrive or change later.
      this._headerText = text;
      header.appendChild(text);

      if (!this._config.hide_home_controls) {
        header.appendChild(this._buildHomeControls());
      }
      card.appendChild(header);
    }

    this._body = document.createElement("div");
    card.appendChild(this._body);

    this.shadowRoot.innerHTML = "";
    this.shadowRoot.appendChild(card);
    this._update();
  }

  _update() {
    if (!this._body || !this._hass) return;

    // The header names the hub when no title is configured, so it has to track a rename
    // (and the first load, where the device registry may arrive after the first render).
    if (this._headerText) {
      const title = this._headingText();
      if (this._headerText.textContent !== title) this._headerText.textContent = title;
    }

    const blinds = this._collectBlinds();
    const rooms = this._roomsOf(blinds);

    // Rebuild only when the set of blinds changes; otherwise patch values in place so a
    // slider being dragged is never replaced under the user's finger.
    const signature = rooms
      .map(([room, list]) => `${room}:${list.map((b) => b.deviceId).join(",")}`)
      .join("|");
    if (signature !== this._signature) {
      this._signature = signature;
      this._build(rooms);
    }
    this._patch();
  }

  _build(rooms) {
    this._body.innerHTML = "";
    this._cells = [];

    if (!rooms.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent =
        "No Norman blinds found. Set up the Norman integration, or check that its cover " +
        "entities are not hidden.";
      this._body.appendChild(empty);
      return;
    }

    for (const [roomName, list] of rooms) {
      const room = document.createElement("div");
      room.className = "room";

      // Each room heading carries its own open/stop/close, so a whole room moves in one
      // press. Set `hide_room_controls: true` for plain headings. They are skipped when the
      // headings themselves are hidden, since there would be nothing to attach them to.
      if (!this._config.hide_room_names) {
        const label = document.createElement("div");
        label.className = "room-name";

        const text = document.createElement("span");
        text.className = "room-name-text";
        text.textContent = roomName;
        label.appendChild(text);

        // Both control sets share one container so they wrap under the heading together.
        const controls = document.createElement("div");
        controls.className = "controls";
        if (!this._config.hide_room_controls) {
          controls.appendChild(this._buildRoomControls(roomName, list));
        }
        if (!this._config.hide_room_presets) {
          controls.appendChild(this._buildRoomPresets(roomName));
        }
        if (controls.children.length) label.appendChild(controls);
        room.appendChild(label);
      }

      // The room's blinds share one rounded group, so a room reads as one object.
      const group = document.createElement("div");
      group.className = "group";
      for (const blind of list) {
        group.appendChild(this._buildBlind(blind));
      }
      room.appendChild(group);
      this._body.appendChild(room);
    }
  }

  /**
   * Open / stop / close every rail of every blind in one room.
   *
   * This is NOT the hub's own room verb, and it is not the same as the Norman app's room
   * buttons. Close here sends close_cover to every rail, so a two-rail blind ends at
   * bottom 0 AND middle 0 -- both fabrics down. The app's "Best Privacy" is bottom 0 with
   * middle 100: private, but the sheer fabric fully open so the room stays lit. The hub
   * verb that does that needs its own RoomID, which no entity exposes, so it lives in the
   * norman.room_command action instead (see docs/services.md).
   */
  _buildRoomControls(roomName, blinds) {
    const controls = document.createElement("div");
    controls.className = "pill room-buttons";

    for (const [icon, service, label] of [
      ["mdi:arrow-up", "open_cover", "Open"],
      ["mdi:stop", "stop_cover", "Stop"],
      ["mdi:arrow-down", "close_cover", "Close"],
    ]) {
      const button = document.createElement("ha-icon-button");
      const inner = document.createElement("ha-icon");
      inner.setAttribute("icon", icon);
      button.appendChild(inner);
      button.title = `${label} every blind in ${roomName}`;
      button.setAttribute("aria-label", button.title);
      button.addEventListener("click", () => {
        // Every rail in the room: the bottom rails, plus the middle rails of two-rail
        // blinds. One service call with a list, not one call per entity.
        const entityId = [];
        for (const blind of blinds) {
          if (blind.bottomCover) entityId.push(blind.bottomCover);
          if (blind.middleCover) entityId.push(blind.middleCover);
        }
        if (entityId.length) this._hass.callService("cover", service, { entity_id: entityId });
      });
      controls.appendChild(button);
    }
    return controls;
  }

  /**
   * The Norman app's own room buttons, via the norman.room_command action.
   *
   * These are the hub's room-wide verbs, not a fan-out: one request moves the room, and
   * the rail positions are the hub's own. "Privacy" is bottom 0 with the middle rail fully
   * open, which the cover services above cannot express, and "favorite" has no Home
   * Assistant equivalent at all.
   *
   * The action matches on the HUB's room name. The card groups by Home Assistant area,
   * which the integration seeds from those names -- so they agree until an area is
   * renamed, and the action reports the names it knows if one does not match. That
   * mismatch is why these were once opt-in, which was the wrong trade: it hid the app's
   * three buttons from everyone to spare the few who rename an area, and those few get a
   * named error listing the rooms the hub does know. Set `hide_room_presets: true` to
   * drop them.
   */
  /**
   * The app's three buttons for the whole house, via the hub's own scope-less verb.
   *
   * Omitting RoomID entirely is what makes the hub treat a command as house-wide, so this
   * is one request no matter how many blinds there are. These are the same three buttons
   * the app's own "All Rooms" screen sends, captured from it.
   *
   * They carry the app's names and icons rather than open/close arrows, because they are
   * not open and close: "Best privacy" is bottom 0 with the middle rail fully OPEN, so a
   * two-rail blind ends private but still lit. Labelling that as a plain "close" would
   * promise both fabrics down, which is not what the hub does. The room buttons in
   * _buildRoomPresets are the same three verbs scoped to one room, and match deliberately.
   *
   * Every verb here works on single-rail blinds too: a per-blind capture of a single-rail
   * shade shows the app sending Switch 0, Switch 1 and Favorite to it unchanged.
   *
   * There is deliberately no house-wide Stop: the hub's stop is per blind, so it would
   * have to fan out over every cover, and a Stop that lags the blinds it is stopping is
   * worse than none. Use a room's Stop, which does fan out over a smaller set.
   */
  _buildHomeControls() {
    const controls = document.createElement("div");
    controls.className = "chips home-buttons";
    for (const preset of PRESETS) {
      controls.appendChild(
        this._buildChip(preset, `${preset.title} — every room`, () => {
          // No `room`: the action omits RoomID, which the hub reads as every blind.
          this._hass.callService("norman", "room_command", { command: preset.command });
        }),
      );
    }
    return controls;
  }

  _buildRoomPresets(roomName) {
    const presets = document.createElement("div");
    presets.className = "chips room-presets";
    for (const preset of PRESETS) {
      presets.appendChild(
        this._buildChip(preset, `${preset.title} — ${roomName}`, () => {
          this._hass.callService("norman", "room_command", {
            room: roomName,
            command: preset.command,
          });
        }),
      );
    }
    return presets;
  }

  /**
   * A labelled chip: an icon and a short word.
   *
   * The presets had been bare icons, and "blinds-horizontal" does not say "privacy" to
   * anyone who has not already learned it. A word does. The icon stays because it is what
   * the eye lands on first when scanning a row of rooms for the same control.
   */
  _buildChip(preset, title, onClick) {
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.type = "button";
    const icon = document.createElement("ha-icon");
    icon.setAttribute("icon", preset.icon);
    const text = document.createElement("span");
    text.textContent = preset.label;
    chip.append(icon, text);
    chip.title = title;
    chip.setAttribute("aria-label", title);
    chip.addEventListener("click", onClick);
    return chip;
  }

  _buildBlind(blind) {
    const row = document.createElement("div");
    row.className = "blind";

    const head = document.createElement("div");
    head.className = "blind-head";

    const name = document.createElement("div");
    name.className = "blind-name";
    name.textContent = blind.name;
    name.addEventListener("click", () => this._showMore(blind.bottomCover));
    head.appendChild(name);

    let batteryEl = null;
    if (blind.battery && !this._config.hide_battery) {
      batteryEl = document.createElement("span");
      batteryEl.className = "battery";
      const icon = document.createElement("ha-icon");
      const text = document.createElement("span");
      batteryEl.append(icon, text);
      // A bare "84%" next to a blind is ambiguous -- it reads as a position. The icon
      // carries the meaning visually; the title and aria-label carry it for a screen
      // reader and on hover.
      batteryEl.title = "Battery";
      batteryEl.setAttribute("role", "img");
      batteryEl.addEventListener("click", () => this._showMore(blind.battery));
      head.appendChild(batteryEl);
    }

    row.appendChild(head);

    // _railsOf returns the rail descriptors; _buildRail wraps each one with its elements.
    // The picture needs the descriptors (it reads rail.label and the entity ids), so keep
    // both rather than digging the descriptor back out of the wrapper.
    const railDefs = this._railsOf(blind);
    const rails = railDefs.map((rail) => this._buildRail(rail));
    const shade = this._config.hide_picture ? null : this._buildShade(blind, railDefs);
    if (shade) row.appendChild(shade.element);
    for (const { element } of rails) row.appendChild(element);

    this._cells.push({ blind, row, batteryEl, rails, shade });
    return row;
  }

  /**
   * The window picture for one blind: fabric hanging from the head down to each rail.
   *
   * Draggable. A rail is picked up by pressing anywhere on the picture -- the nearest one
   * takes the drag -- and follows the pointer until release, when the position is written
   * once. Dragging tracks pointer deltas rather than absolute coordinates, so a tap with no
   * movement leaves the blind exactly where it is instead of jumping to the tapped row: a
   * mis-tap on a phone should do nothing, not move a blind across the room.
   *
   * The rails are ordered so that `rails[0]` is the bottom rail and `rails[1]`, when there
   * is one, is the middle rail (see _railsOf).
   */
  _buildShade(blind, rails) {
    const element = document.createElement("div");
    element.className = "shade";
    element.setAttribute("role", "group");
    element.setAttribute("aria-label", `${blind.name} position`);

    const head = document.createElement("div");
    head.className = "shade-head";

    // One band and one rail per rail entity, plus a target line. The band above the
    // middle rail is the sheer cell, the one below it the blackout cell; a single-rail
    // blind gets one blackout band, since there is no second fabric to distinguish.
    const bands = [];
    const railEls = [];
    const targets = [];
    const twoRail = rails.length > 1;
    for (let index = 0; index < rails.length; index += 1) {
      const band = document.createElement("div");
      // Which fabric this band is.
      //
      // On a day/night shade the BLACKOUT fabric hangs from the head down to the middle
      // rail, and the SHEER hangs from the middle rail down to the bottom rail. So the
      // band spanning head->middle (index 1, the middle rail's band) is the blackout, and
      // the band spanning middle->bottom (index 0) is the sheer.
      //
      // Checked against the app's own presets: "Best privacy" is bottom 0 / middle 100,
      // which stacks the blackout away at the head and draws the sheer across the whole
      // window -- "closed for privacy, sheer fabric still open" (docs/entities.md). Fully
      // closed (both 0) draws the blackout across the whole window. Getting this backwards
      // makes a closed blind look like a sheer one, which is a privacy question, not a
      // cosmetic one.
      //
      // A single-rail blind has one fabric and no second cell to distinguish, so it is
      // drawn as the opaque one.
      band.className = `shade-band ${twoRail && index === 0 ? "sheer" : "blackout"}`;
      bands.push(band);

      const railEl = document.createElement("div");
      railEl.className = `shade-rail ${index === 1 ? "middle" : "bottom"}`;
      railEls.push(railEl);

      const target = document.createElement("div");
      target.className = "shade-target";
      targets.push(target);
    }

    const readouts = document.createElement("div");
    readouts.className = "shade-readouts";
    const readoutEls = rails.map(() => {
      const readout = document.createElement("div");
      readout.className = "shade-readout";
      readouts.appendChild(readout);
      return readout;
    });

    // The frame goes on last so its reveal and sill sit over the fabric's edges.
    const frame = document.createElement("div");
    frame.className = "shade-frame";

    element.append(head, ...bands, ...railEls, ...targets, readouts, frame);

    const shade = { element, bands, railEls, targets, readoutEls, rails };
    this._bindShadeDrag(shade);
    return shade;
  }

  /**
   * Make the picture draggable: press to pick up the nearest rail, drag, release to write.
   *
   * Deltas, not absolute position. `pointerdown` records where the pointer started and
   * where that rail already was; every `pointermove` applies the difference. A press with
   * no movement therefore writes nothing at all.
   *
   * A two-rail blind's rails cannot cross: the middle rail is physically above the bottom
   * one, so each is clamped against the other's current position. Without that, dragging
   * the middle rail past the bottom one would draw a negative-height band and ask the hub
   * for a geometry the blind cannot make.
   */
  _bindShadeDrag(shade) {
    const { element } = shade;
    let active = null;

    const positionFromEvent = (event) => {
      // getBoundingClientRect is read once per drag, on pickup: the card can scroll under
      // the finger mid-drag, and re-reading would make the shade jump.
      const fraction = (event.clientY - active.top) / active.height;
      // The picture reads top-down (0% of travel at the head) but a cover position is
      // 100 = open, so the two run opposite ways.
      return clampToStep(100 - fraction * 100);
    };

    element.addEventListener("pointerdown", (event) => {
      if (element.classList.contains("disabled")) return;
      const rect = element.getBoundingClientRect();
      if (!rect.height) return;

      // Whichever rail is nearest the press takes the drag.
      const pressed = 100 - ((event.clientY - rect.top) / rect.height) * 100;
      let index = 0;
      let best = Infinity;
      for (let i = 0; i < shade.rails.length; i += 1) {
        const value = this._railValue(shade.rails[i]);
        const distance = Math.abs((value === null ? 0 : value) - pressed);
        if (distance < best) {
          best = distance;
          index = i;
        }
      }

      active = { index, top: rect.top, height: rect.height };
      shade.holding = true;
      const rail = shade.rails[index];
      this._dragging.add(rail.numberId || rail.coverId);
      element.classList.add("dragging");
      element.setPointerCapture?.(event.pointerId);
      event.preventDefault();
    });

    element.addEventListener("pointermove", (event) => {
      if (!active) return;
      shade.dragValues ||= {};
      shade.dragValues[active.index] = this._clampRail(
        shade,
        active.index,
        positionFromEvent(event),
      );
      this._drawShade(shade);
    });

    const release = (event) => {
      if (!active) return;
      const { index } = active;
      const rail = shade.rails[index];
      const chosen = shade.dragValues?.[index];
      active = null;
      shade.holding = false;
      element.classList.remove("dragging");
      this._dragging.delete(rail.numberId || rail.coverId);
      if (shade.dragValues) delete shade.dragValues[index];
      // No movement, no write: a tap must not move the blind.
      if (chosen !== undefined) this._setRail(rail, chosen);
      else this._drawShade(shade);
      if (event) element.releasePointerCapture?.(event.pointerId);
    };
    element.addEventListener("pointerup", release);
    element.addEventListener("pointercancel", release);
  }

  /** Keep a rail on its own side of the other one, so the fabric never inverts. */
  _clampRail(shade, index, value) {
    if (shade.rails.length < 2) return value;
    const other = this._shadeValue(shade, index === 0 ? 1 : 0);
    if (other === null) return value;
    // rails[0] is the bottom rail and rails[1] the middle: the bottom can never be above
    // the middle, which in cover terms (100 = open = high) means bottom <= middle.
    return index === 0 ? Math.min(value, other) : Math.max(value, other);
  }

  /** What a rail should currently be drawn at: the drag, else a pending write, else state. */
  _shadeValue(shade, index) {
    const dragged = shade.dragValues?.[index];
    if (dragged !== undefined) return dragged;
    const rail = shade.rails[index];
    const pending = this._pending.get(rail.numberId || rail.coverId);
    if (pending !== undefined) return pending;
    return this._railValue(rail);
  }

  /**
   * Write every coupled measurement of one picture in a single pass.
   *
   * Fabric geometry and rail geometry are the same numbers, so they are set together here
   * rather than in separate places that could disagree and leave a rail floating off its
   * fabric's edge.
   */
  _drawShade(shade) {
    const head = SHADE_HEAD_PCT;
    const travel = 100 - head;
    // Where each rail sits, as a percentage down the picture: a cover position of 100
    // (open) puts the rail at the head, 0 (closed) at the sill.
    const dropOf = (value) => head + ((100 - (value === null ? 0 : value)) / 100) * travel;

    for (let index = 0; index < shade.rails.length; index += 1) {
      const value = this._shadeValue(shade, index);
      const drop = dropOf(value);
      // The band above this rail starts at the head, or at the rail above it.
      const above = index + 1 < shade.rails.length ? dropOf(this._shadeValue(shade, index + 1)) : head;
      const band = shade.bands[index];
      band.style.top = `${above}%`;
      band.style.height = `${Math.max(0, drop - above)}%`;
      shade.railEls[index].style.top = `${drop}%`;
    }
  }

  _buildRail(rail) {
    const element = document.createElement("div");
    element.className = "rail";

    // The bar carries its own label and value, so the row is just bar + pill and the bar
    // gets the width a slider needs. Layered back to front: fill, target marker, label
    // and value, then the invisible range input that actually takes the pointer.
    const bar = document.createElement("div");
    bar.className = "bar";

    const fill = document.createElement("div");
    fill.className = "bar-fill";

    const targetMark = document.createElement("div");
    targetMark.className = "bar-target";

    const label = document.createElement("div");
    label.className = "bar-label";
    label.textContent = rail.label;

    const value = document.createElement("div");
    value.className = "bar-value";

    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = "0";
    slider.max = "100";
    slider.step = String(STEP);
    slider.setAttribute("aria-label", `${rail.label} position`);

    bar.append(fill, targetMark, label, value, slider);

    // Open / stop / close for THIS rail. Each rail is its own cover entity, so the middle
    // rail of a two-rail blind gets the same controls as the bottom rail rather than the
    // buttons silently driving the bottom one.
    const buttons = document.createElement("div");
    buttons.className = "pill";
    const railButtons = [];
    for (const [icon, service, label] of [
      ["mdi:arrow-up", "open_cover", "Open"],
      ["mdi:stop", "stop_cover", "Stop"],
      ["mdi:arrow-down", "close_cover", "Close"],
    ]) {
      const button = document.createElement("ha-icon-button");
      const inner = document.createElement("ha-icon");
      inner.setAttribute("icon", icon);
      button.appendChild(inner);
      button.title = `${label} ${rail.label.toLowerCase()}`;
      button.setAttribute("aria-label", button.title);
      if (rail.coverId) {
        button.addEventListener("click", () =>
          this._hass.callService("cover", service, { entity_id: rail.coverId }),
        );
      }
      buttons.appendChild(button);
      railButtons.push(button);
    }

    const target = rail.numberId || rail.coverId;
    slider.addEventListener("pointerdown", () => this._dragging.add(target));
    slider.addEventListener("input", () => {
      // Follow the thumb while it is held, so the fill tracks the finger.
      const chosen = clampToStep(slider.value);
      value.textContent = `${chosen}%`;
      fill.style.width = `${chosen}%`;
    });
    slider.addEventListener("change", () => {
      this._dragging.delete(target);
      this._setRail(rail, clampToStep(slider.value));
    });

    element.append(bar, buttons);
    return { rail, element, slider, value, buttons: railButtons, bar, fill, targetMark };
  }

  /** Where the hub says a rail is heading, or null if it does not say. */
  _railTarget(rail) {
    const cover = this._hass.states[rail.coverId];
    const target = cover?.attributes?.target_position;
    return target === undefined || target === null ? null : Number(target);
  }

  /** Write a rail position, preferring the number entity so the 10% step is enforced. */
  _setRail(rail, position) {
    const target = rail.numberId || rail.coverId;
    this._pending.set(target, position);
    const call = rail.numberId
      ? this._hass.callService("number", "set_value", {
          entity_id: rail.numberId,
          value: position,
        })
      : this._hass.callService("cover", "set_cover_position", {
          entity_id: rail.coverId,
          position,
        });
    Promise.resolve(call).finally(() => {
      // Keep the optimistic value briefly: the hub reports the blind mid-travel, so
      // clearing immediately would snap the label back to where the blind still is.
      setTimeout(() => {
        this._pending.delete(target);
        this._patch();
      }, 3000);
    });
  }

  _patch() {
    if (!this._cells) return;
    for (const cell of this._cells) {
      const unavailable = this._isUnavailable(cell.blind);
      cell.row.classList.toggle("unavailable", unavailable);

      if (cell.shade) {
        const shade = cell.shade;
        shade.element.classList.toggle("disabled", unavailable);
        // Never redraw a rail the user is holding: the hub's value lags the finger.
        if (!shade.holding) this._drawShade(shade);

        const head = SHADE_HEAD_PCT;
        const travel = 100 - head;
        for (let index = 0; index < shade.rails.length; index += 1) {
          const rail = shade.rails[index];
          const key = rail.numberId || rail.coverId;
          const current = this._railValue(rail);
          const heading = this._railTarget(rail);
          const pending = this._pending.has(key);
          const moving =
            !pending &&
            heading !== null &&
            current !== null &&
            Math.round(heading) !== Math.round(current);

          const target = shade.targets[index];
          target.classList.toggle("showing", moving);
          if (moving) target.style.top = `${head + ((100 - heading) / 100) * travel}%`;

          const readout = shade.readoutEls[index];
          const label = shade.rails.length > 1 ? `${rail.label}: ` : "";
          readout.classList.toggle("moving", moving);
          if (current === null) readout.textContent = `${label}—`;
          else if (moving) {
            readout.textContent = `${label}${Math.round(current)}% → ${Math.round(heading)}%`;
          } else readout.textContent = `${label}${Math.round(current)}%`;
        }
      }

      if (cell.batteryEl) {
        const level = this._numberOf(cell.blind.battery);
        cell.batteryEl.className = `battery ${batteryClass(level)}`;
        cell.batteryEl.firstChild.setAttribute("icon", batteryIcon(level));
        const shown = level === null ? "—" : `${Math.round(level)}%`;
        cell.batteryEl.lastChild.textContent = shown;
        cell.batteryEl.title = level === null ? "Battery level unknown" : `Battery ${shown}`;
        cell.batteryEl.setAttribute("aria-label", cell.batteryEl.title);
      }

      for (const { rail, slider, value, buttons, bar, fill, targetMark } of cell.rails) {
        const key = rail.numberId || rail.coverId;
        const current = this._railValue(rail);
        const heading = this._railTarget(rail);
        slider.disabled = unavailable;
        bar.classList.toggle("disabled", unavailable);
        // A rail with no cover entity (a slider-only rail) has nothing to open or stop.
        for (const button of buttons) button.disabled = unavailable || !rail.coverId;

        // A blind takes up to ~30 s to travel, and the hub reports where it IS the whole
        // way. The target tells the user the press registered: "40% → 80%", a ghost mark
        // at 80, and the stop button lit -- until the two numbers meet. While a write is
        // pending the chosen value is shown alone: the hub's target is still the old one.
        const pending = this._pending.has(key);
        const moving =
          !pending && heading !== null && current !== null && Math.round(heading) !== Math.round(current);
        bar.classList.toggle("moving", moving);
        buttons[1]?.classList.toggle("active", moving);
        if (current === null) {
          value.textContent = "—";
        } else if (moving) {
          value.textContent = `${Math.round(current)}% → ${Math.round(heading)}%`;
        } else {
          value.textContent = `${Math.round(current)}%`;
        }
        if (moving) targetMark.style.left = `${Math.round(heading)}%`;

        // Never move a slider (or its fill) the user is holding.
        if (!this._dragging.has(key)) {
          const shown = clampToStep(current === null ? 0 : current);
          slider.value = String(shown);
          fill.style.width = `${current === null ? 0 : Math.round(current)}%`;
        }
      }
    }
  }

  _showMore(entityId) {
    if (!entityId) return;
    const event = new Event("hass-more-info", { bubbles: true, composed: true });
    event.detail = { entityId };
    this.dispatchEvent(event);
  }
}

/** Minimal visual editor so the card can be configured without YAML. */
class NormanShadesCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = "";

    const wrap = document.createElement("div");
    wrap.style.padding = "8px 0";

    const fields = [
      { key: "title", label: "Title", type: "text" },
      { key: "hide_picture", label: "Hide the window picture", type: "checkbox" },
      { key: "hide_battery", label: "Hide battery levels", type: "checkbox" },
      { key: "hide_room_names", label: "Hide room headings", type: "checkbox" },
      { key: "hide_room_controls", label: "Hide whole-room open/close", type: "checkbox" },
      { key: "hide_room_presets", label: "Hide the app's room buttons", type: "checkbox" },
      { key: "hide_home_controls", label: "Hide the app's whole-house buttons", type: "checkbox" },
    ];

    for (const field of fields) {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;gap:8px;padding:6px 0;";

      const label = document.createElement("label");
      label.textContent = field.label;
      label.style.flex = "1";

      const input = document.createElement("input");
      input.type = field.type;
      if (field.type === "checkbox") input.checked = Boolean(this._config[field.key]);
      else input.value = this._config[field.key] ?? "";

      input.addEventListener("change", () => {
        const value = field.type === "checkbox" ? input.checked : input.value;
        this._config = { ...this._config, [field.key]: value };
        if (value === "" || value === false) delete this._config[field.key];
        const event = new CustomEvent("config-changed", {
          detail: { config: this._config },
          bubbles: true,
          composed: true,
        });
        this.dispatchEvent(event);
      });

      row.append(label, input);
      wrap.appendChild(row);
    }

    this.shadowRoot.appendChild(wrap);
  }
}

if (!customElements.get("norman-shades-card")) {
  customElements.define("norman-shades-card", NormanShadesCard);
}
if (!customElements.get("norman-shades-card-editor")) {
  customElements.define("norman-shades-card-editor", NormanShadesCardEditor);
}

// Register in the dashboard's "Add card" picker.
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "norman-shades-card")) {
  window.customCards.push({
    type: "norman-shades-card",
    name: "Norman Shades",
    description: "Norman blinds grouped by room, with battery levels and per-rail sliders.",
    preview: true,
    documentationURL: "https://github.com/kedube/ha-norman/blob/main/docs/dashboard.md",
  });
}

// The loaded build, in the browser console. This is the only place a version mismatch is
// visible from the browser side: if this does not match the integration version on the
// Norman device page, the browser is running a cached copy of an older card.
console.info(
  `%c NORMAN-SHADES-CARD %c v${CARD_VERSION} `,
  "color: #fff; background: #4a6572; font-weight: 700;",
  "color: #4a6572; background: #fff; font-weight: 700;"
);
