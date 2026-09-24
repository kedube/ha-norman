/**
 * Norman shades card.
 *
 * Every Norman blind, grouped by room, drawn as a window with its shade hanging in it. The
 * picture is the control: each rail has a pull tab, and dragging it moves that rail. A
 * two-rail (day/night) blind has two -- the middle rail between the two fabrics, and the
 * bottom rail -- and they stack and part the way the real rails do.
 *
 * Written as a plain custom element with no build step and no external dependencies, so the
 * file that ships is the file that runs. The picture is drawn in CSS with its geometry in
 * percent, so it follows the theme, stays crisp at any pixel density and scales with the card.
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

const DOMAIN = "norman";
const STEP = 10;

// The shade's geometry, as percentages of the window opening's height: the headrail's depth
// and each rail's thickness. The CSS tokens --n-head and --n-rail draw the same two numbers,
// so if they disagree the fabric detaches from its rails. Keep them equal.
const SHADE_HEAD_PCT = 9;
const SHADE_RAIL_PCT = 4.5;

// How long a position the user chose is drawn before the hub must have taken it up. Past this
// the card shows the hub's own values again, so a command the hub dropped is visible.
const PENDING_MS = 15000;
// Keyboard moves are gathered into one write: the hub drops commands sent closer together
// than about 1.6 s, so one write per key press would lose most of them.
const KEY_COMMIT_MS = 900;
// How far (px) a press must travel before it becomes a drag, so a tap never moves a blind.
const DRAG_SLOP = 4;

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

// The Norman app's three presets. The short label is what is printed; the title is the full
// name, used for the tooltip and for assistive technology.
const PRESETS = [
  { command: "best_privacy", icon: "mdi:blinds-horizontal", label: "Privacy", title: "Best privacy" },
  { command: "best_view", icon: "mdi:weather-sunny", label: "View", title: "Best view" },
  { command: "favorite", icon: "mdi:star", label: "Favorite", title: "Favorite" },
];

const ROOM_ACTIONS = [
  ["mdi:arrow-up", "open_cover", "Open"],
  ["mdi:stop", "stop_cover", "Stop"],
  ["mdi:arrow-down", "close_cover", "Close"],
];

const clamp = (value, low = 0, high = 100) => Math.max(low, Math.min(high, value));
const clampToStep = (value) => Math.round(clamp(Number(value) || 0) / STEP) * STEP;
const round3 = (value) => Math.round(value * 1000) / 1000;

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const haIcon = (name) => {
  const node = document.createElement("ha-icon");
  node.setAttribute("icon", name);
  return node;
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

// The view through the window follows the sun, so the picture reads like the real window.
const skyOf = (sun) => {
  if (!sun) return "day";
  const elevation = Number(sun.attributes?.elevation);
  if (Number.isNaN(elevation)) return sun.state === "below_horizon" ? "night" : "day";
  if (elevation > 8) return "day";
  if (elevation > 0) return "golden";
  if (elevation > -6) return "dusk";
  return "night";
};

// "Middle rail" -> "Middle": the status line has room for a word, not a label.
const shortLabel = (rail) => rail.label.split(" ")[0];

const STYLES = `
  :host {
    --n-fg-rgb: var(--rgb-primary-text-color, 33, 33, 33);
    --n-accent: var(--primary-color, #03a9f4);
    --n-accent-rgb: var(--rgb-primary-color, 3, 169, 244);
    --n-muted: var(--secondary-text-color, #6f7378);
    --n-tile: 112px;
    /* Shade geometry, in percent of the window opening. SHADE_HEAD_PCT and SHADE_RAIL_PCT
       in the script are the same numbers. */
    --n-head: 9%;
    --n-rail: 4.5%;
    --n-pleat: 6px;
    --n-ease: cubic-bezier(0.2, 0.7, 0.2, 1);
    display: block;
  }
  [hidden] { display: none !important; }

  /* The illustration's palette: painted trim, aluminium rails, a see-through light-filtering
     fabric and an ivory cloth for everything else -- a single-rail shade and a two-rail
     shade's blackout alike. Dark themes dim the trim so the window does not glare. */
  ha-card {
    --n-trim: #f3f0ea;
    --n-trim-hi: #fdfcfa;
    --n-trim-lo: #dcd6cc;
    --n-trim-edge: rgba(92, 78, 58, 0.22);
    --n-rail-hi: #ffffff;
    --n-rail-face: #eeebe5;
    --n-rail-lo: #cbc5ba;
    --n-rail-edge: rgba(70, 60, 45, 0.35);
    --n-sheer-hi: rgba(255, 253, 248, 0.5);
    --n-sheer: rgba(248, 244, 236, 0.4);
    --n-sheer-lo: rgba(232, 225, 212, 0.52);
    --n-sheer-crease: rgba(176, 164, 144, 0.7);
    --n-cloth-hi: #fbf9f4;
    --n-cloth: #f0ebe2;
    --n-cloth-lo: #ddd5c7;
    --n-cloth-crease: #bdb2a0;
    container-type: inline-size;
    padding: 16px 16px 18px;
    overflow: visible;
  }
  ha-card[data-theme="dark"] {
    --n-trim: #45484d;
    --n-trim-hi: #53575c;
    --n-trim-lo: #34373b;
    --n-trim-edge: rgba(0, 0, 0, 0.45);
    --n-rail-hi: #f2f0ec;
    --n-rail-face: #d9d5ce;
    --n-rail-lo: #aba497;
    --n-cloth-hi: #e6e1d8;
    --n-cloth: #d6cfc3;
    --n-cloth-lo: #c0b7a8;
    --n-cloth-crease: #a39886;
  }

  /* ---- header ---------------------------------------------------------------------- */
  .header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px 16px;
  }
  .titles { flex: 1 1 160px; min-width: 0; }
  .header-text {
    font-size: var(--ha-card-header-font-size, 20px);
    font-weight: var(--ha-card-header-font-weight, 500);
    line-height: 1.25;
    color: var(--ha-card-header-color, var(--primary-text-color));
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .summary {
    margin-top: 2px;
    font-size: 13px;
    color: var(--n-muted);
    font-variant-numeric: tabular-nums;
  }
  .summary > span:not(.sep) { white-space: nowrap; }
  .summary .warn { color: var(--warning-color, #e39700); }
  .summary .live { color: var(--n-accent); }

  /* The app's presets, as one segmented control rather than three loose buttons. */
  .segmented {
    display: inline-flex;
    flex: none;
    gap: 2px;
    padding: 3px;
    border-radius: 12px;
    background: rgba(var(--n-fg-rgb), 0.06);
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    padding: 0 12px 0 10px;
    border: 0;
    border-radius: 9px;
    background: transparent;
    color: var(--primary-text-color);
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    line-height: 1;
    white-space: nowrap;
    cursor: pointer;
    transition: background-color 0.15s, box-shadow 0.15s, color 0.15s;
  }
  .chip ha-icon { --mdc-icon-size: 17px; color: var(--n-muted); transition: color 0.15s; }
  .chip:hover {
    background: var(--card-background-color, #fff);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.14), 0 0 0 0.5px rgba(0, 0, 0, 0.06);
  }
  .chip:hover ha-icon, .chip.sent ha-icon, .chip.sent { color: var(--n-accent); }
  .chip:active { transform: scale(0.97); }
  .chip:focus-visible, .icon-btn:focus-visible, .name:focus-visible, .stop:focus-visible {
    outline: 2px solid var(--n-accent);
    outline-offset: 1px;
  }
  @container (max-width: 400px) {
    .home-buttons .chip span { display: none; }
    .home-buttons .chip { padding: 0 10px; }
  }

  /* ---- rooms ----------------------------------------------------------------------- */
  .room { margin-top: 22px; }
  .room:first-child { margin-top: 18px; }
  .room-head {
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 34px;
    margin-bottom: 12px;
  }
  .room-name {
    flex: 1;
    min-width: 0;
    font-size: 15px;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .icon-group {
    display: inline-flex;
    flex: none;
    border-radius: 10px;
    background: rgba(var(--n-fg-rgb), 0.05);
  }
  .icon-btn {
    display: grid;
    place-items: center;
    width: 34px;
    height: 32px;
    padding: 0;
    border: 0;
    border-radius: 10px;
    background: transparent;
    color: var(--primary-text-color);
    cursor: pointer;
    transition: background-color 0.15s, color 0.15s;
  }
  .icon-btn ha-icon { --mdc-icon-size: 18px; }
  .icon-btn:hover { background: rgba(var(--n-fg-rgb), 0.08); }
  .icon-btn:active { transform: scale(0.94); }
  .icon-btn.more { flex: none; }
  .icon-btn.more.open { background: rgba(var(--n-accent-rgb), 0.14); color: var(--n-accent); }
  .tray { margin: -4px 0 14px; }
  .tray .segmented { display: flex; width: fit-content; max-width: 100%; }

  /* ---- a blind: the window, then its name and state --------------------------------- */
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(var(--n-tile), 1fr));
    gap: 20px 14px;
  }
  .tile { position: relative; min-width: 0; }
  .meta { margin-top: 9px; padding: 0 1px; }
  .name {
    display: block;
    width: 100%;
    padding: 0;
    border: 0;
    background: none;
    color: var(--primary-text-color);
    font: inherit;
    font-size: 14px;
    font-weight: 500;
    line-height: 1.3;
    text-align: left;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    cursor: pointer;
  }
  .name:hover { text-decoration: underline; text-underline-offset: 2px; }
  .battery {
    display: inline-flex;
    align-items: center;
    flex: none;
    margin: 1px 0 0 auto;
    line-height: 16px;
    font-size: 11.5px;
    color: var(--n-muted);
    font-variant-numeric: tabular-nums;
    cursor: pointer;
  }
  .battery ha-icon { --mdc-icon-size: 15px; }
  .battery span:empty { display: none; }
  .battery.low { color: var(--warning-color, #e39700); }
  .battery.critical { color: var(--error-color, #db4437); }
  .meta-bottom { display: flex; align-items: flex-start; gap: 6px; min-height: 18px; }
  .status {
    flex: 1;
    min-width: 0;
    margin-top: 1px;
    font-size: 12.5px;
    line-height: 1.35;
    color: var(--n-muted);
    font-variant-numeric: tabular-nums;
    /* A two-rail blind's "Middle 70% · Bottom 30%" wraps between the rails, never inside one. */
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    overflow: hidden;
  }
  .status.moving { color: var(--n-accent); }

  /* Stop, while a blind is travelling: on the window's corner in the grid, inline in the list. */
  .stop {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 2px;
    flex: none;
    padding: 0;
    border: 0;
    color: var(--n-accent);
    font: inherit;
    font-size: 11.5px;
    font-weight: 600;
    cursor: pointer;
  }
  .stop ha-icon { --mdc-icon-size: 16px; }
  .tile > .stop {
    position: absolute;
    top: -6px;
    right: -2px;
    z-index: 8;
    width: 30px;
    height: 30px;
    border-radius: 50%;
    background: var(--card-background-color, #fff);
    box-shadow: 0 0 0 1.5px rgba(var(--n-accent-rgb), 0.5), 0 2px 6px rgba(0, 0, 0, 0.25);
    animation: n-pop 0.2s var(--n-ease);
  }
  .tile > .stop span { display: none; }
  .tile > .stop:hover { background: var(--n-accent); color: var(--text-primary-color, #fff); }
  .row .stop {
    height: 22px;
    padding: 0 8px 0 5px;
    border-radius: 11px;
    background: rgba(var(--n-accent-rgb), 0.14);
  }
  .row .stop ha-icon { --mdc-icon-size: 14px; }
  @keyframes n-pop { from { transform: scale(0.4); opacity: 0; } }
  .tile.unavailable .win { filter: grayscale(1); opacity: 0.45; }

  /* ---- the window -------------------------------------------------------------------
     A painted casing and sill around a recessed opening. Everything that moves is placed
     in percent of .opening, so the picture scales with the tile. */
  .win {
    position: relative;
    aspect-ratio: 5 / 6;
    cursor: grab;
    touch-action: pan-y;
    -webkit-user-select: none;
    user-select: none;
    -webkit-tap-highlight-color: transparent;
  }
  .win.dragging { cursor: grabbing; }
  .win.disabled { cursor: default; }
  .frame {
    position: absolute;
    left: 4%;
    right: 4%;
    top: 0;
    bottom: 5%;
    border-radius: 3px;
    background: linear-gradient(to bottom, var(--n-trim-hi), var(--n-trim) 10%, var(--n-trim) 85%, var(--n-trim-lo));
    box-shadow: 0 0 0 1px var(--n-trim-edge), 0 8px 18px -10px rgba(40, 30, 20, 0.45);
  }
  .sill {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: 7%;
    border-radius: 2px;
    background: linear-gradient(to bottom, var(--n-trim-hi), var(--n-trim) 35%, var(--n-trim-lo));
    box-shadow: 0 0 0 1px var(--n-trim-edge), 0 5px 8px -5px rgba(40, 30, 20, 0.45);
  }
  .opening {
    position: absolute;
    top: 7%;
    bottom: 5%;
    left: 8.5%;
    right: 8.5%;
  }

  /* The view: sky that follows the sun, a line of hills, the glazing bars and a glint. */
  .view {
    position: absolute;
    inset: 0;
    overflow: hidden;
    background: linear-gradient(to bottom, #6ea6da, #a6cbee 55%, #d9eaf6);
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.2), inset 0 3px 6px rgba(0, 0, 0, 0.25);
  }
  .sun {
    position: absolute;
    inset: 0;
    background: radial-gradient(circle at 76% 30%, rgba(255, 251, 235, 0.95) 0 5%, rgba(255, 244, 214, 0.45) 11%, transparent 32%);
  }
  .hills {
    position: absolute;
    left: -10%;
    right: -10%;
    bottom: 0;
    height: 30%;
    background:
      radial-gradient(70% 100% at 22% 100%, #8fb09a 0 60%, transparent 61%),
      radial-gradient(80% 85% at 82% 100%, #a9c4ae 0 60%, transparent 61%);
  }
  .mullion, .transom {
    position: absolute;
    background: var(--n-trim);
    box-shadow: 0 0 0 0.5px var(--n-trim-edge), 0 1px 2px rgba(0, 0, 0, 0.18);
  }
  .mullion { top: 0; bottom: 0; left: 50%; width: 3.2%; transform: translateX(-50%); }
  .transom { left: 0; right: 0; top: 48%; height: 2.8%; }
  .glint {
    position: absolute;
    inset: 0;
    background: linear-gradient(118deg, transparent 0 30%, rgba(255, 255, 255, 0.22) 30% 38%, transparent 38% 44%, rgba(255, 255, 255, 0.12) 44% 47%, transparent 47%);
  }
  ha-card[data-sky="golden"] .view { background: linear-gradient(to bottom, #7f9fd4, #e8b48d 62%, #f6d7ae); }
  ha-card[data-sky="golden"] .sun { background: radial-gradient(circle at 70% 62%, rgba(255, 236, 196, 0.95) 0 6%, rgba(255, 206, 150, 0.45) 14%, transparent 38%); }
  ha-card[data-sky="golden"] .hills { filter: saturate(0.6) brightness(0.8); }
  ha-card[data-sky="dusk"] .view { background: linear-gradient(to bottom, #26325b, #6b5b88 58%, #d38e77); }
  ha-card[data-sky="dusk"] .sun { background: none; }
  ha-card[data-sky="dusk"] .hills { filter: brightness(0.38) saturate(0.5) hue-rotate(40deg); }
  ha-card[data-sky="night"] .view { background: linear-gradient(to bottom, #0b1224, #16223f 60%, #243559); }
  ha-card[data-sky="night"] .sun {
    background:
      radial-gradient(circle at 72% 24%, #f4f1e4 0 3.2%, rgba(244, 241, 228, 0.25) 5%, transparent 12%),
      radial-gradient(circle at 18% 16%, #fff 0 0.5%, transparent 0.9%),
      radial-gradient(circle at 36% 34%, #fff 0 0.4%, transparent 0.8%),
      radial-gradient(circle at 58% 12%, #fff 0 0.35%, transparent 0.7%),
      radial-gradient(circle at 88% 44%, #fff 0 0.4%, transparent 0.8%),
      radial-gradient(circle at 12% 46%, #fff 0 0.3%, transparent 0.7%);
  }
  ha-card[data-sky="night"] .hills { filter: brightness(0.22) saturate(0.4); }
  ha-card[data-sky="night"] .glint { opacity: 0.4; }

  /* Fabric: cellular (honeycomb) pleats. Each cell is a crease, a shadowed lip, a lit
     face and a darker belly, repeated up from the rail so the pleats travel with it. */
  .fabric {
    position: absolute;
    left: 0;
    right: 0;
    top: var(--n-head);
    height: 0;
    z-index: 1;
    transition: top 0.45s var(--n-ease), height 0.45s var(--n-ease);
  }
  /* The pleat, bottom to top: the glued fold, the shadowed underside of the cell, its lit
     face, and a little shade where the cell above overhangs it. */
  .fabric.sheer, .fabric.single, .fabric.blackout {
    background:
      linear-gradient(to right, var(--n-side), transparent 9%, transparent 91%, var(--n-side)),
      repeating-linear-gradient(
        to top,
        var(--n-crease) 0,
        var(--n-crease) 1px,
        var(--n-lo) 1px,
        var(--n-lo) calc(var(--n-pleat) * 0.3),
        var(--n-hi) calc(var(--n-pleat) * 0.68),
        var(--n-mid) calc(var(--n-pleat) * 0.92),
        var(--n-lo) var(--n-pleat)
      );
  }
  .fabric.single, .fabric.blackout {
    --n-side: rgba(90, 70, 40, 0.1);
    --n-crease: var(--n-cloth-crease);
    --n-lo: var(--n-cloth-lo);
    --n-mid: var(--n-cloth);
    --n-hi: var(--n-cloth-hi);
  }
  /* The light-filtering fabric is see-through: the view -- sky, hills, glazing bars --
     shows through it softened, bright by day and dark at night, as it does in the room. */
  .fabric.sheer {
    --n-side: rgba(90, 70, 40, 0.08);
    --n-crease: var(--n-sheer-crease);
    --n-lo: var(--n-sheer-lo);
    --n-mid: var(--n-sheer);
    --n-hi: var(--n-sheer-hi);
    background-color: rgba(252, 249, 243, 0.14);
    -webkit-backdrop-filter: blur(1.2px) brightness(1.06) saturate(0.85);
    backdrop-filter: blur(1.2px) brightness(1.06) saturate(0.85);
  }
  .fabric.single::after, .fabric.blackout::after {
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(90% 70% at 70% 30%, rgba(255, 250, 235, 0.55), transparent 70%);
    mix-blend-mode: soft-light;
  }
  ha-card[data-sky="night"] .fabric.single::after,
  ha-card[data-sky="night"] .fabric.blackout::after,
  ha-card[data-sky="dusk"] .fabric.single::after,
  ha-card[data-sky="dusk"] .fabric.blackout::after { display: none; }
  ha-card[data-theme="dark"] .fabric,
  ha-card[data-theme="dark"] .rail,
  ha-card[data-theme="dark"] .headrail { filter: brightness(0.88); }

  /* Rails and the headrail: extruded aluminium, lit from above. */
  .rail, .headrail {
    position: absolute;
    background: linear-gradient(to bottom, var(--n-rail-hi), var(--n-rail-face) 40%, var(--n-rail-lo));
  }
  .rail {
    left: 0;
    right: 0;
    top: var(--n-head);
    height: var(--n-rail);
    min-height: 4px;
    z-index: 3;
    border-radius: 1px;
    box-shadow: 0 0 0 0.5px var(--n-rail-edge), 0 2px 3px -1px rgba(0, 0, 0, 0.4);
    transition: top 0.45s var(--n-ease);
  }
  .rail.middle { z-index: 4; }
  .win.stacked .rail.middle .tab { height: calc(100% + 7px); }
  .headrail {
    left: -3%;
    right: -3%;
    top: 0;
    height: var(--n-head);
    z-index: 5;
    border-radius: 2px 2px 1px 1px;
    background: linear-gradient(to bottom, var(--n-rail-hi), var(--n-rail-face) 30%, var(--n-rail-face) 62%, var(--n-rail-lo));
    box-shadow: 0 0 0 0.5px var(--n-rail-edge), 0 3px 5px -2px rgba(0, 0, 0, 0.45);
  }

  /* The pull tab: what a hand reaches for on a cordless shade, and what the card drags. */
  .tab {
    position: absolute;
    left: 50%;
    top: 100%;
    width: 26%;
    min-width: 20px;
    max-width: 38px;
    height: 7px;
    transform: translateX(-50%);
    border-radius: 0 0 5px 5px;
    background: linear-gradient(to bottom, var(--n-rail-face), var(--n-rail-lo));
    box-shadow: 0 0 0 0.5px var(--n-rail-edge), 0 2px 3px -1px rgba(0, 0, 0, 0.4);
    transition: background-color 0.15s, height 0.15s, box-shadow 0.15s;
  }
  .rail.hot .tab, .rail.held .tab {
    height: 9px;
    background: var(--n-accent);
    box-shadow: 0 0 0 0.5px rgba(0, 0, 0, 0.25), 0 2px 8px rgba(var(--n-accent-rgb), 0.55);
  }
  .rail.moving:not(.held) .tab { animation: n-pulse 1.6s ease-in-out infinite; }
  @keyframes n-pulse {
    50% { background: var(--n-accent); box-shadow: 0 0 0 0.5px rgba(0, 0, 0, 0.25), 0 1px 6px rgba(var(--n-accent-rgb), 0.5); }
  }

  /* Where a rail actually is while it travels to where it was sent. */
  .marker {
    position: absolute;
    left: 0;
    right: 0;
    height: 0;
    z-index: 2;
    border-top: 2px dashed var(--n-accent);
    transform: translateY(-1px);
    opacity: 0;
    transition: opacity 0.25s, top 0.8s linear;
    filter: drop-shadow(0 0 1px rgba(255, 255, 255, 0.9));
    pointer-events: none;
  }
  .marker.on { opacity: 0.95; }

  /* Grab zones: a band around each rail, the only place a touch starts a drag. Everywhere
     else on the picture a finger scrolls the page, so swiping past cannot move a blind. */
  .zone {
    position: absolute;
    left: -8%;
    right: -8%;
    height: 34px;
    z-index: 6;
    border-radius: 8px;
    transform: translateY(-50%);
    touch-action: none;
    outline: none;
    transition: top 0.45s var(--n-ease);
  }
  .zone:focus-visible { box-shadow: 0 0 0 2px var(--n-accent); }
  .win.dragging .fabric, .win.dragging .rail, .win.dragging .zone { transition: none; }
  .win.disabled .zone { touch-action: pan-y; }

  .bubble {
    position: absolute;
    left: 50%;
    z-index: 7;
    padding: 3px 8px;
    border-radius: 11px;
    background: rgba(24, 26, 30, 0.86);
    color: #fff;
    font-size: 12px;
    font-weight: 600;
    line-height: 16px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    transform: translate(-50%, calc(-100% - 10px));
    opacity: 0;
    transition: opacity 0.15s;
    pointer-events: none;
  }
  .bubble.on { opacity: 1; }

  /* ---- list layout (hide_picture) --------------------------------------------------- */
  .list { display: flex; flex-direction: column; gap: 12px; }
  /* One line per blind: the name, then its status (while moving), Stop and battery. */
  .row .meta { display: flex; align-items: center; gap: 8px; margin: 0 0 2px; }
  .row .name { flex: 1; width: auto; min-width: 0; }
  .row .meta-bottom { flex: none; align-items: center; min-height: 0; }
  .row .battery { margin-top: 0; }
  .slider {
    display: grid;
    grid-template-columns: 64px 1fr 40px;
    align-items: center;
    gap: 10px;
    min-height: 30px;
  }
  .slider-label { font-size: 12.5px; color: var(--n-muted); }
  .slider-value {
    text-align: right;
    font-size: 13px;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
  }
  .slider input {
    -webkit-appearance: none;
    appearance: none;
    width: 100%;
    height: 6px;
    margin: 0;
    border-radius: 3px;
    background: linear-gradient(to right, var(--n-accent) var(--n-fill, 0%), rgba(var(--n-fg-rgb), 0.12) var(--n-fill, 0%));
    cursor: pointer;
  }
  .slider input::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 0 0 0.5px rgba(0, 0, 0, 0.2), 0 1px 4px rgba(0, 0, 0, 0.3);
  }
  .slider input::-moz-range-thumb {
    width: 20px;
    height: 20px;
    border: 0;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 0 0 0.5px rgba(0, 0, 0, 0.2), 0 1px 4px rgba(0, 0, 0, 0.3);
  }
  .slider input:focus-visible { outline: 2px solid var(--n-accent); outline-offset: 4px; }
  .slider input:disabled { cursor: default; }
  /* The sliders already say where each rail is; the status line only speaks up to say it
     is moving or unavailable. */
  .row .status.rest { display: none; }
  .row.unavailable { opacity: 0.5; }

  .empty { padding: 8px 0 4px; color: var(--n-muted); }
`;

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
    // Positions the user chose, drawn until the hub reports them as its target. Keyed by
    // the entity the write went to; each entry is { value, at }.
    this._pending = new Map();
    this._cells = [];
    // The header's text node and summary line (see _render).
    this._headerText = null;
    this._summary = null;
  }

  setConfig(config) {
    this._config = config || {};
    this._rendered = false;
    this._signature = undefined;
    if (this.shadowRoot) this.shadowRoot.innerHTML = "";
  }

  getCardSize() {
    const blinds = this._hass ? this._collectBlinds().length : 3;
    return 2 + Math.ceil(blinds / 3) * 4;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
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

  // ---- data ------------------------------------------------------------------------

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
        // even when its translation key says otherwise.
        blind.battery = entityId;
      }
    }

    // A device with no cover is the hub, not a blind.
    return [...blinds.values()].filter((blind) => blind.bottomCover);
  }

  /**
   * The heading to show: the configured title, else the hub's name.
   *
   * A configured `title` always wins, whatever it says -- including `""` for a blank
   * heading. With no title the header names the hub, so a house with two hubs gets two
   * cards you can tell apart; "Shades" is only the fallback for when no hub device can be
   * found (an install with no Norman devices yet, or before the registry has loaded).
   *
   * Cards added from the picker before v0.30 have `title: "Shades"` saved in their config,
   * because `getStubConfig()` used to supply it. Those keep saying "Shades" until the title
   * is removed -- the card cannot tell a saved default from a deliberate choice.
   */
  _headingText() {
    const configured = this._config.title;
    return configured !== undefined ? configured : (this._hubName() ?? "Shades");
  }

  /**
   * The hub's name, as Home Assistant has it.
   *
   * The hub is the one Norman device with entities but no cover -- it carries the MAC
   * address, Wi-Fi and time-zone sensors. `name_by_user` wins, matching how Home Assistant
   * shows the device everywhere else. Returns null when there is no hub to name.
   */
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

  /** Blinds grouped by room: in the configured `rooms` order if one is given, else A-Z. */
  _roomsOf(blinds) {
    const filter =
      Array.isArray(this._config.rooms) && this._config.rooms.length ? this._config.rooms : null;
    const rooms = new Map();
    for (const blind of blinds) {
      if (filter && !filter.includes(blind.room)) continue;
      if (!rooms.has(blind.room)) rooms.set(blind.room, []);
      rooms.get(blind.room).push(blind);
    }
    for (const list of rooms.values()) {
      list.sort((a, b) => a.name.localeCompare(b.name));
    }
    const order = (room) => (filter ? filter.indexOf(room) : 0);
    return [...rooms.entries()].sort((a, b) => order(a[0]) - order(b[0]) || a[0].localeCompare(b[0]));
  }

  _numberOf(entityId) {
    const state = this._hass.states[entityId];
    if (!state || state.state === "unknown" || state.state === "unavailable") return null;
    const value = Number(state.state);
    return Number.isNaN(value) ? null : value;
  }

  /**
   * A blind's rails, bottom first: `rails[0]` is the bottom rail and `rails[1]`, when there
   * is one, the middle rail above it.
   */
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

  /** Where the hub says a rail is, and where it is sending it (equal when idle). */
  _railState(rail) {
    const cover = this._hass.states[rail.coverId];
    let current = rail.numberId ? this._numberOf(rail.numberId) : null;
    if (current === null) {
      const position = cover?.attributes?.current_position;
      current = position === undefined || position === null ? null : Number(position);
    }
    const heading = cover?.attributes?.target_position;
    const target = heading === undefined || heading === null ? current : Number(heading);
    return { current, target };
  }

  /**
   * Where a rail is drawn: the position the user just chose while the hub takes it up,
   * else where the hub is sending it. The picture shows where the shade is GOING; the
   * marker and the status line say where it is on the way.
   */
  _railValue(rail) {
    const pending = this._pending.get(rail.numberId || rail.coverId);
    if (pending) return pending.value;
    return this._railState(rail).target;
  }

  _isUnavailable(blind) {
    const state = this._hass.states[blind.bottomCover];
    return !state || state.state === "unavailable";
  }

  // ---- building --------------------------------------------------------------------

  _render() {
    const style = document.createElement("style");
    style.textContent = STYLES;

    const card = document.createElement("ha-card");
    card.appendChild(style);
    this._card = card;

    // With no configured title the header names the HUB rather than saying "Shades": a
    // house with two hubs gets two cards, and "Shades" twice says nothing about which.
    const header = el("div", "header");
    const titles = el("div", "titles");
    const text = el("div", "header-text", this._headingText());
    // Kept so the heading can follow a hub rename, or fill in once the device registry has
    // loaded -- _render() runs once, but the hub's name can arrive or change later.
    this._headerText = text;
    this._summary = el("div", "summary");
    titles.append(text, this._summary);
    header.appendChild(titles);
    if (!this._config.hide_home_controls) header.appendChild(this._buildHomeControls());
    card.appendChild(header);

    this._body = el("div", "body");
    card.appendChild(this._body);

    this.shadowRoot.innerHTML = "";
    this.shadowRoot.appendChild(card);
    this._update();
  }

  _update() {
    if (!this._body || !this._hass) return;

    const sky = skyOf(this._hass.states["sun.sun"]);
    if (this._card.dataset.sky !== sky) this._card.dataset.sky = sky;
    const theme = this._hass.themes?.darkMode ? "dark" : "light";
    if (this._card.dataset.theme !== theme) this._card.dataset.theme = theme;

    if (this._headerText) {
      const title = this._headingText();
      if (this._headerText.textContent !== title) this._headerText.textContent = title;
      this._headerText.hidden = !title;
    }

    const rooms = this._roomsOf(this._collectBlinds());

    // Rebuild only when the set of blinds (or a name) changes; otherwise patch values in
    // place so a rail being dragged is never replaced under the user's finger.
    const signature = rooms
      .map(([room, list]) => `${room}:${list.map((b) => `${b.deviceId}=${b.name}`).join(",")}`)
      .join("|");
    if (signature !== this._signature) {
      this._signature = signature;
      this._build(rooms);
    }

    // Home Assistant sets `hass` on every state change in the house. Redraw only when one of
    // this card's own entities changed -- state objects are replaced, never mutated, so an
    // identity check is enough.
    const seen = this._watched.map((entityId) => this._hass.states[entityId]);
    if (this._seen && seen.every((state, index) => state === this._seen[index])) return;
    this._seen = seen;
    this._patch();
  }

  _build(rooms) {
    this._body.innerHTML = "";
    this._cells = [];
    this._seen = null;
    this._watched = [
      ...rooms.flatMap(([, list]) =>
        list.flatMap((blind) => [
          blind.bottomCover,
          blind.middleCover,
          blind.bottomNumber,
          blind.middleNumber,
          blind.battery,
        ]),
      ),
    ].filter(Boolean);

    if (!rooms.length) {
      this._body.appendChild(
        el(
          "div",
          "empty",
          "No Norman blinds found. Set up the Norman integration, or check that its cover " +
            "entities are not hidden.",
        ),
      );
      return;
    }

    // With the headings hidden the rooms run together as one grid.
    const sections = this._config.hide_room_names
      ? [[null, rooms.flatMap(([, list]) => list)]]
      : rooms;

    for (const [roomName, list] of sections) {
      const room = el("section", "room");
      if (roomName !== null) this._buildRoomHead(room, roomName, list);

      const grid = el("div", this._config.hide_picture ? "list" : "grid");
      for (const blind of list) grid.appendChild(this._buildBlind(blind));
      room.appendChild(grid);
      this._body.appendChild(room);
    }
  }

  /**
   * A room's heading: its name and count, open/stop/close for the whole room, and a button
   * that folds out the app's three presets for the room.
   */
  _buildRoomHead(room, roomName, blinds) {
    const head = el("div", "room-head");
    head.appendChild(el("div", "room-name", roomName));
    room.appendChild(head);

    if (!this._config.hide_room_controls) {
      head.appendChild(this._buildRoomControls(roomName, blinds));
    }
    if (!this._config.hide_room_presets) {
      const tray = el("div", "tray");
      tray.hidden = true;
      tray.appendChild(this._buildRoomPresets(roomName));
      const more = this._iconButton("mdi:dots-horizontal", `Presets for ${roomName}`, () => {
        tray.hidden = !tray.hidden;
        more.classList.toggle("open", !tray.hidden);
        more.setAttribute("aria-expanded", String(!tray.hidden));
      });
      more.className = "icon-btn more";
      more.setAttribute("aria-expanded", "false");
      head.appendChild(more);
      room.appendChild(tray);
    }
  }

  /**
   * Open / stop / close every rail of every blind in one room.
   *
   * This is NOT the hub's own room verb. Close here sends close_cover to every rail, so a
   * two-rail blind ends at bottom 0 AND middle 0 -- both rails down, which leaves the
   * light-filtering sheer across the window. The app's "Best privacy" is bottom 0 with
   * middle 100: the sheer stacked away and the blackout across the window instead. That one
   * lives in the presets tray (norman.room_command).
   */
  _buildRoomControls(roomName, blinds) {
    const controls = el("div", "icon-group room-buttons");
    for (const [icon, service, label] of ROOM_ACTIONS) {
      controls.appendChild(
        this._iconButton(icon, `${label} every blind in ${roomName}`, () => {
          // Every rail in the room: the bottom rails, plus the middle rails of two-rail
          // blinds. One service call with a list, not one call per entity.
          const entityId = [];
          for (const blind of blinds) {
            if (blind.bottomCover) entityId.push(blind.bottomCover);
            if (blind.middleCover) entityId.push(blind.middleCover);
          }
          if (entityId.length) this._hass.callService("cover", service, { entity_id: entityId });
        }),
      );
    }
    return controls;
  }

  /**
   * The app's three buttons for the whole house, via the hub's own scope-less verb.
   *
   * Omitting RoomID is what makes the hub treat a command as house-wide, so this is one
   * request however many blinds there are -- the same three the app's "All Rooms" screen
   * sends. They carry the app's names rather than open/close arrows because they are not
   * open and close: "Best privacy" leaves a two-rail blind's middle rail fully OPEN.
   *
   * There is deliberately no house-wide Stop: the hub's stop is per blind, so it would have
   * to fan out over every cover, and a Stop that lags the blinds it is stopping is worse
   * than none. A room's Stop fans out over a smaller set.
   */
  _buildHomeControls() {
    const controls = el("div", "segmented home-buttons");
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

  /**
   * The same three, scoped to one room, via norman.room_command.
   *
   * The action matches on the HUB's room name while the card groups by Home Assistant area.
   * The integration seeds areas from those names, so they agree until an area is renamed --
   * and then the action names the rooms the hub does know.
   */
  _buildRoomPresets(roomName) {
    const presets = el("div", "segmented room-presets");
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

  /** A preset: an icon and a word, since "blinds-horizontal" alone does not say "privacy". */
  _buildChip(preset, title, onClick) {
    const chip = el("button", "chip");
    chip.type = "button";
    chip.append(haIcon(preset.icon), el("span", null, preset.label));
    chip.title = title;
    chip.setAttribute("aria-label", title);
    chip.addEventListener("click", () => {
      onClick();
      // The blinds take many seconds to answer, so the button acknowledges the press.
      chip.classList.add("sent");
      setTimeout(() => chip.classList.remove("sent"), 1500);
    });
    return chip;
  }

  _iconButton(icon, label, onClick) {
    const button = el("button", "icon-btn");
    button.type = "button";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.appendChild(haIcon(icon));
    button.addEventListener("click", onClick);
    return button;
  }

  /** One blind: the window (or, with hide_picture, a slider per rail), its name and state. */
  _buildBlind(blind) {
    const rails = this._railsOf(blind);
    const list = Boolean(this._config.hide_picture);
    const tile = el("div", list ? "row" : "tile");

    const shade = list ? null : this._buildShade(blind, rails);
    if (shade) tile.appendChild(shade.element);

    const meta = el("div", "meta");
    const name = el("button", "name", blind.name);
    name.type = "button";
    name.title = `${blind.name} details`;
    name.addEventListener("click", () => this._showMore(blind.bottomCover));

    const bottom = el("div", "meta-bottom");
    const status = el("span", "status");
    bottom.appendChild(status);

    let batteryEl = null;
    if (blind.battery && !this._config.hide_battery) {
      batteryEl = el("span", "battery");
      batteryEl.append(haIcon("mdi:battery"), el("span"));
      // A bare "84%" next to a blind reads as a position; the icon, title and aria-label
      // say it is the battery.
      batteryEl.setAttribute("role", "img");
      batteryEl.addEventListener("click", () => this._showMore(blind.battery));
      bottom.appendChild(batteryEl);
    }

    const stop = el("button", "stop");
    stop.type = "button";
    stop.hidden = true;
    stop.title = `Stop ${blind.name}`;
    stop.setAttribute("aria-label", stop.title);
    stop.append(haIcon("mdi:stop"), el("span", null, "Stop"));
    stop.addEventListener("click", () => this._stop(rails));
    // On the window's corner in the grid -- outside the window itself, so a press on it is
    // never taken for the start of a drag.
    (list ? bottom : tile).appendChild(stop);
    meta.append(name, bottom);
    tile.appendChild(meta);

    // In the list layout the rails are sliders, top rail first as on the blind.
    const sliders = list ? [...rails].reverse().map((rail) => this._buildSlider(rails, rail)) : [];
    for (const slider of sliders) tile.appendChild(slider.row);

    this._cells.push({ blind, rails, tile, shade, batteryEl, status, stop, sliders });
    return tile;
  }

  /**
   * The window for one blind: casing, sill, the view, and the shade hanging in it.
   *
   * One fabric band, one rail and one grab zone per rail. On a two-rail blind the band from
   * the headrail to the middle rail is the light-filtering sheer and the band from the
   * middle rail to the bottom rail the blackout. The app's "Best privacy" (bottom 0,
   * middle 100) therefore stacks the sheer away and draws the blackout across the window:
   * "closed for privacy, sheer fabric still open".
   *
   * The two rails' pull tabs sit apart -- the middle rail's left of centre, the bottom
   * rail's right -- so that both can still be taken hold of when the rails are together.
   */
  _buildShade(blind, rails) {
    const element = el("div", "win");
    element.setAttribute("role", "group");
    element.setAttribute("aria-label", blind.name);

    const frame = el("div", "frame");
    const opening = el("div", "opening");
    const view = el("div", "view");
    view.append(el("div", "sun"), el("div", "hills"), el("div", "mullion"), el("div", "transom"), el("div", "glint"));

    const twoRail = rails.length > 1;
    const bands = rails.map((_, index) =>
      el("div", `fabric ${twoRail ? (index === 1 ? "sheer" : "blackout") : "single"}`),
    );
    const markers = rails.map(() => el("div", "marker"));
    const railEls = rails.map((_, index) => {
      const rail = el("div", `rail ${index === 0 ? "bottom" : "middle"}`);
      const tab = el("div", "tab");
      tab.style.left = `${this._tabX(rails, index)}%`;
      rail.appendChild(tab);
      return rail;
    });
    const zones = rails.map((rail, index) => {
      const zone = el("div", "zone");
      zone.tabIndex = 0;
      zone.dataset.index = String(index);
      zone.setAttribute("role", "slider");
      zone.setAttribute("aria-orientation", "vertical");
      zone.setAttribute("aria-valuemin", "0");
      zone.setAttribute("aria-valuemax", "100");
      zone.setAttribute("aria-label", twoRail ? `${blind.name} ${rail.label.toLowerCase()}` : blind.name);
      return zone;
    });
    const bubble = el("div", "bubble");

    opening.append(view, ...bands, ...markers, ...railEls, el("div", "headrail"), ...zones, bubble);
    frame.appendChild(opening);
    element.append(frame, el("div", "sill"));

    const shade = { element, opening, bands, markers, railEls, zones, bubble, rails, dragValues: {} };
    this._bindShade(shade);
    return shade;
  }

  /**
   * Dragging and keys.
   *
   * A mouse can press anywhere on the window and the nearest rail follows; a finger has to
   * start on a rail's grab zone, so the rest of the picture still scrolls the page. The
   * drag follows the pointer's movement rather than its position, so a press never makes a
   * rail jump, and nothing is written until release -- a tap writes nothing at all.
   */
  _bindShade(shade) {
    const { element, opening } = shade;
    let press = null;

    const setHot = (index) => {
      shade.railEls.forEach((rail, i) => rail.classList.toggle("hot", i === index));
    };
    // Which rail a press means: the nearest one, or -- where the two rails are together and
    // so equally near -- the one whose tab is on that side.
    const pick = (event) => {
      const rect = opening.getBoundingClientRect();
      const y = ((event.clientY - rect.top) / rect.height) * 100;
      const centers = shade.rails.map(
        (_, index) => this._railTop(shade, index, this._shadeValue(shade, index)) + SHADE_RAIL_PCT / 2,
      );
      if (shade.rails.length > 1 && centers[0] - centers[1] < SHADE_RAIL_PCT * 2.5) {
        const nearStack = y > centers[1] - SHADE_RAIL_PCT * 3 && y < centers[0] + SHADE_RAIL_PCT * 3;
        if (nearStack) return event.clientX - rect.left < rect.width / 2 ? 1 : 0;
      }
      let best = 0;
      centers.forEach((center, index) => {
        if (Math.abs(center - y) < Math.abs(centers[best] - y)) best = index;
      });
      return best;
    };

    element.addEventListener("pointerdown", (event) => {
      if (shade.disabled || press) return;
      if (event.pointerType === "mouse" && event.button !== 0) return;
      const onZone = event.target?.classList?.contains("zone");
      if (event.pointerType !== "mouse" && !onZone) return;
      const rect = opening.getBoundingClientRect();
      if (!rect.height) return;
      press = { id: event.pointerId, index: pick(event), y0: event.clientY, rect, started: false, step: null };
      element.setPointerCapture?.(event.pointerId);
      event.preventDefault();
    });

    element.addEventListener("pointermove", (event) => {
      if (!press) {
        if (event.pointerType === "mouse" && !shade.disabled) setHot(pick(event));
        return;
      }
      if (event.pointerId !== press.id) return;
      const dy = event.clientY - press.y0;
      if (!press.started) {
        if (Math.abs(dy) < DRAG_SLOP) return;
        press.started = true;
        press.start = this._shadeValue(shade, press.index) ?? 0;
        press.travel = (press.rect.height * this._travelPct(shade)) / 100;
        element.classList.add("dragging");
        shade.railEls[press.index].classList.add("held");
        setHot(press.index);
      }
      const value = clamp(press.start - (dy / press.travel) * 100);
      this._dragTo(shade, press.index, value);
      const step = clampToStep(value);
      this._showBubble(shade, press.index, step);
      if (press.step !== null && step !== press.step) navigator.vibrate?.(4);
      press.step = step;
    });

    const finish = (event, commit) => {
      if (!press || event.pointerId !== press.id) return;
      const { index, started } = press;
      press = null;
      element.releasePointerCapture?.(event.pointerId);
      element.classList.remove("dragging");
      shade.railEls[index].classList.remove("held");
      if (event.pointerType !== "mouse") setHot(-1);
      this._hideBubble(shade);
      if (!started) return;
      const value = shade.dragValues[index];
      shade.dragValues = {};
      if (commit) this._move(shade.rails, index, clampToStep(value));
      this._patch();
    };
    element.addEventListener("pointerup", (event) => finish(event, true));
    // A cancelled pointer (the browser took the gesture) puts the rail back.
    element.addEventListener("pointercancel", (event) => finish(event, false));
    element.addEventListener("pointerleave", (event) => {
      if (!press && event.pointerType === "mouse") setHot(-1);
    });

    shade.zones.forEach((zone, index) => {
      zone.addEventListener("focus", () => setHot(index));
      zone.addEventListener("blur", () => setHot(-1));
      zone.addEventListener("keydown", (event) => this._onKey(shade, index, event));
    });
  }

  /** Arrow keys move a rail a step; the write goes out once the keys stop. */
  _onKey(shade, index, event) {
    if (shade.disabled) return;
    const now = this._shadeValue(shade, index) ?? 0;
    const moves = {
      ArrowUp: now + STEP,
      ArrowRight: now + STEP,
      ArrowDown: now - STEP,
      ArrowLeft: now - STEP,
      PageUp: now + 3 * STEP,
      PageDown: now - 3 * STEP,
      Home: 0,
      End: 100,
    };
    if (!(event.key in moves)) return;
    event.preventDefault();
    const value = clampToStep(moves[event.key]);
    this._dragTo(shade, index, value);
    this._showBubble(shade, index, value);
    clearTimeout(shade.keyTimer);
    shade.keyTimer = setTimeout(() => {
      shade.dragValues = {};
      this._hideBubble(shade);
      this._move(shade.rails, index, value);
      this._patch();
    }, KEY_COMMIT_MS);
  }

  /**
   * Where a two-rail blind's other rail ends up when rail `index` goes to `value`.
   *
   * The middle rail always hangs above the bottom rail, so the other rail stays where it is
   * unless `value` would pass it -- and then it is carried along, as it is on the blind: the
   * middle rail pulled down past the bottom rail takes the bottom rail with it, and the
   * bottom rail pushed up past the middle rail takes the middle rail up. The integration
   * does the same when it sends the move, in the one command. Null on a single-rail blind.
   */
  _carried(rails, index, value) {
    if (rails.length < 2) return null;
    const other = this._railValue(rails[1 - index]);
    if (other === null) return null;
    return index === 0 ? Math.max(other, value) : Math.min(other, value);
  }

  /** Draw rail `index` at `value` mid-drag, with the other rail carried if it is passed. */
  _dragTo(shade, index, value) {
    shade.dragValues = { [index]: value };
    const carried = this._carried(shade.rails, index, value);
    if (carried !== null && carried !== this._railValue(shade.rails[1 - index])) {
      shade.dragValues[1 - index] = carried;
    }
    this._drawShade(shade);
  }

  /**
   * Send rail `index` to `value`. One write: the integration carries the other rail along
   * in the same hub command when it has to, so that rail is only drawn there until the hub
   * reports it -- never written separately, where two commands could cross in flight.
   */
  _move(rails, index, value) {
    const rail = rails[index];
    if (value === this._railValue(rail)) return;
    const carried = this._carried(rails, index, value);
    if (carried !== null && carried !== this._railValue(rails[1 - index])) {
      this._expect(rails[1 - index], carried);
    }
    this._setRail(rail, value);
  }

  /** Where a two-rail blind's pull tab sits across the rail, in percent: apart, so both can be reached. */
  _tabX(rails, index) {
    if (rails.length < 2) return 50;
    return index === 1 ? 32 : 68;
  }

  /** What a rail is drawn at right now: a drag or key press, else _railValue. */
  _shadeValue(shade, index) {
    const dragged = shade.dragValues?.[index];
    if (dragged !== undefined) return dragged;
    return this._railValue(shade.rails[index]);
  }

  /** The distance a rail travels, as a percentage of the opening: what the rails leave. */
  _travelPct(shade) {
    return 100 - SHADE_HEAD_PCT - shade.rails.length * SHADE_RAIL_PCT;
  }

  /**
   * Where a rail's top edge sits, in percent down the opening. Open (100) is tucked under
   * the headrail -- or under the middle rail, for the bottom rail of a two-rail blind --
   * and closed (0) rests on the sill.
   */
  _railTop(shade, index, value) {
    const above = shade.rails.length - 1 - index;
    const position = value === null || value === undefined ? 0 : value;
    return SHADE_HEAD_PCT + above * SHADE_RAIL_PCT + ((100 - position) / 100) * this._travelPct(shade);
  }

  /**
   * Place every band, rail and grab zone of one picture in a single pass, top rail first:
   * each band hangs from the edge above it (the headrail, or the rail above) to its rail.
   */
  _drawShade(shade) {
    if (shade.rails.length > 1) {
      const together = this._shadeValue(shade, 1) - this._shadeValue(shade, 0) < 1;
      shade.element.classList.toggle("stacked", together);
    }
    let edge = SHADE_HEAD_PCT;
    for (let index = shade.rails.length - 1; index >= 0; index -= 1) {
      const top = this._railTop(shade, index, this._shadeValue(shade, index));
      const band = shade.bands[index];
      band.style.top = `${round3(edge)}%`;
      band.style.height = `${round3(Math.max(0, top - edge))}%`;
      shade.railEls[index].style.top = `${round3(top)}%`;
      shade.zones[index].style.top = `${round3(top + SHADE_RAIL_PCT / 2)}%`;
      edge = top + SHADE_RAIL_PCT;
    }
  }

  _showBubble(shade, index, value) {
    const { bubble } = shade;
    bubble.textContent = `${Math.round(value)}%`;
    bubble.style.top = `${round3(this._railTop(shade, index, this._shadeValue(shade, index)))}%`;
    bubble.style.left = `${this._tabX(shade.rails, index)}%`;
    bubble.classList.add("on");
  }

  _hideBubble(shade) {
    shade.bubble.classList.remove("on");
  }

  /** The list layout's control for one rail: a plain range input, in 10% steps. */
  _buildSlider(rails, rail) {
    const row = el("label", "slider");
    const label = el("span", "slider-label", rails.length > 1 ? shortLabel(rail) : "Position");
    const input = el("input");
    input.type = "range";
    input.min = "0";
    input.max = "100";
    input.step = String(STEP);
    input.setAttribute("aria-label", `${rail.label} position`);
    const value = el("span", "slider-value");
    const slider = { rail, row, input, value, holding: false };
    input.addEventListener("pointerdown", () => {
      slider.holding = true;
    });
    input.addEventListener("input", () => {
      value.textContent = `${clampToStep(input.value)}%`;
      input.style.setProperty?.("--n-fill", `${input.value}%`);
    });
    input.addEventListener("change", () => {
      slider.holding = false;
      this._move(rails, rails.indexOf(rail), clampToStep(input.value));
      this._patch();
    });
    row.append(label, input, value);
    return slider;
  }

  // ---- writing ---------------------------------------------------------------------

  /**
   * Draw a rail at `position` until the hub reports it as the rail's target. Past
   * PENDING_MS the hub's own value is shown again, so a move that never happened shows.
   * Returns a function that drops the expectation early (a failed call).
   */
  _expect(rail, position) {
    const key = rail.numberId || rail.coverId;
    const entry = { value: position, at: Date.now() };
    this._pending.set(key, entry);
    const retire = () => {
      if (this._pending.get(key) !== entry) return;
      this._pending.delete(key);
      this._patch();
    };
    setTimeout(retire, PENDING_MS);
    return retire;
  }

  /** Write a rail position, preferring the number entity so the 10% step is enforced. */
  _setRail(rail, position) {
    const retire = this._expect(rail, position);
    const call = rail.numberId
      ? this._hass.callService("number", "set_value", { entity_id: rail.numberId, value: position })
      : this._hass.callService("cover", "set_cover_position", { entity_id: rail.coverId, position });
    // A failed call is reported by Home Assistant; the picture goes back to the hub's values.
    Promise.resolve(call).catch(retire);
  }

  /** Call a cover service on the rail's own entity -- never the blind's bottom rail. */
  _coverService(rail, service) {
    if (rail.coverId) this._hass.callService("cover", service, { entity_id: rail.coverId });
  }

  /**
   * Stop a blind. The hub's stop is per blind, so one call on a moving rail stops them all;
   * a second would only queue behind it at the hub's pace.
   */
  _stop(rails) {
    const moving = rails.find((rail) => {
      const { current, target } = this._railState(rail);
      return current !== null && target !== null && Math.round(current) !== Math.round(target);
    });
    for (const rail of rails) this._pending.delete(rail.numberId || rail.coverId);
    this._coverService(moving || rails[0], "stop_cover");
    this._patch();
  }

  // ---- patching --------------------------------------------------------------------

  _patch() {
    if (!this._cells || !this._hass) return;
    let open = 0;
    let moving = 0;
    let lowBattery = 0;

    for (const cell of this._cells) {
      const { blind, rails, shade } = cell;
      const unavailable = this._isUnavailable(blind);
      cell.tile.classList.toggle("unavailable", unavailable);

      const states = rails.map((rail) => {
        const state = this._railState(rail);
        const key = rail.numberId || rail.coverId;
        const pending = this._pending.get(key);
        // The hub has taken the choice up once it reports it as the target.
        if (pending && state.target !== null && Math.round(state.target) === pending.value) {
          this._pending.delete(key);
        }
        const shown = this._railValue(rail);
        return {
          ...state,
          shown,
          moving:
            !unavailable &&
            state.current !== null &&
            shown !== null &&
            Math.round(shown) !== Math.round(state.current),
        };
      });

      if (shade) this._patchShade(shade, states, unavailable);
      for (const slider of cell.sliders) this._patchSlider(slider, unavailable);

      const status = this._statusOf(rails, states, unavailable);
      cell.status.textContent = status;
      const isMoving = states.some((state) => state.moving);
      cell.status.classList.toggle("moving", isMoving);
      cell.status.classList.toggle("rest", !isMoving && !unavailable);
      cell.stop.hidden = !isMoving;

      if (cell.batteryEl) {
        const level = this._numberOf(blind.battery);
        const kind = batteryClass(level);
        cell.batteryEl.className = `battery ${kind}`;
        cell.batteryEl.firstChild.setAttribute("icon", batteryIcon(level));
        const shown = level === null ? "—" : `${Math.round(level)}%`;
        cell.batteryEl.lastChild.textContent = shown;
        cell.batteryEl.title = level === null ? "Battery level unknown" : `Battery ${shown}`;
        cell.batteryEl.setAttribute("aria-label", cell.batteryEl.title);
        if (kind === "low" || kind === "critical") lowBattery += 1;
      }

      if ((states[0].shown ?? 0) > 0) open += 1;
      if (isMoving) moving += 1;
    }

    this._patchSummary(this._cells.length, open, moving, lowBattery);
  }

  _patchShade(shade, states, unavailable) {
    shade.disabled = unavailable;
    shade.element.classList.toggle("disabled", unavailable);
    this._drawShade(shade);
    states.forEach((state, index) => {
      const held = shade.dragValues[index] !== undefined;
      const marker = shade.markers[index];
      const showMarker = state.moving && !held;
      marker.classList.toggle("on", showMarker);
      if (showMarker) {
        marker.style.top = `${round3(this._railTop(shade, index, state.current) + SHADE_RAIL_PCT / 2)}%`;
      }
      shade.railEls[index].classList.toggle("moving", state.moving);
      const zone = shade.zones[index];
      const value = Math.round(this._shadeValue(shade, index) ?? 0);
      zone.setAttribute("aria-valuenow", String(value));
      zone.setAttribute("aria-valuetext", `${value}% open`);
      zone.setAttribute("aria-disabled", String(unavailable));
    });
  }

  _patchSlider(slider, unavailable) {
    const { rail, input, value } = slider;
    input.disabled = unavailable;
    if (slider.holding) return;
    const shown = this._railValue(rail);
    input.value = String(clampToStep(shown ?? 0));
    input.style.setProperty?.("--n-fill", `${shown ?? 0}%`);
    value.textContent = shown === null ? "—" : `${Math.round(shown)}%`;
  }

  /**
   * A blind's state in a few words. At rest: "Open", "Closed", "60% open" -- or, on a
   * two-rail blind, "Privacy" for the app's preset and both rails otherwise. On the move:
   * which way, and where it has got to.
   */
  _statusOf(rails, states, unavailable) {
    if (unavailable) return "Unavailable";
    const travelling = states.findIndex((state) => state.moving);
    if (travelling >= 0) {
      const { current, shown } = states[travelling];
      const verb = shown > current ? "Opening" : "Closing";
      const which = rails.length > 1 ? `${shortLabel(rails[travelling])}\u00a0` : "";
      return `${verb} · ${which}${Math.round(current)}%`;
    }
    const [bottom, middle] = states.map((state) => (state.shown === null ? null : Math.round(state.shown)));
    if (bottom === null) return "Position unknown";
    if (rails.length < 2 || middle === null) {
      if (bottom >= 100) return "Open";
      if (bottom <= 0) return "Closed";
      return `${bottom}% open`;
    }
    if (bottom >= 100 && middle >= 100) return "Open";
    if (bottom <= 0 && middle <= 0) return "Closed";
    if (bottom <= 0 && middle >= 100) return "Privacy";
    return `${shortLabel(rails[1])}\u00a0${middle}%\u00a0· ${shortLabel(rails[0])}\u00a0${bottom}%`;
  }

  _patchSummary(total, open, moving, lowBattery) {
    const summary = this._summary;
    if (!summary) return;
    const parts = [[`${total} ${total === 1 ? "shade" : "shades"}`, ""]];
    if (total) {
      if (open === 0) parts.push(["all closed", ""]);
      else if (open === total) parts.push([total === 1 ? "open" : "all open", ""]);
      else parts.push([`${open} open`, ""]);
    }
    if (moving) parts.push([`${moving} moving`, "live"]);
    if (lowBattery) parts.push([`${lowBattery} low ${lowBattery === 1 ? "battery" : "batteries"}`, "warn"]);

    const key = parts.map((part) => part.join(":")).join("|");
    if (summary.dataset.key === key) return;
    summary.dataset.key = key;
    summary.innerHTML = "";
    parts.forEach(([text, kind], index) => {
      if (index) summary.appendChild(el("span", "sep", " · "));
      summary.appendChild(el("span", kind || null, text));
    });
  }

  _showMore(entityId) {
    if (!entityId) return;
    const event = new Event("hass-more-info", { bubbles: true, composed: true });
    event.detail = { entityId };
    this.dispatchEvent(event);
  }
}

/**
 * The visual editor. Home Assistant's own form when it is available, so the options look
 * like every other card's; plain inputs otherwise.
 */
const EDITOR_FIELDS = [
  { key: "title", label: "Title (leave empty to use the hub's name)", type: "text" },
  { key: "hide_picture", label: "List layout (sliders instead of windows)", type: "boolean" },
  { key: "hide_battery", label: "Hide battery levels", type: "boolean" },
  { key: "hide_room_names", label: "Hide room headings", type: "boolean" },
  { key: "hide_room_controls", label: "Hide room open / stop / close", type: "boolean" },
  { key: "hide_room_presets", label: "Hide room presets", type: "boolean" },
  { key: "hide_home_controls", label: "Hide whole-house presets", type: "boolean" },
];

class NormanShadesCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
  }

  _changed(config) {
    const next = { ...config };
    for (const { key } of EDITOR_FIELDS) {
      if (next[key] === "" || next[key] === false) delete next[key];
    }
    this._config = next;
    this.dispatchEvent(
      new CustomEvent("config-changed", { detail: { config: next }, bubbles: true, composed: true }),
    );
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = "";

    if (customElements.get("ha-form")) {
      const form = document.createElement("ha-form");
      form.hass = this._hass;
      form.data = this._config;
      form.schema = EDITOR_FIELDS.map(({ key, type }) => ({
        name: key,
        selector: type === "boolean" ? { boolean: {} } : { text: {} },
      }));
      const labels = Object.fromEntries(EDITOR_FIELDS.map(({ key, label }) => [key, label]));
      form.computeLabel = (field) => labels[field.name] || field.name;
      form.addEventListener("value-changed", (event) => this._changed(event.detail.value));
      this._form = form;
      this.shadowRoot.appendChild(form);
      return;
    }

    // ha-form is loaded lazily by the dashboard editor; redraw with it once it arrives.
    customElements.whenDefined?.("ha-form").then(() => this._render());
    const wrap = document.createElement("div");
    wrap.style.padding = "8px 0";
    for (const field of EDITOR_FIELDS) {
      const row = document.createElement("label");
      row.style.cssText = "display:flex;align-items:center;gap:8px;padding:6px 0;";
      const text = document.createElement("span");
      text.textContent = field.label;
      text.style.flex = "1";
      const input = document.createElement("input");
      input.type = field.type === "boolean" ? "checkbox" : "text";
      if (field.type === "boolean") input.checked = Boolean(this._config[field.key]);
      else input.value = this._config[field.key] ?? "";
      input.addEventListener("change", () => {
        const value = field.type === "boolean" ? input.checked : input.value;
        this._changed({ ...this._config, [field.key]: value });
      });
      row.append(text, input);
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
    description: "Norman blinds grouped by room, each drawn as a window you drag to move.",
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
