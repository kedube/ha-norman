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
 * listed in the card configuration. With more than one hub, `config_entry_id` limits the card
 * to one of them and sends its presets and refreshes to that hub.
 *
 * The integration also shows this card full screen as a sidebar panel (norman-panel.js).
 * There it carries a `panel` attribute and a `narrow` property from Home Assistant: on phones
 * it runs edge to edge and its header gains the button that opens Home Assistant's sidebar.
 *
 * With the integration's view option on, the panel also gives it a `view` attribute and a
 * `view` property (norman-view.js): each window then looks out on a photograph for the hour
 * and the weather, a room's windows on one view between them, and the page behind takes the
 * photograph's colours. The card lies over them as dark glass and says the temperature and the
 * weather under its heading, with the forecast for the hours ahead beside it. The shades
 * themselves are drawn in CSS exactly as on a dashboard.
 *
 * Each shade is drawn in its own color, which the integration keeps on the blind as a select
 * entity: a fabric for a shade, a paint or a stain for a Shutter. In the sidebar panel the
 * header's color button lets each window's color be chosen against the view, and on a phone a
 * bar at the foot of the screen goes to each room.
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
// How long a rail counts as moving once the hub reports a new target. A blind reports its new
// position when it stops, 10-45 s after a command (some only a minute or more after, unless
// asked), and the integration's watchdog gives a
// silent one three sends, 70 s apart (const.py: MOVE_TIMEOUT + MOVE_REPORT_WAIT, MOVE_ATTEMPTS).
// Past this the hub has not heard the blind arrive, and may not for hours: the blind missed the
// command, or carried it out and its report was lost. So the card stops saying "Closing" and
// says the move is not confirmed.
const MOVE_WINDOW_MS = 3 * (60 + 10) * 1000;
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
// A Shutter's one cover: its louvers, driven through the cover's tilt.
const KEY_LOUVERS = "louvers";
const KEY_BOTTOM_POSITION = "bottom_rail_position";
const KEY_MIDDLE_POSITION = "middle_rail_position";
const KEY_BATTERY = "battery_level";
// A scene saved in one of the hub's rooms, on that room's device, listed with the room. A
// scene group sits on the hub's device and acts on several rooms, so it goes in the header
// with the whole-house presets instead.
const KEY_ROOM_SCENE = "room_scene";
const KEY_SCENE_GROUP = "scene_group";
// Home Assistant's own icon for a scene.
const SCENE_ICON = "mdi:palette";
// A blind's color (select.py): a fabric for a shade, a paint or a stain for a Shutter. The card
// draws the colors below, in the same order the select offers them; a blind with no color
// entity, or a color this card does not know, is drawn in the default.
const KEY_SHADE_COLOR = "shade_color";
const KEY_SHUTTER_COLOR = "shutter_color";
const COLOR_ICON = "mdi:palette-swatch-outline";
// Each fabric's four tones, as the cloth tokens take them: the lit face of a pleat, the cloth,
// its shaded underside and the crease. Ivory is the cloth the card has always drawn, so it is
// left to the CSS (and its dark-theme tones); the warm fabrics shade warm, as ivory does, and
// the cool ones keep their hue.
const SHADE_COLORS = {
  white: ["#fcfbf9", "#f6f4ef", "#e2ddd2", "#c2b9aa"],
  ivory: null,
  linen: ["#f2ede5", "#e5dccc", "#d3c7b4", "#b5a791"],
  sand: ["#e3d7c3", "#d3c09f", "#c2ae8c", "#a79271"],
  taupe: ["#c3b8ab", "#ae9f8d", "#a0907c", "#897964"],
  gray: ["#cccfd0", "#b3b7b8", "#a1a5a6", "#858888"],
  slate: ["#868f99", "#6b7682", "#606a75", "#4f5760"],
  charcoal: ["#5b5f64", "#3f4349", "#393c42", "#2f3236"],
  navy: ["#4b576f", "#2c3a56", "#28344d", "#212b40"],
  sage: ["#b8c1ac", "#9daa8c", "#8d997e", "#747e68"],
  terracotta: ["#ca9f88", "#bb8366", "#ac775a", "#946448"],
};
const DEFAULT_SHADE_COLOR = "ivory";
// A Shutter's paint or stain, as the trim tokens take it: lit, flat and shaded, and the edge.
// White is the trim the card has always drawn it in, so it too is left to the CSS.
const SHUTTER_COLORS = {
  white: null,
  ivory: ["#f5f1e9", "#ebe2d0", "#d4c9b3", "rgba(92, 78, 58, 0.24)"],
  gray: ["#cccece", "#b5b8b8", "#a3a49e", "rgba(40, 44, 48, 0.3)"],
  black: ["#4a4c50", "#2e3034", "#26282b", "rgba(0, 0, 0, 0.5)"],
  oak: ["#c9a47e", "#b8895a", "#9d7148", "rgba(70, 45, 20, 0.4)"],
  walnut: ["#80644f", "#6a4a35", "#563a28", "rgba(30, 18, 10, 0.5)"],
};
const DEFAULT_SHUTTER_COLOR = "white";
// The color a swatch shows for each: the cloth itself, or the paint.
const swatchOf = (shutter, color) =>
  (shutter ? SHUTTER_COLORS[color]?.[1] ?? "#f3f0ea" : SHADE_COLORS[color]?.[1] ?? "#f0ebe2");
// A window's divided lights (select.py): the glazing bars across its glass, each upright (`down`)
// or `across`, centred at a share of the glass's width or height, as thick as a share of it, and
// reaching from and to a share of the other way (the whole of it unless given). The heavier bar
// across the middle of a double-hung window is its meeting rail; "over none" divides only the
// upper sash, above it. Two over two is the glass the card has always drawn, so a window nobody
// has chosen for looks as it did.
const KEY_WINDOW_LIGHTS = "window_lights";
const LIGHTS_ICON = "mdi:window-closed-variant";
const MEETING_RAIL = ["across", 50, 2.8];
const UPPER_SASH = [0, 50];
const WINDOW_LIGHTS = {
  none: [],
  one_over_one: [MEETING_RAIL],
  side_by_side: [["down", 50, 3.2]],
  two_over_none: [["down", 50, 2.2, ...UPPER_SASH], MEETING_RAIL],
  two_over_two: [["down", 50, 3.2], MEETING_RAIL],
  three_over_none: [["down", 33.33, 2.2, ...UPPER_SASH], ["down", 66.67, 2.2, ...UPPER_SASH], MEETING_RAIL],
  four_over_none: [["down", 50, 2.2, ...UPPER_SASH], ["across", 25, 2], MEETING_RAIL],
  four_over_four: [["down", 50, 2.2], ["across", 25, 2], MEETING_RAIL, ["across", 75, 2]],
  six_over_none: [["down", 33.33, 2.2, ...UPPER_SASH], ["down", 66.67, 2.2, ...UPPER_SASH], ["across", 25, 2], MEETING_RAIL],
  six_over_six: [["down", 33.33, 2.2], ["down", 66.67, 2.2], ["across", 25, 2], MEETING_RAIL, ["across", 75, 2]],
  prairie: [["down", 13, 2.2], ["down", 87, 2.2], ["across", 12, 2], ["across", 88, 2]],
};
const DEFAULT_WINDOW_LIGHTS = "two_over_two";
// The page's settings, in the sidebar panel: a button beside the refresh at the top.
const SETTINGS_ICON = "mdi:cog-outline";
// What the sidebar page has each window choose (_setChoosing): its shade's color, or its glass's
// divided lights. Each is an item in the settings menu, with its words, and the mode the card is
// in while it is chosen.
const CHOICES = {
  colors: {
    icon: COLOR_ICON,
    mode: "coloring",
    words: { button: "colors", title: "colors_title", hint: "colors_hint", every: "color_every", of: "color_of", option: "color_" },
  },
  lights: {
    icon: LIGHTS_ICON,
    mode: "lighting",
    words: { button: "lights", title: "lights_title", hint: "lights_hint", every: "lights_every", of: "lights_of", option: "lights_" },
  },
};
// How long a color or divided lights chosen here is drawn before Home Assistant must have taken
// it up.
const CHOICE_PENDING_MS = 5000;

// The forecast beside the weather over the view: Home Assistant's weather icons, by state, and
// the night's for a clear or partly cloudy hour with the sun down. A weather entity offers its
// forecast as a subscription, hourly, twice a day or daily by its supported features; the
// card asks for the finest it has.
const WEATHER_ICONS = {
  "clear-night": "mdi:weather-night",
  cloudy: "mdi:weather-cloudy",
  exceptional: "mdi:alert-circle-outline",
  fog: "mdi:weather-fog",
  hail: "mdi:weather-hail",
  lightning: "mdi:weather-lightning",
  "lightning-rainy": "mdi:weather-lightning-rainy",
  partlycloudy: "mdi:weather-partly-cloudy",
  pouring: "mdi:weather-pouring",
  rainy: "mdi:weather-rainy",
  snowy: "mdi:weather-snowy",
  "snowy-rainy": "mdi:weather-snowy-rainy",
  sunny: "mdi:weather-sunny",
  windy: "mdi:weather-windy",
  "windy-variant": "mdi:weather-windy-variant",
};
const NIGHT_ICONS = { sunny: "mdi:weather-night", partlycloudy: "mdi:weather-night-partly-cloudy" };
const FORECAST_TYPES = [
  ["hourly", 2],
  ["twice_daily", 4],
  ["daily", 1],
];
// Now and the hours after it. A wide page shows them all; a phone the first FORECAST_NARROW.
const FORECAST_CELLS = 8;
const FORECAST_NARROW = 6;
// A chance of rain or snow worth saying under the hour's icon, in percent.
const FORECAST_WET = 30;
// A blind's Request status button, found by its translation key like the KEY_* entities: it
// asks the blind to report in, and nothing moves. The hub's and rooms' Report battery levels
// buttons can close shades, so the card offers none of them.
const BUTTON_REQUEST_STATUS = "request_status";
const REFRESH_ICON = "mdi:refresh";
// A refresh control's icon turns once when pressed, to say the request went. The answers come
// later -- a blind's within seconds, a whole hub's over a couple of minutes -- and the card
// redraws as they arrive.
const REFRESH_SPIN_MS = 1000;
// A second press of the same refresh control within this long is ignored: each press queues
// status requests at the hub's pace, and repeats only push the answers back.
const REFRESH_HOLD_MS = 5000;
// Entities only the hub device carries, which is how the card tells the hub from the rest:
// each of the hub's rooms is a Norman device without a cover as well. Several, because the
// frontend registry leaves out disabled entities and any one of these can be disabled.
const HUB_KEYS = new Set([
  "mac_address",
  "time_zone",
  "wifi_ssid",
  "wifi_rssi",
  "pairing_mode",
  "refresh_blinds",
  "start_pairing",
  "push_updates",
]);

// The hub's name as the Norman app has it. The integration keeps the hub device's own name in
// step with the app (coordinator._sync_device_names), and the card names the hub by it even
// where the device has been renamed in Home Assistant: the hub is named where it is set up.
// Until the hub has said its name, the device has the entry's placeholder, "Norman Hub
// (<address>)" (const.py, default_title), and a name given in Home Assistant is the better one.
const hubNameOf = (device) => {
  const own = device.name?.trim();
  if (own && !(own.startsWith("Norman Hub (") && own.endsWith(")"))) return own;
  return device.name_by_user?.trim() || own || null;
};

// The card's words, in every language the integration ships (norman-strings.js), imported at
// this file's own ?v= stamp: /norman/ is served with long-lived cache headers, so a plain relative
// import could hand an upgraded card the previous release's words.
const { languageOf, translate } = await import(
  new URL(`./norman-strings.js?v=${encodeURIComponent(CARD_VERSION)}`, import.meta.url).href
);

// The Norman app's three presets. The short label is what is printed; the title is the full
// name, used for the tooltip and for assistive technology. Both are keys into the card's words.
const PRESETS = [
  { command: "best_privacy", icon: "mdi:blinds-horizontal", label: "preset_privacy", title: "preset_privacy_title" },
  { command: "best_view", icon: "mdi:weather-sunny", label: "preset_view", title: "preset_view_title" },
  { command: "favorite", icon: "mdi:star", label: "preset_favorite", title: "preset_favorite_title" },
];

// A room's open / stop / close: the icon, the cover service, and the tooltip's key in the
// card's words.
const ROOM_ACTIONS = [
  ["mdi:arrow-up", "open_cover", "room_open"],
  ["mdi:stop", "stop_cover", "room_stop"],
  ["mdi:arrow-down", "close_cover", "room_close"],
];

const clamp = (value, low = 0, high = 100) => Math.max(low, Math.min(high, value));
const clampToStep = (value, step = STEP) => Math.round(clamp(Number(value) || 0) / step) * step;
// The config entries a device belongs to. Newer Home Assistant versions name one
// (`config_entry_id`); older ones list them (`config_entries`).
const entriesOf = (device) =>
  device?.config_entry_id ? [device.config_entry_id] : device?.config_entries || [];
// A Shutter's louvers stop at the hub's eight Positions, 7 (shut) to 0. The cover's tilt for
// each, by Position, is their whole turn: 0 shut, 50 horizontal (Position 3), and 100 at 0,
// as far as they turn the other way (SHUTTER_TILTS in const.py).
const LOUVER_TILTS = [100, 83, 67, 50, 38, 25, 13, 0];
// The same stops from shut, which a drag, a key or the list's slider moves between.
const LOUVER_STOPS = [...LOUVER_TILTS].reverse();
const LOUVER_HORIZONTAL = 50;
const LOUVER_OPEN_POSITION = 3;
const LOUVER_COUNT = 9;
// How far the louvers turn at horizontal: nearly edge-on, as a real louver stops short.
const LOUVER_OPEN_DEG = 78;
// The part of the opening a drag has to cover to turn the louvers through their whole turn.
const LOUVER_TRAVEL_PCT = 70;
/** The louver stop nearest `value`, as a tilt; a tie goes to the one nearer shut. */
const louverStop = (value) => {
  const tilt = clamp(Number(value) || 0);
  return LOUVER_STOPS.reduce((best, stop) => (Math.abs(stop - tilt) < Math.abs(best - tilt) ? stop : best));
};
/** The louvers' Position for a tilt, 7 (shut) to 0, in between two while a drag is between their stops. */
const louverPosition = (value) => {
  const tilt = clamp(Number(value) || 0);
  for (let position = LOUVER_TILTS.length - 1; position > 0; position -= 1) {
    const low = LOUVER_TILTS[position];
    const high = LOUVER_TILTS[position - 1];
    if (tilt <= high) return position - (tilt - low) / (high - low);
  }
  return 0;
};
/**
 * How open the louvers are at a tilt, 0 (shut) to 1 (horizontal), and which way they lean:
 * -1 past horizontal. Position 0 is turned nearly shut the other way and still lets light in,
 * so it is a step of the four between shut and horizontal open (cover.py's _louver_openness).
 */
const louverTurn = (value) => {
  const position = louverPosition(value);
  const past = position < LOUVER_OPEN_POSITION;
  const steps = past ? position + 1 : LOUVER_TILTS.length - 1 - position;
  return { open: steps / (LOUVER_TILTS.length - 1 - LOUVER_OPEN_POSITION), lean: past ? -1 : 1 };
};
/** Where `value` lands on `rail`: a louver stop, or a rail's 10% step. */
const snapOf = (rail, value) => (rail.louvers ? louverStop(value) : clampToStep(value));
/** `steps` stops on from `value` on `rail` (back when negative), within its range. */
const stepFrom = (rail, value, steps) => {
  if (!rail.louvers) return clampToStep((Number(value) || 0) + steps * STEP);
  const index = LOUVER_STOPS.indexOf(louverStop(value)) + steps;
  return LOUVER_STOPS[Math.max(0, Math.min(LOUVER_STOPS.length - 1, index))];
};
// The list layout's slider for `rail` takes 0-100 in 10% steps, or for a Shutter's louvers
// the index of their stop, 0 (shut) to 7, so that it moves one stop at a time.
const sliderMax = (rail) => (rail.louvers ? LOUVER_STOPS.length - 1 : 100);
const sliderValueOf = (rail, value) =>
  String(rail.louvers ? LOUVER_STOPS.indexOf(louverStop(value)) : clampToStep(value));
const sliderPosition = (rail, raw) =>
  rail.louvers ? LOUVER_STOPS[Math.round(clamp(Number(raw) || 0, 0, sliderMax(rail)))] : clampToStep(raw);

// A roller shade's fabric winds onto a roll at the top: thickest with the shade up, thinnest
// with it down. In percent of the opening's height. Fully up, the roll's underside is where a
// cellular shade's headrail ends, so the bottom bar tucks beneath it the same way.
const ROLL_TOP_PCT = 0.5;
const ROLL_MIN_PCT = 4;
const ROLL_MAX_PCT = SHADE_HEAD_PCT - ROLL_TOP_PCT;

// A SmartDrape: fabric vanes on a sheer, hung from a track and drawn across the window
// sideways. Widths are percent of the opening's width.
const DRAPE_VANES = 14; // across the whole window; a split drape has half on each side
const DRAPE_STACK_PCT = 16; // how much of the window the drape covers gathered to one side
const DRAPE_TRACK_PCT = 4.5; // the track's depth, in percent of the opening's height
const DRAPE_VANE_OVERLAP = 1.15; // a vane's width over its share of the closed drape
// How far the vanes turn at fully open: nearly edge-on to the window, as the real ones stop.
const VANE_OPEN_DEG = 75;
// The sides a drape gathers to when open, by the cover's `stack` attribute.
const STACK_SIDES = { left: ["left"], right: ["right"], split: ["left", "right"] };

// A Roman shade (flat fold, batten back): one flat panel with a seam at each batten, which
// folds up from the bottom as the shade rises. The folds hang loose, half a section deep,
// until every section is folded, then pack tighter as the shade goes the rest of the way up.
// The CSS draws the seams at the same count. In percent of the opening's height.
const ROMAN_SECTIONS = 5;
const ROMAN_STACK_PCT = 24; // the folds' depth with the shade fully up
const ROMAN_LAP_PCT = 0.6; // how far the flat panel runs on under the top fold, so no sky shows at the join

// A PerfectSheer: soft fabric vanes between two sheers, rolled up into a cassette. With the
// shade fully down the vanes open, each to a band this much of its pitch; raised, they are
// closed, as the shade closes them before it rolls up.
const SHEER_VANES = 11;
const SHEER_VANE_OPEN = 0.42;

// Which picture a blind gets, from its device's model_id: the hub's ModuleType/ModuleDetail
// ("48/1"), as the integration records it. The roller family (48 and 49) is a roller shade,
// a Roman shade (detail 2) or a PerfectSheer (detail 3), and a SmartDrape is 80; each is
// drawn as itself. Anything else is drawn as a cellular shade.
const ROLLER_FAMILY = { 2: "roman", 3: "perfectsheer" };
const productOf = (device) => {
  const [type, detail] = String(device?.model_id ?? "").split("/").map(Number);
  if (type === 80) return "drape";
  if (type === 48 || type === 49) return ROLLER_FAMILY[detail] || "roller";
  return null;
};
const round3 = (value) => Math.round(value * 1000) / 1000;

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

// Write a node's text or an attribute only when it changes. The card patches every tile on
// each change to one of its entities, and a write of the same text still costs the browser a
// fresh layout of the tile.
const setText = (node, text) => {
  if (node.textContent !== text) node.textContent = text;
};
const setAttr = (node, name, value) => {
  if (node.getAttribute(name) !== value) node.setAttribute(name, value);
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

// The CSS that draws each blind in its color: the cloth's tokens on a shade's window, a
// Shutter's trim tokens on its panel. The default colors have none, and are drawn as before.
const colorRules = () =>
  [
    ...Object.entries(SHADE_COLORS)
      .filter(([, tones]) => tones)
      .map(
        ([color, [hi, cloth, lo, crease]]) =>
          `.win[data-color="${color}"] { --n-cloth-hi: ${hi}; --n-cloth: ${cloth}; --n-cloth-lo: ${lo}; --n-cloth-crease: ${crease}; }`,
      ),
    ...Object.entries(SHUTTER_COLORS)
      .filter(([, tones]) => tones)
      .map(
        ([color, [hi, trim, lo, edge]]) =>
          `.win.shutter[data-color="${color}"] .panel { --n-trim-hi: ${hi}; --n-trim: ${trim}; --n-trim-lo: ${lo}; --n-trim-edge: ${edge}; }`,
      ),
  ].join("\n  ");

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
  /* In the sidebar panel on a phone the card is the page: edge to edge, with no frame. */
  :host([panel][narrow]) ha-card { border: none; border-radius: 0; box-shadow: none; }
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
  /* The buttons wrap onto a line of their own before the hub's name is cut short. */
  .titles { flex: 1 1 240px; min-width: 0; }
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
  .chip:focus-visible, .icon-btn:focus-visible, .name:focus-visible, .stop:focus-visible, .refresh:focus-visible,
  .battery:focus-visible {
    outline: 2px solid var(--n-accent);
    outline-offset: 1px;
  }
  /* The whole-house presets shrink to their icons only on a really narrow card. On a phone they
     already have a line to themselves, where their words fit, and a touch screen shows no
     tooltip to say what an icon means. */
  @container (max-width: 300px) {
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
  .icon-btn.menu { flex: none; margin: 0 -6px 0 -8px; }
  .icon-btn.menu ha-icon { --mdc-icon-size: 24px; }
  .tray { display: flex; flex-wrap: wrap; gap: 8px; margin: -4px 0 14px; }
  .tray .segmented { display: flex; width: fit-content; max-width: 100%; }
  /* A room's scenes after its presets, and the hub's scene groups after the whole-house
     presets: as many as the app has, so they wrap. The groups keep their words on a narrow
     card, where the presets beside them shrink to icons, since one palette looks like
     another. */
  .room-scenes, .home-scenes { flex-wrap: wrap; max-width: 100%; }
  .room-scenes .chip, .home-scenes .chip { max-width: 100%; }
  .room-scenes .chip span, .home-scenes .chip span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .chip:disabled { opacity: 0.45; cursor: default; pointer-events: none; }

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
    position: relative;
    display: inline-flex;
    align-items: center;
    flex: none;
    margin: 1px 0 0 auto;
    padding: 0;
    border: 0;
    border-radius: 4px;
    background: none;
    font-family: inherit;
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
  /* Refresh: beside the battery on every blind, in each room's tray and in the header. A press
     turns its icon once (REFRESH_SPIN_MS in the script is the same second). */
  .refresh {
    position: relative;
    display: grid;
    place-items: center;
    flex: none;
    width: 20px;
    height: 18px;
    margin-right: -3px;
    padding: 0;
    border: 0;
    border-radius: 6px;
    background: none;
    color: var(--n-muted);
    cursor: pointer;
  }
  /* A finger gets a wider target than the icon, without the row growing. */
  .refresh::after { content: ""; position: absolute; inset: -6px -4px; }
  .refresh ha-icon { --mdc-icon-size: 15px; }
  .refresh:hover { color: var(--n-accent); }
  .refresh:disabled { opacity: 0.45; cursor: default; }
  .spin ha-icon { color: var(--n-accent); animation: n-spin 1s var(--n-ease); }
  @keyframes n-spin { to { transform: rotate(360deg); } }
  .home-refresh { border-radius: 12px; background: rgba(var(--n-fg-rgb), 0.06); }
  .home-refresh .icon-btn { width: 36px; height: 36px; border-radius: 12px; }
  /* The page's settings, in the sidebar panel: a button beside the refresh, and the menu it
     opens beneath it, of what can be chosen for each window (_buildSettings). */
  .home-settings { position: relative; border-radius: 12px; background: rgba(var(--n-fg-rgb), 0.06); }
  .home-refresh + .home-settings { margin-left: -10px; }
  .home-settings .icon-btn { width: 36px; height: 36px; border-radius: 12px; }
  .home-settings .icon-btn.open { background: rgba(var(--n-accent-rgb), 0.14); color: var(--n-accent); }
  .settings-menu {
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    z-index: 20;
    display: flex;
    flex-direction: column;
    min-width: 200px;
    padding: 6px;
    border-radius: 16px;
    background: var(--ha-card-background, var(--card-background-color, #fff));
    box-shadow: 0 0 0 1px rgba(var(--n-fg-rgb), 0.08), 0 14px 32px -12px rgba(0, 0, 0, 0.45);
  }
  .menu-item {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 44px;
    padding: 0 14px;
    border: 0;
    border-radius: 11px;
    background: transparent;
    color: var(--primary-text-color);
    font: inherit;
    font-size: 14px;
    font-weight: 500;
    text-align: start;
    white-space: nowrap;
    cursor: pointer;
  }
  .menu-item:hover, .menu-item:focus-visible { background: rgba(var(--n-accent-rgb), 0.12); outline: none; }
  .menu-item ha-icon { --mdc-icon-size: 20px; color: var(--n-accent); }
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
  /* The glazing bars, laid for the window's divided lights (_layBars): each placed and sized
     from WINDOW_LIGHTS in the script. */
  .bars { position: absolute; inset: 0; }
  .mullion, .transom {
    position: absolute;
    background: var(--n-trim);
    box-shadow: 0 0 0 0.5px var(--n-trim-edge), 0 1px 2px rgba(0, 0, 0, 0.18);
  }
  .mullion { transform: translateX(-50%); }
  .transom { transform: translateY(-50%); }
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
  ha-card[data-theme="dark"] .headrail,
  ha-card[data-theme="dark"] .roll,
  ha-card[data-theme="dark"] .hanging { filter: brightness(0.88); }

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

  /* ---- a roller shade ---------------------------------------------------------------
     Plain woven fabric off a roll at the top: no pleats, and the roll grows as the shade
     winds up onto it. The bottom bar is the shade's weighted hem. */
  .win.roller .roll {
    position: absolute;
    left: -1.5%;
    right: -1.5%;
    top: 0.5%;
    height: 8.5%;
    z-index: 5;
    border-radius: 999px;
    background: linear-gradient(to bottom, var(--n-cloth-lo), var(--n-cloth-hi) 24%, var(--n-cloth) 52%, var(--n-cloth-lo) 80%, var(--n-cloth-crease));
    box-shadow: 0 0 0 0.5px rgba(90, 70, 40, 0.3), 0 2px 3px -1px rgba(0, 0, 0, 0.35);
    transition: height 0.45s var(--n-ease);
  }
  .win.roller .jamb {
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    z-index: 4;
    background: linear-gradient(to bottom, var(--n-trim-lo), var(--n-trim));
    transition: height 0.45s var(--n-ease);
  }
  /* The brackets the roll turns in, at each end. */
  .win.roller .bracket {
    position: absolute;
    top: 0;
    height: var(--n-head);
    width: 4%;
    min-width: 3px;
    z-index: 6;
    border-radius: 1px;
    background: linear-gradient(to right, var(--n-rail-lo), var(--n-rail-hi) 45%, var(--n-rail-lo));
    box-shadow: 0 0 0 0.5px var(--n-rail-edge);
  }
  .win.roller .bracket.left { left: -3.5%; }
  .win.roller .bracket.right { right: -3.5%; }
  /* A fine weave in both directions over a soft fall of light, and the roll's shadow at the top. */
  .fabric.roller {
    background:
      linear-gradient(to right, rgba(90, 70, 40, 0.1), transparent 8%, transparent 92%, rgba(90, 70, 40, 0.1)),
      linear-gradient(to bottom, rgba(60, 45, 25, 0.18), transparent 6%),
      repeating-linear-gradient(to bottom, rgba(140, 120, 90, 0.045) 0 0.5px, transparent 0.5px 1.5px),
      repeating-linear-gradient(to right, rgba(140, 120, 90, 0.03) 0 0.5px, transparent 0.5px 2px),
      linear-gradient(to bottom, var(--n-cloth-hi), var(--n-cloth) 55%, var(--n-cloth-lo));
  }
  .fabric.roller::after {
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(90% 70% at 70% 30%, rgba(255, 250, 235, 0.55), transparent 70%);
    mix-blend-mode: soft-light;
  }
  ha-card[data-sky="night"] .fabric.roller::after,
  ha-card[data-sky="dusk"] .fabric.roller::after { display: none; }
  .win.roller .rail { border-radius: 2px; }
  .win.dragging .roll, .win.dragging .jamb { transition: none; }

  /* ---- a Roman shade ----------------------------------------------------------------
     Norman's flat fold with a batten back: a woven panel under a fabric-covered head, with
     a seam at each batten. It folds up from the bottom into soft horizontal folds, each
     lapping over the one below, and the hem -- the bottom bar, sewn in -- is what the card
     drags. The panel is drawn at its full length and clipped, so its seams stay put. */
  .win.roman .headrail {
    left: -1.5%;
    right: -1.5%;
    border-radius: 2px;
    background:
      repeating-linear-gradient(to bottom, rgba(140, 120, 90, 0.05) 0 0.5px, transparent 0.5px 1.5px),
      linear-gradient(to bottom, var(--n-cloth-hi), var(--n-cloth) 40%, var(--n-cloth-lo) 86%, var(--n-cloth-crease));
    box-shadow: 0 0 0 0.5px rgba(90, 70, 40, 0.3), 0 2px 3px -1px rgba(0, 0, 0, 0.3);
  }
  /* The seams repeat every fifth of the panel: ROMAN_SECTIONS in the script. The panel and
     its folds overhang the opening a hair, so no sky shows down their sides. */
  .fabric.roman, .fabric.fold { left: -0.6%; right: -0.6%; }
  .fabric.roman {
    height: calc(100% - var(--n-head) - var(--n-rail));
    background:
      linear-gradient(to right, rgba(90, 70, 40, 0.1), transparent 8%, transparent 92%, rgba(90, 70, 40, 0.1)),
      repeating-linear-gradient(
        to bottom,
        transparent 0 calc(100% / 5 - 1.5px),
        rgba(120, 100, 70, 0.3) calc(100% / 5 - 1.5px) calc(100% / 5 - 0.5px),
        rgba(255, 255, 255, 0.4) calc(100% / 5 - 0.5px) calc(100% / 5)
      ),
      repeating-linear-gradient(to bottom, rgba(140, 120, 90, 0.05) 0 0.5px, transparent 0.5px 1.5px),
      linear-gradient(to bottom, var(--n-cloth-hi), var(--n-cloth) 55%, var(--n-cloth-lo));
    clip-path: inset(0 0 100% 0);
    transition: clip-path 0.45s var(--n-ease);
  }
  /* A fold: a flat face of cloth whose lower edge rounds under -- lit where it turns, dark
     at the crease beneath -- lapping over the fold below and shadowing it. */
  .fabric.fold {
    z-index: 2;
    background:
      linear-gradient(to right, rgba(90, 70, 40, 0.12), transparent 8%, transparent 92%, rgba(90, 70, 40, 0.12)),
      repeating-linear-gradient(to bottom, rgba(140, 120, 90, 0.05) 0 0.5px, transparent 0.5px 1.5px),
      linear-gradient(to bottom, var(--n-cloth) 0, var(--n-cloth-hi) 14%, var(--n-cloth) 66%, var(--n-cloth-hi) 80%, var(--n-cloth-lo) 93%, var(--n-cloth-crease));
    box-shadow: 0 1px 2px rgba(60, 45, 25, 0.32);
  }
  .fabric.roman::after, .fabric.fold::after {
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(90% 70% at 70% 30%, rgba(255, 250, 235, 0.5), transparent 70%);
    mix-blend-mode: soft-light;
  }
  ha-card[data-sky="night"] .fabric.roman::after, ha-card[data-sky="night"] .fabric.fold::after,
  ha-card[data-sky="dusk"] .fabric.roman::after, ha-card[data-sky="dusk"] .fabric.fold::after { display: none; }
  .win.roman .rail {
    border-radius: 0 0 3px 3px;
    background: linear-gradient(to bottom, var(--n-cloth-lo), var(--n-cloth) 28%, var(--n-cloth-hi) 52%, var(--n-cloth-lo) 88%, var(--n-cloth-crease));
    box-shadow: 0 0 0 0.5px rgba(90, 70, 40, 0.28), 0 2px 3px -1px rgba(0, 0, 0, 0.35);
  }

  /* ---- a PerfectSheer ---------------------------------------------------------------
     Soft fabric vanes held between two sheers, under a curved cassette the fabric rolls up
     into. Open, the vanes narrow to bands with the view through the sheer between them;
     closed, they meet in a soft wall of cloth. */
  .win.perfectsheer .headrail {
    border-radius: 3px 3px 4px 4px;
    background: linear-gradient(to bottom, var(--n-rail-lo), var(--n-rail-hi) 12%, var(--n-rail-face) 46%, var(--n-rail-lo) 90%);
  }
  .win.perfectsheer .clip {
    position: absolute;
    left: 0;
    right: 0;
    top: var(--n-head);
    bottom: 0;
    z-index: 1;
    overflow: hidden;
  }
  .win.perfectsheer .cloth {
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    background-color: rgba(252, 249, 243, 0.2);
    background-image:
      linear-gradient(to right, rgba(90, 70, 40, 0.08), transparent 8%, transparent 92%, rgba(90, 70, 40, 0.08)),
      repeating-linear-gradient(to bottom, rgba(176, 164, 144, 0.2) 0 0.5px, transparent 0.5px 2px);
    -webkit-backdrop-filter: blur(0.8px) brightness(1.06) saturate(0.8);
    backdrop-filter: blur(0.8px) brightness(1.06) saturate(0.8);
    transition: top 0.45s var(--n-ease);
  }
  /* The front sheer, over the vanes as well as between them. */
  .win.perfectsheer .cloth::after {
    content: "";
    position: absolute;
    inset: 0;
    background: repeating-linear-gradient(to bottom, rgba(255, 255, 255, 0.14) 0 0.5px, transparent 0.5px 2px);
  }
  .win.perfectsheer .vane {
    position: absolute;
    left: 0;
    right: 0;
    transform-origin: top;
    background: linear-gradient(to bottom, var(--n-cloth-lo), var(--n-cloth-hi) 10%, var(--n-cloth) 58%, var(--n-cloth-lo));
    box-shadow: 0 0.5px 0 rgba(150, 135, 110, 0.35);
    opacity: 0.94;
    transition: transform 0.45s var(--n-ease);
  }
  .win.dragging .cloth { transition: none; }
  ha-card[data-theme="dark"] .win.perfectsheer .vane { filter: brightness(0.88); }

  /* ---- a SmartDrape -------------------------------------------------------------------
     Fabric vanes on a sheer, hung from a track to the sill and drawn sideways. Each vane
     turns about its long axis -- flat and overlapping when closed, nearly edge-on when
     open, the view between them -- and the leading edge is what a hand, and the card, pulls. */
  .win.drape .headrail { height: 4.5%; }
  .win.drape .hanging {
    position: absolute;
    top: 4.5%;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 1;
    perspective: 320px;
  }
  .win.drape .sheer {
    position: absolute;
    top: 0;
    bottom: 0;
    background-color: rgba(252, 249, 243, 0.2);
    background-image: repeating-linear-gradient(to right, rgba(176, 164, 144, 0.2) 0 1px, transparent 1px 3px);
    -webkit-backdrop-filter: blur(1px) brightness(1.05) saturate(0.85);
    backdrop-filter: blur(1px) brightness(1.05) saturate(0.85);
    transition: left 0.45s var(--n-ease), width 0.45s var(--n-ease);
  }
  .win.drape .vane {
    position: absolute;
    top: 0;
    bottom: 0;
    background: linear-gradient(to right, var(--n-cloth-lo), var(--n-cloth-hi) 30%, var(--n-cloth) 62%, var(--n-cloth-lo));
    box-shadow: 0 0 0 0.5px rgba(120, 100, 70, 0.28), 1px 0 2px rgba(60, 45, 25, 0.16);
    transform: rotateY(0deg);
    transition: left 0.45s var(--n-ease), width 0.45s var(--n-ease), transform 0.45s var(--n-ease);
  }
  /* The leading edge: a slim bar down the drape's edge with a pull at its middle, pointing
     the way the drape draws. */
  .win.drape .lead {
    top: 4.5%;
    bottom: 0;
    right: auto;
    height: auto;
    width: 3%;
    min-width: 3px;
    min-height: 0;
    background: linear-gradient(to right, var(--n-rail-lo), var(--n-rail-hi) 40%, var(--n-rail-face) 70%, var(--n-rail-lo));
    transition: left 0.45s var(--n-ease);
  }
  .win.drape .lead.left { transform: translateX(-100%); }
  .win.drape .lead .tab {
    top: 44%;
    left: 100%;
    width: 7px;
    height: 14%;
    min-width: 0;
    max-width: none;
    transform: none;
    border-radius: 0 5px 5px 0;
    background: linear-gradient(to right, var(--n-rail-face), var(--n-rail-lo));
  }
  .win.drape .lead.right .tab {
    left: auto;
    right: 100%;
    border-radius: 5px 0 0 5px;
    background: linear-gradient(to left, var(--n-rail-face), var(--n-rail-lo));
  }
  .win.drape .rail.hot .tab, .win.drape .rail.held .tab { width: 9px; height: 14%; background: var(--n-accent); }
  .win.drape .zone {
    top: 4.5%;
    bottom: 0;
    left: 0;
    right: auto;
    width: 24%;
    height: auto;
    transform: translateX(-50%);
    transition: left 0.45s var(--n-ease);
  }
  .win.drape .marker {
    top: 4.5%;
    bottom: 0;
    right: auto;
    width: 0;
    height: auto;
    border-top: 0;
    border-left: 2px dashed var(--n-accent);
    transform: translateX(-1px);
    transition: opacity 0.25s, left 0.8s linear;
  }
  .win.dragging .vane, .win.dragging .sheer, .win.dragging .lead { transition: none; }

  /* ---- a Shutter ---------------------------------------------------------------------
     Painted louvers in a frame of stiles and rails, set into the window. Each louver turns
     about its long axis -- flat and overlapping when shut, nearly edge-on when open -- and
     the tilt rod down their middle is what a hand, and the card, moves. */
  .win.shutter .panel {
    position: absolute;
    inset: 0;
    z-index: 1;
  }
  .win.shutter .panel::before {
    content: "";
    position: absolute;
    inset: 0;
    z-index: 2;
    pointer-events: none;
    background:
      linear-gradient(to right, var(--n-trim) 0 7%, transparent 7% 93%, var(--n-trim) 93%),
      linear-gradient(to bottom, var(--n-trim-hi) 0, var(--n-trim) 2%, var(--n-trim) 6%, transparent 6% 94%, var(--n-trim) 94%, var(--n-trim-lo));
    box-shadow: inset 0 0 0 1px var(--n-trim-edge), 0 1px 2px rgba(40, 30, 20, 0.25);
  }
  /* Tucked a little under the frame, so no sky shows where a shut louver meets a stile. */
  .win.shutter .louvers {
    position: absolute;
    top: 5.5%;
    bottom: 5.5%;
    left: 6.5%;
    right: 6.5%;
    z-index: 1;
    display: flex;
    flex-direction: column;
    perspective: 260px;
    box-shadow: inset 0 2px 4px rgba(40, 30, 20, 0.25);
  }
  .win.shutter .louver {
    flex: 1 1 0;
    margin: -0.8% 0;
    border-radius: 1px;
    background: linear-gradient(to bottom, var(--n-trim-hi), var(--n-trim) 42%, var(--n-trim) 70%, var(--n-trim-lo));
    box-shadow: 0 0 0 0.5px var(--n-trim-edge), 0 1px 1.5px rgba(60, 45, 25, 0.3);
    transform: rotateX(0deg);
    transition: transform 0.45s var(--n-ease);
  }
  .win.shutter .rod {
    position: absolute;
    left: 50%;
    top: 7%;
    bottom: 7%;
    width: 3.4%;
    min-width: 3px;
    z-index: 3;
    border-radius: 2px;
    background: linear-gradient(to right, var(--n-trim-lo), var(--n-trim-hi) 45%, var(--n-trim) 70%, var(--n-trim-lo));
    box-shadow: 0 0 0 0.5px var(--n-trim-edge), 1px 1px 2px rgba(0, 0, 0, 0.3);
    transform: translate(-50%, 0);
    transition: transform 0.45s var(--n-ease), background-color 0.15s, box-shadow 0.15s;
  }
  .win.shutter .rod.hot, .win.shutter .rod.held {
    background: var(--n-accent);
    box-shadow: 0 0 0 0.5px rgba(0, 0, 0, 0.25), 0 0 8px rgba(var(--n-accent-rgb), 0.55);
  }
  .win.shutter .rod.moving:not(.held) { animation: n-pulse 1.6s ease-in-out infinite; }
  .win.shutter .rod-zone { left: 32%; right: 32%; top: 50%; height: 86%; }
  .win.shutter .marker { display: none; }
  .win.dragging .louver, .win.dragging .rod { transition: none; }
  ha-card[data-theme="dark"] .win.shutter .panel { filter: brightness(0.88); }

  /* ---- each blind's color ------------------------------------------------------------------
     A blind's color (its select entity) sets the cloth's tokens on its window -- the fabric, a
     roll, a Roman shade's head and hem, a PerfectSheer's or a SmartDrape's vanes, a two-rail
     shade's blackout, its sheer keeping its own white -- or a Shutter's trim tokens on its
     panel. From SHADE_COLORS and SHUTTER_COLORS in the script. */
  ${colorRules()}

  /* Choosing for each window, in the sidebar panel: its shade's color (the whole-house row's
     colors button) or its glass's divided lights (the lights button). Each window becomes one
     button: a native select laid over it, so a phone shows its own picker, with the choice's name
     beneath and a color on a swatch at the window's corner. While the divided lights are chosen
     the shades are drawn away, so that each window shows its glass. The whole-house row gives way
     to a bar that chooses for every window at once and ends the choosing; a rail is not dragged
     meanwhile. */
  .pick, .color-badge, .choice-name, .choice-bar { display: none; }
  ha-card.coloring .pick.colors, ha-card.lighting .pick.lights {
    display: block;
    position: absolute;
    inset: 0;
    z-index: 9;
    width: 100%;
    height: 100%;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: 4px;
    -webkit-appearance: none;
    appearance: none;
    background: transparent;
    color: transparent;
    /* A phone zooms into a smaller one when it takes the focus. */
    font-size: 16px;
    cursor: pointer;
  }
  ha-card.choosing .pick option { color: #10151d; background: #fff; }
  ha-card.choosing .pick:focus-visible { outline: 2px solid var(--n-accent); outline-offset: 3px; }
  ha-card.choosing .win { cursor: pointer; }
  ha-card.choosing .frame { box-shadow: 0 0 0 2px rgba(var(--n-accent-rgb), 0.7), 0 8px 18px -10px rgba(40, 30, 20, 0.45); }
  ha-card.lighting .opening > :not(.view) { visibility: hidden; }
  ha-card.coloring .color-badge {
    display: block;
    position: absolute;
    top: 2%;
    right: 0;
    z-index: 8;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: var(--n-swatch, #f0ebe2);
    box-shadow: 0 0 0 2px #fff, 0 2px 6px rgba(0, 0, 0, 0.45);
    pointer-events: none;
  }
  ha-card.coloring .meta-bottom > :not(.choice-name.colors),
  ha-card.lighting .meta-bottom > :not(.choice-name.lights),
  ha-card.choosing .tile > .stop { display: none !important; }
  ha-card.coloring .choice-name.colors, ha-card.lighting .choice-name.lights {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    font-size: 12.5px;
    line-height: 1.35;
    color: var(--n-muted);
  }
  .choice-name i {
    flex: none;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--n-swatch, #f0ebe2);
    box-shadow: 0 0 0 1px rgba(var(--n-fg-rgb), 0.35);
  }
  .choice-name span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  ha-card.choosing .tools { display: none; }
  ha-card.coloring .choice-bar.colors, ha-card.lighting .choice-bar.lights {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px 12px;
    margin-top: 4px;
  }
  .choice-text { flex: 1 1 220px; min-width: 0; }
  .choice-title { font-size: 15px; font-weight: 600; }
  .choice-hint { margin-top: 2px; font-size: 13px; color: var(--n-muted); }
  .choice-actions { display: flex; flex-wrap: wrap; gap: 8px; }
  /* Every window at once: a select over a chip, as each window has one over it. */
  .choice-every { position: relative; }
  .choice-every select {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    margin: 0;
    border: 0;
    opacity: 0;
    font-size: 16px;
    cursor: pointer;
  }
  .choice-every:focus-within { outline: 2px solid var(--n-accent); outline-offset: 1px; }

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
     is moving, that its move is not confirmed, or that it is unavailable. */
  .row .status.rest { display: none; }
  .row.unavailable { opacity: 0.5; }

  .empty { padding: 8px 0 4px; color: var(--n-muted); }

  /* ---- the sidebar panel ------------------------------------------------------------------
     The header stays at the top as the page scrolls: it carries the button back to Home
     Assistant's sidebar, which a phone hides. It keeps to one line -- the whole-house presets
     and scene groups go in a row of their own beneath it -- and pads itself by the phone's
     status bar (--n-safe-top, from norman-panel.js), so its colour reaches under it. */
  :host([panel]) .header {
    position: sticky;
    top: 0;
    z-index: 10;
    flex-wrap: nowrap;
    margin: -16px -16px 0;
    padding: calc(12px + var(--n-safe-top, 0px)) 16px 12px;
    border-radius: var(--ha-card-border-radius, 12px) var(--ha-card-border-radius, 12px) 0 0;
    background: var(--ha-card-background, var(--card-background-color, #fff));
  }
  :host([panel][narrow]) .header { border-radius: 0; }
  /* On a phone the hub's name has the room its buttons leave it, so they stand a little closer. */
  :host([panel][narrow]) .header { column-gap: 10px; }
  :host([panel][narrow]) .home-refresh + .home-settings { margin-left: -4px; }
  .tools { display: flex; flex-wrap: wrap; align-items: center; gap: 12px 16px; margin-top: 4px; }

  /* ---- a wide card -----------------------------------------------------------------------
     The rooms sit side by side, in columns packed without gaps, so each room's controls stay
     beside its blinds rather than at the far end of a mostly empty row, and the windows grow a
     little. A room never splits between two columns. With the room headings hidden there is
     one section, which keeps the whole width. */
  @container (min-width: 700px) {
    .body:not(.single) { columns: 340px; column-gap: 32px; padding-top: 18px; }
    .body:not(.single) > .room,
    .body:not(.single) > .room:first-child { margin: 0 0 22px; break-inside: avoid; }
    .grid { --n-tile: 136px; }
  }

  /* ---- a touch screen ----------------------------------------------------------------------
     Finger-sized targets. A drag starts only on a rail's pull tab, in a box around it; the rest
     of the window scrolls the page, so a swipe to scroll that lands on a rail moves nothing. A
     Shutter's tilt rod is the same, and a SmartDrape is drawn sideways, so a swipe up or down
     its edge scrolls too. */
  @media (pointer: coarse) {
    .icon-btn { width: 44px; height: 40px; }
    .home-refresh .icon-btn, .home-settings .icon-btn { width: 40px; height: 40px; }
    .chip { height: 38px; }
    .tile > .stop { top: -10px; right: -6px; width: 38px; height: 38px; }
    .refresh::after { inset: -12px -10px; }
    .battery::after { content: ""; position: absolute; inset: -12px -6px; }
    .name { margin-block: -6px; padding-block: 6px; }
    .slider { min-height: 44px; }
    .slider input::-webkit-slider-thumb { width: 26px; height: 26px; }
    .slider input::-moz-range-thumb { width: 26px; height: 26px; }
    .win:not(.drape) .zone:not(.rod-zone) {
      left: var(--n-tab-x, 50%);
      right: auto;
      width: 56px;
      height: 44px;
      transform: translate(-50%, -50%);
    }
    .win.shutter .rod-zone { left: 50%; right: auto; width: 48px; transform: translate(-50%, -50%); }
    .win.drape .zone { touch-action: pan-y; }
  }

  /* ---- less motion, less transparency ----------------------------------------------------- */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
    }
    /* Without its pulse, a moving rail's tab says so in the accent colour. */
    .rail.moving .tab, .win.shutter .rod.moving { background: var(--n-accent); }
  }
  @media (prefers-reduced-transparency: reduce) {
    .fabric.sheer, .win.perfectsheer .cloth, .win.drape .sheer {
      -webkit-backdrop-filter: none;
      backdrop-filter: none;
    }
  }

  /* ---- the sidebar page with its view ---------------------------------------------------------
     With the integration's view option on, each window looks out on a real photograph, drawn
     by the panel's view (norman-view.js) on a canvas (.photo), so the drawn sky and hills go.
     The page behind takes the photograph's colours (norman-panel.js) and the card is laid over
     them: no card of its own, its heading and the weather straight on the colours, and the
     whole-house buttons and each room on glass. In Home Assistant's dark theme the colours are
     deep, the glass dark and the words white; in its light theme ([light], from the panel) the
     colours are pale, the glass light and the words dark, every colour below a token of one set
     or the other. Everything here is under :host([panel][view]); a card on a dashboard never
     matches. */
  :host([panel][view]) {
    --n-fg: #fff;
    --n-fg-rgb: 255, 255, 255;
    --n-accent: #93d5ff;
    --n-accent-rgb: 147, 213, 255;
    --n-muted: rgba(255, 255, 255, 0.76);
    --n-faint: rgba(255, 255, 255, 0.66);
    --n-glass: rgba(13, 17, 25, 0.44);
    --n-glass-strong: rgba(13, 17, 25, 0.68);
    --n-glass-solid: rgba(13, 17, 25, 0.9);
    --n-glass-line: rgba(255, 255, 255, 0.15);
    --n-glass-fill: rgba(255, 255, 255, 0.09);
    --n-glass-hover: rgba(255, 255, 255, 0.18);
    --n-glass-blur: blur(22px) saturate(1.4);
    --n-glass-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.07), 0 20px 40px -26px rgba(0, 0, 0, 0.6);
    --n-float-shadow: 0 20px 40px -18px rgba(0, 0, 0, 0.75);
    --n-frame-shadow: 0 14px 22px -12px rgba(0, 0, 0, 0.7);
    /* What is pressed or chosen: a chip whose preset was sent, an open tray, the room in view. */
    --n-pressed: rgba(255, 255, 255, 0.92);
    --n-pressed-fg: #10151d;
    --n-pressed-accent: #0b6ea6;
    /* Words straight on the colours keep a shadow, a deep ground being bright in places. */
    --n-on-photo: 0 1px 3px rgba(0, 0, 0, 0.5), 0 0 16px rgba(0, 0, 0, 0.4);
    --n-on-ground: 0 1px 12px rgba(0, 0, 0, 0.45);
    --n-on-ground-soft: 0 1px 18px rgba(0, 0, 0, 0.3);
    --n-on-ground-small: 0 1px 3px rgba(0, 0, 0, 0.6);
    --primary-text-color: #fff;
    --secondary-text-color: rgba(255, 255, 255, 0.76);
    --text-primary-color: #10151d;
    --card-background-color: #1b222d;
    --ha-card-header-color: #fff;
    --warning-color: #ffc56e;
    --error-color: #ff9b8f;
    color: var(--n-fg);
  }
  /* The light theme's: words dark enough on every pale ground, a shadow needed nowhere. */
  :host([panel][view][light]) {
    --n-fg: #141a24;
    --n-fg-rgb: 20, 26, 36;
    --n-accent: #0a6496;
    --n-accent-rgb: 10, 100, 150;
    --n-muted: rgba(20, 26, 36, 0.72);
    --n-faint: rgba(20, 26, 36, 0.72);
    --n-glass: rgba(255, 255, 255, 0.5);
    --n-glass-strong: rgba(248, 250, 252, 0.8);
    --n-glass-solid: rgba(248, 250, 252, 0.95);
    --n-glass-line: rgba(20, 26, 36, 0.09);
    --n-glass-fill: rgba(20, 26, 36, 0.05);
    --n-glass-hover: rgba(20, 26, 36, 0.1);
    --n-glass-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7), 0 1px 2px rgba(20, 26, 36, 0.05),
      0 18px 36px -24px rgba(20, 26, 36, 0.32);
    --n-float-shadow: 0 14px 32px -14px rgba(20, 26, 36, 0.38);
    --n-frame-shadow: 0 12px 20px -12px rgba(20, 26, 36, 0.4);
    --n-pressed: rgba(20, 26, 36, 0.88);
    --n-pressed-fg: #fff;
    --n-pressed-accent: #93d5ff;
    --n-on-photo: none;
    --n-on-ground: none;
    --n-on-ground-soft: none;
    --n-on-ground-small: none;
    --primary-text-color: #141a24;
    --secondary-text-color: rgba(20, 26, 36, 0.72);
    --text-primary-color: #fff;
    --card-background-color: #fff;
    --ha-card-header-color: #141a24;
    --warning-color: #8f5300;
    --error-color: #a8231c;
  }
  /* White trim and ivory cloth, as by day in the light theme, whatever the theme is. */
  :host([panel][view]) ha-card,
  :host([panel][view]) ha-card[data-theme="dark"] {
    --n-trim: #f3f1ec;
    --n-trim-hi: #fdfcfa;
    --n-trim-lo: #d8d3ca;
    --n-trim-edge: rgba(0, 0, 0, 0.3);
    --n-rail-hi: #ffffff;
    --n-rail-face: #eeebe5;
    --n-rail-lo: #cbc5ba;
    --n-cloth-hi: #fbf9f4;
    --n-cloth: #f0ebe2;
    --n-cloth-lo: #ddd5c7;
    --n-cloth-crease: #bdb2a0;
    padding: 0;
    border: none;
    border-radius: 0;
    box-shadow: none;
    background: none;
    color: var(--n-fg);
  }
  /* The windows darken with the light outside, not with the theme: the trim by its colours, so
     the view through the glass is left alone, and the shade by a filter of its own. */
  :host([panel][view]) ha-card[data-sky="dusk"] {
    --n-trim: #d3d0ca;
    --n-trim-hi: #e2e0db;
    --n-trim-lo: #b7b3aa;
  }
  :host([panel][view]) ha-card[data-sky="night"] {
    --n-trim: #a9a8a5;
    --n-trim-hi: #bbbab7;
    --n-trim-lo: #8e8c87;
  }
  :host([panel][view]) ha-card .fabric,
  :host([panel][view]) ha-card .rail,
  :host([panel][view]) ha-card .headrail,
  :host([panel][view]) ha-card .roll,
  :host([panel][view]) ha-card .hanging,
  :host([panel][view]) ha-card .win.perfectsheer .vane,
  :host([panel][view]) ha-card .win.shutter .panel { filter: none; }
  :host([panel][view]) ha-card[data-sky="dusk"] .fabric,
  :host([panel][view]) ha-card[data-sky="dusk"] .rail,
  :host([panel][view]) ha-card[data-sky="dusk"] .headrail,
  :host([panel][view]) ha-card[data-sky="dusk"] .roll,
  :host([panel][view]) ha-card[data-sky="dusk"] .hanging,
  :host([panel][view]) ha-card[data-sky="dusk"] .win.perfectsheer .vane,
  :host([panel][view]) ha-card[data-sky="dusk"] .win.shutter .panel { filter: brightness(0.88); }
  :host([panel][view]) ha-card[data-sky="night"] .fabric,
  :host([panel][view]) ha-card[data-sky="night"] .rail,
  :host([panel][view]) ha-card[data-sky="night"] .headrail,
  :host([panel][view]) ha-card[data-sky="night"] .roll,
  :host([panel][view]) ha-card[data-sky="night"] .hanging,
  :host([panel][view]) ha-card[data-sky="night"] .win.perfectsheer .vane,
  :host([panel][view]) ha-card[data-sky="night"] .win.shutter .panel { filter: brightness(0.74); }

  /* The header: straight on the page's colours at the top, and on frosted glass once the page
     has scrolled under it (the panel marks the card as scrolled). */
  :host([panel][view]) .header {
    margin: 0 -8px;
    padding: calc(12px + var(--n-safe-top, 0px)) 12px 12px;
    border: 1px solid transparent;
    border-top: 0;
    border-radius: 0 0 22px 22px;
    background: none;
    transition: background-color 0.25s, border-color 0.25s;
  }
  :host([panel][view][scrolled]) .header {
    border-color: var(--n-glass-line);
    background: var(--n-glass-strong);
    -webkit-backdrop-filter: var(--n-glass-blur);
    backdrop-filter: var(--n-glass-blur);
  }
  :host([panel][view]) .header-text { text-shadow: var(--n-on-ground); }
  :host([panel][view]) .icon-btn.menu { margin: 0; }
  :host([panel][view]) .home-refresh, :host([panel][view]) .home-settings { background: none; }
  :host([panel][view]) .icon-btn.menu,
  :host([panel][view]) .home-refresh .icon-btn,
  :host([panel][view]) .home-settings .icon-btn {
    width: 44px;
    height: 44px;
    background: var(--n-glass);
  }
  :host([panel][view]) .home-settings .icon-btn.open { background: rgba(var(--n-accent-rgb), 0.24); color: var(--n-accent); }
  /* Over the view the settings menu is solid glass, so its words read over any photograph. */
  :host([panel][view]) .settings-menu {
    border: 1px solid var(--n-glass-line);
    background: var(--n-glass-solid);
    box-shadow: var(--n-float-shadow);
  }
  :host([panel][view]) .menu-item { color: var(--n-fg); }

  /* The weather, large, with the house's counts beneath, and the forecast for the hours ahead:
     beside it where there is room, beneath it on a phone. */
  .hero {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 18px 28px;
    padding: 10px 6px 0;
    margin-bottom: 26px;
    text-shadow: var(--n-on-ground-soft);
  }
  .hero .now { flex: 1 1 260px; min-width: 0; }
  .hours {
    flex: 0 1 540px;
    display: flex;
    min-width: 0;
    margin: 0 0 0 auto;
    padding: 10px 4px;
    list-style: none;
    border: 1px solid var(--n-glass-line);
    border-radius: 22px;
    background: var(--n-glass);
    box-shadow: var(--n-glass-shadow);
    text-shadow: none;
  }
  .hours li {
    position: relative;
    flex: 1 1 0;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    font-weight: 600;
    color: var(--n-muted);
    white-space: nowrap;
  }
  /* Now and the first hours on a phone; the rest where the forecast sits beside the weather. */
  .hours li:nth-child(n + ${FORECAST_NARROW + 1}) { display: none; }
  .hours ha-icon { --mdc-icon-size: 24px; color: var(--n-fg); }
  .hours .wet { min-height: 14px; font-size: 11px; line-height: 14px; color: var(--n-accent); font-variant-numeric: tabular-nums; }
  .hours .deg { color: var(--n-fg); font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums; }
  /* A day's low, under its high. */
  .hours .low { display: block; margin-top: 1px; color: var(--n-muted); font-size: 13px; font-weight: 500; text-align: center; }
  /* Words for a screen reader, not shown. */
  .said { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  .hero .temp {
    font-size: 92px;
    font-weight: 300;
    line-height: 0.95;
    letter-spacing: -0.04em;
    font-variant-numeric: tabular-nums;
  }
  .hero .cond { margin-top: 8px; font-size: 17px; font-weight: 500; text-shadow: var(--n-on-photo); }
  .hero .summary { margin-top: 4px; font-size: 14px; color: var(--n-fg); text-shadow: var(--n-on-photo); }
  .hero .summary .live, .hero .summary .warn { color: var(--n-fg); font-weight: 600; }

  /* Dark glass: the whole-house row, and each room. Behind them is only the page's gradient,
     which a blur would not change, so they are not blurred: on a phone a blur is work for every
     frame of a scroll. Only the header blurs, once the page scrolls under it. */
  :host([panel][view]) .tools,
  :host([panel][view]) .body > .room {
    border: 1px solid var(--n-glass-line);
    border-radius: 26px;
    background: var(--n-glass);
    box-shadow: var(--n-glass-shadow);
  }
  :host([panel][view]) .tools { gap: 8px; margin: 0; padding: 12px; }
  :host([panel][view]) .segmented { gap: 8px; padding: 0; border-radius: 0; background: none; }
  :host([panel][view]) .home-buttons {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    flex: 1 1 320px;
    max-width: 560px;
  }
  :host([panel][view]) .chip {
    justify-content: center;
    height: 40px;
    padding: 0 14px 0 12px;
    border: 1px solid var(--n-glass-line);
    border-radius: 999px;
    background: var(--n-glass-fill);
    color: var(--n-fg);
    font-weight: 600;
  }
  :host([panel][view]) .chip ha-icon { color: var(--n-accent); }
  :host([panel][view]) .chip:hover { background: var(--n-glass-hover); box-shadow: none; }
  :host([panel][view]) .chip.sent { background: var(--n-pressed); color: var(--n-pressed-fg); }
  :host([panel][view]) .chip.sent ha-icon { color: var(--n-pressed-accent); }

  /* The rooms sit side by side wherever there is room for two, each on its own pane; a grid,
     not the plain card's columns, which split a pane of glass badly. */
  :host([panel][view]) .body,
  :host([panel][view]) .body:not(.single) {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 330px), 1fr));
    align-items: start;
    gap: 14px;
    columns: auto;
    margin-top: 14px;
    padding-top: 0;
  }
  :host([panel][view]) .body.single { grid-template-columns: minmax(0, 1fr); }
  :host([panel][view]) .body > .room,
  :host([panel][view]) .body > .room:first-child,
  :host([panel][view]) .body:not(.single) > .room,
  :host([panel][view]) .body:not(.single) > .room:first-child { margin: 0; padding: 16px 14px 18px; }
  :host([panel][view]) .room-head { min-height: 44px; margin-bottom: 14px; padding-left: 4px; }
  .room-titles { flex: 1; min-width: 0; }
  :host([panel][view]) .room-name { font-size: 13px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }
  .room-line {
    margin-top: 2px;
    font-size: 13px;
    color: var(--n-muted);
    font-variant-numeric: tabular-nums;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  /* The house's line starts with a count; a room's starts with a word, so it takes a capital. */
  .room-line::first-letter { text-transform: uppercase; }
  .room-line .live { color: var(--n-accent); }
  :host([panel][view]) .icon-group { gap: 6px; background: none; }
  :host([panel][view]) .icon-btn {
    width: 40px;
    height: 40px;
    border: 1px solid var(--n-glass-line);
    border-radius: 50%;
    background: var(--n-glass-fill);
    color: var(--n-fg);
  }
  :host([panel][view]) .icon-btn:hover { background: var(--n-glass-hover); }
  :host([panel][view]) .icon-btn.more.open { background: var(--n-pressed); color: var(--n-pressed-fg); }
  :host([panel][view]) .tray { margin: -2px 0 14px; }

  /* Three windows across, on a phone as on a desktop; a name too long for its window takes a
     second line, and the battery and refresh go under the state. */
  :host([panel][view]) .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px 12px; padding: 0 2px; }
  :host([panel][view]) .name {
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    font-size: 13px;
    font-weight: 600;
    white-space: normal;
    overflow-wrap: anywhere;
  }
  :host([panel][view]) .meta-bottom { flex-wrap: wrap; gap: 3px 6px; }
  :host([panel][view]) .tile .status { flex: 1 1 100%; font-size: 12px; }
  :host([panel][view]) .tile .battery { margin-left: 0; }
  :host([panel][view]) .frame { box-shadow: 0 0 0 1px var(--n-trim-edge), var(--n-frame-shadow); }

  /* The view through each window: the photograph, drawn by the panel's view on a canvas. A
     room's windows look out on one strip of it, each on the part behind it. */
  .photo { position: absolute; inset: 0; width: 100%; height: 100%; }
  :host([panel][view]) .view,
  :host([panel][view]) ha-card[data-sky] .view { background: #0b1220; }
  :host([panel][view]) .sun, :host([panel][view]) .hills { display: none; }

  @container (min-width: 700px) {
    .hero .temp { font-size: 112px; }
    .hours li:nth-child(n + ${FORECAST_NARROW + 1}) { display: flex; }
    /* On a wide screen the whole-house row is only as wide as its buttons, the presets no
       wider than their words need, so what follows them stays on their line where it fits. */
    :host([panel][view]) .tools { box-sizing: border-box; width: fit-content; max-width: 100%; }
    :host([panel][view]) .home-buttons { flex: 0 1 auto; }
  }

  /* Over the view the choosing bar is a pane of glass, as the whole-house row it stands in for. */
  :host([panel][view]) ha-card.choosing .choice-bar {
    margin: 0;
    padding: 12px 12px 12px 18px;
    border: 1px solid var(--n-glass-line);
    border-radius: 26px;
    background: var(--n-glass);
    box-shadow: var(--n-glass-shadow);
  }
  :host([panel][view]) .choice-hint { color: var(--n-muted); }

  /* ---- the rooms bar: the sidebar panel on a phone ------------------------------------------
     A bar at the foot of the screen with a button for each room, and one for the top of the
     page, the part in view marked. Sticky at the bottom of the panel's scroll box, so it stays
     put as the page scrolls, and it scrolls sideways itself when the rooms will not fit. A dot
     says a room has a shade moving, or one with a low battery. */
  .rooms-bar { display: none; }
  :host([panel][narrow]) .rooms-bar:not([hidden]) {
    position: sticky;
    bottom: calc(12px + var(--n-safe-bottom, 0px));
    z-index: 9;
    display: flex;
    gap: 4px;
    margin: 18px 0 0;
    padding: 5px;
    overflow-x: auto;
    overscroll-behavior-x: contain;
    scrollbar-width: none;
    border-radius: 999px;
    background: var(--ha-card-background, var(--card-background-color, #fff));
    box-shadow: 0 0 0 1px rgba(var(--n-fg-rgb), 0.1), 0 10px 28px -8px rgba(0, 0, 0, 0.4);
  }
  .rooms-bar::-webkit-scrollbar { display: none; }
  .room-tab {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 44px;
    padding: 0 15px;
    border: 0;
    border-radius: 999px;
    background: none;
    color: var(--primary-text-color);
    font: inherit;
    font-size: 14px;
    font-weight: 600;
    white-space: nowrap;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }
  .room-tab ha-icon { --mdc-icon-size: 18px; }
  .room-tab[aria-current="true"] { background: var(--n-accent); color: var(--text-primary-color, #fff); }
  .room-tab:focus-visible { outline: 2px solid var(--n-accent); outline-offset: -2px; }
  .room-tab .dot { flex: none; width: 6px; height: 6px; border-radius: 50%; }
  .room-tab .dot.live { background: var(--n-accent); }
  .room-tab .dot.warn { background: var(--warning-color, #e39700); }
  .room-tab[aria-current="true"] .dot.live { background: currentColor; }
  :host([panel][view][narrow]) .rooms-bar:not([hidden]) {
    border: 1px solid var(--n-glass-line);
    background: var(--n-glass-strong);
    -webkit-backdrop-filter: var(--n-glass-blur);
    backdrop-filter: var(--n-glass-blur);
    box-shadow: var(--n-float-shadow);
  }
  :host([panel][view]) .room-tab { color: var(--n-fg); }
  :host([panel][view]) .room-tab[aria-current="true"] { background: var(--n-pressed); color: var(--n-pressed-fg); }
  :host([panel][view]) .room-tab[aria-current="true"] .dot.live { background: var(--n-pressed-accent); }
  @media (pointer: coarse) {
    :host([panel][view]) .icon-btn { width: 44px; height: 44px; }
    :host([panel][view]) .chip { height: 44px; }
    /* A name's finger-sized reach is above it only: a third line would show in room beneath. */
    :host([panel][view]) .name { margin-block: -6px 0; padding-block: 6px 0; }
  }
  @media (prefers-reduced-transparency: reduce) {
    :host([panel][view]) .tools,
    :host([panel][view]) .body > .room,
    :host([panel][view][scrolled]) .header,
    :host([panel][view]) .icon-btn.menu,
    :host([panel][view]) .home-refresh .icon-btn,
    :host([panel][view]) .home-settings .icon-btn,
    :host([panel][view]) .hours,
    :host([panel][view]) ha-card.choosing .choice-bar,
    :host([panel][view][narrow]) .rooms-bar:not([hidden]) {
      -webkit-backdrop-filter: none;
      backdrop-filter: none;
      background: var(--n-glass-solid);
    }
  }
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
    // This card's last write to each rail, keyed and shaped like _pending: its `at` is when it
    // went. Sending a blind the target the hub already holds leaves the cover's state as it
    // was, so without this its last_updated would not restart the move window (see
    // _railState). A write that fails is taken back out (see _expect).
    this._sent = new Map();
    // The side each SmartDrape was last seen stacking to, by device: an unavailable cover
    // carries no attributes, and the drape keeps its side meanwhile (see _collectBlinds).
    this._stacks = new Map();
    // Redraws the card when the next move window closes (see _patch).
    this._settleTimer = null;
    // What the card has read from Home Assistant's registries, by name (see _fromRegistry).
    this._registryCache = new Map();
    // When each refresh control last sent, by control, so the hold outlasts a rebuild (see
    // _bindRefresh).
    this._refreshedAt = new Map();
    this._cells = [];
    // The header's text node and summary line (see _render).
    this._headerText = null;
    this._summary = null;
    // Set by the sidebar panel: Home Assistant hides its sidebar on phones (see narrow).
    this._narrow = false;
    this._menuButton = null;
    // The panel's view, when the integration's view option is on (see view), the way to stop
    // hearing from it, and what the card draws over it: the weather under the heading, each
    // room's line of counts and each window's canvas. The photographs are credited in NOTICE,
    // which the view option's description links to, not on the page.
    this._view = null;
    this._viewOff = null;
    this._hero = null;
    this._roomLines = [];
    this._panes = [];
    // The forecast beside the weather over the view (_syncForecast): its list, and the
    // subscription it comes by.
    this._hours = null;
    this._forecast = null;
    // Choosing for each window in the sidebar panel (_setChoosing): what the page is choosing
    // ("colors", "lights" or null); the settings button at the top, its menu and each kind's item
    // in it (_buildSettings); each kind's bar that stands in for the whole-house row meanwhile,
    // with its "every" chip and Done; and the choices made here that Home Assistant has yet to
    // take up, by entity ({ value, at }).
    this._choosing = null;
    this._settings = null;
    this._settingsButton = null;
    this._settingsMenu = null;
    this._choiceItems = {};
    this._choiceBars = {};
    this._choiceEvery = {};
    this._choiceDone = {};
    this._choicePending = new Map();
    // The rooms bar on a phone (_buildDock): its buttons, the scroll box it follows, and how long
    // a press on it holds the marking still while the page scrolls to the room.
    this._dock = null;
    this._tabs = [];
    this._scroller = null;
    this._spyHeld = 0;
    this._connected = false;
  }

  connectedCallback() {
    this._connected = true;
    if (!this._rendered) return;
    this._syncForecast();
    this._watchScroll();
  }

  disconnectedCallback() {
    this._connected = false;
    this._stopForecast();
    this._unwatchScroll();
    this._toggleSettings(false);
  }

  setConfig(config) {
    this._config = config || {};
    this._rendered = false;
    this._signature = undefined;
    if (this.shadowRoot) this.shadowRoot.innerHTML = "";
    // A dashboard hands a card a changed config with setConfig alone (hui-card), and hass only
    // with the next state change in the house. A card that already has hass draws itself now.
    if (this._hass) this.hass = this._hass;
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
    // Every word on the card is built in the user's language, so a change of language (from
    // their profile) redraws it rather than patching values into the old words.
    const language = languageOf(hass);
    if (this._rendered && language !== this._language) {
      this._signature = undefined;
      this._rendered = false;
    }
    this._language = language;
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    } else {
      this._update();
    }
  }

  /** A string in the user's language (norman-strings.js). */
  _t(key, vars) {
    return translate(languageOf(this._hass), key, vars);
  }

  /** A percentage as the user's language writes it: "84%", or "84 %" in German and French. */
  _pct(value) {
    return this._t("percent", { value: Math.round(value) });
  }

  // The sidebar panel passes Home Assistant's `narrow` on (phones: the sidebar is hidden).
  set narrow(narrow) {
    this._narrow = Boolean(narrow);
    this.toggleAttribute("narrow", this._narrow);
    this._syncMenuButton();
  }

  get narrow() {
    return this._narrow;
  }

  /**
   * The panel's view (norman-view.js), or null. The panel marks the card with a `view` attribute
   * before the card first draws, since over the view it is built differently; the view itself
   * arrives here once its photographs' index has loaded.
   */
  set view(view) {
    this._viewOff?.();
    this._view = view || null;
    this._viewOff = this._view ? this._view.subscribe(() => this._viewChanged()) : null;
    this._viewChanged();
  }

  get view() {
    return this._view;
  }

  /** Whether the card is drawn over the panel's view. */
  _overView() {
    return this.hasAttribute("panel") && this.hasAttribute("view");
  }

  // The view has a new photograph, or follows another weather entity: hand it the windows, and
  // draw the weather again.
  _viewChanged() {
    if (!this._rendered) return;
    this._syncPanes();
    this._inputs = null;
    this._update();
  }

  /**
   * Give the view each window's canvas, and the room it is in: a room's windows look out on
   * one view between them, each on the part behind it.
   */
  _syncPanes() {
    if (!this._view) return;
    this._view.setPanes(
      this._roomLines.flatMap(({ photos }, group) => photos.map((canvas) => ({ canvas, group }))),
    );
  }

  // In the sidebar panel, wherever Home Assistant isn't showing its sidebar (the same test its
  // own menu button uses), the header offers the way back to it. On a dashboard Home
  // Assistant's own toolbar already has that button.
  _wantsMenuButton() {
    if (!this.hasAttribute("panel")) return false;
    return this._narrow || this._hass?.dockedSidebar === "always_hidden";
  }

  _syncMenuButton() {
    if (this._menuButton) this._menuButton.hidden = !this._wantsMenuButton();
  }

  // ---- data ------------------------------------------------------------------------

  /**
   * Whether a device belongs on this card: any Norman device, or with `config_entry_id` only
   * that hub's. The frontend's device registry lists each device's config entries; the
   * entity registry it sends does not carry one.
   */
  _inScope(deviceId) {
    const entryId = this._config.config_entry_id;
    if (!entryId) return true;
    return entriesOf((this._hass?.devices || {})[deviceId]).includes(entryId);
  }

  /**
   * The hub a device is on: its config entry, or null when the device registry does not say.
   * A device another integration has added itself to lists that integration's entry as well
   * (one that tracks a blind's battery, say); its primary entry is the one that created it,
   * which for a Norman device is its hub's.
   */
  _entryOf(deviceId) {
    const device = this._hass?.devices?.[deviceId];
    return device?.config_entry_id ?? device?.primary_config_entry ?? entriesOf(device)[0] ?? null;
  }

  /**
   * `compute()`, kept under `name` until Home Assistant's registries, the language or the
   * card's config change.
   *
   * Home Assistant sets `hass` on every state change in the house, but replaces its entity,
   * device and area registries (`entities`, `devices`, `areas`) only when one of them changes.
   * So what the card reads from those alone is worked out once per change, not by scanning
   * every entity in the house on every update. Nothing read from `hass.states` belongs here:
   * the callers read that afresh each time.
   */
  _fromRegistry(name, compute) {
    const hass = this._hass;
    const key = [hass?.entities, hass?.devices, hass?.areas, languageOf(hass), this._config];
    const kept = this._registryCache.get(name);
    if (kept && kept.key.every((part, index) => part === key[index])) return kept.value;
    const value = compute();
    this._registryCache.set(name, { key, value });
    return value;
  }

  /**
   * Every Norman blind visible to this dashboard, assembled from its entities.
   *
   * A blind is identified by its device id, so the bottom rail, middle rail, sliders, battery
   * sensor and Request status button are grouped even though their entity ids are independent.
   *
   * Everything but a drape's `stack` comes from the registries and is kept between updates
   * (_fromRegistry). The stack is the drape cover's state, so it is read on every call.
   */
  _collectBlinds() {
    if (!this._hass) return [];
    const states = this._hass.states || {};
    // A drape is drawn gathering to the side it stacks to, which its cover reports. The kept
    // blinds are shared between calls, so a drape gets a copy rather than being changed.
    return this._fromRegistry("blinds", () => this._registryBlinds()).map((blind) => {
      if (blind.product !== "drape") return blind;
      const stack = states[blind.bottomCover]?.attributes?.stack;
      // Home Assistant leaves an unavailable entity's attributes out, `stack` with them. The
      // drape keeps the side it was last seen on meanwhile, rather than being redrawn
      // gathering left -- a new side would rebuild the card under the user's hands.
      if (stack !== undefined && stack !== null) {
        this._stacks.set(blind.deviceId, STACK_SIDES[stack] ? stack : "left");
      }
      return { ...blind, stack: this._stacks.get(blind.deviceId) || "left" };
    });
  }

  /** The blinds as the registries have them, with no `stack` yet (see _collectBlinds). */
  _registryBlinds() {
    const hass = this._hass;
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
          // The area's name, or null for a blind in none, grouped under `default_room` or
          // "Unassigned" instead.
          area: area.name || null,
          room: area.name || this._config.default_room || this._t("unassigned"),
          product: productOf(device),
          stack: null,
          bottomCover: null,
          middleCover: null,
          louvers: false,
          bottomNumber: null,
          middleNumber: null,
          battery: null,
          // The blind's Request status button, or null when it has none on the card.
          refresh: null,
          // The blind's color (select.py), or null: drawn in the default then.
          color: null,
          // Its window's divided lights (select.py), or null: drawn with the default then.
          lights: null,
        });
      }
      return blinds.get(deviceId);
    };

    for (const [entityId, entry] of Object.entries(registry)) {
      if (entry.platform !== DOMAIN || !entry.device_id) continue;
      // The frontend's registry marks a hidden entity `hidden: true` and leaves disabled ones
      // out; `hidden_by` and `disabled_by` are the backend's names for the same. A hidden color
      // still colors its shade, and hidden divided lights still divide its glass: hiding them
      // tidies the device page, it does not undo the choice.
      if (entry.disabled_by) continue;
      const drawn = [KEY_SHADE_COLOR, KEY_SHUTTER_COLOR, KEY_WINDOW_LIGHTS].includes(entry.translation_key);
      if ((entry.hidden || entry.hidden_by) && !drawn) continue;
      if (!this._inScope(entry.device_id)) continue;

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
        } else if (key === KEY_LOUVERS) {
          blind.bottomCover = entityId;
          blind.louvers = true;
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
      } else if (domain === "button" && key === BUTTON_REQUEST_STATUS) {
        blind.refresh = entityId;
      } else if (domain === "select" && (key === KEY_SHADE_COLOR || key === KEY_SHUTTER_COLOR)) {
        blind.color = entityId;
      } else if (domain === "select" && key === KEY_WINDOW_LIGHTS) {
        blind.lights = entityId;
      }
    }

    // A device with no cover is the hub or one of its rooms, not a blind.
    return [...blinds.values()].filter((blind) => blind.bottomCover);
  }

  /**
   * The scenes saved in the Norman app, by room: a map from a room's name, as the blinds are
   * grouped (its area), to its scenes in name order.
   *
   * A room scene sits on its room's device, which the integration places in the area of the
   * same name; an area set on the scene itself wins, as it does everywhere in Home Assistant.
   * Scene groups are left out: they act on several rooms, so none of the rooms is theirs. So
   * is a scene hidden or disabled in Home Assistant, and one whose room has no area.
   *
   * The name is the registry's: the user's own name for the scene, or else the app's, which
   * Home Assistant brings into the registry whenever the entity's name changes.
   */
  _collectScenes() {
    const scenes = new Map();
    const devices = this._hass?.devices || {};
    const areas = this._hass?.areas || {};
    for (const { entityId, entry, name } of this._sceneEntities(KEY_ROOM_SCENE)) {
      const area = areas[entry.area_id || devices[entry.device_id]?.area_id];
      if (!area?.name) continue;
      if (!scenes.has(area.name)) scenes.set(area.name, []);
      scenes.get(area.name).push({ entityId, name });
    }
    return scenes;
  }

  /** The hub's scene groups, in name order: room scenes in several rooms, run together. */
  _collectSceneGroups() {
    return this._sceneEntities(KEY_SCENE_GROUP).map(({ entityId, name }) => ({ entityId, name }));
  }

  /**
   * Norman scene entities with translation key `key` that belong on this card, in name order:
   * not hidden or disabled in Home Assistant, and on this card's hub when it has one.
   *
   * Which scenes they are is kept between updates (_fromRegistry); a scene the registry leaves
   * unnamed is named from its state, so the names are read on every call.
   */
  _sceneEntities(key) {
    const hass = this._hass;
    const entries = this._fromRegistry(`scenes ${key}`, () => {
      const found = [];
      for (const [entityId, entry] of Object.entries(hass?.entities || {})) {
        if (entry.platform !== DOMAIN || entry.translation_key !== key) continue;
        if (!entry.device_id || entry.hidden || entry.hidden_by || entry.disabled_by) continue;
        if (!this._inScope(entry.device_id)) continue;
        found.push({ entityId, entry });
      }
      return found;
    });
    return entries
      .map(({ entityId, entry }) => ({
        entityId,
        entry,
        name: entry.name || hass.states?.[entityId]?.attributes?.friendly_name || entityId,
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  /**
   * The heading to show: the configured title, else the hub's name.
   *
   * A configured `title` always wins, whatever it says -- including `""` for a blank
   * heading. With no title the header names the hub, so a house with two hubs gets two
   * cards you can tell apart; "Shades" is the fallback for when no hub device can be found
   * (an install with no Norman devices yet, or before the registry has loaded), and for a
   * card with no hub chosen that shows the blinds of more than one (see _hubName).
   *
   * Cards added from the picker before v0.30 have `title: "Shades"` saved in their config,
   * because `getStubConfig()` used to supply it. Those keep saying "Shades" until the title
   * is removed -- the card cannot tell a saved default from a deliberate choice.
   */
  _headingText() {
    const configured = this._config.title;
    return configured !== undefined ? configured : (this._hubName() ?? this._t("heading_fallback"));
  }

  /**
   * The hub's name, as the Norman app has it (hubNameOf).
   *
   * The hub is the Norman device carrying the hub's own entities (`HUB_KEYS`): its MAC
   * address, Wi-Fi and time-zone sensors, pairing and refresh. Not just any device without a
   * cover -- each of the hub's rooms is one of those too. Returns null when there is no hub
   * to name.
   *
   * A card with no `config_entry_id` shows every hub's blinds. Showing one hub's, it names
   * that hub, not another one set up beside it; showing several hubs', it names none of them.
   */
  _hubName() {
    const hass = this._hass;
    if (!hass) return null;

    return this._fromRegistry("hub name", () => {
      const registry = hass.entities || {};
      const devices = hass.devices || {};
      let hubs = null;
      if (!this._config.config_entry_id) {
        const shown = this._roomsOf(this._fromRegistry("blinds", () => this._registryBlinds()));
        hubs = new Set(shown.flatMap(([, list]) => list.map((blind) => this._entryOf(blind.deviceId))).filter(Boolean));
        if (hubs.size > 1) return null;
        if (!hubs.size) hubs = null;
      }

      for (const entry of Object.values(registry)) {
        if (entry.platform !== DOMAIN || !entry.device_id) continue;
        if (!HUB_KEYS.has(entry.translation_key)) continue;
        if (!this._inScope(entry.device_id)) continue;
        if (hubs && !hubs.has(this._entryOf(entry.device_id))) continue;
        const device = devices[entry.device_id];
        const name = device && hubNameOf(device);
        if (name) return name;
      }
      return null;
    });
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
    if (blind.louvers) {
      // A Shutter has no rails: its one control is the louvers, which the cover exposes as
      // tilt -- their whole turn, 0 (shut) through 50 (horizontal) to 100.
      return [
        {
          key: "louvers",
          label: this._t("louvers"),
          short: this._t("louvers"),
          coverId: blind.bottomCover,
          numberId: null,
          louvers: true,
        },
      ];
    }
    // `short` is the word the status line has room for: "Middle" for "Middle rail". A label
    // set in the card's config is shortened to its first word, as before.
    const rail = (key, configured) => ({
      key,
      label: configured || this._t(`${key}_rail`),
      short: configured ? configured.split(" ")[0] : this._t(`${key}_short`),
    });
    const rails = [
      { ...rail("bottom", this._config.bottom_label), coverId: blind.bottomCover, numberId: blind.bottomNumber },
    ];
    if (blind.middleCover || blind.middleNumber) {
      rails.push({
        ...rail("middle", this._config.middle_label),
        coverId: blind.middleCover,
        numberId: blind.middleNumber,
      });
    }
    return rails;
  }

  /**
   * Where the hub says a rail is, and where it is sending it (equal when idle). While the two
   * differ, `until` is when the move window closes, and past it `stale` is set.
   *
   * The hub stores a new target whether or not the blind hears the command, and keeps both
   * values until the blind next reports in. So a target the blind has not been heard
   * reaching within MOVE_WINDOW_MS is no longer a move under way, but neither value can be
   * trusted: a blind sat at "100, heading for 0" for two hours on 2026-10-12, and had
   * closed. The rail's cover changes state whenever the hub reports a new position or target
   * for it, so its last_updated is when the move began, unless this card has written the
   * rail since. With neither (a state without timestamps), the move is taken as under way.
   */
  _railState(rail) {
    const cover = this._hass.states[rail.coverId];
    let current;
    let heading;
    if (rail.louvers) {
      const tilt = cover?.attributes?.current_tilt_position;
      current = tilt === undefined || tilt === null ? null : Number(tilt);
      heading = cover?.attributes?.target_tilt;
    } else {
      current = rail.numberId ? this._numberOf(rail.numberId) : null;
      if (current === null) {
        const position = cover?.attributes?.current_position;
        current = position === undefined || position === null ? null : Number(position);
      }
      heading = cover?.attributes?.target_position;
    }
    const target = heading === undefined || heading === null ? current : Number(heading);
    if (current === null || target === null || Math.round(current) === Math.round(target)) {
      return { current, target };
    }
    const updated = Date.parse(cover?.last_updated);
    const since = Math.max(
      Number.isNaN(updated) ? -Infinity : updated,
      this._sent.get(rail.numberId || rail.coverId)?.at ?? -Infinity,
    );
    if (since === -Infinity) return { current, target };
    const until = since + MOVE_WINDOW_MS;
    return Date.now() < until ? { current, target, until } : { current, target, stale: true };
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
    // Shown only in the sidebar panel where Home Assistant hides its sidebar (_wantsMenuButton).
    // It fires the same event as Home Assistant's own menu button, which opens the sidebar.
    this._menuButton = this._iconButton("mdi:menu", this._t("open_sidebar"), () =>
      this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true })),
    );
    this._menuButton.classList.add("menu");
    this._syncMenuButton();
    header.appendChild(this._menuButton);
    const titles = el("div", "titles");
    const text = el("div", "header-text", this._headingText());
    // Kept so the heading can follow a hub rename, or fill in once the device registry has
    // loaded -- _render() runs once, but the hub's name can arrive or change later.
    this._headerText = text;
    this._header = header;
    this._summary = el("div", "summary");
    // Over the view the counts go under the weather, large at the top of the page, not in the header.
    const overView = this._overView();
    titles.append(text, ...(overView ? [] : [this._summary]));
    header.appendChild(titles);
    const panel = this.hasAttribute("panel");
    // In the sidebar panel the header stays at the top as the page scrolls, so it keeps to one
    // line: the whole-house presets and scene groups go in a row of their own beneath it.
    const tools = panel ? el("div", "tools") : header;
    this._tools = panel ? tools : null;
    this._homeScenes = null;
    if (!this._config.hide_home_controls) {
      if (!this._config.hide_refresh) header.appendChild(this._buildHomeRefresh());
      tools.appendChild(this._buildHomeControls());
      // Filled with the hub's scene groups on every rebuild (_fillHomeScenes).
      this._homeScenes = el("div", "segmented home-scenes");
      this._homeScenes.hidden = true;
      tools.appendChild(this._homeScenes);
    }
    // In the sidebar panel, beside the refresh at the top: the page's settings, whose menu turns
    // the page to choosing each window's color or its divided lights (_setChoosing).
    this._toggleSettings(false);
    this._settings = null;
    this._settingsButton = null;
    this._settingsMenu = null;
    this._choiceItems = {};
    this._choiceBars = {};
    if (panel) header.appendChild(this._buildSettings());
    card.appendChild(header);
    this._hero = null;
    this._stopForecast();
    this._hours = null;
    if (overView) {
      // The temperature and the weather, from the weather entity the view follows; hidden
      // until there is one (_patchHero). Beside them the forecast, hidden until it comes
      // (_patchForecast). The house's counts go beneath. With the integration's weather option
      // off the panel passes `hide_weather` (frontend.py): only the counts are built, and with
      // no forecast list the forecast is never asked for.
      const hero = el("div", "hero");
      const now = el("div", "now");
      if (!this._config.hide_weather) {
        this._hero = { temp: el("div", "temp"), cond: el("div", "cond") };
        this._hero.temp.hidden = true;
        this._hero.cond.hidden = true;
        now.append(this._hero.temp, this._hero.cond);
      }
      now.append(this._summary);
      hero.appendChild(now);
      if (this._hero) {
        this._hours = el("ol", "hours");
        this._hours.setAttribute("aria-label", this._t("forecast"));
        this._hours.hidden = true;
        hero.appendChild(this._hours);
      }
      card.appendChild(hero);
    }
    if (tools !== header) card.appendChild(tools);
    for (const kind of Object.keys(this._choiceItems)) {
      this._choiceBars[kind] = this._buildChoiceBar(kind);
      card.appendChild(this._choiceBars[kind]);
    }

    this._body = el("div", "body");
    card.appendChild(this._body);
    // On a phone, the bar that goes to each room (_buildDock); filled with the rooms.
    this._unwatchScroll();
    this._tabs = [];
    this._dock = null;
    if (panel) {
      this._dock = el("nav", "rooms-bar");
      this._dock.setAttribute("aria-label", this._t("rooms"));
      this._dock.hidden = true;
      card.appendChild(this._dock);
    }
    // A new body has no rooms in it yet, so _update builds them whatever it last built.
    this._signature = undefined;
    this._inputs = null;
    this._markChoosing(card);

    this.shadowRoot.innerHTML = "";
    this.shadowRoot.appendChild(card);
    this._update();
  }

  _update() {
    if (!this._body || !this._hass) return;

    // Home Assistant sets `hass` on every state change in the house. When nothing the card draws
    // from has changed -- the registries, the sun, the theme, the sidebar, the language, and the
    // card's own entities (state objects are replaced, never mutated) -- there is nothing to do,
    // and it returns before regrouping its blinds.
    const hass = this._hass;
    // Over the view the card also says the weather, from the entity the view follows.
    const weather = this._hero && this._view?.weatherEntity ? hass.states[this._view.weatherEntity] : undefined;
    const inputs = [hass.entities, hass.devices, hass.areas, hass.states["sun.sun"], hass.themes?.darkMode,
      hass.dockedSidebar, this._language, weather];
    if (
      this._inputs &&
      this._seen &&
      inputs.every((input, index) => input === this._inputs[index]) &&
      this._watched.every((entityId, index) => hass.states[entityId] === this._seen[index])
    ) {
      return;
    }
    this._inputs = inputs;

    const sky = skyOf(this._hass.states["sun.sun"]);
    if (this._card.dataset.sky !== sky) this._card.dataset.sky = sky;
    const theme = this._hass.themes?.darkMode ? "dark" : "light";
    if (this._card.dataset.theme !== theme) this._card.dataset.theme = theme;

    if (this._headerText) {
      const title = this._headingText();
      if (this._headerText.textContent !== title) this._headerText.textContent = title;
      this._headerText.hidden = !title;
    }
    // The user can hide the sidebar from their profile, which arrives as a new hass.
    this._syncMenuButton();
    this._patchHero(weather);

    const rooms = this._roomsOf(this._collectBlinds());
    this._scenes = this._collectScenes();
    this._sceneGroups = this._collectSceneGroups();

    // Rebuild only when the set of blinds, a name, a blind's entities, or a room's scenes
    // change; otherwise patch values in place so a rail being dragged is never replaced under
    // the user's finger. The entity ids are in it because each tile is bound to them: an id
    // changed by "Recreate entity IDs", or an entity disabled or enabled, has to rebind it.
    const blindKey = (b) =>
      [b.deviceId, b.name, b.area, b.product, b.stack, b.louvers, b.bottomCover, b.middleCover,
        b.bottomNumber, b.middleNumber, b.battery, b.refresh, b.color, b.lights].join("/");
    const signature = rooms
      .map(
        ([room, list]) =>
          `${room}:${list.map(blindKey).join(",")}` +
          `:${(this._scenes.get(room) || []).map((scene) => `${scene.entityId}=${scene.name}`).join(",")}`,
      )
      .concat(this._sceneGroups.map((group) => `group ${group.entityId}=${group.name}`))
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
    this._sceneChips = [];
    this._roomLines = [];
    this._seen = null;
    this._watched = [
      ...rooms.flatMap(([, list]) =>
        list.flatMap((blind) => [
          blind.bottomCover,
          blind.middleCover,
          blind.bottomNumber,
          blind.middleNumber,
          blind.battery,
          // Its refresh button is greyed out while the Request status button is unavailable.
          blind.refresh,
          // Its color and its divided lights are drawn from their selects' states.
          blind.color,
          blind.lights,
        ]),
      ),
      // A scene's chip is greyed out while the scene is unavailable.
      ...rooms.flatMap(([room]) => (this._scenes?.get(room) || []).map((scene) => scene.entityId)),
      ...(this._sceneGroups || []).map((group) => group.entityId),
    ].filter(Boolean);
    this._fillHomeScenes();

    if (!rooms.length) {
      this._body.appendChild(el("div", "empty", this._t("empty")));
      this._syncPanes();
      this._syncChoosing();
      this._buildDock();
      return;
    }

    // With the headings hidden the rooms run together as one grid.
    const sections = this._config.hide_room_names
      ? [[null, rooms.flatMap(([, list]) => list)]]
      : rooms;
    // A wide card puts its rooms in columns; a single section keeps the whole width.
    this._body.classList.toggle("single", sections.length === 1);

    for (const [roomName, list] of sections) {
      const room = el("section", "room");
      const line = roomName !== null ? this._buildRoomHead(room, roomName, list) : null;

      const grid = el("div", this._config.hide_picture ? "list" : "grid");
      // The windows built from here on are this room's (_buildView).
      this._panes = [];
      const first = this._cells.length;
      for (const blind of list) grid.appendChild(this._buildBlind(blind));
      this._roomLines.push({ name: roomName, section: room, line, cells: this._cells.slice(first), photos: this._panes });
      room.appendChild(grid);
      this._body.appendChild(room);
    }
    this._syncPanes();
    this._syncChoosing();
    this._buildDock();
  }

  /**
   * A room's heading: its name and count, open/stop/close for the whole room, and a button
   * that folds out the app's three presets for the room, followed by the room's scenes and
   * its refresh.
   *
   * The presets go to exactly the blinds shown under the heading (_roomCommand), so they work
   * for an area renamed since, for blinds moved between areas, and for blinds in no area,
   * grouped under "Unassigned" or `default_room`.
   *
   * hide_room_presets takes the presets and scenes out of the tray, and hide_refresh the
   * refresh; the tray and its button are there while anything is left in it.
   */
  _buildRoomHead(room, roomName, blinds) {
    const head = el("div", "room-head");
    // Over the view each room is a pane of glass of its own, and says under its name how many
    // of its shades are open (_patchRoomLines).
    let line = null;
    if (this._overView()) {
      line = el("div", "room-line");
      const titles = el("div", "room-titles");
      titles.append(el("div", "room-name", roomName), line);
      head.appendChild(titles);
    } else {
      head.appendChild(el("div", "room-name", roomName));
    }
    room.appendChild(head);

    if (!this._config.hide_room_controls) {
      head.appendChild(this._buildRoomControls(roomName, blinds));
    }
    const runs = !this._config.hide_room_presets;
    const presets = runs ? this._buildRoomPresets(roomName, blinds) : null;
    const scenes = runs ? this._buildRoomScenes(roomName) : null;
    const refresh = this._config.hide_refresh ? null : this._buildRoomRefresh(roomName, blinds);
    if (!presets && !scenes && !refresh) return line;
    const tray = el("div", "tray");
    tray.hidden = true;
    for (const part of [presets, scenes, refresh]) if (part) tray.appendChild(part);
    const label = presets || scenes ? "room_presets" : "room_more";
    const more = this._iconButton("mdi:dots-horizontal", this._t(label, { room: roomName }), () => {
      tray.hidden = !tray.hidden;
      more.classList.toggle("open", !tray.hidden);
      more.setAttribute("aria-expanded", String(!tray.hidden));
    });
    more.className = "icon-btn more";
    more.setAttribute("aria-expanded", "false");
    head.appendChild(more);
    room.appendChild(tray);
    return line;
  }

  /**
   * Open / stop / close every blind in one room, both rails of a two-rail blind included.
   *
   * Open and close go through the covers, one per blind, so one hub command per blind: the
   * integration paces commands about 1.6 s apart, and a second command to the same blind only
   * holds the room's others back. Open goes to each blind's bottom rail, which takes a two-rail
   * blind's middle rail up with it, as the integration carries a rail the other would pass.
   * Close goes to a two-rail blind's middle rail, which takes the bottom rail down with it.
   *
   * Stop goes to the integration (norman.room_command) with the blinds shown here. One that
   * waited its turn per blind would reach the last of a room's blinds seconds late, so a whole
   * room of the hub's gets the room's one MotorStop, and only the rest a stop each -- a
   * Shutter none, as its louvers take no stop.
   *
   * This is NOT the hub's own room verb. Close here ends a two-rail blind at bottom 0 AND
   * middle 0 -- both rails down, which leaves the light-filtering sheer across the window.
   * The app's "Best privacy" is bottom 0 with middle 100: the sheer stacked away and the
   * blackout across the window instead. That one lives in the presets tray
   * (norman.room_command).
   */
  _buildRoomControls(roomName, blinds) {
    const controls = el("div", "icon-group room-buttons");
    for (const [icon, service, label] of ROOM_ACTIONS) {
      controls.appendChild(
        this._iconButton(icon, this._t(label, { room: roomName }), () => {
          if (service === "stop_cover") {
            // The integration stops a whole room of the hub's with the room's one MotorStop,
            // and only the rest blind by blind, so a stop never waits its turn per blind.
            this._roomCommand({ command: "stop" }, blinds, { targeted: true });
            return;
          }
          // One service call with a list, not one call per entity.
          const entityId = [];
          for (const blind of blinds) {
            const cover = service === "close_cover" ? blind.middleCover || blind.bottomCover : blind.bottomCover;
            if (cover) entityId.push(cover);
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
   * request per hub however many blinds there are -- the same three the app's "All Rooms"
   * screen sends. They carry the app's names rather than open/close arrows because they are
   * not open and close: "Best privacy" leaves a two-rail blind's middle rail fully OPEN.
   *
   * There is no house-wide Stop button. The hub accepted an unscoped MotorStop and stopped
   * one moving blind in a direct test, but stopping simultaneous motors across rooms has
   * not been verified. A room's Stop here still fans out through its covers.
   */
  _buildHomeControls() {
    const controls = el("div", "segmented home-buttons");
    for (const preset of PRESETS) {
      controls.appendChild(
        this._buildChip(preset.icon, this._t(preset.label), this._t("preset_every_room", { preset: this._t(preset.title) }), () => {
          // No `room`: the action omits RoomID, which the hub reads as every blind. Sent to
          // each hub with a blind on the card.
          this._roomCommand({ command: preset.command }, this._cells.map((cell) => cell.blind));
        }),
      );
    }
    return controls;
  }

  /**
   * The whole house's refresh, beside its presets: norman.room_command's refresh with no room,
   * which asks every blind on the hub to report in with one request -- to each hub with a
   * blind on the card. Nothing moves.
   */
  _buildHomeRefresh() {
    const group = el("div", "icon-group home-refresh");
    const button = this._iconButton(REFRESH_ICON, this._t("home_refresh"));
    this._bindRefresh(button, "home", () => {
      this._roomCommand({ command: "refresh" }, this._cells.map((cell) => cell.blind));
    });
    group.appendChild(button);
    return group;
  }

  /**
   * The hub's scene groups, after the whole-house presets: one chip each, which runs the group
   * -- room scenes in several rooms at once -- with every blind checked afterwards by the
   * integration. Empty and hidden when the hub has none.
   */
  _fillHomeScenes() {
    const box = this._homeScenes;
    if (!box) return;
    box.innerHTML = "";
    for (const group of this._sceneGroups || []) {
      const chip = this._buildChip(SCENE_ICON, group.name, group.name, () => {
        this._hass.callService("scene", "turn_on", { entity_id: group.entityId });
      });
      chip.dataset.entityId = group.entityId;
      (this._sceneChips ||= []).push(chip);
      box.appendChild(chip);
    }
    box.hidden = !box.children.length;
  }

  /**
   * The same three, for the blinds shown under one heading, via norman.room_command.
   *
   * The card groups blinds by Home Assistant area, which need not be a room of the hub's: an
   * area can be renamed, and a blind moved to another. So the presets name the blinds, not the
   * room. The integration sends a whole room of the hub's its one room-wide preset and each
   * other blind its own, so a preset reaches exactly the blinds it sits above.
   */
  _buildRoomPresets(roomName, blinds = []) {
    const presets = el("div", "segmented room-presets");
    for (const preset of PRESETS) {
      presets.appendChild(
        this._buildChip(preset.icon, this._t(preset.label), this._t("preset_in_room", { preset: this._t(preset.title), room: roomName }), () => {
          this._roomCommand({ command: preset.command }, blinds, { targeted: true });
        }),
      );
    }
    return presets;
  }

  /**
   * The room's scenes, saved in the Norman app: one chip each, which runs the scene. The
   * integration then watches every blind the scene moves. Null when the room has none, so a
   * room without scenes shows only its presets.
   */
  _buildRoomScenes(roomName) {
    const list = this._scenes?.get(roomName);
    if (!list?.length) return null;
    const group = el("div", "segmented room-scenes");
    for (const scene of list) {
      const title = this._t("preset_in_room", { preset: scene.name, room: roomName });
      const chip = this._buildChip(SCENE_ICON, scene.name, title, () => {
        this._hass.callService("scene", "turn_on", { entity_id: scene.entityId });
      });
      chip.dataset.entityId = scene.entityId;
      (this._sceneChips ||= []).push(chip);
      group.appendChild(chip);
    }
    return group;
  }

  /**
   * The room's refresh, after its presets and scenes: each of its blinds asked to report in,
   * and nothing moved. It presses their Request status buttons in one call -- the one status
   * request per blind the hub's own room refresh sends, but for exactly the blinds shown here,
   * so it needs neither a room of the hub's by the area's name nor a hub to route to. Null
   * when none of them has one.
   */
  _buildRoomRefresh(roomName, blinds) {
    if (!blinds.some((blind) => blind.refresh)) return null;
    const box = el("div", "segmented room-refresh");
    const chip = this._buildChip(REFRESH_ICON, this._t("refresh"), this._t("room_refresh", { room: roomName }));
    this._bindRefresh(chip, `room ${roomName}`, () => this._requestStatus(blinds));
    box.appendChild(chip);
    return box;
  }

  /**
   * norman.room_command, sent to this card's hub when it has one (`config_entry_id`). A card
   * with none shows every hub's blinds, and with two hubs the action cannot pick one itself,
   * so the card sends one call to each hub `blinds` are on, read from their devices.
   *
   * An unavailable blind does not count while others do: it may be on a hub that is not set
   * up, which the action refuses. With every one of them unavailable they all count, so the
   * call still names their hubs, and the action says what is wrong with them rather than
   * asking which hub was meant. With no hub to go on the action picks the only one, as it
   * always has.
   *
   * `targeted` sends the command to exactly `blinds`, named by their covers (the action's
   * `blinds`), rather than to every blind on each hub: a room's presets and its stop.
   */
  _roomCommand(data, blinds = [], { targeted = false } = {}) {
    const pinned = this._config.config_entry_id;
    if (targeted) {
      // Exactly these blinds, by their covers: one call per hub they are on.
      const byHub = new Map();
      for (const blind of blinds) {
        const hub = pinned || this._entryOf(blind.deviceId) || "";
        if (!byHub.has(hub)) byHub.set(hub, []);
        byHub.get(hub).push(blind.bottomCover);
      }
      for (const [hub, covers] of byHub) {
        this._hass.callService(DOMAIN, "room_command", { ...data, blinds: covers, ...(hub ? { config_entry_id: hub } : {}) });
      }
      return;
    }
    const hubsOf = (list) => [...new Set(list.map((blind) => this._entryOf(blind.deviceId)).filter(Boolean))];
    let hubs = pinned ? [pinned] : hubsOf(blinds.filter((blind) => !this._isUnavailable(blind)));
    if (!hubs.length) hubs = hubsOf(blinds);
    if (!hubs.length) {
      this._hass.callService(DOMAIN, "room_command", data);
      return;
    }
    for (const entryId of hubs) {
      this._hass.callService(DOMAIN, "room_command", { ...data, config_entry_id: entryId });
    }
  }

  /** Press the Request status button of each of `blinds` that has one, in one call. */
  _requestStatus(blinds) {
    const buttons = blinds.map((blind) => blind.refresh).filter(Boolean);
    if (!buttons.length) return;
    this._hass.callService("button", "press", { entity_id: buttons.length === 1 ? buttons[0] : buttons });
  }

  /**
   * Make `button` a refresh control: a press runs `send`, and its icon turns once to say the
   * request went. A second press of the same control (`key`) within REFRESH_HOLD_MS is
   * ignored, rebuilt or not, so repeats do not queue more requests at the hub.
   */
  _bindRefresh(button, key, send) {
    button.addEventListener("click", () => {
      const now = Date.now();
      if (now - (this._refreshedAt.get(key) ?? -Infinity) < REFRESH_HOLD_MS) return;
      this._refreshedAt.set(key, now);
      send();
      button.classList.add("spin");
      setTimeout(() => button.classList.remove("spin"), REFRESH_SPIN_MS);
    });
  }

  /**
   * A preset or a scene: an icon and a word, since "blinds-horizontal" alone does not say
   * "privacy". Without `onClick` the chip is left for the caller to bind (a refresh).
   */
  _buildChip(icon, text, title, onClick) {
    const chip = el("button", "chip");
    chip.type = "button";
    chip.append(haIcon(icon), el("span", null, text));
    chip.title = title;
    chip.setAttribute("aria-label", title);
    if (!onClick) return chip;
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
    if (onClick) button.addEventListener("click", onClick);
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
    name.title = this._t("blind_details", { name: blind.name });
    name.addEventListener("click", () => this._showMore(blind.bottomCover));

    const bottom = el("div", "meta-bottom");
    const status = el("span", "status");
    bottom.appendChild(status);

    let batteryEl = null;
    if (blind.battery && !this._config.hide_battery) {
      // A button, as it opens the battery's details: reachable by keyboard, and announced as one.
      batteryEl = el("button", "battery");
      batteryEl.type = "button";
      batteryEl.append(haIcon("mdi:battery"), el("span"));
      // A bare "84%" next to a blind reads as a position; the icon, title and aria-label
      // say it is the battery.
      batteryEl.addEventListener("click", () => this._showMore(blind.battery));
      bottom.appendChild(batteryEl);
    }

    // Beside the battery: the blind's Request status, which has it report in without moving.
    let refreshEl = null;
    if (blind.refresh && !this._config.hide_refresh) {
      refreshEl = this._iconButton(REFRESH_ICON, this._t("refresh_blind", { name: blind.name }));
      refreshEl.className = "refresh";
      this._bindRefresh(refreshEl, blind.refresh, () => this._requestStatus([blind]));
      bottom.appendChild(refreshEl);
    }

    const stop = el("button", "stop");
    stop.type = "button";
    stop.hidden = true;
    stop.title = this._t("stop_blind", { name: blind.name });
    stop.setAttribute("aria-label", stop.title);
    stop.append(haIcon("mdi:stop"), el("span", null, this._t("stop")));
    stop.addEventListener("click", () => this._stop(rails));
    // On the window's corner in the grid -- outside the window itself, so a press on it is
    // never taken for the start of a drag.
    (list ? bottom : tile).appendChild(stop);
    meta.append(name, bottom);
    tile.appendChild(meta);

    // In the list layout the rails are sliders, top rail first as on the blind.
    const sliders = list ? [...rails].reverse().map((rail) => this._buildSlider(blind, rails, rail)) : [];
    for (const slider of sliders) tile.appendChild(slider.row);

    const cell = { blind, rails, tile, shade, batteryEl, refreshEl, status, stop, sliders };
    // In the sidebar panel a window gets what choosing shows (_setChoosing), for each kind it
    // has to choose: a select over the window and the choice's name in place of its state, and
    // for a color a swatch at its corner. Hidden until then.
    cell.picks = {};
    cell.choiceNames = {};
    cell.colorBadge = null;
    if (shade && this._settings) {
      for (const [kind, { words }] of Object.entries(CHOICES)) {
        if (!this._choiceEntity(kind, blind)) continue;
        const pick = el("select", `pick ${kind}`);
        pick.setAttribute("aria-label", this._t(words.of, { name: blind.name }));
        for (const value of Object.keys(this._choicesOf(kind, blind))) {
          const option = el("option", null, this._t(`${words.option}${value}`));
          option.value = value;
          pick.appendChild(option);
        }
        pick.addEventListener("change", () => this._choose(cell, kind, pick.value));
        shade.element.appendChild(pick);
        const name = el("span", `choice-name ${kind}`);
        if (kind === "colors") name.appendChild(el("i"));
        name.appendChild(el("span"));
        bottom.appendChild(name);
        cell.picks[kind] = pick;
        cell.choiceNames[kind] = name;
      }
      if (cell.picks.colors) {
        cell.colorBadge = el("span", "color-badge");
        shade.element.appendChild(cell.colorBadge);
      }
    }
    this._cells.push(cell);
    return tile;
  }

  /**
   * The view through a blind's window: the sky, a line of hills, the glazing bars of its
   * divided lights and a glint on the glass. Over the panel's view (norman-view.js) the sky and
   * hills give way to a canvas, on which the view draws its photograph, moving. Returns the
   * view and the box its bars are laid in (_layBars).
   */
  _buildView(blind) {
    const view = el("div", "view");
    if (this._overView()) {
      const photo = el("canvas", "photo");
      photo.setAttribute("aria-hidden", "true");
      this._panes.push(photo);
      view.append(photo);
    }
    const bars = el("div", "bars");
    this._layBars(bars, this._lightsOf(blind));
    view.append(el("div", "sun"), el("div", "hills"), bars, el("div", "glint"));
    return { view, bars };
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
   *
   * A roller shade hangs plain fabric off a roll in place of the headrail, and the roll
   * grows as the shade winds up onto it. A Roman shade's panel folds up into a stack above
   * its hem. A PerfectSheer's vanes, between two sheers, slide up into a cassette.
   */
  _buildShade(blind, rails) {
    if (blind.louvers) return this._buildShutter(blind, rails);
    if (blind.product === "drape") return this._buildDrape(blind, rails);
    const { product } = blind;
    const roller = product === "roller";
    const element = el("div", product ? `win ${product}` : "win");
    element.setAttribute("role", "group");
    element.setAttribute("aria-label", blind.name);

    const frame = el("div", "frame");
    const opening = el("div", "opening");
    const { view, bars } = this._buildView(blind);

    const twoRail = rails.length > 1;
    const single = roller || product === "roman" ? product : "single";
    let bands = rails.map((_, index) =>
      el("div", `fabric ${twoRail ? (index === 1 ? "sheer" : "blackout") : single}`),
    );
    // A Roman shade's folds, bottom one first, drawn over the flat panel above them.
    const folds = product === "roman" ? Array.from({ length: ROMAN_SECTIONS }, () => el("div", "fabric fold")) : [];
    // A PerfectSheer's fabric is drawn at its full length and slides up out of sight into
    // the cassette, so it hangs in a clip below the cassette rather than as a band.
    let cloth = null;
    let vanes = [];
    if (product === "perfectsheer") {
      cloth = el("div", "cloth");
      vanes = Array.from({ length: SHEER_VANES }, (_, k) => {
        const vane = el("div", "vane");
        vane.style.top = `${round3((k / SHEER_VANES) * 100)}%`;
        vane.style.height = `${round3(100 / SHEER_VANES)}%`;
        return vane;
      });
      cloth.append(...vanes);
      const clip = el("div", "clip");
      clip.appendChild(cloth);
      bands = [clip];
    }
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
      // Where its rail's pull tab sits, for the finger-sized box a touch screen gets around it.
      zone.style.setProperty?.("--n-tab-x", `${this._tabX(rails, index)}%`);
      zone.setAttribute("role", "slider");
      zone.setAttribute("aria-orientation", "vertical");
      zone.setAttribute("aria-valuemin", "0");
      zone.setAttribute("aria-valuemax", "100");
      zone.setAttribute("aria-label", this._railName(blind, rails, rail));
      return zone;
    });
    const bubble = el("div", "bubble");

    const head = el("div", roller ? "roll" : "headrail");
    // Behind a roll, the top of the window's recess: no sky shows round the roll's ends.
    const jamb = roller ? el("div", "jamb") : null;
    const brackets = roller ? [el("div", "bracket left"), el("div", "bracket right")] : [];
    opening.append(view, ...bands, ...folds, ...markers, ...railEls, ...(jamb ? [jamb] : []), head, ...brackets, ...zones, bubble);
    frame.appendChild(opening);
    element.append(frame, el("div", "sill"));

    const shade = {
      element,
      opening,
      bars,
      bands,
      markers,
      railEls,
      zones,
      bubble,
      rails,
      product,
      roll: roller ? head : null,
      jamb,
      folds,
      cloth,
      vanes,
      dragValues: {},
    };
    this._bindShade(shade);
    return shade;
  }

  /**
   * A Shutter in its window: a painted frame of stiles and rails, a column of louvers, and
   * the tilt rod down their middle -- the rod is what the card drags, as a hand would.
   *
   * The louvers turn about their long axis, so how open they are is drawn as a rotation:
   * flat and overlapping when shut, nearly edge-on with the view between them when open.
   * Dragging the rod up on from horizontal turns them past it, leaning the other way (the
   * hub's Positions 0-2).
   */
  _buildShutter(blind, rails) {
    const element = el("div", "win shutter");
    element.setAttribute("role", "group");
    element.setAttribute("aria-label", blind.name);

    const frame = el("div", "frame");
    const opening = el("div", "opening");
    const { view, bars } = this._buildView(blind);

    const panel = el("div", "panel");
    const louverBox = el("div", "louvers");
    const louverEls = Array.from({ length: LOUVER_COUNT }, () => el("div", "louver"));
    louverBox.append(...louverEls);
    const rod = el("div", "rod");
    panel.append(louverBox, rod);

    const zone = el("div", "zone rod-zone");
    zone.tabIndex = 0;
    zone.dataset.index = "0";
    zone.setAttribute("role", "slider");
    zone.setAttribute("aria-orientation", "vertical");
    zone.setAttribute("aria-valuemin", "0");
    zone.setAttribute("aria-valuemax", "100");
    zone.setAttribute("aria-label", this._railName(blind, rails, rails[0]));
    const marker = el("div", "marker");
    const bubble = el("div", "bubble");

    opening.append(view, panel, zone, bubble);
    frame.appendChild(opening);
    element.append(frame, el("div", "sill"));

    const shade = {
      element,
      opening,
      bars,
      bands: [],
      markers: [marker],
      railEls: [rod],
      zones: [zone],
      bubble,
      rails,
      louverEls,
      louvers: true,
      dragValues: {},
    };
    this._bindShade(shade);
    return shade;
  }

  /**
   * A SmartDrape in its window: fabric vanes on a sheer, hung from a track to the sill and
   * drawn sideways -- gathered to the side it stacks to when open, spread across the window
   * when closed. A split drape parts in the middle and gathers to both sides.
   *
   * The leading edge is what the card drags, sideways. The vanes turn with the cover's tilt,
   * flat and overlapping when closed and nearly edge-on when open; turning them is the tilt
   * in the blind's more-info dialog, not a drag here.
   */
  _buildDrape(blind, rails) {
    const element = el("div", "win drape");
    element.setAttribute("role", "group");
    element.setAttribute("aria-label", blind.name);

    const frame = el("div", "frame");
    const opening = el("div", "opening");
    const { view, bars } = this._buildView(blind);

    const sides = STACK_SIDES[blind.stack] || STACK_SIDES.left;
    const hanging = el("div", "hanging");
    const parts = sides.map((side) => {
      const sheer = el("div", "sheer");
      const vanes = Array.from({ length: DRAPE_VANES / sides.length }, () => el("div", "vane"));
      hanging.append(sheer, ...vanes);
      const lead = el("div", `rail lead ${side}`);
      lead.dataset.index = "0";
      lead.appendChild(el("div", "tab"));
      const zone = el("div", "zone");
      zone.tabIndex = 0;
      zone.dataset.index = "0";
      zone.dataset.side = side;
      zone.setAttribute("role", "slider");
      zone.setAttribute("aria-orientation", "horizontal");
      zone.setAttribute("aria-valuemin", "0");
      zone.setAttribute("aria-valuemax", "100");
      zone.setAttribute("aria-label", sides.length > 1 ? this._t(`blind_${side}_half`, { name: blind.name }) : blind.name);
      return { side, sheer, vanes, lead, zone, marker: el("div", "marker") };
    });
    const bubble = el("div", "bubble");

    opening.append(
      view,
      hanging,
      ...parts.map((part) => part.marker),
      ...parts.map((part) => part.lead),
      el("div", "headrail"),
      ...parts.map((part) => part.zone),
      bubble,
    );
    frame.appendChild(opening);
    element.append(frame, el("div", "sill"));

    const shade = {
      element,
      opening,
      bars,
      bands: [],
      markers: parts.map((part) => part.marker),
      railEls: parts.map((part) => part.lead),
      zones: parts.map((part) => part.zone),
      bubble,
      rails,
      drape: true,
      parts,
      dragValues: {},
    };
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

    // A rail's elements: one, except a split drape's rail, which has a leading edge per half.
    const indexOf = (rail, i) => Number(rail.dataset?.index ?? i);
    const railElsAt = (index) => shade.railEls.filter((rail, i) => indexOf(rail, i) === index);
    const setHot = (index) => {
      shade.railEls.forEach((rail, i) => rail.classList.toggle("hot", indexOf(rail, i) === index));
    };
    // Which rail a press means: the nearest one, or -- where the two rails are together and
    // so equally near -- the one whose tab is on that side.
    const pick = (event) => {
      if (shade.drape) return 0;
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
      // While choosing, a press on the window is for its choice (_setChoosing).
      if (shade.disabled || press || this._choosing) return;
      if (event.pointerType === "mouse" && event.button !== 0) return;
      const onZone = event.target?.classList?.contains("zone");
      if (event.pointerType !== "mouse" && !onZone) return;
      const rect = opening.getBoundingClientRect();
      if (!rect.height) return;
      press = {
        id: event.pointerId,
        index: pick(event),
        x0: event.clientX,
        y0: event.clientY,
        rect,
        side: shade.drape ? this._drapeSideAt(shade, event, rect) : null,
        started: false,
        step: null,
        // A move the arrow keys were gathering on the dragged rail, taken over by the drag.
        keys: null,
      };
      // Arrow keys are ignored until the press ends (_onKey): the drag owns the blind's drawing.
      shade.pressing = true;
      shade.activeSide = press.side;
      element.setPointerCapture?.(event.pointerId);
      event.preventDefault();
    });

    element.addEventListener("pointermove", (event) => {
      if (!press) {
        if (event.pointerType === "mouse" && !shade.disabled && !this._choosing) setHot(pick(event));
        return;
      }
      if (event.pointerId !== press.id) return;
      const delta = shade.drape ? event.clientX - press.x0 : event.clientY - press.y0;
      if (!press.started) {
        if (Math.abs(delta) < DRAG_SLOP) return;
        press.started = true;
        // A move the arrow keys are still gathering cannot be left to its timer, which would go
        // off mid-drag. On the dragged rail the drag takes it over: it starts where the keys
        // left the rail, and its release is the one write. On the other rail it is sent now.
        if (shade.keyMove?.index === press.index) {
          press.keys = shade.keyMove;
          clearTimeout(shade.keyTimer);
          shade.keyTimer = null;
          shade.keyMove = null;
        } else {
          this._sendKeys(shade);
        }
        press.start = this._shadeValue(shade, press.index) ?? 0;
        press.travel = shade.drape
          ? (press.rect.width * this._drapeTravelPct(shade)) / 100
          : (press.rect.height * this._travelPct(shade)) / 100;
        element.classList.add("dragging");
        for (const rail of railElsAt(press.index)) rail.classList.add("held");
        setHot(press.index);
      }
      // Up opens a shade; a drape opens towards the side it gathers to.
      const sign = shade.drape && press.side === "right" ? 1 : -1;
      const value = clamp(press.start + sign * (delta / press.travel) * 100);
      this._dragTo(shade, press.index, value);
      const step = snapOf(shade.rails[press.index], value);
      this._showBubble(shade, press.index, step);
      if (press.step !== null && step !== press.step) navigator.vibrate?.(4);
      press.step = step;
    });

    const finish = (event, commit) => {
      if (!press || event.pointerId !== press.id) return;
      const { index, started, keys } = press;
      press = null;
      shade.pressing = false;
      element.releasePointerCapture?.(event.pointerId);
      element.classList.remove("dragging");
      for (const rail of railElsAt(index)) rail.classList.remove("held");
      if (event.pointerType !== "mouse") setHot(-1);
      this._hideBubble(shade);
      if (!started) return;
      const value = shade.dragValues[index];
      shade.dragValues = {};
      // A rail with no value is never written: clampToStep would make it 0 and close the blind.
      if (commit && value !== undefined) {
        this._move(shade.rails, index, snapOf(shade.rails[index], value));
      } else if (keys) {
        // The drag was called off, but the keys' move it took over still stands.
        this._move(shade.rails, keys.index, keys.value);
      }
      this._patch();
    };
    element.addEventListener("pointerup", (event) => finish(event, true));
    // A cancelled pointer (the browser took the gesture) puts the rail back where the hub, or
    // the arrow keys before the drag, had it.
    element.addEventListener("pointercancel", (event) => finish(event, false));
    element.addEventListener("pointerleave", (event) => {
      if (!press && event.pointerType === "mouse") setHot(-1);
    });

    shade.zones.forEach((zone, i) => {
      const index = indexOf(zone, i);
      const side = zone.dataset.side;
      zone.addEventListener("focus", () => {
        shade.activeSide = side;
        setHot(index);
      });
      zone.addEventListener("blur", () => setHot(-1));
      zone.addEventListener("keydown", (event) => this._onKey(shade, index, event, side));
    });
  }

  /**
   * Arrow keys move a rail a step, or a Shutter's louvers a stop; the write goes out once the
   * keys stop. On a drape the left and right arrows move its edge that way, so the one towards
   * its stack opens it.
   *
   * A blind gathers one rail's keys at a time: keys on its other rail first send the move
   * gathered so far, which would otherwise be dropped with the timer and the drawing it shares.
   * While a pointer is pressed on the blind its arrow keys only keep the page from scrolling:
   * the drag draws the blind, and its release sends it. A key held with Alt, Ctrl or Meta is
   * a shortcut of the browser's or the system's (Alt+Left is Back), so it is left to them.
   */
  _onKey(shade, index, event, side) {
    if (shade.disabled || event.altKey || event.ctrlKey || event.metaKey) return;
    const activeSide = shade.drape ? side || shade.parts[0].side : null;
    const across = shade.drape && activeSide !== "right" ? -1 : 1;
    // How many steps each key moves the rail; Home and End go all the way, to 0 and to 100.
    const moves = {
      ArrowUp: 1,
      ArrowRight: across,
      ArrowDown: -1,
      ArrowLeft: -across,
      PageUp: 3,
      PageDown: -3,
      Home: -100,
      End: 100,
    };
    if (!(event.key in moves)) return;
    event.preventDefault();
    if (shade.pressing) return;
    if (shade.drape) shade.activeSide = activeSide;
    if (shade.keyMove && shade.keyMove.index !== index) this._sendKeys(shade);
    const value = stepFrom(shade.rails[index], this._shadeValue(shade, index) ?? 0, moves[event.key]);
    this._dragTo(shade, index, value);
    this._showBubble(shade, index, value);
    // A screen reader says the new value now, not when the keys' move is sent.
    shade.zones.forEach((zone, i) => {
      if (Number(zone.dataset?.index ?? i) === index) this._sayValue(zone, value, Boolean(shade.louvers));
    });
    clearTimeout(shade.keyTimer);
    shade.keyMove = { index, value };
    shade.keyTimer = setTimeout(() => this._sendKeys(shade), KEY_COMMIT_MS);
  }

  /** Send the move the arrow keys have gathered on a blind, if there is one (see _onKey). */
  _sendKeys(shade) {
    const move = shade.keyMove;
    clearTimeout(shade.keyTimer);
    shade.keyTimer = null;
    shade.keyMove = null;
    if (!move) return;
    shade.dragValues = {};
    this._hideBubble(shade);
    this._move(shade.rails, move.index, move.value);
    this._patch();
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
   *
   * A rail already drawn at `value` is not sent there again, unless its move is not confirmed:
   * the blind may never have heard it, and sending it again starts a new move.
   */
  _move(rails, index, value) {
    const rail = rails[index];
    if (value === this._railValue(rail) && !this._railState(rail).stale) return;
    const carried = this._carried(rails, index, value);
    let undoCarried = null;
    if (carried !== null && carried !== this._railValue(rails[1 - index])) {
      undoCarried = this._expect(rails[1 - index], carried);
    }
    this._setRail(rail, value, undoCarried);
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

  /** How thick a roller shade's roll is at `value`, in percent of the opening's height. */
  _rollSize(value) {
    return ROLL_MIN_PCT + ((ROLL_MAX_PCT - ROLL_MIN_PCT) * clamp(value ?? 0)) / 100;
  }

  /** How much of the window one side of a drape spans: all of it, or half when split. */
  _drapeSpan(shade) {
    return shade.parts.length > 1 ? 50 : 100;
  }

  /** How far a drape's edge travels, in percent of the opening's width: its span, less its stack. */
  _drapeTravelPct(shade) {
    const span = this._drapeSpan(shade);
    return span - (DRAPE_STACK_PCT * span) / 100;
  }

  /** How far a drape reaches from the side it gathers to at `value` (100 open, 0 drawn). */
  _drapeReach(shade, value) {
    const span = this._drapeSpan(shade);
    const gathered = (DRAPE_STACK_PCT * span) / 100;
    return gathered + ((100 - clamp(value ?? 0)) / 100) * this._drapeTravelPct(shade);
  }

  /** Where one side's leading edge is, in percent across the opening. */
  _drapeEdge(part, reach) {
    return part.side === "left" ? reach : 100 - reach;
  }

  /** Which side of a drape a press takes hold of: its own, or on a split drape the nearer. */
  _drapeSideAt(shade, event, rect) {
    const own = event.target?.dataset?.side;
    if (own) return own;
    if (shade.parts.length === 1) return shade.parts[0].side;
    return event.clientX - rect.left < rect.width / 2 ? "left" : "right";
  }

  /** How open a drape's or a PerfectSheer's vanes are drawn, 0 to 1: where the cover's tilt is heading. */
  _vanesOpen(shade) {
    const attributes = this._hass?.states?.[shade.rails[0].coverId]?.attributes || {};
    const tilt = attributes.target_tilt ?? attributes.current_tilt_position;
    return tilt === undefined || tilt === null ? 0 : clamp(Number(tilt) || 0) / 100;
  }

  /** The distance a rail travels, as a percentage of the opening: what the rails leave. */
  _travelPct(shade) {
    if (shade.louvers) return LOUVER_TRAVEL_PCT;
    return 100 - SHADE_HEAD_PCT - this._stackPct(shade) - shade.rails.length * SHADE_RAIL_PCT;
  }

  /** What stays below the headrail with the shade fully up: a Roman shade's folds, else nothing. */
  _stackPct(shade) {
    return shade.product === "roman" ? ROMAN_STACK_PCT : 0;
  }

  /**
   * Where a rail's top edge sits, in percent down the opening. Open (100) is tucked under
   * the headrail -- or under the middle rail, for the bottom rail of a two-rail blind, and
   * under its folds for a Roman shade -- and closed (0) rests on the sill.
   */
  _railTop(shade, index, value) {
    const above = shade.rails.length - 1 - index;
    const position = value === null || value === undefined ? 0 : value;
    return (
      SHADE_HEAD_PCT +
      this._stackPct(shade) +
      above * SHADE_RAIL_PCT +
      ((100 - position) / 100) * this._travelPct(shade)
    );
  }

  /**
   * How a Roman shade's folds hang at `value`: how many sections are folded (a fraction
   * while one is still folding) and how deep each fold is. A fold takes up a section of the
   * panel and, hanging loose, is half a section deep; once every section is folded they
   * pack tighter, to ROMAN_STACK_PCT all told with the shade fully up. The hem rises evenly
   * all the while, so it stays under the pointer.
   */
  _romanFolds(value) {
    const length = 100 - SHADE_HEAD_PCT - SHADE_RAIL_PCT;
    const section = length / ROMAN_SECTIONS;
    const raised = (clamp(value ?? 0) / 100) * (length - ROMAN_STACK_PCT);
    const loose = raised / (section / 2);
    if (loose <= ROMAN_SECTIONS) return { count: loose, depth: section / 2 };
    return { count: ROMAN_SECTIONS, depth: section - raised / ROMAN_SECTIONS };
  }

  /**
   * Hang a Roman shade's folds above its hem at `hem`, bottom fold first, and cut the flat
   * panel off where they begin. The fold still forming is the top one, where the stack
   * takes up the panel above it. The panel keeps its full length, so its seams stay at the
   * battens; it is clipped rather than shortened.
   */
  _drawFolds(shade, hem) {
    const { count, depth } = this._romanFolds(this._shadeValue(shade, 0));
    const length = 100 - SHADE_HEAD_PCT - SHADE_RAIL_PCT;
    const flat = Math.max(0, hem - count * depth - SHADE_HEAD_PCT);
    const shown = Math.min(length, flat + ROMAN_LAP_PCT);
    shade.bands[0].style.clipPath = `inset(0 0 ${round3(100 - (shown / length) * 100)}% 0)`;
    shade.folds.forEach((fold, k) => {
      fold.style.top = `${round3(hem - Math.min(count, k + 1) * depth)}%`;
      fold.style.height = `${round3(clamp(count - k, 0, 1) * depth)}%`;
    });
  }

  /**
   * Hang a PerfectSheer's fabric from the cassette to its bottom rail at `top`. It rolls up
   * into the cassette, so it slides up at its full length rather than shortening. Its vanes
   * open only with the shade fully down; anywhere else they are drawn closed.
   */
  _drawCloth(shade, top) {
    const length = 100 - SHADE_HEAD_PCT - SHADE_RAIL_PCT;
    const clip = 100 - SHADE_HEAD_PCT;
    shade.cloth.style.top = `${round3(((top - SHADE_HEAD_PCT - length) / clip) * 100)}%`;
    shade.cloth.style.height = `${round3((length / clip) * 100)}%`;
    const open = (this._shadeValue(shade, 0) ?? 0) <= 0 ? this._vanesOpen(shade) : 0;
    const band = round3(1 - (1 - SHEER_VANE_OPEN) * open);
    for (const vane of shade.vanes) vane.style.transform = `scaleY(${band})`;
  }

  /**
   * Place every band, rail and grab zone of one picture in a single pass, top rail first:
   * each band hangs from the edge above it (the headrail, or the rail above) to its rail.
   */
  _drawShade(shade) {
    if (shade.louvers) {
      this._drawLouvers(shade);
      return;
    }
    if (shade.drape) {
      this._drawDrape(shade);
      return;
    }
    if (shade.rails.length > 1) {
      const together = this._shadeValue(shade, 1) - this._shadeValue(shade, 0) < 1;
      shade.element.classList.toggle("stacked", together);
    }
    let edge = SHADE_HEAD_PCT;
    if (shade.roll) {
      // The fabric comes off the underside of the roll, which winds up as the shade rises.
      const size = this._rollSize(this._shadeValue(shade, 0));
      shade.roll.style.height = `${round3(size)}%`;
      edge = ROLL_TOP_PCT + size / 2;
      shade.jamb.style.height = `${round3(edge)}%`;
    }
    for (let index = shade.rails.length - 1; index >= 0; index -= 1) {
      const top = this._railTop(shade, index, this._shadeValue(shade, index));
      const band = shade.bands[index];
      if (shade.product === "roman") {
        this._drawFolds(shade, top);
      } else if (shade.product === "perfectsheer") {
        this._drawCloth(shade, top);
      } else {
        band.style.top = `${round3(edge)}%`;
        band.style.height = `${round3(Math.max(0, top - edge))}%`;
      }
      shade.railEls[index].style.top = `${round3(top)}%`;
      shade.zones[index].style.top = `${round3(top + SHADE_RAIL_PCT / 2)}%`;
      edge = top + SHADE_RAIL_PCT;
    }
  }

  /**
   * Turn every louver to where the Shutter is drawn in its turn: flat when shut, nearly
   * edge-on at horizontal (tilt 50), and past it leaning the other way, back towards flat, to
   * a step short of shut at Position 0 (tilt 100). The tilt rod rides with them, a little
   * lower as they open.
   */
  _drawLouvers(shade) {
    const { open, lean } = louverTurn(this._shadeValue(shade, 0) ?? 0);
    const angle = round3(lean * open * LOUVER_OPEN_DEG);
    for (const louver of shade.louverEls) louver.style.transform = `rotateX(${angle}deg)`;
    shade.railEls[0].style.transform = `translate(-50%, ${round3(open * 6)}%)`;
    shade.element.classList.toggle("shut", open <= 0);
  }

  /**
   * Spread a drape's vanes from the side it gathers to out to its edge, evenly, and turn them
   * to how open they are. Gathered, they overlap into a stack; drawn, they close up edge to
   * edge with a little overlap, as the fabric does.
   */
  _drawDrape(shade) {
    const reach = this._drapeReach(shade, this._shadeValue(shade, 0));
    const angle = round3(this._vanesOpen(shade) * VANE_OPEN_DEG);
    for (const part of shade.parts) {
      const count = part.vanes.length;
      const width = (this._drapeSpan(shade) / count) * DRAPE_VANE_OVERLAP;
      part.vanes.forEach((vane, k) => {
        const along = ((k + 0.5) / count) * reach;
        const centre = part.side === "left" ? along : 100 - along;
        vane.style.left = `${round3(centre - width / 2)}%`;
        vane.style.width = `${round3(width)}%`;
        vane.style.transform = `rotateY(${angle}deg)`;
      });
      const edge = this._drapeEdge(part, reach);
      part.sheer.style.left = `${round3(part.side === "left" ? 0 : edge)}%`;
      part.sheer.style.width = `${round3(reach)}%`;
      part.lead.style.left = `${round3(edge)}%`;
      part.zone.style.left = `${round3(edge)}%`;
    }
    shade.element.classList.toggle("drawn", (this._shadeValue(shade, 0) ?? 0) <= 0);
  }

  _showBubble(shade, index, value) {
    const { bubble } = shade;
    if (shade.drape) {
      const part = shade.parts.find((each) => each.side === shade.activeSide) || shade.parts[0];
      bubble.textContent = this._pct(value);
      bubble.style.top = "42%";
      bubble.style.left = `${round3(this._drapeEdge(part, this._drapeReach(shade, this._shadeValue(shade, index))))}%`;
      bubble.classList.add("on");
      return;
    }
    bubble.textContent = this._pct(value);
    bubble.style.top = shade.louvers
      ? "50%"
      : `${round3(this._railTop(shade, index, this._shadeValue(shade, index)))}%`;
    bubble.style.left = `${this._tabX(shade.rails, index)}%`;
    bubble.classList.add("on");
  }

  _hideBubble(shade) {
    shade.bubble.classList.remove("on");
  }

  /**
   * What a rail's control is called for assistive technology, the same on the picture and in
   * the list: the blind's name, with the rail's on a two-rail blind and "louvers" on a
   * Shutter, so each control on the card is told apart from the others.
   */
  _railName(blind, rails, rail) {
    if (rail.louvers) return this._t("blind_louvers", { name: blind.name });
    return rails.length > 1 ? this._t("blind_rail", { name: blind.name, rail: rail.label }) : blind.name;
  }

  /** The list layout's control for one rail of `blind`: a plain range input, in 10% steps or louver stops. */
  _buildSlider(blind, rails, rail) {
    const row = el("label", "slider");
    const label = el("span", "slider-label", rail.louvers || rails.length > 1 ? rail.short : this._t("position"));
    const input = el("input");
    input.type = "range";
    input.min = "0";
    input.max = String(sliderMax(rail));
    input.step = rail.louvers ? "1" : String(STEP);
    input.setAttribute("aria-label", this._railName(blind, rails, rail));
    const value = el("span", "slider-value");
    // `holding` while a pointer is down on it and `keyTimer` while arrow keys are gathering a
    // move: _patchSlider leaves the slider alone for both. `keys` when a key moved it last, and
    // `keyMove` the position the keys have gathered until it is sent. `moved` once the held
    // pointer has moved it.
    const slider = { rail, row, input, value, holding: false, moved: false, keys: false, keyTimer: null, keyMove: null };
    // A blind that has gone unavailable takes no write, and its slider goes back to the hub's value.
    const send = (position) => {
      clearTimeout(slider.keyTimer);
      slider.keyTimer = null;
      slider.keyMove = null;
      if (!this._isUnavailable(blind)) this._move(rails, rails.indexOf(rail), position);
      this._patch();
    };
    input.addEventListener("pointerdown", () => {
      slider.holding = true;
      slider.moved = false;
      slider.keys = false;
      slider.pressedAt = input.value;
      // A move the keys are still gathering waits on the press, which sends it or its own.
      clearTimeout(slider.keyTimer);
      slider.keyTimer = null;
    });
    // A press can end without a `change`: a tap on the thumb, a drag back to where it began,
    // or a touch the browser takes for a scroll (pointercancel). So the hold ends however the
    // press does. A press that moved the slider has a `change` coming, which sends it in place
    // of any move the keys gathered. Any other press -- and any on a blind gone unavailable,
    // whose `change` sends nothing -- sends the keys' move if there is one, or else catches the
    // slider up with the hub at once. A drag back to where it began sends that position on a
    // rail whose move is not confirmed, as a drag of the picture does: it is the one way to
    // send the blind the position it is drawn at again (see _move).
    const release = (cancelled) => {
      if (!slider.holding) return;
      slider.holding = false;
      const unavailable = this._isUnavailable(blind);
      if (!cancelled && !unavailable && input.value !== slider.pressedAt) return;
      const resend = !cancelled && !unavailable && slider.moved && this._railState(rail).stale;
      if (slider.keyMove !== null) send(slider.keyMove);
      else if (resend) send(sliderPosition(rail, input.value));
      else this._patchSlider(slider, unavailable);
    };
    input.addEventListener("pointerup", () => release(false));
    input.addEventListener("pointercancel", () => release(true));
    input.addEventListener("lostpointercapture", () => release(false));
    input.addEventListener("blur", () => release(false));
    // A range input fires `change` on every arrow key, so keyed changes are gathered into one
    // write as on the picture (KEY_COMMIT_MS); a pointer's is sent on release.
    input.addEventListener("keydown", () => {
      slider.keys = true;
    });
    input.addEventListener("input", () => {
      if (slider.holding) slider.moved = true;
      value.textContent = this._pct(sliderPosition(rail, input.value));
      input.style.setProperty?.("--n-fill", `${round3((100 * Number(input.value)) / sliderMax(rail))}%`);
    });
    input.addEventListener("change", () => {
      const position = sliderPosition(rail, input.value);
      slider.holding = false;
      if (!slider.keys) {
        send(position);
        return;
      }
      clearTimeout(slider.keyTimer);
      slider.keyMove = position;
      slider.keyTimer = setTimeout(() => send(position), KEY_COMMIT_MS);
    });
    row.append(label, input, value);
    return slider;
  }

  // ---- writing ---------------------------------------------------------------------

  /**
   * Draw a rail at `position` until the hub reports it as the rail's target. Past
   * PENDING_MS the hub's own value is shown again, so a move that never happened shows.
   *
   * Returns a function that takes the expectation back, for a call that failed: the rail is
   * drawn where the hub has it again, and its move window is the one it had before (see
   * _railState), so a write that never left Home Assistant does not read as a move.
   */
  _expect(rail, position) {
    const key = rail.numberId || rail.coverId;
    const entry = { value: position, at: Date.now() };
    const before = this._sent.get(key);
    this._pending.set(key, entry);
    this._sent.set(key, entry);
    setTimeout(() => {
      if (this._pending.get(key) !== entry) return;
      this._pending.delete(key);
      this._patch();
    }, PENDING_MS);
    return () => {
      if (this._pending.get(key) === entry) this._pending.delete(key);
      // Unless a later write to the rail has taken its place.
      if (this._sent.get(key) !== entry) return;
      if (before === undefined) this._sent.delete(key);
      else this._sent.set(key, before);
    };
  }

  /**
   * Write a rail position, preferring the number entity so the 10% step is enforced.
   * `undoCarried` takes back the other rail's expectation when this write carries it along.
   */
  _setRail(rail, position, undoCarried = null) {
    const undo = this._expect(rail, position);
    let call;
    if (rail.louvers) {
      call = this._hass.callService("cover", "set_cover_tilt_position", {
        entity_id: rail.coverId,
        tilt_position: position,
      });
    } else if (rail.numberId) {
      call = this._hass.callService("number", "set_value", { entity_id: rail.numberId, value: position });
    } else {
      call = this._hass.callService("cover", "set_cover_position", { entity_id: rail.coverId, position });
    }
    // A failed call is reported by Home Assistant. The picture goes back to the hub's values,
    // the carried rail's included, and the status to what it said before the write.
    Promise.resolve(call).catch(() => {
      undo();
      undoCarried?.();
      this._patch();
    });
  }

  /** Call a cover service on the rail's own entity -- never the blind's bottom rail. */
  _coverService(rail, service) {
    if (rail.coverId) this._hass.callService("cover", service, { entity_id: rail.coverId });
  }

  /**
   * Stop this blind. Its rails share one motor, so one call on a moving rail stops them all;
   * a second would only queue behind it at the hub's pace.
   */
  _stop(rails) {
    const moving = rails.find((rail) => {
      const { current, target, stale } = this._railState(rail);
      return !stale && current !== null && target !== null && Math.round(current) !== Math.round(target);
    });
    for (const rail of rails) this._pending.delete(rail.numberId || rail.coverId);
    this._coverService(moving || rails[0], "stop_cover");
    this._patch();
  }

  // ---- patching --------------------------------------------------------------------

  _patch() {
    if (!this._cells || !this._hass) return;
    const isOff = (entityId) => {
      const state = this._hass.states[entityId];
      return !state || state.state === "unavailable";
    };
    for (const chip of this._sceneChips || []) {
      const off = isOff(chip.dataset.entityId);
      if (chip.disabled !== off) chip.disabled = off;
    }
    let open = 0;
    let moving = 0;
    let lowBattery = 0;
    let settles = Infinity;

    for (const cell of this._cells) {
      const { blind, rails, shade } = cell;
      const unavailable = this._isUnavailable(blind);
      cell.tile.classList.toggle("unavailable", unavailable);

      const states = rails.map((rail) => {
        const state = this._railState(rail);
        if (state.until) settles = Math.min(settles, state.until);
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
            !state.stale &&
            state.current !== null &&
            shown !== null &&
            Math.round(shown) !== Math.round(state.current),
          unconfirmed: !unavailable && Boolean(state.stale),
        };
      });

      if (shade) {
        this._patchShade(shade, states, unavailable);
        this._paintColor(cell);
        this._paintLights(cell);
      }
      for (const slider of cell.sliders) this._patchSlider(slider, unavailable);

      setText(cell.status, this._statusOf(rails, states, unavailable));
      const isMoving = states.some((state) => state.moving);
      const unconfirmed = states.some((state) => state.unconfirmed);
      cell.status.classList.toggle("moving", isMoving);
      cell.status.classList.toggle("rest", !isMoving && !unconfirmed && !unavailable);
      // A Shutter's louvers turn in a moment and take no stop.
      const noStop = !isMoving || Boolean(blind.louvers);
      if (cell.stop.hidden !== noStop) cell.stop.hidden = noStop;

      cell.low = false;
      if (cell.batteryEl) {
        const battery = cell.batteryEl;
        const level = this._numberOf(blind.battery);
        const kind = batteryClass(level);
        if (battery.className !== `battery ${kind}`) battery.className = `battery ${kind}`;
        setAttr(battery.firstChild, "icon", batteryIcon(level));
        const shown = level === null ? "—" : this._pct(level);
        setText(battery.lastChild, shown);
        const title = level === null ? this._t("battery_unknown") : this._t("battery", { value: shown });
        if (battery.title !== title) battery.title = title;
        setAttr(battery, "aria-label", title);
        cell.low = kind === "low" || kind === "critical";
        if (cell.low) lowBattery += 1;
      }
      if (cell.refreshEl) {
        // Greyed out while the blind's Request status button is unavailable, as it is with the blind.
        const off = isOff(blind.refresh);
        if (cell.refreshEl.disabled !== off) cell.refreshEl.disabled = off;
      }

      cell.open = (states[0].shown ?? 0) > 0;
      cell.moving = isMoving;
      if (cell.open) open += 1;
      if (isMoving) moving += 1;
    }

    this._patchSummary(this._cells.length, open, moving, lowBattery);
    this._patchRoomLines();

    // Redraw when the next move window closes, even if no state changes by then: a blind that
    // missed its move should stop reading "Closing" on time, not at the next update.
    clearTimeout(this._settleTimer);
    this._settleTimer = Number.isFinite(settles)
      ? setTimeout(() => this._patch(), Math.max(0, settles - Date.now()) + 100)
      : null;
  }

  _patchShade(shade, states, unavailable) {
    shade.disabled = unavailable;
    shade.element.classList.toggle("disabled", unavailable);
    this._drawShade(shade);
    if (shade.drape) {
      // One rail, drawn at a leading edge per side: each side gets the marker and the state.
      const [state] = states;
      const showMarker = (state.moving || state.unconfirmed) && shade.dragValues[0] === undefined;
      const reach = showMarker ? this._drapeReach(shade, state.current) : 0;
      const value = Math.round(this._shadeValue(shade, 0) ?? 0);
      for (const part of shade.parts) {
        part.marker.classList.toggle("on", showMarker);
        if (showMarker) part.marker.style.left = `${round3(this._drapeEdge(part, reach))}%`;
        part.lead.classList.toggle("moving", state.moving);
        this._sayValue(part.zone, value);
        setAttr(part.zone, "aria-disabled", String(unavailable));
      }
      return;
    }
    states.forEach((state, index) => {
      const held = shade.dragValues[index] !== undefined;
      const marker = shade.markers[index];
      const showMarker = (state.moving || state.unconfirmed) && !held && !shade.louvers;
      marker.classList.toggle("on", showMarker);
      if (showMarker) {
        marker.style.top = `${round3(this._railTop(shade, index, state.current) + SHADE_RAIL_PCT / 2)}%`;
      }
      shade.railEls[index].classList.toggle("moving", state.moving);
      const zone = shade.zones[index];
      this._sayValue(zone, Math.round(this._shadeValue(shade, index) ?? 0), Boolean(shade.louvers));
      setAttr(zone, "aria-disabled", String(unavailable));
    });
  }

  /** Where a rail's grab zone says the rail is, to assistive technology; a Shutter's in its words. */
  _sayValue(zone, value, louvers = false) {
    setAttr(zone, "aria-valuenow", String(value));
    setAttr(zone, "aria-valuetext", louvers ? this._louverWords(value) : this._t("percent_open", { value }));
  }

  /**
   * A Shutter's louvers in a word or two: "Closed" shut, "Open" horizontal, otherwise the
   * tilt -- not how open they are, which past horizontal falls as the tilt rises.
   */
  _louverWords(tilt) {
    const value = Math.round(tilt);
    if (value <= 0) return this._t("closed");
    if (value === LOUVER_HORIZONTAL) return this._t("open");
    return this._t("tilt_percent", { value });
  }

  _patchSlider(slider, unavailable) {
    const { rail, input, value } = slider;
    // Nothing changes under a pointer that holds the slider -- not even `disabled`, as Chromium
    // fires `change` on a held range input it disables, which would send the half-dragged value.
    // The press's end patches it (_buildSlider).
    if (slider.holding) return;
    if (input.disabled !== unavailable) input.disabled = unavailable;
    if (slider.keyTimer) return;
    const shown = this._railValue(rail);
    const position = sliderValueOf(rail, shown ?? 0);
    if (input.value !== position) input.value = position;
    // A rail's fill shows where the hub has it; a Shutter's, the stop its thumb is on.
    const fill = rail.louvers ? `${round3((100 * Number(position)) / sliderMax(rail))}%` : `${shown ?? 0}%`;
    if (input.style.getPropertyValue?.("--n-fill") !== fill) input.style.setProperty?.("--n-fill", fill);
    setText(value, shown === null ? "—" : this._pct(shown));
  }

  /**
   * A blind's state in a few words. At rest: "Open", "Closed", "60% open" -- or, on a
   * two-rail blind, "Privacy" for the app's preset and both rails otherwise, and on a Shutter
   * "Tilt 25%" between shut and horizontal. On the move: which way, and where it has got to;
   * a Shutter's louvers open turning towards horizontal, from either side.
   */
  _statusOf(rails, states, unavailable) {
    if (unavailable) return this._t("unavailable");
    const travelling = states.findIndex((state) => state.moving);
    if (travelling >= 0) {
      const { current, shown } = states[travelling];
      const opening = rails[travelling].louvers
        ? louverTurn(shown).open > louverTurn(current).open
        : shown > current;
      const verb = opening ? "opening" : "closing";
      const value = Math.round(current);
      return rails.length > 1
        ? this._t(`${verb}_rail`, { rail: rails[travelling].short, value })
        : this._t(verb, { value });
    }
    // Drawn where it was sent, with the marker where the hub last heard it.
    if (states.some((state) => state.unconfirmed)) return this._t("unconfirmed");
    const [bottom, middle] = states.map((state) => (state.shown === null ? null : Math.round(state.shown)));
    if (bottom === null) return this._t("position_unknown");
    if (rails[0].louvers) return this._louverWords(bottom);
    if (rails.length < 2 || middle === null) {
      if (bottom >= 100) return this._t("open");
      if (bottom <= 0) return this._t("closed");
      return this._t("percent_open", { value: bottom });
    }
    if (bottom >= 100 && middle >= 100) return this._t("open");
    if (bottom <= 0 && middle <= 0) return this._t("closed");
    if (bottom <= 0 && middle >= 100) return this._t("privacy");
    return this._t("two_rails", { middle_rail: rails[1].short, middle, bottom_rail: rails[0].short, bottom });
  }

  _patchSummary(total, open, moving, lowBattery) {
    if (this._summary) this._fillCounts(this._summary, total, open, moving, lowBattery);
  }

  /**
   * "12 shades · 9 open · 1 moving · 2 low batteries" in `line`, rewritten only when it changes.
   * A room's line leaves the count out (`counted` false): its windows are right beneath it.
   */
  _fillCounts(line, total, open, moving, lowBattery, counted = true) {
    const parts = counted ? [[this._t("shades", { count: total }), ""]] : [];
    if (total) {
      if (open === 0) parts.push([this._t("all_closed"), ""]);
      else if (open === total) parts.push([this._t(total === 1 ? "one_open" : "all_open"), ""]);
      else parts.push([this._t("some_open", { count: open }), ""]);
    }
    if (moving) parts.push([this._t("moving", { count: moving }), "live"]);
    if (lowBattery) parts.push([this._t("low_battery", { count: lowBattery }), "warn"]);

    const key = parts.map((part) => part.join(":")).join("|");
    if (line.dataset.key === key) return;
    line.dataset.key = key;
    line.innerHTML = "";
    parts.forEach(([text, kind], index) => {
      if (index) line.appendChild(el("span", "sep", " · "));
      line.appendChild(el("span", kind || null, text));
    });
  }

  /**
   * Over the view, each room's own counts under its name; and on the rooms bar, a dot for a room
   * with a shade moving or one with a low battery, said in the button's name as well.
   */
  _patchRoomLines() {
    for (const { line, cells } of this._roomLines) {
      if (!line) continue;
      const count = (test) => cells.filter(test).length;
      this._fillCounts(line, cells.length, count((cell) => cell.open), count((cell) => cell.moving), 0, false);
    }
    for (const tab of this._tabs) {
      if (!tab.room) continue;
      const moving = tab.room.cells.filter((cell) => cell.moving).length;
      const low = tab.room.cells.filter((cell) => cell.low).length;
      if (tab.live.hidden !== !moving) tab.live.hidden = !moving;
      if (tab.warn.hidden !== !low) tab.warn.hidden = !low;
      const said = [
        tab.room.name,
        moving ? this._t("moving", { count: moving }) : null,
        low ? this._t("low_battery", { count: low }) : null,
      ].filter(Boolean).join(" · ");
      setAttr(tab.button, "aria-label", said);
      if (tab.button.title !== said) tab.button.title = said;
    }
  }

  /**
   * Over the view, the temperature and the weather under the heading, from the weather entity
   * the view follows: "67°" and "Partly cloudy", in Home Assistant's own words for the state.
   * Hidden while there is no such entity, or it has nothing to say.
   */
  _patchHero(weather) {
    if (!this._hero) return;
    const { temp, cond } = this._hero;
    const known = Boolean(weather) && !["unavailable", "unknown"].includes(weather.state);
    const degrees = known ? Number(weather.attributes?.temperature) : NaN;
    temp.hidden = Number.isNaN(degrees);
    if (!temp.hidden) setText(temp, `${Math.round(degrees)}°`);
    cond.hidden = !known;
    if (known) setText(cond, this._hass.formatEntityState?.(weather) ?? weather.state);
    this._syncForecast();
    this._patchForecast();
  }

  // ---- the forecast ---------------------------------------------------------------------------

  /**
   * Over the view, hear the forecast of the weather entity the view follows: Home Assistant's
   * weather/subscribe_forecast, which sends it now and again whenever it changes. Hourly where
   * the entity has it (its supported features say), else twice a day, else daily; nothing for
   * an entity with no forecast, nor while the card is off the page.
   */
  _syncForecast() {
    const entityId = this._hours && this._view?.weatherEntity;
    const weather = entityId ? this._hass?.states?.[entityId] : null;
    const features = Number(weather?.attributes?.supported_features) || 0;
    const type = FORECAST_TYPES.find(([, bit]) => features & bit)?.[0];
    const connection = this._hass?.connection;
    const wanted = weather && type && connection && this._connected ? `${entityId} ${type}` : null;
    if (wanted === (this._forecast?.key ?? null)) return;
    this._stopForecast();
    if (!wanted) return;
    const forecast = { key: wanted, entityId, type, list: null, unsubscribe: null, stopped: false };
    this._forecast = forecast;
    // The hours go by between forecasts: one that has passed leaves the strip.
    forecast.timer = setInterval(() => this._patchForecast(), 5 * 60 * 1000);
    Promise.resolve()
      .then(() =>
        connection.subscribeMessage(
          (message) => {
            if (forecast.stopped) return;
            forecast.list = Array.isArray(message?.forecast) ? message.forecast : [];
            this._patchForecast();
          },
          { type: "weather/subscribe_forecast", forecast_type: type, entity_id: entityId },
        ),
      )
      .then(
        (unsubscribe) => {
          if (forecast.stopped) this._unsubscribe(unsubscribe);
          else forecast.unsubscribe = unsubscribe;
        },
        // The entity would not give one after all: the strip stays hidden.
        () => {},
      );
  }

  /** Stop hearing the forecast, if the card is. */
  _stopForecast() {
    const forecast = this._forecast;
    if (!forecast) return;
    forecast.stopped = true;
    clearInterval(forecast.timer);
    this._unsubscribe(forecast.unsubscribe);
    this._forecast = null;
  }

  // A subscription's way to stop, which a closed connection can refuse: it is gone either way.
  _unsubscribe(unsubscribe) {
    try {
      Promise.resolve(unsubscribe?.()).catch(() => {});
    } catch {
      // Already gone.
    }
  }

  /** Draw the forecast's cells, rewritten only when they change; hidden with nothing to say. */
  _patchForecast() {
    const box = this._hours;
    if (!box) return;
    const cells = this._forecastCells();
    const hidden = cells.length < 2;
    if (box.hidden !== hidden) box.hidden = hidden;
    const key = JSON.stringify(cells);
    if (box.dataset.key === key) return;
    box.dataset.key = key;
    box.innerHTML = "";
    for (const cell of cells) {
      const item = el("li");
      const parts = [el("span", "when", cell.when), haIcon(cell.icon), el("span", "wet", cell.wet), el("span", "deg", cell.deg)];
      if (cell.low) parts[3].appendChild(el("span", "low", cell.low));
      for (const part of parts) part.setAttribute("aria-hidden", "true");
      item.append(el("span", "said", cell.said), ...parts);
      box.appendChild(item);
    }
  }

  /**
   * The forecast as the strip shows it: now, from the weather entity itself, then what is
   * ahead -- the next hours, or for a daily forecast the days after today -- each with its
   * time, its weather's icon (the night's for a clear hour after dark), its chance of rain or
   * snow when that is worth saying, and its temperature (and a day's low). Empty until the
   * forecast has come.
   */
  _forecastCells() {
    const forecast = this._forecast;
    const weather = forecast ? this._hass?.states?.[forecast.entityId] : null;
    if (!forecast?.list?.length || !weather || ["unavailable", "unknown"].includes(weather.state)) return [];
    const locale = this._hass.locale || {};
    const language = locale.language || this._hass.language || "en";
    const options = {
      ...(locale.time_format === "12" ? { hour12: true } : locale.time_format === "24" ? { hour12: false } : {}),
      ...(locale.time_zone === "server" && this._hass.config?.time_zone ? { timeZone: this._hass.config.time_zone } : {}),
    };
    const format = (parts) => {
      try {
        return new Intl.DateTimeFormat(language, { ...options, ...parts });
      } catch {
        return new Intl.DateTimeFormat("en", parts);
      }
    };
    const hours = format({ hour: "numeric" });
    const days = format({ weekday: "short" });
    const dayOf = format({ year: "numeric", month: "numeric", day: "numeric" });
    const night = (at, condition) => {
      if (condition === "clear-night") return true;
      const sun = this._view?.sunAt?.(new Date(at));
      return Boolean(sun) && sun.elevation < -0.83;
    };
    const degrees = (value) => (Number.isFinite(Number(value)) && value !== null ? `${Math.round(Number(value))}°` : "");
    const say = (condition) => this._hass.formatEntityState?.(weather, condition) ?? condition;
    const cell = (when, condition, temperature, { low, wet, dark } = {}) => {
      const icon = (dark && NIGHT_ICONS[condition]) || WEATHER_ICONS[condition] || "mdi:weather-cloudy";
      const chance = Number(wet);
      const wetText = Number.isFinite(chance) && wet !== null && chance >= FORECAST_WET ? this._pct(chance) : "";
      const said = [when, condition ? say(condition) : null, degrees(temperature), low !== undefined ? degrees(low) : null,
        wetText ? this._t("chance", { value: Math.round(chance) }) : null].filter(Boolean).join(", ");
      return { when, icon, wet: wetText, deg: degrees(temperature), ...(low !== undefined ? { low: degrees(low) } : {}), said };
    };

    const now = Date.now();
    const cells = [cell(this._t("now"), weather.state, weather.attributes?.temperature, { dark: night(now, weather.state) })];
    const today = dayOf.format(new Date(now));
    for (const entry of forecast.list) {
      if (cells.length >= FORECAST_CELLS) break;
      const at = Date.parse(entry?.datetime);
      if (!Number.isFinite(at)) continue;
      if (forecast.type === "daily") {
        if (dayOf.format(new Date(at)) === today || at < now) continue;
        cells.push(cell(days.format(new Date(at)), entry.condition, entry.temperature,
          { low: entry.templow ?? null, wet: entry.precipitation_probability ?? null }));
      } else if (at > now) {
        const dark = forecast.type === "twice_daily" ? entry.is_daytime === false : night(at, entry.condition);
        const when = forecast.type === "twice_daily" ? days.format(new Date(at)) : hours.format(new Date(at));
        cells.push(cell(when, entry.condition, entry.temperature, { wet: entry.precipitation_probability ?? null, dark }));
      }
    }
    return cells;
  }

  // ---- colors and divided lights --------------------------------------------------------------

  /** The colors a blind can have: a Shutter's paints and stains, any other blind's fabrics. */
  _colorsOf(blind) {
    return blind.louvers ? SHUTTER_COLORS : SHADE_COLORS;
  }

  /** A blind's select for a kind of choice: its color's, or its window's divided lights'. */
  _choiceEntity(kind, blind) {
    return kind === "colors" ? blind.color : blind.lights;
  }

  /** What a blind can choose from, for a kind of choice. */
  _choicesOf(kind, blind) {
    return kind === "colors" ? this._colorsOf(blind) : WINDOW_LIGHTS;
  }

  /**
   * What is chosen on a select: one just chosen here, while Home Assistant takes it up, else
   * the select's state, else the default.
   */
  _chosen(entityId, choices, fallback) {
    if (!entityId) return fallback;
    const state = this._hass?.states?.[entityId]?.state;
    const pending = this._choicePending.get(entityId);
    if (pending && (state === pending.value || Date.now() - pending.at > CHOICE_PENDING_MS)) {
      this._choicePending.delete(entityId);
    } else if (pending) {
      return pending.value;
    }
    return Object.hasOwn(choices, state) ? state : fallback;
  }

  /** The color a blind is drawn in. */
  _colorOf(blind) {
    return this._chosen(blind.color, this._colorsOf(blind), blind.louvers ? DEFAULT_SHUTTER_COLOR : DEFAULT_SHADE_COLOR);
  }

  /** The divided lights a blind's window is drawn with. */
  _lightsOf(blind) {
    return this._chosen(blind.lights, WINDOW_LIGHTS, DEFAULT_WINDOW_LIGHTS);
  }

  /** Draw a window in its blind's color, and say the color where choosing shows it. */
  _paintColor(cell) {
    const { blind, shade } = cell;
    const color = this._colorOf(blind);
    const fallback = blind.louvers ? DEFAULT_SHUTTER_COLOR : DEFAULT_SHADE_COLOR;
    const drawn = color === fallback ? undefined : color;
    if (shade.element.dataset.color !== drawn) {
      if (drawn) shade.element.dataset.color = drawn;
      else delete shade.element.dataset.color;
    }
    const pick = cell.picks.colors;
    if (!pick) return;
    if (pick.value !== color) pick.value = color;
    const swatch = swatchOf(Boolean(blind.louvers), color);
    for (const part of [cell.colorBadge, cell.choiceNames.colors]) {
      if (part.style.getPropertyValue?.("--n-swatch") !== swatch) part.style.setProperty?.("--n-swatch", swatch);
    }
    setText(cell.choiceNames.colors.lastChild, this._t(`color_${color}`));
  }

  /** Draw a window's glass with its divided lights, and say them where choosing shows them. */
  _paintLights(cell) {
    const lights = this._lightsOf(cell.blind);
    this._layBars(cell.shade.bars, lights);
    const pick = cell.picks.lights;
    if (!pick) return;
    if (pick.value !== lights) pick.value = lights;
    setText(cell.choiceNames.lights.lastChild, this._t(`lights_${lights}`));
  }

  /** Lay a window's glazing bars for its divided lights (WINDOW_LIGHTS), when they change. */
  _layBars(bars, lights) {
    if (bars.dataset.lights === lights) return;
    bars.dataset.lights = lights;
    bars.innerHTML = "";
    for (const [way, at, weight, from = 0, to = 100] of WINDOW_LIGHTS[lights] ?? WINDOW_LIGHTS[DEFAULT_WINDOW_LIGHTS]) {
      const down = way === "down";
      const bar = el("div", down ? "mullion" : "transom");
      bar.style[down ? "left" : "top"] = `${at}%`;
      bar.style[down ? "width" : "height"] = `${weight}%`;
      bar.style[down ? "top" : "left"] = `${from}%`;
      bar.style[down ? "height" : "width"] = `${to - from}%`;
      bars.appendChild(bar);
    }
  }

  /** A choice made for one window: drawn at once, and kept on the blind's select. */
  _choose(cell, kind, value) {
    const entityId = this._choiceEntity(kind, cell.blind);
    if (!entityId || !Object.hasOwn(this._choicesOf(kind, cell.blind), value)) return;
    this._choicePending.set(entityId, { value, at: Date.now() });
    if (kind === "colors") this._paintColor(cell);
    else this._paintLights(cell);
    this._keepChoice([entityId], value);
  }

  /**
   * The windows a choice for every window at once goes to: every window with that choice, but
   * a color only to the shades, not a Shutter, whose colors are paints.
   */
  _everyFor(kind) {
    return this._cells.filter((cell) => cell.picks[kind] && (kind !== "colors" || !cell.blind.louvers));
  }

  /** A choice made for every window at once. */
  _chooseEvery(kind, value) {
    const cells = this._everyFor(kind);
    if (!cells.length || !Object.hasOwn(kind === "colors" ? SHADE_COLORS : WINDOW_LIGHTS, value)) return;
    const at = Date.now();
    for (const cell of cells) {
      this._choicePending.set(this._choiceEntity(kind, cell.blind), { value, at });
      if (kind === "colors") this._paintColor(cell);
      else this._paintLights(cell);
    }
    this._keepChoice(cells.map((cell) => this._choiceEntity(kind, cell.blind)), value);
  }

  // One call for every select; one Home Assistant refuses is drawn as it was, and so is any it
  // has not taken up once CHOICE_PENDING_MS has passed.
  _keepChoice(entityIds, value) {
    const settle = () => {
      for (const entityId of entityIds) this._choicePending.delete(entityId);
      this._patch();
    };
    Promise.resolve(
      this._hass.callService("select", "select_option", { entity_id: entityIds.length === 1 ? entityIds[0] : entityIds, option: value }),
    ).catch(settle);
    setTimeout(() => this._patch(), CHOICE_PENDING_MS + 100);
  }

  /** Turn the page to choosing a kind of thing for each window ("colors" or "lights"), or back (null). */
  _setChoosing(kind) {
    const was = this._choosing;
    const item = kind ? this._choiceItems[kind] : null;
    this._choosing = item && !item.hidden ? kind : null;
    this._toggleSettings(false);
    this._syncChoosing();
    // The bar's Done takes the focus, so nothing scrolls, and gives it back to the settings
    // button the choosing began from.
    if (this._choosing && this._choosing !== was) this._choiceDone[this._choosing]?.focus?.({ preventScroll: true });
    if (was && !this._choosing) this._settingsButton?.focus?.({ preventScroll: true });
  }

  /**
   * Each kind's item in the settings menu shows while a window has that to choose, and the
   * settings button while either does; the page is drawn choosing, or not, as `_choosing` says.
   */
  _syncChoosing() {
    const settings = this._settings;
    if (!settings) return;
    for (const [kind, item] of Object.entries(this._choiceItems)) {
      const any = this._cells.some((cell) => cell.picks[kind]);
      if (item.hidden !== !any) item.hidden = !any;
      if (!any && this._choosing === kind) this._choosing = null;
      const every = this._choiceEvery[kind];
      if (every) every.hidden = !this._everyFor(kind).length;
    }
    const none = Object.values(this._choiceItems).every((item) => item.hidden);
    if (settings.hidden !== none) settings.hidden = none;
    if (none) this._toggleSettings(false);
    const tools = this._tools;
    if (tools) {
      const empty = [...(tools.children || [])].every((child) => child.hidden);
      if (tools.hidden !== empty) tools.hidden = empty;
    }
    this._markChoosing(this._card);
  }

  /**
   * The page's settings, at the top of the sidebar panel beside the refresh: a button that opens
   * a menu of what can be chosen for each window, its shade's color and its divided lights, each
   * of which turns the page to choosing it (_setChoosing). Hidden until a window has something
   * to choose (_syncChoosing).
   */
  _buildSettings() {
    const group = el("div", "icon-group home-settings");
    group.hidden = true;
    const button = this._iconButton(SETTINGS_ICON, this._t("settings"), () => this._toggleSettings());
    button.classList.add("settings");
    button.setAttribute("aria-haspopup", "menu");
    button.setAttribute("aria-expanded", "false");
    const menu = el("div", "settings-menu");
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", this._t("settings"));
    menu.hidden = true;
    this._choiceItems = {};
    for (const [kind, { icon, words }] of Object.entries(CHOICES)) {
      const item = el("button", `menu-item ${kind}`);
      item.type = "button";
      item.setAttribute("role", "menuitem");
      item.append(haIcon(icon), el("span", null, this._t(words.button)));
      item.hidden = true;
      item.addEventListener("click", () => this._setChoosing(kind));
      this._choiceItems[kind] = item;
      menu.appendChild(item);
    }
    menu.addEventListener("keydown", (event) => this._settingsKey(event));
    group.append(button, menu);
    this._settings = group;
    this._settingsButton = button;
    this._settingsMenu = menu;
    return group;
  }

  /**
   * Open the settings menu, or close it (`open` false); with no argument, the other of the two.
   * Open, its first item takes the focus, and a press anywhere else closes it.
   */
  _toggleSettings(open = Boolean(this._settingsMenu?.hidden)) {
    const menu = this._settingsMenu;
    if (!menu || menu.hidden === !open) return;
    menu.hidden = !open;
    this._settingsButton.setAttribute("aria-expanded", String(open));
    this._settingsButton.classList.toggle("open", open);
    this._onOutside ??= (event) => {
      if (!event.composedPath?.().includes(this._settings)) this._toggleSettings(false);
    };
    if (open) {
      document.addEventListener?.("pointerdown", this._onOutside, true);
      Object.values(this._choiceItems).find((item) => !item.hidden)?.focus?.({ preventScroll: true });
    } else {
      document.removeEventListener?.("pointerdown", this._onOutside, true);
    }
  }

  /** The settings menu by the keyboard: up and down go between its items, Escape closes it. */
  _settingsKey(event) {
    const items = Object.values(this._choiceItems).filter((item) => !item.hidden);
    if (event.key === "Escape") {
      event.preventDefault();
      this._toggleSettings(false);
      this._settingsButton.focus?.();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const at = items.indexOf(this.shadowRoot?.activeElement ?? event.target);
      const step = event.key === "ArrowDown" ? 1 : -1;
      items[(at + step + items.length) % items.length]?.focus?.();
    } else if (event.key === "Tab") {
      this._toggleSettings(false);
    }
  }

  /** Mark the card with what is being chosen, for the CSS. */
  _markChoosing(card) {
    if (!card) return;
    card.classList.toggle("choosing", Boolean(this._choosing));
    for (const [kind, { mode }] of Object.entries(CHOICES)) card.classList.toggle(mode, this._choosing === kind);
  }

  /**
   * What stands in for the whole-house row while a kind of thing is chosen: what to do, one
   * for every window at once, and Done.
   */
  _buildChoiceBar(kind) {
    const { icon, words } = CHOICES[kind];
    const bar = el("div", `choice-bar ${kind}`);
    const text = el("div", "choice-text");
    text.append(el("div", "choice-title", this._t(words.button)), el("div", "choice-hint", this._t(words.hint)));
    const actions = el("div", "choice-actions");
    const every = el("div", "chip choice-every");
    every.append(haIcon(icon), el("span", null, this._t(words.every)));
    const select = el("select");
    select.setAttribute("aria-label", this._t(words.every));
    const prompt = el("option", null, this._t(words.every));
    prompt.value = "";
    prompt.disabled = true;
    select.appendChild(prompt);
    for (const value of Object.keys(kind === "colors" ? SHADE_COLORS : WINDOW_LIGHTS)) {
      const option = el("option", null, this._t(`${words.option}${value}`));
      option.value = value;
      select.appendChild(option);
    }
    select.value = "";
    select.addEventListener("change", () => {
      const value = select.value;
      select.value = "";
      if (value) this._chooseEvery(kind, value);
    });
    every.appendChild(select);
    this._choiceEvery[kind] = every;
    const done = this._buildChip("mdi:check", this._t("choose_done"), this._t("choose_done"), () => this._setChoosing(null));
    this._choiceDone[kind] = done;
    actions.append(every, done);
    bar.append(text, actions);
    return bar;
  }

  // ---- the rooms bar --------------------------------------------------------------------------

  /**
   * In the sidebar panel, the bar at the foot of a phone's screen: the top of the page, then a
   * button for each room, which scrolls to it. Hidden with fewer than two rooms to go between,
   * or with the room headings hidden; the CSS shows it only where Home Assistant says the
   * screen is narrow.
   */
  _buildDock() {
    const dock = this._dock;
    if (!dock) return;
    dock.innerHTML = "";
    this._tabs = [];
    const rooms = this._roomLines.filter((room) => room.name !== null && room.name !== undefined);
    dock.hidden = rooms.length < 2;
    if (dock.hidden) {
      this._unwatchScroll();
      return;
    }
    const tab = (label, room, icon) => {
      const button = el("button", "room-tab");
      button.type = "button";
      if (icon) button.appendChild(haIcon(icon));
      button.appendChild(el("span", null, label));
      const live = el("i", "dot live");
      const warn = el("i", "dot warn");
      live.hidden = true;
      warn.hidden = true;
      live.setAttribute("aria-hidden", "true");
      warn.setAttribute("aria-hidden", "true");
      button.append(live, warn);
      const index = this._tabs.length;
      button.addEventListener("click", () => this._goTo(index));
      dock.appendChild(button);
      this._tabs.push({ button, room, live, warn });
    };
    tab(this._t("home"), null, "mdi:home-outline");
    this._tabs[0].button.setAttribute("aria-label", this._t("home_top"));
    this._tabs[0].button.title = this._t("home_top");
    for (const room of rooms) tab(room.name, room);
    this._markTab(0);
    this._watchScroll();
  }

  /** Scroll to a room, below the header that stays at the top, or to the top of the page. */
  _goTo(index) {
    const tab = this._tabs[index];
    if (!tab) return;
    const smooth = !globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const target = tab.room ? tab.room.section : this._card;
    if (tab.room) {
      const header = this._header?.getBoundingClientRect?.().height ?? 0;
      target.style.scrollMarginTop = `${Math.round(header + 10)}px`;
    }
    // The marking follows the press, not the rooms scrolling past on the way.
    this._spyHeld = Date.now() + 900;
    target.scrollIntoView?.({ behavior: smooth ? "smooth" : "auto", block: "start" });
    this._markTab(index);
  }

  /** Mark the part of the page in view on the bar, and bring its button into the bar's view. */
  _markTab(index) {
    this._tabs.forEach((tab, i) => {
      const current = tab.button.getAttribute("aria-current") === "true";
      if (i === index && !current) tab.button.setAttribute("aria-current", "true");
      else if (i !== index && current) tab.button.removeAttribute("aria-current");
    });
    const button = this._tabs[index]?.button;
    const bar = this._dock;
    if (!button || !bar?.scrollTo || bar.scrollWidth <= bar.clientWidth) return;
    const left = Math.max(0, button.offsetLeft - (bar.clientWidth - button.offsetWidth) / 2);
    if (Math.abs(bar.scrollLeft - left) > 1) bar.scrollTo({ left, behavior: "smooth" });
  }

  /** The box the page scrolls in: the panel's, found up the tree through its shadow roots. */
  _scrollBox() {
    let node = this;
    while (node) {
      node = node.assignedSlot || node.parentNode || node.host;
      if (node?.nodeType !== 1) continue;
      const overflow = getComputedStyle(node).overflowY;
      if (overflow === "auto" || overflow === "scroll") return node;
    }
    return null;
  }

  /** Follow the page's scrolling, to mark the room in view on the bar. */
  _watchScroll() {
    this._unwatchScroll();
    if (!this._connected || !this._dock || this._dock.hidden || typeof getComputedStyle !== "function") return;
    const box = this._scrollBox();
    if (!box) return;
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        this._spy(box);
      });
    };
    box.addEventListener("scroll", onScroll, { passive: true });
    // The page's parts move without a scroll as well: the forecast arriving, a room's tray
    // opening, the screen turning.
    const resize = typeof ResizeObserver === "function" ? new ResizeObserver(onScroll) : null;
    resize?.observe(this._card);
    this._scroller = { box, onScroll, resize };
    onScroll();
  }

  _unwatchScroll() {
    if (!this._scroller) return;
    this._scroller.box.removeEventListener("scroll", this._scroller.onScroll);
    this._scroller.resize?.disconnect();
    this._scroller = null;
  }

  /**
   * The part of the page in view: the top of the page until it scrolls, then the last room whose
   * top has come up past a line a third of the way down below the header; at the very end of the
   * page, the last room, which may be too short to reach the line.
   */
  _spy(box) {
    if (!this._tabs.length || Date.now() < this._spyHeld) return;
    const header = this._header?.getBoundingClientRect().bottom ?? 0;
    const view = box.getBoundingClientRect();
    const line = header + (view.bottom - header) / 3;
    let active = 0;
    if (box.scrollTop > 4) {
      this._tabs.forEach((tab, index) => {
        if (tab.room && tab.room.section.getBoundingClientRect().top <= line) active = index;
      });
      if (box.scrollTop + box.clientHeight >= box.scrollHeight - 2) active = this._tabs.length - 1;
    }
    this._markTab(active);
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
  { key: "title", label: "editor_title", type: "text" },
  { key: "config_entry_id", label: "editor_hub", type: "entry" },
  { key: "hide_picture", label: "editor_hide_picture", type: "boolean" },
  { key: "hide_battery", label: "editor_hide_battery", type: "boolean" },
  { key: "hide_room_names", label: "editor_hide_room_names", type: "boolean" },
  { key: "hide_room_controls", label: "editor_hide_room_controls", type: "boolean" },
  { key: "hide_room_presets", label: "editor_hide_room_presets", type: "boolean" },
  { key: "hide_home_controls", label: "editor_hide_home_controls", type: "boolean" },
  { key: "hide_refresh", label: "editor_hide_refresh", type: "boolean" },
];

class NormanShadesCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    // Home Assistant hands the editor its config back after every change it reports, and the
    // title field reports one per keystroke. Rebuilding the form would take the focus out of
    // the field being typed in, so a form already drawn is only given the new values.
    if (this._form) this._form.data = this._config;
    else this._render();
  }

  set hass(hass) {
    const language = languageOf(hass);
    const changed = this._config !== undefined && language !== languageOf(this._hass);
    this._hass = hass;
    // The labels are in the user's language, which is only known once hass arrives.
    if (changed) this._render();
    else if (this._form) this._form.hass = hass;
  }

  _label(field) {
    return translate(languageOf(this._hass), field.label);
  }

  /**
   * Report a changed config, without the options left empty or turned off: the card's
   * defaults. A blank title is kept unless it is the title field that was just emptied --
   * `title: ""` set in YAML is a heading left blank on purpose, which a change to another
   * option must not turn back into the hub's name.
   */
  _changed(config) {
    const next = { ...config };
    for (const { key } of EDITOR_FIELDS) {
      if (key === "title" && next.title === "" && this._config?.title === "") continue;
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
      const selectors = {
        boolean: { boolean: {} },
        entry: { config_entry: { integration: DOMAIN } },
        text: { text: {} },
      };
      form.schema = EDITOR_FIELDS.map(({ key, type }) => ({ name: key, selector: selectors[type] }));
      const labels = Object.fromEntries(EDITOR_FIELDS.map((field) => [field.key, this._label(field)]));
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
      text.textContent = this._label(field);
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

// Register in the dashboard's "Add card" picker. There is no hass yet, so the page's language
// (Home Assistant sets it to the user's) picks the words.
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "norman-shades-card")) {
  const language = languageOf(null);
  window.customCards.push({
    type: "norman-shades-card",
    name: translate(language, "card_name"),
    description: translate(language, "card_description"),
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
