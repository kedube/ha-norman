// Exercise the Norman shades card outside a browser.
//
//     node scripts/check_card.mjs
//
// The card assembles a blind from its entities using the *frontend* entity registry, which
// is a reduced view: it carries translation_key but NOT unique_id (see
// EntityRegistryEntry._as_display_dict in homeassistant/helpers/entity_registry.py). Reading
// a field that is not there fails silently -- the entity is simply never found -- so this
// harness feeds the card a hass object shaped exactly like the real one and asserts that the
// middle rail, both sliders and the battery are all located. It then drives the picture's
// geometry, the status line and the service calls the controls make.
//
// CI runs this in the Card job; tests/test_repo_consistency.py pins the same contract in
// Python by reading the source.

const els = new Map();
globalThis.window = globalThis;
globalThis.HTMLElement = class {
  constructor(){ this.children=[]; this.attrs={}; }
  attachShadow(){ this.shadowRoot = mk('root'); return this.shadowRoot; }
  appendChild(c){ this.children.push(c); return c; }
  addEventListener(){}
  dispatchEvent(e){ (this._events ||= []).push(e); }
  setAttribute(k,v){ this.attrs[k]=String(v); }
  getAttribute(k){ return this.attrs[k]; }
  hasAttribute(k){ return k in this.attrs; }
  removeAttribute(k){ delete this.attrs[k]; }
  toggleAttribute(k, force){ const on = force ?? !this.hasAttribute(k); on ? this.setAttribute(k, "") : this.removeAttribute(k); return on; }
};
globalThis.customElements = { get: () => undefined, define: (n,c) => els.set(n,c) };
// A class list that really edits className, so the checks can read state the card toggles.
const classListOf = (el) => {
  const list = () => String(el.className).split(/\s+/).filter(Boolean);
  const set = (names) => { el.className = names.join(" "); };
  return {
    add(...n){ set([...new Set([...list(), ...n])]); },
    remove(...n){ set(list().filter((c) => !n.includes(c))); },
    toggle(n, force){ const on = force ?? !list().includes(n); on ? this.add(n) : this.remove(n); return on; },
    contains(n){ return list().includes(n); },
  };
};
const mk = (tag) => {
  const el = {
    tagName: tag, children: [], style: {}, dataset: {}, attrs: {}, _text: "",
    className: "",
    appendChild(c){ this.children.push(c); return c; },
    append(...c){ this.children.push(...c); },
    prepend(...c){ this.children.unshift(...c); },
    addEventListener(ev,fn){ (this._on ||= {})[ev] = fn; },
    setAttribute(k,v){ this.attrs[k]=String(v); }, getAttribute(k){ return this.attrs[k]; },
    removeAttribute(k){ delete this.attrs[k]; },
    remove(){}, querySelector(){ return null; }, querySelectorAll(){ return []; },
    get firstChild(){ return this.children[0]; },
    get lastChild(){ return this.children[this.children.length-1]; },
    set textContent(v){ this._text = String(v); }, get textContent(){ return this._text; },
    set innerHTML(v){ if(v==="") this.children=[]; },
  };
  el.classList = classListOf(el);
  return el;
};
// A defined custom element is constructed, as a browser would; anything else is a plain mock.
globalThis.document = { createElement: (tag) => (els.has(tag) ? new (els.get(tag))() : mk(tag)) };
globalThis.console.info = () => {};

const url = new URL("file://" + process.cwd() + "/custom_components/norman/www/norman-shades-card.js");
url.searchParams.set("v", "test");
await import(url.href);

// The card's own text, for the few checks that pin a design constant shared between the
// CSS and the JS rather than any runtime behaviour.
const cardSource = await import("node:fs").then((fs) => fs.readFileSync(url, "utf8"));

// How long the card treats a new target as a move under way, and the watchdog it mirrors:
// three sends, each followed by MOVE_TIMEOUT and MOVE_REPORT_WAIT (const.py).
const MOVE_WINDOW_MS = Function(`return ${/const MOVE_WINDOW_MS = ([^;]+);/.exec(cardSource)[1]}`)();
// How long the card gathers arrow keys before it writes the move they make.
const KEY_COMMIT_MS = Number(/const KEY_COMMIT_MS = (\d+);/.exec(cardSource)[1]);
// How long a refresh control's icon turns, how long a second press of it is ignored, and the
// translation key of the blind's Request status button.
const REFRESH_SPIN_MS = Number(/const REFRESH_SPIN_MS = (\d+);/.exec(cardSource)?.[1]);
const REFRESH_HOLD_MS = Number(/const REFRESH_HOLD_MS = (\d+);/.exec(cardSource)?.[1]);
const REQUEST_STATUS = /const BUTTON_REQUEST_STATUS = "(\w+)";/.exec(cardSource)?.[1];

// The headrail depth and rail thickness are design constants shared by the CSS and the JS;
// read them rather than restating them.
const HEAD = Number(/--n-head:\s*([\d.]+)%/.exec(cardSource)[1]);
const RAIL = Number(/--n-rail:\s*([\d.]+)%/.exec(cardSource)[1]);
// A Roman shade's sections and the depth of its folds fully up.
const SECTIONS = Number(/const ROMAN_SECTIONS = (\d+);/.exec(cardSource)[1]);
const STACK = Number(/const ROMAN_STACK_PCT = ([\d.]+);/.exec(cardSource)[1]);
const LAP = Number(/const ROMAN_LAP_PCT = ([\d.]+);/.exec(cardSource)[1]);
const top = (el) => parseFloat(el.style.top);
const height = (el) => parseFloat(el.style.height);
const near = (a, b) => Math.abs(a - b) < 0.01;

const Card = els.get("norman-shades-card");
const card = new Card();

// Two blinds: a two-rail (day/night) and a single-rail, as HA would present them.
const entities = {
  "cover.front_bedroom_1_bottom_rail": { platform:"norman", device_id:"d1", translation_key:"bottom_rail" },
  "cover.front_bedroom_1_middle_rail": { platform:"norman", device_id:"d1", translation_key:"middle_rail" },
  "number.front_bedroom_1_bottom_rail_position": { platform:"norman", device_id:"d1", translation_key:"bottom_rail_position" },
  "number.front_bedroom_1_middle_rail_position": { platform:"norman", device_id:"d1", translation_key:"middle_rail_position" },
  "sensor.front_bedroom_1_battery": { platform:"norman", device_id:"d1", translation_key:"battery_level" },
  "cover.den_1_bottom_rail": { platform:"norman", device_id:"d2", translation_key:"bottom_rail" },
  "number.den_1_bottom_rail_position": { platform:"norman", device_id:"d2", translation_key:"bottom_rail_position" },
  "sensor.den_1_battery": { platform:"norman", device_id:"d2", translation_key:"battery_level" },
  "button.front_bedroom_1_request_status": { platform:"norman", device_id:"d1", translation_key:"request_status" },
  "button.den_1_request_status": { platform:"norman", device_id:"d2", translation_key:"request_status" },
  // Noise that must be ignored:
  "button.den_1_jog_up": { platform:"norman", device_id:"d2", translation_key:"jog_up" },
  "sensor.norman_hub_wi_fi_network": { platform:"norman", device_id:"hub", translation_key:"wifi_ssid" },
  "light.kitchen": { platform:"hue", device_id:"d9" },
};
const hass = {
  entities,
  devices: { d1:{ name:"Front_Bedroom_1", area_id:"a1" }, d2:{ name:"Den_1", area_id:"a2" }, hub:{ name:"Lakehouse Shades", area_id:null } },
  areas: { a1:{ name:"Front Bedroom" }, a2:{ name:"Den" } },
  states: {
    "cover.front_bedroom_1_bottom_rail": { state:"open", attributes:{ current_position:60 } },
    "cover.front_bedroom_1_middle_rail": { state:"open", attributes:{ current_position:80 } },
    "number.front_bedroom_1_bottom_rail_position": { state:"60" },
    "number.front_bedroom_1_middle_rail_position": { state:"80" },
    "sensor.front_bedroom_1_battery": { state:"84" },
    "cover.den_1_bottom_rail": { state:"open", attributes:{ current_position:90 } },
    "number.den_1_bottom_rail_position": { state:"90" },
    "sensor.den_1_battery": { state:"12" },
    "button.front_bedroom_1_request_status": { state:"unknown" },
    "button.den_1_request_status": { state:"unknown" },
  },
};
card._hass = hass;
card.setConfig({ type:"custom:norman-shades-card" });
card._hass = hass;

const blinds = card._collectBlinds();
let fail = 0;
const check = (label, cond, extra="") => { console.log(`${cond?"PASS":"FAIL"}  ${label}${extra&&!cond?"  -> "+extra:""}`); if(!cond) fail++; };

// The card's move window is the integration's watchdog, end to end.
{
  const constPy = await import("node:fs").then((fs) => fs.readFileSync(new URL("../const.py", url), "utf8"));
  const number = (name) => Number(new RegExp(`^${name} = ([\\d.]+)`, "m").exec(constPy)[1]);
  const watchdog = number("MOVE_ATTEMPTS") * (number("MOVE_TIMEOUT") + number("MOVE_REPORT_WAIT")) * 1000;
  check("the card's move window matches the integration's watchdog", MOVE_WINDOW_MS === watchdog,
        `${MOVE_WINDOW_MS} vs ${watchdog}`);
}

check("finds exactly 2 blinds (hub excluded)", blinds.length===2, JSON.stringify(blinds.map(b=>b.name)));
const fb = blinds.find(b=>b.deviceId==="d1");
const den = blinds.find(b=>b.deviceId==="d2");
check("two-rail: bottom cover", fb?.bottomCover==="cover.front_bedroom_1_bottom_rail", String(fb?.bottomCover));
check("two-rail: MIDDLE cover found", fb?.middleCover==="cover.front_bedroom_1_middle_rail", String(fb?.middleCover));
check("two-rail: bottom slider", fb?.bottomNumber==="number.front_bedroom_1_bottom_rail_position", String(fb?.bottomNumber));
check("two-rail: MIDDLE slider found", fb?.middleNumber==="number.front_bedroom_1_middle_rail_position", String(fb?.middleNumber));
check("two-rail: battery found", fb?.battery==="sensor.front_bedroom_1_battery", String(fb?.battery));
check("two-rail: Request status button found", fb?.refresh==="button.front_bedroom_1_request_status", String(fb?.refresh));
check("single-rail: Request status button found", den?.refresh==="button.den_1_request_status", String(den?.refresh));
check("a blind's other buttons are not taken for Request status", blinds.every((b) => !String(b.refresh).includes("jog")));
check("two-rail: room from area", fb?.room==="Front Bedroom", String(fb?.room));
check("single-rail: no middle cover", den?.middleCover===null, String(den?.middleCover));
check("single-rail: no middle slider", den?.middleNumber===null, String(den?.middleNumber));
check("single-rail: battery found", den?.battery==="sensor.den_1_battery", String(den?.battery));

// A sensor whose entity id ends in "_battery" but whose translation key says it is
// something else must NOT be taken as the battery. The key is the authority; the id is
// only a fallback for an entity that somehow has no key.
{
  const reg = {
    "cover.imposter_bottom_rail": { platform:"norman", device_id:"d9", translation_key:"bottom_rail" },
    "sensor.imposter_battery":    { platform:"norman", device_id:"d9", translation_key:"battery_level" },
    // Same device, id ends in _battery, but it is really the last-seen sensor.
    "sensor.decoy_battery":       { platform:"norman", device_id:"d9", translation_key:"last_seen" },
  };
  const c = new Card();
  const h = { ...hass, entities: reg, devices: { d9: { name:"Imposter", area_id:"a1" } },
              states: { "cover.imposter_bottom_rail": { state:"open", attributes:{ current_position:50 } },
                        "sensor.imposter_battery": { state:"77" },
                        "sensor.decoy_battery": { state:"2020-01-01T00:00:00Z" } } };
  c._hass = h; c.setConfig({ type:"custom:norman-shades-card" }); c._hass = h;
  const [only] = c._collectBlinds();
  check("a non-battery sensor ending in _battery is not taken as the battery",
        only?.battery === "sensor.imposter_battery", String(only?.battery));
}

// The frontend's registry marks a hidden entity `hidden: true`; it has no `hidden_by`. A blind
// whose cover is hidden is left off the card, as docs/dashboard.md says.
{
  const h = { ...hass, entities: { ...entities,
    "cover.den_1_bottom_rail": { ...entities["cover.den_1_bottom_rail"], hidden:true } } };
  const c = new Card();
  c._hass = h; c.setConfig({ type:"custom:norman-shades-card" }); c._hass = h;
  const ids = c._collectBlinds().map((b) => b.deviceId);
  check("a blind whose cover is hidden is left out", JSON.stringify(ids) === '["d1"]', JSON.stringify(ids));
}

const rails = card._railsOf(fb);
check("two-rail has TWO rails", rails.length===2, JSON.stringify(rails.map(r=>r.label)));
check("rail labels are Bottom/Middle", rails[0].label==="Bottom rail" && rails[1].label==="Middle rail");
check("single-rail has ONE rail", card._railsOf(den).length===1);
check("rail values read from number entity", card._railValue(rails[0])===60 && card._railValue(rails[1])===80);

const rooms = card._roomsOf(blinds);
check("groups into 2 rooms", rooms.length===2, JSON.stringify(rooms.map(r=>r[0])));
check("rooms sorted alphabetically", rooms[0][0]==="Den" && rooms[1][0]==="Front Bedroom");
{
  // `rooms:` is documented as "only these areas, in this order" -- the order has to hold.
  const c = new Card(); c._hass = hass;
  c.setConfig({ type:"custom:norman-shades-card", rooms:["Front Bedroom", "Den"] }); c._hass = hass;
  const ordered = c._roomsOf(blinds).map(r => r[0]);
  check("a configured rooms list sets the order", JSON.stringify(ordered) === JSON.stringify(["Front Bedroom","Den"]),
        JSON.stringify(ordered));
  c.setConfig({ type:"custom:norman-shades-card", rooms:["Den"] }); c._hass = hass;
  check("a configured rooms list filters", c._roomsOf(blinds).length === 1);
}

const calls = [];
hass.callService = (domain, service, data) => { calls.push([domain, service, data]); return Promise.resolve(); };

// A rendered card, and helpers to find things in it.
const rendered = (cfg = {}, h = hass) => {
  const c = new Card();
  c._hass = h; c.setConfig({ type:"custom:norman-shades-card", ...cfg }); c._hass = h;
  c._render();
  return c;
};
const findAll = (root, pred) => {
  const out = [];
  const walk = (el) => { if (el && pred(el)) out.push(el); (el?.children || []).forEach(walk); };
  walk(root);
  return out;
};
const byClass = (root, name) => findAll(root, (el) => String(el.className || "").split(" ").includes(name));

// --- room-wide controls --------------------------------------------------------------
calls.length = 0;
const roomCard = new Card();
roomCard._hass = hass;
roomCard.setConfig({ type:"custom:norman-shades-card" });
roomCard._hass = hass;
roomCard._cells = [];
const fbRoom = roomCard._buildRoomControls("Front Bedroom", [fb]);
check("room controls render 3 buttons", fbRoom.children.length === 3, String(fbRoom.children.length));

// Open and close: one cover per blind, so one paced hub command per blind. A two-rail blind's
// other rail is carried by the integration (rails_to_send): open on the bottom rail takes the
// middle rail up, close on the middle rail takes the bottom rail down. Stop goes to the
// integration with the blinds shown, which stops a whole room of the hub's with one request.
fbRoom.children[0]._on?.click?.();
check("room open sends ONE call", calls.length === 1, JSON.stringify(calls));
check("room open sends a two-rail blind's bottom rail only, which carries the middle rail up",
      JSON.stringify(calls[0]?.[2]?.entity_id) === '["cover.front_bedroom_1_bottom_rail"]',
      JSON.stringify(calls[0]?.[2]));
calls.length = 0;
fbRoom.children[1]._on?.click?.();
check("room stop names a two-rail blind once, not once per rail, to norman.room_command",
      calls.length === 1 && calls[0][0] === "norman" && calls[0][1] === "room_command" &&
      calls[0][2].command === "stop" && JSON.stringify(calls[0][2].blinds) === '["cover.front_bedroom_1_bottom_rail"]',
      JSON.stringify(calls));
calls.length = 0;
fbRoom.children[2]._on?.click?.();
check("room close sends a two-rail blind's middle rail only, which carries the bottom rail down",
      calls[0]?.[1] === "close_cover" && JSON.stringify(calls[0][2].entity_id) === '["cover.front_bedroom_1_middle_rail"]',
      JSON.stringify(calls));

calls.length = 0;
const denRoom = roomCard._buildRoomControls("Den", [den]);
denRoom.children[2]._on?.click?.();
check("single-rail room close targets its one cover",
      calls.length === 1 && JSON.stringify(calls[0][2].entity_id) === JSON.stringify(["cover.den_1_bottom_rail"]),
      JSON.stringify(calls));
check("room close uses close_cover", calls[0]?.[1] === "close_cover", String(calls[0]?.[1]));

calls.length = 0;
const multi = roomCard._buildRoomControls("Everything", [fb, den]);
multi.children[1]._on?.click?.();
check("a room's stop names every blind shown in it, in one call",
      calls.length === 1 && JSON.stringify(calls[0][2].blinds) === '["cover.front_bedroom_1_bottom_rail","cover.den_1_bottom_rail"]',
      JSON.stringify(calls));
check("...as norman.room_command's stop, never a stop_cover per blind",
      calls[0]?.[0] === "norman" && calls[0]?.[1] === "room_command" && calls[0]?.[2].command === "stop" &&
      !("room" in calls[0][2]));
check("room buttons are labelled with the room name",
      String(fbRoom.children[0].title).includes("Front Bedroom"), String(fbRoom.children[0].title));

// On by default: the user asked for whole-room control, so it must not need a setting.
const countIn = (cfg, className) => {
  const c = rendered(cfg);
  return byClass(c.shadowRoot, className).reduce((n, el) => n + el.children.length, 0);
};
check("_build attaches room controls by default", countIn({}, "room-buttons") === 6,
      String(countIn({}, "room-buttons")));
check("_build attaches none when opted out", countIn({ hide_room_controls:true }, "room-buttons") === 0);
check("hiding room headings also hides room controls",
      countIn({ hide_room_names:true }, "room-buttons") === 0);

// --- the app's room presets ------------------------------------------------------------
{
  const svcCalls = [];
  const c = new Card();
  c._hass = { ...hass, callService: (d,s2,data) => svcCalls.push([d,s2,data]) };
  c.setConfig({ type:"custom:norman-shades-card" });
  c._hass = { ...hass, callService: (d,s2,data) => svcCalls.push([d,s2,data]) };
  const presets = c._buildRoomPresets("Office", [fb, den]);
  check("room presets render 3 buttons", presets.children.length === 3, String(presets.children.length));
  [...presets.children].forEach(b => b._on?.click?.());
  check("presets call norman.room_command",
        svcCalls.every(x => x[0] === "norman" && x[1] === "room_command"), JSON.stringify(svcCalls));
  check("presets send best_privacy / best_view / favorite for the room",
        JSON.stringify(svcCalls.map(x => x[2].command)) === JSON.stringify(["best_privacy","best_view","favorite"]),
        JSON.stringify(svcCalls.map(x => x[2])));
  // The card's rooms are areas, which need not be the hub's rooms: the presets name the blinds
  // shown, and the integration sends a whole room of the hub's its one room-wide preset.
  check("presets name the blinds shown, not the room",
        svcCalls.every(x => !("room" in x[2]) &&
          JSON.stringify(x[2].blinds) === '["cover.front_bedroom_1_bottom_rail","cover.den_1_bottom_rail"]'),
        JSON.stringify(svcCalls[0]?.[2]));
}
check("_build attaches presets by default", countIn({}, "room-presets") === 6,
      String(countIn({}, "room-presets")));
check("_build drops presets when hidden", countIn({ hide_room_presets:true }, "room-presets") === 0);
{
  // Blinds in no area are grouped under "Unassigned", which is no room of the hub's. The presets
  // name the blinds, not the room, so these get them too.
  const h = { ...hass, devices: { ...hass.devices, d2:{ name:"Den_1", area_id:null } } };
  const c = rendered({}, h);
  const section = byClass(c.shadowRoot, "room").find((r) => byClass(r, "room-name")[0]?.textContent === "Unassigned");
  check("blinds in no area are grouped under Unassigned", Boolean(section));
  check("...with the room's open/stop/close", byClass(section, "room-buttons")[0]?.children.length === 3);
  check("...and the presets and refresh in its tray",
        JSON.stringify(byClass(section, "tray")[0]?.children.map((ch) => ch.className)) ===
          '["segmented room-presets","segmented room-refresh"]',
        JSON.stringify(byClass(section, "tray")[0]?.children.map((ch) => ch.className)));
  const sent = [];
  c._hass = { ...c._hass, callService: (d, s2, data) => sent.push([d, s2, data]) };
  byClass(section, "room-presets")[0].children[0]._on.click();
  check("...which go to exactly its blinds",
        JSON.stringify(sent.map((x) => x[2])) === JSON.stringify([{ command:"best_privacy", blinds:["cover.den_1_bottom_rail"] }]),
        JSON.stringify(sent.map((x) => x[2])));
  check("every room gets its presets", byClass(c.shadowRoot, "room-presets").length === 2);
  // With no Request status button among them there is nothing for its refresh to press either.
  const bare = { ...h, entities: Object.fromEntries(Object.entries(h.entities).filter(([id]) => !id.endsWith("_request_status"))) };
  const plain = byClass(rendered({}, bare).shadowRoot, "room").find((r) => byClass(r, "room-name")[0]?.textContent === "Unassigned");
  check("...and with nothing to refresh, the tray holds the presets alone",
        JSON.stringify(byClass(plain, "tray")[0]?.children.map((ch) => ch.className)) === '["segmented room-presets"]',
        JSON.stringify(byClass(plain, "tray")[0]?.children.map((ch) => ch.className)));
}
{
  // The presets fold out of the heading: hidden until its button is pressed.
  const c = rendered();
  const [tray] = byClass(c.shadowRoot, "tray");
  const [more] = byClass(c.shadowRoot, "more");
  check("a room's presets start folded away", tray?.hidden === true, String(tray?.hidden));
  more._on.click();
  check("the room's presets button folds them out", tray.hidden === false && more.attrs["aria-expanded"] === "true");
}

// --- a room's scenes, after its presets ---------------------------------------------------
{
  // Den's room device (r2) holds two scenes, one hidden in Home Assistant, and the hub -- here
  // placed in Den's area too -- holds a scene group, which belongs to no single room. Loft
  // has a scene but no blinds, so no section on the card.
  const sceneHass = (extra = {}, states = {}) => ({
    ...hass,
    entities: {
      ...hass.entities,
      "scene.den_home_assistant": { platform:"norman", device_id:"r2", translation_key:"room_scene", name:"Home Assistant" },
      "scene.den_evening": { platform:"norman", device_id:"r2", translation_key:"room_scene", name:"Evening" },
      "scene.den_hidden": { platform:"norman", device_id:"r2", translation_key:"room_scene", name:"Hidden", hidden:true },
      "scene.norman_hub_bedtime": { platform:"norman", device_id:"hub", translation_key:"scene_group", name:"Bedtime" },
      "scene.loft_morning": { platform:"norman", device_id:"r3", translation_key:"room_scene", name:"Morning" },
      ...extra,
    },
    devices: {
      ...hass.devices,
      hub: { name:"Lakehouse Shades", area_id:"a2" },
      r2: { name:"Den", area_id:"a2" },
      r3: { name:"Loft", area_id:"a3" },
    },
    areas: { ...hass.areas, a3: { name:"Loft" } },
    states: {
      ...hass.states,
      "scene.den_home_assistant": { state:"2026-10-12T21:24:02+00:00", attributes:{} },
      "scene.den_evening": { state:"unknown", attributes:{} },
      ...states,
    },
    callService: (d, s2, data) => calls.push([d, s2, data]),
  });
  const trayOf = (c, room) => {
    const rooms = byClass(c.shadowRoot, "room");
    const section = rooms.find((r) => byClass(r, "room-name")[0]?.textContent === room);
    return section && byClass(section, "tray")[0];
  };
  const sceneChips = (tray) => (byClass(tray, "room-scenes")[0]?.children || []);
  const words = (chips) => chips.map((chip) => chip.children[1].textContent);

  let c = rendered({}, sceneHass());
  const denTray = trayOf(c, "Den");
  check("a room's scenes follow its presets in the tray, and its refresh them",
        JSON.stringify(denTray?.children.map((ch) => ch.className)) ===
          '["segmented room-presets","segmented room-scenes","segmented room-refresh"]',
        JSON.stringify(denTray?.children.map((ch) => ch.className)));
  check("a room's scenes are folded away with its presets", denTray?.hidden === true);
  check("a room's scenes are listed by name, without hidden ones or scene groups",
        JSON.stringify(words(sceneChips(denTray))) === JSON.stringify(["Evening", "Home Assistant"]),
        JSON.stringify(words(sceneChips(denTray))));
  const fbTray = trayOf(c, "Front Bedroom");
  check("a room without scenes shows only its presets and refresh",
        JSON.stringify(fbTray?.children.map((ch) => ch.className)) === '["segmented room-presets","segmented room-refresh"]',
        JSON.stringify(fbTray?.children.map((ch) => ch.className)));
  check("a scene in a room with no blinds is not shown",
        !byClass(c.shadowRoot, "room-scenes").some((group) => words(group.children).includes("Morning")));
  check("a hub without scenes shows none", countIn({}, "room-scenes") === 0);
  check("hiding the room presets hides the scenes too", byClass(rendered({ hide_room_presets:true }, sceneHass()).shadowRoot, "room-scenes").length === 0);

  const [evening] = sceneChips(denTray);
  check("a scene chip says which room it acts on", evening.title === "Evening — Den", evening.title);
  calls.length = 0;
  evening._on.click();
  check("a scene chip runs the scene",
        JSON.stringify(calls) === JSON.stringify([["scene", "turn_on", { entity_id:"scene.den_evening" }]]),
        JSON.stringify(calls));

  // Greyed out while the scene is unavailable, and back when it returns.
  const down = sceneHass({}, { "scene.den_home_assistant": { state:"unavailable", attributes:{} } });
  c = rendered({}, down);
  const chipFor = (card, entityId) =>
    sceneChips(trayOf(card, "Den")).find((chip) => chip.dataset.entityId === entityId);
  check("an unavailable scene's chip is disabled", chipFor(c, "scene.den_home_assistant")?.disabled === true);
  check("an available scene's chip is not", chipFor(c, "scene.den_evening")?.disabled === false);
  c._hass = sceneHass(); c._update();
  check("a scene's chip comes back when the scene does", chipFor(c, "scene.den_home_assistant")?.disabled === false);

  // A scene added, or renamed, in the app rebuilds the room's tray.
  c._hass = sceneHass({ "scene.den_movie": { platform:"norman", device_id:"r2", translation_key:"room_scene", name:"Movie" } });
  c._update();
  check("a new scene appears in its room",
        JSON.stringify(words(sceneChips(trayOf(c, "Den")))) === JSON.stringify(["Evening", "Home Assistant", "Movie"]),
        JSON.stringify(words(sceneChips(trayOf(c, "Den")))));

  // An area set on the scene itself wins over its room device's, as everywhere in Home Assistant.
  c = rendered({}, sceneHass({ "scene.den_evening": { platform:"norman", device_id:"r2", translation_key:"room_scene", name:"Evening", area_id:"a1" } }));
  check("a scene placed in another area shows in that room",
        JSON.stringify(words(sceneChips(trayOf(c, "Front Bedroom")))) === JSON.stringify(["Evening"]) &&
        JSON.stringify(words(sceneChips(trayOf(c, "Den")))) === JSON.stringify(["Home Assistant"]));

  // With a hub configured, only that hub's scenes.
  const scoped = new Card();
  const two = sceneHass();
  two.devices = { ...two.devices, r2: { ...two.devices.r2, config_entries:["home"] } };
  scoped._hass = two; scoped.setConfig({ type:"custom:norman-shades-card", config_entry_id:"cabin" }); scoped._hass = two;
  check("another hub's scenes are left out", scoped._collectScenes().size === 0);
  scoped.setConfig({ type:"custom:norman-shades-card", config_entry_id:"home" }); scoped._hass = two;
  check("this hub's scenes are kept", scoped._collectScenes().get("Den")?.length === 2);
}

// --- the hub's scene groups, after the whole-house presets ----------------------------------
{
  const groupHass = (extra = {}, states = {}) => ({
    ...hass,
    entities: {
      ...hass.entities,
      "scene.norman_hub_bedtime": { platform:"norman", device_id:"hub", translation_key:"scene_group", name:"Bedtime" },
      "scene.norman_hub_away": { platform:"norman", device_id:"hub", translation_key:"scene_group", name:"Away" },
      "scene.norman_hub_secret": { platform:"norman", device_id:"hub", translation_key:"scene_group", name:"Secret", hidden:true },
      "scene.den_evening": { platform:"norman", device_id:"r2", translation_key:"room_scene", name:"Evening" },
      ...extra,
    },
    devices: { ...hass.devices, r2: { name:"Den", area_id:"a2" } },
    states: {
      ...hass.states,
      "scene.norman_hub_bedtime": { state:"unknown", attributes:{} },
      "scene.norman_hub_away": { state:"unknown", attributes:{} },
      "scene.den_evening": { state:"unknown", attributes:{} },
      ...states,
    },
    callService: (d, s2, data) => calls.push([d, s2, data]),
  });
  const words = (chips) => chips.map((chip) => chip.children[1].textContent);
  const headerOf = (c) => byClass(c.shadowRoot, "header")[0];

  let c = rendered({}, groupHass());
  const header = headerOf(c);
  const order = header.children.map((child) => child.className);
  check("scene groups follow the whole-house presets in the header",
        order.indexOf("segmented home-scenes") === order.indexOf("segmented home-buttons") + 1,
        JSON.stringify(order));
  const [box] = byClass(header, "home-scenes");
  check("the header lists the hub's scene groups by name, without hidden ones or room scenes",
        box.hidden === false && JSON.stringify(words(box.children)) === JSON.stringify(["Away", "Bedtime"]),
        JSON.stringify(words(box.children)));
  check("a scene group's chip is named for the group", box.children[1].title === "Bedtime", box.children[1].title);
  calls.length = 0;
  box.children[1]._on.click();
  check("a scene group's chip runs the group",
        JSON.stringify(calls) === JSON.stringify([["scene", "turn_on", { entity_id:"scene.norman_hub_bedtime" }]]),
        JSON.stringify(calls));
  check("a scene group is not listed with a room",
        !byClass(c.shadowRoot, "room-scenes").some((group) => words(group.children).includes("Bedtime")));

  const none = byClass(rendered().shadowRoot, "home-scenes")[0];
  check("a hub without scene groups shows none", none?.hidden === true && none.children.length === 0);
  check("hiding the whole-house presets hides the scene groups too",
        byClass(rendered({ hide_home_controls:true }, groupHass()).shadowRoot, "home-scenes").length === 0);

  c = rendered({}, groupHass({}, { "scene.norman_hub_away": { state:"unavailable", attributes:{} } }));
  const chipOf = (card, entityId) =>
    byClass(card.shadowRoot, "home-scenes")[0].children.find((chip) => chip.dataset.entityId === entityId);
  check("an unavailable scene group's chip is disabled", chipOf(c, "scene.norman_hub_away")?.disabled === true);
  check("an available scene group's chip is not", chipOf(c, "scene.norman_hub_bedtime")?.disabled === false);

  // A group added in the app appears without a reload, and one deleted goes.
  c._hass = groupHass({ "scene.norman_hub_morning": { platform:"norman", device_id:"hub", translation_key:"scene_group", name:"Morning" } });
  c._update();
  check("a new scene group appears in the header",
        JSON.stringify(words(byClass(c.shadowRoot, "home-scenes")[0].children)) === JSON.stringify(["Away", "Bedtime", "Morning"]));
  const gone = groupHass();
  delete gone.entities["scene.norman_hub_away"];
  delete gone.entities["scene.norman_hub_bedtime"];
  c._hass = gone; c._update();
  check("the header's scene groups go when the hub has none left", byClass(c.shadowRoot, "home-scenes")[0].hidden === true);

  // With a hub configured, only that hub's groups.
  const scoped = new Card();
  const two = groupHass();
  two.devices = { ...two.devices, hub: { ...two.devices.hub, config_entries:["home"] } };
  scoped._hass = two; scoped.setConfig({ type:"custom:norman-shades-card", config_entry_id:"cabin" }); scoped._hass = two;
  check("another hub's scene groups are left out", scoped._collectSceneGroups().length === 0);
  scoped.setConfig({ type:"custom:norman-shades-card", config_entry_id:"home" }); scoped._hass = two;
  check("this hub's scene groups are kept", scoped._collectSceneGroups().length === 2);
}

// --- presets are labelled chips ---------------------------------------------------------
{
  const c = rendered();
  const chips = [...c._buildRoomPresets("Den").children];
  check("presets are buttons with a visible word",
        chips.every(ch => ch.tagName === "button" && ch.children[1]?.textContent),
        JSON.stringify(chips.map(ch => ch.children[1]?.textContent)));
  check("preset words are Privacy / View / Favorite",
        JSON.stringify(chips.map(ch => ch.children[1].textContent)) === JSON.stringify(["Privacy","View","Favorite"]));
  check("chip tooltips carry the full name and the room",
        chips[0].title === "Best privacy — Den", chips[0].title);
  const home = [...c._buildHomeControls().children];
  check("house chips say which scope they act on",
        home.every(ch => String(ch.title).endsWith("every room")), JSON.stringify(home.map(ch => ch.title)));
}

// --- the header names the hub -------------------------------------------------------
const headerTextOf = (cfg, h = hass) => byClass(rendered(cfg, h).shadowRoot, "header-text")[0]?.textContent ?? null;
{
  const c = new Card(); c._hass = hass; c.setConfig({ type:"custom:norman-shades-card" }); c._hass = hass;
  check("_hubName returns the hub device's name", c._hubName() === "Lakehouse Shades", String(c._hubName()));
}
{
  // Each of the hub's rooms is a device too, with sliders and buttons but no cover. Listed
  // ahead of the hub, it must neither name the card nor be drawn as a blind.
  const withRoom = {
    ...hass,
    entities: {
      "number.den_den_bottom_rail_position": { platform:"norman", device_id:"r1", translation_key:"room_bottom_rail_position" },
      "button.den_den_stop": { platform:"norman", device_id:"r1", translation_key:"room_stop" },
      ...hass.entities,
    },
    devices: { r1:{ name:"Den", area_id:"a2" }, ...hass.devices },
  };
  const c = new Card(); c._hass = withRoom; c.setConfig({ type:"custom:norman-shades-card" }); c._hass = withRoom;
  check("a room device is not taken for the hub", c._hubName() === "Lakehouse Shades", String(c._hubName()));
  check("...nor drawn as a blind", c._collectBlinds().length === 2, JSON.stringify(c._collectBlinds().map(b => b.name)));
}
check("with no title the header shows the hub name", headerTextOf({}) === "Lakehouse Shades", String(headerTextOf({})));
check("an explicit title still wins", headerTextOf({ title:"Upstairs" }) === "Upstairs");
// A user who deliberately blanks the title should get a blank header, not the hub name.
check("an explicit empty title is respected", headerTextOf({ title:"" }) === "", JSON.stringify(headerTextOf({ title:"" })));
{
  // The hub is named as the Norman app has it (the device's own name, which the integration keeps
  // in step with the app), even where its device has been renamed in Home Assistant.
  const hubAs = (device) => ({ ...hass, devices: { ...hass.devices, hub:{ area_id:null, ...device } } });
  const renamed = hubAs({ name:"Lakehouse Shades", name_by_user:"Norman Hub" });
  check("the Norman app's name wins over a rename in Home Assistant", headerTextOf({}, renamed) === "Lakehouse Shades",
        headerTextOf({}, renamed));
  // Until the hub has said its name the device has the entry's placeholder: a name given in Home
  // Assistant is better, and with none the placeholder is still a name.
  const unread = hubAs({ name:"Norman Hub (192.168.1.50)", name_by_user:"Hallway Hub" });
  check("until the hub has said its name, a rename in Home Assistant names it", headerTextOf({}, unread) === "Hallway Hub",
        headerTextOf({}, unread));
  const placeholder = hubAs({ name:"Norman Hub (192.168.1.50)" });
  check("...and with none, the placeholder does", headerTextOf({}, placeholder) === "Norman Hub (192.168.1.50)",
        headerTextOf({}, placeholder));
  const unnamed = hubAs({ name:null, name_by_user:"Hallway Hub" });
  check("a device with no name of its own is named as in Home Assistant", headerTextOf({}, unnamed) === "Hallway Hub",
        headerTextOf({}, unnamed));
}
{
  const noHub = { ...hass, devices: { d1:hass.devices.d1, d2:hass.devices.d2 } };
  check("with no hub device the header falls back to Shades", headerTextOf({}, noHub) === "Shades");
}
{
  // The header is built once, so a later rename has to be patched in by _update.
  const c = rendered();
  c.hass = { ...hass, devices: { ...hass.devices, hub:{ name:"Renamed Hub", area_id:null } } };
  check("the header follows a hub rename", byClass(c.shadowRoot, "header-text")[0].textContent === "Renamed Hub");
}
check("a configured title always wins, even 'Shades'", headerTextOf({ title:"Shades" }) === "Shades");
{
  // A dashboard hands a card a changed config with setConfig alone (hui-card), and hass only
  // with the next state change in the house: the card draws itself with the hass it has.
  const c = new Card();
  c.setConfig({ type:"custom:norman-shades-card" });
  c.hass = hass;
  c.setConfig({ type:"custom:norman-shades-card", title:"Upstairs", hide_picture:true });
  check("a new config is drawn at once, without waiting for the next hass",
        byClass(c.shadowRoot, "header-text")[0]?.textContent === "Upstairs" && byClass(c.shadowRoot, "row").length === 2,
        JSON.stringify(byClass(c.shadowRoot, "header-text").map((x) => x.textContent)));
  const before = new Card();
  before.setConfig({ type:"custom:norman-shades-card" });
  check("...and a card with no hass yet waits for it", before.shadowRoot.children.length === 0);
}
{
  const empty = { ...hass, devices: {} };
  const c = new Card();
  c._hass = empty; c.setConfig({ type:"custom:norman-shades-card" }); c.hass = empty;
  check("before the registry loads the header falls back", byClass(c.shadowRoot, "header-text")[0].textContent === "Shades");
  c.hass = hass;
  check("the header fills in once devices arrive", byClass(c.shadowRoot, "header-text")[0].textContent === "Lakehouse Shades");
}
check("the stub config does not hardcode a title",
      Card.getStubConfig().title === undefined, JSON.stringify(Card.getStubConfig()));

// --- house-wide controls ----------------------------------------------------------------
const homeCalls = [];
const homeCard = new Card();
homeCard._hass = { ...hass, callService: (d,s2,data) => homeCalls.push([d,s2,data]) };
homeCard.setConfig({ type:"custom:norman-shades-card" });
homeCard._hass = { ...hass, callService: (d,s2,data) => homeCalls.push([d,s2,data]) };
const home = homeCard._buildHomeControls();
check("home controls render 3 buttons (no stop)", home.children.length === 3, String(home.children.length));
[...home.children].forEach(b => b._on?.click?.());
check("home buttons call norman.room_command",
      homeCalls.length === 3 && homeCalls.every(c => c[0]==="norman" && c[1]==="room_command"),
      JSON.stringify(homeCalls));
check("home controls send best_privacy / best_view / favorite",
      JSON.stringify(homeCalls.map(c => c[2].command)) === JSON.stringify(["best_privacy","best_view","favorite"]));
// They are the app's named presets, not open/close: a down arrow would promise both
// fabrics down, but best_privacy leaves the middle rail fully open.
const homeIcons = [...home.children].map(b => b.children[0]?.getAttribute?.("icon"));
check("house buttons are not labelled as open/close arrows",
      !homeIcons.includes("mdi:arrow-up") && !homeIcons.includes("mdi:arrow-down"), JSON.stringify(homeIcons));
// The absence of `room` is what makes it house-wide; sending one would scope it to a room.
check("home controls omit the room entirely", homeCalls.every(c => !("room" in c[2])));
// With no hub configured, and none named by its blinds' devices, the action picks the only one,
// as it always has.
check("an unpinned card with no hub to go on sends none", homeCalls.every(c => !("config_entry_id" in c[2])));
check("home controls render by default", countIn({}, "home-buttons") === 3);
check("home controls render alongside a title", countIn({ title:"Shades" }, "home-buttons") === 3);
check("home controls drop out when hidden", countIn({ hide_home_controls:true }, "home-buttons") === 0);

// --- one hub of several -------------------------------------------------------------------
// The frontend's device registry lists each device's config entries; config_entry_id keeps the
// card to that hub's devices and sends its presets to that hub.
{
  const twoHubs = {
    ...hass,
    entities: {
      ...hass.entities,
      "cover.cabin_1_bottom_rail": { platform:"norman", device_id:"c1", translation_key:"bottom_rail" },
      "sensor.cabin_hub_wi_fi_network": { platform:"norman", device_id:"hub2", translation_key:"wifi_ssid" },
    },
    devices: {
      d1: { ...hass.devices.d1, config_entries:["home"] },
      d2: { ...hass.devices.d2, config_entries:["home"] },
      hub: { ...hass.devices.hub, config_entries:["home"] },
      c1: { name:"Cabin_1", area_id:null, config_entries:["cabin"] },
      hub2: { name:"Cabin Hub", area_id:null, config_entries:["cabin"] },
    },
    states: { ...hass.states, "cover.cabin_1_bottom_rail": { state:"open", attributes:{ current_position:0 } } },
  };
  const svc = [];
  const scoped = (cfg) => {
    const h = { ...twoHubs, callService: (d,s2,data) => svc.push([d,s2,data]) };
    const c = new Card(); c._hass = h; c.setConfig({ type:"custom:norman-shades-card", ...cfg }); c._hass = h;
    return c;
  };
  check("with no hub configured, every hub's blinds show", scoped({})._collectBlinds().length === 3);
  const cabin = scoped({ config_entry_id:"cabin" });
  const cabinIds = cabin._collectBlinds().map(b => b.deviceId);
  check("config_entry_id shows only that hub's blinds", JSON.stringify(cabinIds) === '["c1"]', JSON.stringify(cabinIds));
  check("...and names that hub", cabin._hubName() === "Cabin Hub", String(cabin._hubName()));
  const home = scoped({ config_entry_id:"home" });
  check("the other hub's card shows the other hub",
        home._collectBlinds().length === 2 && home._hubName() === "Lakehouse Shades", String(home._hubName()));
  [...cabin._buildHomeControls().children, ...cabin._buildRoomPresets("Den", cabin._collectBlinds()).children].forEach(b => b._on?.click?.());
  check("a pinned card's presets go to its hub",
        svc.length === 6 && svc.every(x => x[1] === "room_command" && x[2].config_entry_id === "cabin"),
        JSON.stringify(svc.map(x => x[2])));
  check("...the house ones naming no room or blinds, the room's naming its blinds",
        !("room" in svc[0][2]) && !("blinds" in svc[0][2]) && JSON.stringify(svc[3][2].blinds) === '["cover.cabin_1_bottom_rail"]',
        JSON.stringify(svc.map(x => x[2])));

  // With no hub configured the card shows both hubs' blinds, and the action cannot pick a hub
  // itself: each preset goes to the hubs its blinds are on, read from their devices.
  const h = {
    ...twoHubs,
    devices: { ...twoHubs.devices, c1:{ ...twoHubs.devices.c1, area_id:"a3" } },
    areas: { ...twoHubs.areas, a3:{ name:"Cabin" } },
    callService: (d,s2,data) => svc.push([d,s2,data]),
  };
  const both = rendered({}, h);
  // Its heading: neither hub's name for a card showing both hubs' blinds. A configured title
  // still wins, a pinned card names its hub, and a card showing one hub's blinds names that
  // one, not another hub set up beside it.
  check("an unpinned card showing two hubs' blinds is headed Shades, not one hub's name",
        byClass(both.shadowRoot, "header-text")[0]?.textContent === "Shades",
        byClass(both.shadowRoot, "header-text")[0]?.textContent);
  check("...while a configured title still wins, and a pinned card names its hub",
        headerTextOf({ title:"Upstairs" }, h) === "Upstairs" && headerTextOf({ config_entry_id:"cabin" }, h) === "Cabin Hub",
        `${headerTextOf({ title:"Upstairs" }, h)} ${headerTextOf({ config_entry_id:"cabin" }, h)}`);
  const cabinFirst = { ...h, entities: { "sensor.cabin_hub_wi_fi_network": h.entities["sensor.cabin_hub_wi_fi_network"], ...hass.entities } };
  check("an unpinned card showing one hub's blinds names that hub, though another is listed first",
        headerTextOf({}, cabinFirst) === "Lakehouse Shades", headerTextOf({}, cabinFirst));
  const presetsOf = (room) => byClass(byClass(both.shadowRoot, "room")
    .find((r) => byClass(r, "room-name")[0]?.textContent === room), "room-presets")[0].children;
  svc.length = 0;
  presetsOf("Cabin")[0]._on.click();
  presetsOf("Den")[0]._on.click();
  check("an unpinned card sends a room's presets, naming its blinds, to their hub",
        JSON.stringify(svc.map((x) => x[2])) === JSON.stringify([
          { command:"best_privacy", blinds:["cover.cabin_1_bottom_rail"], config_entry_id:"cabin" },
          { command:"best_privacy", blinds:["cover.den_1_bottom_rail"], config_entry_id:"home" }]),
        JSON.stringify(svc.map((x) => x[2])));
  svc.length = 0;
  byClass(both.shadowRoot, "home-buttons")[0].children[1]._on.click();
  check("...and the house's to each hub on the card, one call each",
        svc.length === 2 && svc.every((x) => x[1] === "room_command" && x[2].command === "best_view" && !("room" in x[2])) &&
        JSON.stringify(svc.map((x) => x[2].config_entry_id).sort()) === '["cabin","home"]',
        JSON.stringify(svc.map((x) => x[2])));
  // A blind another integration has added itself to lists that entry too, and the device
  // registry names the hub's as its primary entry: the one that created the device.
  const presetIn = (card, room) => byClass(byClass(card.shadowRoot, "room")
    .find((r) => byClass(r, "room-name")[0]?.textContent === room), "room-presets")[0].children[0];
  const shared = { ...h, devices: { ...h.devices,
    c1:{ ...h.devices.c1, config_entries:["battery_notes", "cabin"], primary_config_entry:"cabin" } } };
  svc.length = 0;
  presetIn(rendered({}, shared), "Cabin")._on.click();
  check("a blind with a second integration's entry still finds its hub",
        svc.length === 1 && svc[0][2].config_entry_id === "cabin", JSON.stringify(svc.map((x) => x[2])));
  // ...even when that integration is on every one of the hub's devices, listed first: no count
  // of entries tells the two apart.
  const everywhere = { ...h, devices: Object.fromEntries(Object.entries(h.devices).map(([id, device]) =>
    [id, device.config_entries[0] === "home"
      ? { ...device, config_entries:["other_integration", "home"], primary_config_entry:"home" } : device])) };
  svc.length = 0;
  presetIn(rendered({}, everywhere), "Den")._on.click();
  check("...even when every device of that hub lists the other entry first",
        svc.length === 1 && svc[0][2].config_entry_id === "home", JSON.stringify(svc.map((x) => x[2])));
  // Newer Home Assistant versions name a device's one entry (config_entry_id); older ones list them.
  const single = Object.fromEntries(Object.entries(twoHubs.devices).map(([id, { config_entries, ...device }]) =>
    [id, { ...device, config_entry_id: config_entries[0] }]));
  const current = scoped({ config_entry_id:"cabin" });
  current._hass = { ...current._hass, devices: single };
  check("a device with only config_entry_id is still on its hub's card",
        JSON.stringify(current._collectBlinds().map((b) => b.deviceId)) === '["c1"]' &&
        current._entryOf("c1") === "cabin");

  // A hub that failed to set up leaves its blinds on the card, restored as unavailable, and the
  // action refuses a call naming it (entry_not_loaded). The house's presets go to the hubs whose
  // blinds are there.
  const unloaded = { ...h, states: { ...h.states, "cover.cabin_1_bottom_rail": { state:"unavailable", attributes:{ restored:true } } } };
  const half = rendered({}, unloaded);
  svc.length = 0;
  byClass(half.shadowRoot, "home-buttons")[0].children[0]._on.click();
  check("an unpinned card leaves a hub with no blind available out of the house's presets",
        JSON.stringify(svc.map((x) => x[2])) === JSON.stringify([{ command:"best_privacy", config_entry_id:"home" }]),
        JSON.stringify(svc.map((x) => x[2])));
  // With every one of them unavailable they all count: a call naming no hub would only have the
  // action ask which hub was meant (multiple_hubs), when it can say what is wrong with this one.
  svc.length = 0;
  presetIn(half, "Cabin")._on.click();
  check("...and a room whose blinds are all unavailable still names their hub",
        JSON.stringify(svc.map((x) => x[2])) ===
          JSON.stringify([{ command:"best_privacy", blinds:["cover.cabin_1_bottom_rail"], config_entry_id:"cabin" }]),
        JSON.stringify(svc.map((x) => x[2])));
  const down = { ...unloaded, states: { ...unloaded.states,
    "cover.front_bedroom_1_bottom_rail": { state:"unavailable", attributes:{} },
    "cover.den_1_bottom_rail": { state:"unavailable", attributes:{} } } };
  svc.length = 0;
  byClass(rendered({}, down).shadowRoot, "home-buttons")[0].children[1]._on.click();
  check("...as does the house's preset with every blind on the card unavailable",
        svc.length === 2 && JSON.stringify(svc.map((x) => x[2].config_entry_id).sort()) === '["cabin","home"]',
        JSON.stringify(svc.map((x) => x[2])));
  svc.length = 0;
  byClass(rendered({}, down).shadowRoot, "home-refresh")[0].children[0]._on.click();
  check("...and the header's refresh",
        svc.length === 2 && svc.every((x) => x[2].command === "refresh") &&
        JSON.stringify(svc.map((x) => x[2].config_entry_id).sort()) === '["cabin","home"]',
        JSON.stringify(svc.map((x) => x[2])));
}

// --- refresh ------------------------------------------------------------------------------
// A refresh asks blinds to report in, and nothing moves. A blind's tile presses its Request
// status button; a room's tray presses the Request status of each blind shown in it, and the
// header sends norman.room_command's refresh with no room, for the whole house. A press turns the icon once, and a second press
// of the same control within REFRESH_HOLD_MS is ignored.
{
  const fs = await import("node:fs");
  const strings = JSON.parse(fs.readFileSync(new URL("../strings.json", url), "utf8"));
  check("the card's Request status key is a button the integration declares",
        Boolean(REQUEST_STATUS && strings.entity.button[REQUEST_STATUS]), String(REQUEST_STATUS));
  check("the card offers no Report battery levels button, which can close shades", !/report_battery/.test(cardSource));

  const svc = [];
  // The hub's and a room's own refresh and Report battery levels buttons are there too: the
  // card presses none of them.
  const refreshHass = (extra = {}) => ({
    ...hass,
    entities: {
      ...hass.entities,
      "button.norman_hub_refresh_blinds": { platform:"norman", device_id:"hub", translation_key:"refresh_blinds" },
      "button.norman_hub_report_battery_levels": { platform:"norman", device_id:"hub", translation_key:"report_battery_levels" },
      "button.den_refresh_blinds": { platform:"norman", device_id:"r2", translation_key:"room_refresh" },
      "button.den_report_battery_levels": { platform:"norman", device_id:"r2", translation_key:"room_report_battery_levels" },
      ...extra.entities,
    },
    devices: { ...hass.devices, r2:{ name:"Den", area_id:"a2" }, ...extra.devices },
    areas: { ...hass.areas, ...extra.areas },
    states: { ...hass.states, ...extra.states },
    callService: (d, s2, data) => { svc.push([d, s2, data]); return Promise.resolve(); },
  });
  const cellOf = (c, id) => c._cells.find((x) => x.blind.deviceId === id);
  const sectionOf = (c, room) => byClass(c.shadowRoot, "room").find((r) => byClass(r, "room-name")[0]?.textContent === room);
  const roomRefresh = (c, room) => byClass(sectionOf(c, room), "room-refresh")[0]?.children[0];
  const homeRefresh = (c) => byClass(c.shadowRoot, "home-refresh")[0]?.children[0];

  // On every tile, in both layouts, beside the battery.
  for (const cfg of [{}, { hide_picture:true }]) {
    const layout = cfg.hide_picture ? "list" : "grid";
    const c = rendered(cfg, refreshHass());
    check(`${layout}: every blind has a refresh button`, c._cells.every((x) => x.refreshEl?.tagName === "button"));
    const den = cellOf(c, "d2");
    const bottom = byClass(den.tile, "meta-bottom")[0];
    check(`${layout}: ...beside its battery`,
          bottom.children.indexOf(den.refreshEl) === bottom.children.indexOf(den.batteryEl) + 1,
          JSON.stringify(bottom.children.map((ch) => ch.className)));
    check(`${layout}: ...with the refresh icon, named for the blind`,
          den.refreshEl.children[0].getAttribute("icon") === "mdi:refresh" && den.refreshEl.title === "Refresh Den_1" &&
          den.refreshEl.attrs["aria-label"] === "Refresh Den_1", den.refreshEl.title);
    svc.length = 0;
    den.refreshEl._on.click();
    check(`${layout}: ...which presses the blind's Request status`,
          JSON.stringify(svc) === JSON.stringify([["button", "press", { entity_id:"button.den_1_request_status" }]]),
          JSON.stringify(svc));
  }
  {
    // A hidden Request status, or one disabled (and so not in the frontend's registry), gives none.
    const hidden = refreshHass({ entities: { "button.den_1_request_status": { ...hass.entities["button.den_1_request_status"], hidden:true } } });
    const missing = refreshHass();
    delete missing.entities["button.front_bedroom_1_request_status"];
    check("a blind whose Request status is hidden has no refresh", cellOf(rendered({}, hidden), "d2").refreshEl === null);
    check("...nor one whose Request status is disabled", cellOf(rendered({}, missing), "d1").refreshEl === null);
    const c = rendered({}, refreshHass({ states: { "button.den_1_request_status": { state:"unavailable" } } }));
    check("a blind's refresh is greyed out while its Request status is unavailable",
          cellOf(c, "d2").refreshEl.disabled === true && cellOf(c, "d1").refreshEl.disabled === false);
    c.hass = refreshHass();
    check("...and comes back with it", cellOf(c, "d2").refreshEl.disabled === false);
  }

  // The acknowledgment, and the hold on repeats.
  {
    const c = rendered({}, refreshHass());
    const button = cellOf(c, "d2").refreshEl;
    svc.length = 0;
    button._on.click();
    check("a refresh press turns its icon", button.classList.contains("spin"));
    button._on.click();
    check("a second press of it straight away sends nothing", svc.length === 1, JSON.stringify(svc));
    c.hass = refreshHass({ devices: { d2:{ ...hass.devices.d2, name_by_user:"Den window" } } });
    const rebuilt = cellOf(c, "d2").refreshEl;
    rebuilt._on.click();
    check("...nor once the tile is rebuilt", rebuilt !== button && svc.length === 1, JSON.stringify(svc));
    cellOf(c, "d1").refreshEl._on.click();
    roomRefresh(c, "Den")._on.click();
    homeRefresh(c)._on.click();
    check("each refresh control is held on its own", svc.length === 4, JSON.stringify(svc));
    const now = Date.now;
    Date.now = () => now() + REFRESH_HOLD_MS;
    try {
      rebuilt._on.click();
    } finally {
      Date.now = now;
    }
    check("...and sends again once its hold is over", svc.length === 5 && svc[4][2].entity_id === "button.den_1_request_status",
          JSON.stringify(svc.at(-1)));
    await new Promise((resolve) => setTimeout(resolve, REFRESH_SPIN_MS + 50));
    check("the icon stops turning after a moment", !button.classList.contains("spin") && !rebuilt.classList.contains("spin"));
  }

  // A room's: at the end of its tray, and sent to the hub as the room's refresh.
  {
    const c = rendered({}, refreshHass());
    const chip = roomRefresh(c, "Den");
    check("a room's tray ends with its refresh",
          byClass(sectionOf(c, "Den"), "tray")[0].children.at(-1).className === "segmented room-refresh" &&
          chip.children[0].getAttribute("icon") === "mdi:refresh" && chip.children[1].textContent === "Refresh" &&
          chip.title === "Refresh every blind in Den", chip?.title);
    svc.length = 0;
    chip._on.click();
    check("...which presses the Request status of each blind shown in it",
          JSON.stringify(svc) === JSON.stringify([["button", "press", { entity_id:"button.den_1_request_status" }]]), JSON.stringify(svc));
    check("...and turns, rather than flashing as a preset does", chip.classList.contains("spin") && !chip.classList.contains("sent"));
  }
  {
    // Blinds in no area are in no room of the hub's: the presets name them, and the refresh
    // presses each one's own button.
    const c = rendered({}, refreshHass({ devices: { d1:{ ...hass.devices.d1, area_id:null }, d2:{ ...hass.devices.d2, area_id:null } } }));
    const section = sectionOf(c, "Unassigned");
    check("blinds in no area get the presets and the refresh in their tray",
          JSON.stringify(byClass(section, "tray")[0]?.children.map((ch) => ch.className)) ===
            '["segmented room-presets","segmented room-refresh"]');
    check("...behind a ⋯ named for its presets", byClass(section, "more")[0]?.title === "Presets for Unassigned",
          byClass(section, "more")[0]?.title);
    svc.length = 0;
    roomRefresh(c, "Unassigned")._on.click();
    check("...which presses each blind's Request status, in one call",
          svc.length === 1 && svc[0][0] === "button" && svc[0][1] === "press" &&
          JSON.stringify([...svc[0][2].entity_id].sort()) === '["button.den_1_request_status","button.front_bedroom_1_request_status"]',
          JSON.stringify(svc));
  }

  // The whole house's: in the header, beside the presets.
  {
    const c = rendered({}, refreshHass());
    const order = byClass(c.shadowRoot, "header")[0].children.map((child) => child.className);
    check("the header's refresh sits beside the whole-house presets",
          order.indexOf("segmented home-buttons") === order.indexOf("icon-group home-refresh") + 1, JSON.stringify(order));
    const button = homeRefresh(c);
    check("...titled for the whole house", button.title === "Refresh every blind" && button.children[0].getAttribute("icon") === "mdi:refresh");
    svc.length = 0;
    button._on.click();
    check("...which sends the refresh with no room",
          JSON.stringify(svc) === JSON.stringify([["norman", "room_command", { command:"refresh" }]]), JSON.stringify(svc));
  }

  // Two hubs on an unpinned card: each refresh goes to the hubs its blinds are on.
  {
    const two = refreshHass({
      entities: {
        "cover.cabin_1_bottom_rail": { platform:"norman", device_id:"c1", translation_key:"bottom_rail" },
        "button.cabin_1_request_status": { platform:"norman", device_id:"c1", translation_key:"request_status" },
        "sensor.cabin_hub_wi_fi_network": { platform:"norman", device_id:"hub2", translation_key:"wifi_ssid" },
      },
      devices: {
        d1:{ ...hass.devices.d1, config_entries:["home"] },
        d2:{ ...hass.devices.d2, config_entries:["home"] },
        hub:{ ...hass.devices.hub, config_entries:["home"] },
        c1:{ name:"Cabin_1", area_id:"a3", config_entries:["cabin"] },
        hub2:{ name:"Cabin Hub", area_id:null, config_entries:["cabin"] },
      },
      areas: { a3:{ name:"Cabin" } },
      states: { "cover.cabin_1_bottom_rail": { state:"open", attributes:{ current_position:0 } },
                "button.cabin_1_request_status": { state:"unknown" } },
    });
    const c = rendered({}, two);
    svc.length = 0;
    roomRefresh(c, "Cabin")._on.click();
    check("a room's refresh needs no hub: it presses the blinds' own buttons",
          JSON.stringify(svc) === JSON.stringify([["button", "press", { entity_id:"button.cabin_1_request_status" }]]),
          JSON.stringify(svc));
    svc.length = 0;
    homeRefresh(c)._on.click();
    check("...and the house's to each hub on the card, one call each",
          svc.length === 2 && svc.every((x) => x[1] === "room_command" && x[2].command === "refresh" && !("room" in x[2])) &&
          JSON.stringify(svc.map((x) => x[2].config_entry_id).sort()) === '["cabin","home"]',
          JSON.stringify(svc.map((x) => x[2])));
    svc.length = 0;
    homeRefresh(rendered({ config_entry_id:"cabin" }, two))._on.click();
    check("a pinned card's house refresh goes to its hub",
          JSON.stringify(svc.map((x) => x[2])) === JSON.stringify([{ command:"refresh", config_entry_id:"cabin" }]),
          JSON.stringify(svc.map((x) => x[2])));
  }

  // What the options take away.
  {
    const count = (cfg, name) => byClass(rendered(cfg, refreshHass()).shadowRoot, name).length;
    check("by default: a refresh per blind and per room, and one for the house",
          count({}, "refresh") === 2 && count({}, "room-refresh") === 2 && count({}, "home-refresh") === 1);
    check("hide_refresh takes every one away, in both layouts",
          [{}, { hide_picture:true }].every((cfg) => ["refresh", "room-refresh", "home-refresh"]
            .every((name) => count({ ...cfg, hide_refresh:true }, name) === 0)));
    check("hide_home_controls takes the house's with the presets, and leaves the rest",
          count({ hide_home_controls:true }, "home-refresh") === 0 && count({ hide_home_controls:true }, "room-refresh") === 2 &&
          count({ hide_home_controls:true }, "refresh") === 2);
    const c = rendered({ hide_room_presets:true }, refreshHass());
    const trays = byClass(c.shadowRoot, "tray");
    check("hide_room_presets leaves each room's ⋯ with only its refresh",
          trays.length === 2 && trays.every((t) => JSON.stringify(t.children.map((ch) => ch.className)) === '["segmented room-refresh"]') &&
          byClass(sectionOf(c, "Den"), "more")[0]?.title === "More for Den",
          JSON.stringify(trays.map((t) => t.children.map((ch) => ch.className))));
    check("...and with hide_refresh too, no ⋯ at all",
          count({ hide_room_presets:true, hide_refresh:true }, "more") === 0 && count({ hide_room_presets:true, hide_refresh:true }, "tray") === 0);
  }

  // Every refresh control, pressed: none presses the hub's or a room's own buttons.
  {
    const c = rendered({}, refreshHass({ devices: { d1:{ ...hass.devices.d1, area_id:null } } }));
    svc.length = 0;
    for (const cell of c._cells) cell.refreshEl._on.click();
    for (const chip of byClass(c.shadowRoot, "room-refresh")) chip.children[0]._on.click();
    homeRefresh(c)._on.click();
    check("no refresh presses a Report battery levels button, or the hub's or a room's own refresh",
          svc.length === 5 && svc.every((x) => !/report_battery|refresh_blinds/.test(JSON.stringify(x))), JSON.stringify(svc));
  }
}

// --- the sidebar panel's menu button -------------------------------------------------------
{
  const [menu] = byClass(rendered().shadowRoot, "menu");
  check("on a dashboard the menu button stays hidden", menu?.hidden === true, String(menu?.hidden));
  const c = new Card();
  c.setAttribute("panel", "");
  c._hass = hass; c.setConfig({ type:"custom:norman-shades-card" }); c.hass = hass;
  const [panelMenu] = byClass(c.shadowRoot, "menu");
  check("in the panel beside a visible sidebar it stays hidden", panelMenu?.hidden === true);
  c.narrow = true;
  check("on a phone the panel's header offers the sidebar", panelMenu.hidden === false);
  check("...and the card is marked narrow for its styles", c.hasAttribute("narrow"));
  panelMenu._on.click();
  const event = c._events?.at(-1);
  check("the button fires Home Assistant's own sidebar toggle",
        event?.type === "hass-toggle-menu" && event.bubbles && event.composed, String(event?.type));
  c.narrow = false;
  c.hass = { ...hass, dockedSidebar:"always_hidden" };
  check("it also shows wherever the user has hidden the sidebar", panelMenu.hidden === false);
  c.hass = hass;
  check("and goes again when the sidebar is back", panelMenu.hidden === true);
}

// --- the sidebar panel ----------------------------------------------------------------------
{
  const panelUrl = new URL("file://" + process.cwd() + "/custom_components/norman/www/norman-panel.js");
  panelUrl.searchParams.set("v", "test");
  await import(panelUrl.href);
  const Panel = els.get("norman-panel");
  check("the panel defines its element", typeof Panel === "function");
  const p = new Panel();
  p.hass = hass;
  p.narrow = true;
  p.panel = { url_path:"norman-shades", config:{ _panel_custom:{ name:"norman-panel" } } };
  // The panel imports the card (at the same ?v=) before it mounts it.
  await new Promise((resolve) => setTimeout(resolve, 0));
  const hosted = p._card;
  check("the panel hosts the card", hosted instanceof Card, String(hosted?.constructor?.name));
  check("...marked as the panel's", hosted?.hasAttribute("panel") === true);
  check("...with Home Assistant's narrow passed on", hosted?.narrow === true && p.hasAttribute("narrow"));
  check("...and none of Home Assistant's bookkeeping in its config",
        hosted && !("_panel_custom" in hosted._config) && hosted._config.type === "custom:norman-shades-card",
        JSON.stringify(hosted?._config));
  check("...drawn straight away", byClass(hosted.shadowRoot, "header-text")[0]?.textContent === "Lakehouse Shades");
  p.panel = { url_path:"norman-shades", config:{ config_entry_id:"home", _panel_custom:{} } };
  check("a hub pinned by the integration reaches the card", hosted._config.config_entry_id === "home");
  check("...and the card redraws for it", byClass(hosted.shadowRoot, "header-text").length === 1);
  p.narrow = false;
  check("narrow follows Home Assistant", hosted.narrow === false && !p.hasAttribute("narrow"));
}

// ---- the rendered card -----------------------------------------------------------------
const renderedText = (cfg = {}) => {
  const seen = [];
  findAll(rendered(cfg).shadowRoot, (el) => {
    if (el._text) seen.push(String(el._text));
    for (const k of ["title", "aria-label", "aria-valuetext"]) if (el.attrs?.[k]) seen.push(String(el.attrs[k]));
    return false;
  });
  return seen.join(" | ");
};
for (const cfg of [{}, { hide_picture:true }]) {
  const text = renderedText(cfg);
  const layout = cfg.hide_picture ? "list" : "grid";
  check(`${layout}: a rendered card shows no stray 'undefined'`, !text.includes("undefined"),
        text.split(" | ").filter(s => s.includes("undefined")).join(" ; "));
  check(`${layout}: a rendered card shows no stray 'NaN'`, !text.includes("NaN"),
        text.split(" | ").filter(s => s.includes("NaN")).join(" ; "));
}
{
  const c = rendered();
  check("each room lays its blinds out in one grid", byClass(c.shadowRoot, "grid").length === 2);
  check("every blind is a tile with a window", byClass(c.shadowRoot, "tile").length === 2 && byClass(c.shadowRoot, "win").length === 2);
  check("the summary counts the shades and the low battery",
        renderedText().includes("2 shades") && renderedText().includes("1 low battery"), renderedText().slice(0, 160));
  const [fbBattery, denBattery] = ["d1", "d2"].map(id => c._cells.find(x => x.blind.deviceId === id).batteryEl);
  check("every battery shows its percentage", fbBattery.lastChild.textContent === "84%" && fbBattery.title === "Battery 84%",
        fbBattery.lastChild.textContent);
  check("a low battery is marked", denBattery.lastChild.textContent === "12%" && denBattery.className.includes("critical"));
}

{
  // Home Assistant sets hass on every state change in the house; only the card's own
  // entities should cost a redraw.
  const c = rendered();
  let patched = 0;
  const original = c._patch.bind(c);
  c._patch = () => { patched += 1; original(); };
  c.hass = { ...hass, states: { ...hass.states, "light.kitchen": { state:"on" } } };
  check("an unrelated state change does not redraw", patched === 0, String(patched));
  c.hass = { ...hass, states: { ...hass.states, "sensor.den_1_battery": { state:"11" } } };
  check("a change to one of the card's own entities does", patched === 1, String(patched));
}
{
  // A redraw writes only the text and attributes that changed: a write of the same text still
  // costs the browser a fresh layout of the tile. Every write to a tile's text is recorded.
  for (const cfg of [{}, { hide_picture:true }]) {
    const layout = cfg.hide_picture ? "list" : "grid";
    const c = rendered(cfg);
    const writes = [];
    const watch = (node, label) => {
      if (!node) return;
      const text = Object.getOwnPropertyDescriptor(node, "textContent");
      Object.defineProperty(node, "textContent", { configurable:true, get: text.get,
        set(v) { writes.push(`${label} text`); text.set.call(this, v); } });
      const setAttribute = node.setAttribute;
      node.setAttribute = function (k, v) { writes.push(`${label} ${k}`); setAttribute.call(this, k, v); };
      let title = node.title;
      Object.defineProperty(node, "title", { configurable:true, get: () => title, set(v) { writes.push(`${label} title`); title = v; } });
    };
    for (const cell of c._cells) {
      const id = cell.blind.deviceId;
      watch(cell.status, `${id} status`);
      watch(cell.batteryEl, `${id} battery`);
      watch(cell.batteryEl?.firstChild, `${id} battery icon`);
      watch(cell.batteryEl?.lastChild, `${id} battery level`);
      for (const zone of cell.shade?.zones || []) watch(zone, `${id} rail`);
      for (const slider of cell.sliders) watch(slider.value, `${id} slider`);
    }
    c._patch();
    check(`${layout}: a redraw with nothing changed writes no text or attributes`, writes.length === 0, writes.join(", "));
    c.hass = { ...hass, states: { ...hass.states, "sensor.den_1_battery": { state:"11" } } };
    check(`${layout}: ...and a new battery level writes only that battery`,
          writes.length > 0 && writes.every((w) => w.startsWith("d2 battery")), writes.join(", "));
  }
}

// Nor should it scan the entity registry: Home Assistant replaces its registries only when they
// change, so what the card reads from them is kept until then. Counted by listing its keys.
let scans = 0;
const counted = (registry) => new Proxy(registry, { ownKeys: (target) => { scans += 1; return Reflect.ownKeys(target); } });
{
  const h = { ...hass, entities: counted(hass.entities) };
  const c = rendered({}, h);
  scans = 0;
  c.hass = { ...h, states: { ...h.states, "light.kitchen": { state:"on" } } };
  c.hass = { ...h, states: { ...h.states, "sensor.den_1_battery": { state:"11" } } };
  check("a state change does not scan the entity registry again", scans === 0, String(scans));
  c.hass = { ...h, entities: counted({ ...hass.entities }) };
  check("a new entity registry is read", scans > 0 && c._cells.length === 2, String(scans));
}
{
  // What the card reads from states still follows them without a registry scan: the side a
  // drape stacks to, and the name of a scene the registry leaves unnamed.
  const registry = {
    entities: counted({
      "cover.living_1_bottom_rail": { platform:"norman", device_id:"l1", translation_key:"bottom_rail" },
      "scene.living_evening": { platform:"norman", device_id:"r1", translation_key:"room_scene" },
    }),
    devices: { l1:{ name:"Living_1", area_id:"a1", model_id:"80/1" }, r1:{ name:"Living", area_id:"a1" } },
    areas: { a1:{ name:"Living" } },
  };
  const at = (stack, sceneName) => ({ ...registry, states: {
    "cover.living_1_bottom_rail": { state:"open", attributes:{ current_position:100, target_position:100, stack } },
    "scene.living_evening": { state:"unknown", attributes:{ friendly_name:sceneName } },
  } });
  const c = rendered({}, at("left", "Evening"));
  const sceneNames = () => byClass(c.shadowRoot, "room-scenes").flatMap((g) => g.children.map((chip) => chip.children[1].textContent));
  check("a drape stacking left is drawn with one side", c._cells[0]?.shade.parts.length === 1);
  check("an unnamed scene takes its state's name", JSON.stringify(sceneNames()) === '["Evening"]', JSON.stringify(sceneNames()));
  scans = 0;
  c.hass = at("split", "Evening");
  check("a drape that now stacks to both sides is redrawn split", c._cells[0]?.shade.parts.length === 2);
  c.hass = at("split", "Dusk");
  check("an unnamed scene follows its state's name", JSON.stringify(sceneNames()) === '["Dusk"]', JSON.stringify(sceneNames()));
  check("...neither by scanning the registry", scans === 0, String(scans));
  // Home Assistant leaves an unavailable entity's attributes out, `stack` with them: the drape
  // keeps its side meanwhile, rather than being redrawn gathering left and the card rebuilt
  // under the user's hands (a drag on another blind, a room's tray folded out).
  const tile = c._cells[0]?.tile;
  const unavailable = at("split", "Dusk");
  unavailable.states["cover.living_1_bottom_rail"] = { state:"unavailable", attributes:{} };
  c.hass = unavailable;
  check("a drape gone unavailable keeps the side it stacks to, without a rebuild",
        c._cells[0]?.tile === tile && c._cells[0].shade.parts.length === 2 && c._cells[0].shade.disabled === true,
        `${c._cells[0]?.tile === tile} ${c._cells[0]?.shade.parts.length}`);
  c.hass = at("split", "Dusk");
  check("...and nor is it rebuilt when it is back", c._cells[0]?.tile === tile && c._cells[0].shade.disabled === false);
  c.hass = at("left", "Dusk");
  check("...while a side the drape reports does redraw it", c._cells[0]?.shade.parts.length === 1);
}

{
  const c = rendered();
  c.hass = { ...hass, devices: { ...hass.devices, d2:{ name:"Den_1", name_by_user:"Den window", area_id:"a2" } } };
  check("a renamed blind is renamed on the card",
        c._cells.some(x => x.blind.name === "Den window"), JSON.stringify(c._cells.map(x => x.blind.name)));
}
{
  // Each tile is bound to its blind's entity ids, so an id that changes ("Recreate entity IDs"),
  // or an entity disabled or enabled, rebuilds the tile rather than leaving it on the old one.
  const renamed = { ...hass.entities, "cover.den_window": hass.entities["cover.den_1_bottom_rail"] };
  delete renamed["cover.den_1_bottom_rail"];
  const states = { ...hass.states, "cover.den_window": hass.states["cover.den_1_bottom_rail"] };
  delete states["cover.den_1_bottom_rail"];
  const c = rendered();
  c.hass = { ...hass, entities: renamed, states };
  const moved = c._cells.find((x) => x.blind.deviceId === "d2");
  check("a cover given a new entity id rebinds its tile",
        moved.blind.bottomCover === "cover.den_window" && moved.status.textContent === "90% open",
        `${moved.blind.bottomCover} ${moved.status.textContent}`);

  // A disabled entity leaves the frontend's registry: the card stops writing to it.
  const disabled = { ...hass.entities };
  delete disabled["number.den_1_bottom_rail_position"];
  c.hass = { ...hass, entities: disabled };
  calls.length = 0;
  c._move(c._cells.find((x) => x.blind.deviceId === "d2").rails, 0, 40);
  check("a disabled slider entity is no longer written; the cover is",
        JSON.stringify(calls) === JSON.stringify([["cover", "set_cover_position", { entity_id:"cover.den_1_bottom_rail", position:40 }]]),
        JSON.stringify(calls));
  c.hass = hass;
  check("...and the slider entity is written again once enabled",
        c._cells.find((x) => x.blind.deviceId === "d2").rails[0].numberId === "number.den_1_bottom_rail_position");
}

// ---- the status line -----------------------------------------------------------------
{
  const statusOf = (states, extra = {}) => {
    const h = { ...hass, states: { ...hass.states, ...states } };
    const c = rendered(extra, h);
    return Object.fromEntries(c._cells.map(x => [x.blind.deviceId, x]));
  };
  let cells = statusOf({});
  check("a single rail part-open reads as its percentage", cells.d2.status.textContent === "90% open", cells.d2.status.textContent);
  check("a two-rail blind at rest names both rails",
        cells.d1.status.textContent.replace(/ /g, " ") === "Middle 80% · Bottom 60%", cells.d1.status.textContent);
  const at = (bottom, middle) => ({
    "number.front_bedroom_1_bottom_rail_position": { state:String(bottom) },
    "number.front_bedroom_1_middle_rail_position": { state:String(middle) },
    "cover.front_bedroom_1_bottom_rail": { state:"open", attributes:{ current_position:bottom } },
    "cover.front_bedroom_1_middle_rail": { state:"open", attributes:{ current_position:middle } },
  });
  check("both rails up reads Open", statusOf(at(100, 100)).d1.status.textContent === "Open");
  check("both rails down reads Closed", statusOf(at(0, 0)).d1.status.textContent === "Closed");
  check("the app's Best privacy reads Privacy", statusOf(at(0, 100)).d1.status.textContent === "Privacy");

  // The hub reports target_position ahead of current_position for the whole travel.
  cells = statusOf({ "cover.den_1_bottom_rail": { state:"closing", attributes:{ current_position:90, target_position:30 } } });
  check("a moving rail says which way and where it is", cells.d2.status.textContent === "Closing · 90%", cells.d2.status.textContent);
  check("a moving rail's status is marked moving", cells.d2.status.classList.contains("moving"));
  check("a moving blind offers Stop", cells.d2.stop.hidden === false);
  check("an idle blind does not", cells.d1.stop.hidden === true);
  // One rail on the single-rail blind: travel is everything below the headrail but the rail.
  const railTopAt = (value) => HEAD + ((100 - value) / 100) * (100 - HEAD - RAIL);
  check("the picture draws a moving rail where it is going",
        near(parseFloat(cells.d2.shade.railEls[0].style.top), railTopAt(30)), cells.d2.shade.railEls[0].style.top);
  check("the marker shows where a moving rail actually is",
        cells.d2.shade.markers[0].classList.contains("on") &&
        near(parseFloat(cells.d2.shade.markers[0].style.top), railTopAt(90) + RAIL / 2),
        cells.d2.shade.markers[0].style.top);
  check("an idle rail has no marker", !cells.d1.shade.markers[0].classList.contains("on"));

  cells = statusOf({ "cover.front_bedroom_1_middle_rail": { state:"opening", attributes:{ current_position:80, target_position:100 } } });
  check("a moving middle rail is named", cells.d1.status.textContent.replace(/ /g, " ") === "Opening · Middle 80%", cells.d1.status.textContent);

  // The hub stores a target whether or not the blind hears the command, and keeps it and the
  // old position until the blind next reports in: a blind sat at bottom 100 heading for 0
  // for two hours, and had in fact closed. Past the move window the card says neither value
  // is confirmed, and draws the rail where it was sent with the marker where it was heard.
  const ago = (ms) => new Date(Date.now() - ms).toISOString();
  const den = (updated) => ({
    "cover.den_1_bottom_rail": { state:"open", last_updated: updated, attributes:{ current_position:90, target_position:30 } } });
  cells = statusOf(den(ago(60_000)));
  check("a target set a minute ago is still a move", cells.d2.status.textContent === "Closing · 90%", cells.d2.status.textContent);
  cells = statusOf(den(ago(10 * 60_000)));
  check("a move the hub never heard arrive reads Not confirmed", cells.d2.status.textContent === "Not confirmed", cells.d2.status.textContent);
  check("an unconfirmed move is not marked moving", !cells.d2.status.classList.contains("moving"));
  check("an unconfirmed move offers no Stop", cells.d2.stop.hidden === true);
  check("an unconfirmed move is drawn where it was sent",
        near(parseFloat(cells.d2.shade.railEls[0].style.top), railTopAt(30)), cells.d2.shade.railEls[0].style.top);
  check("an unconfirmed move marks where the hub last heard the rail",
        cells.d2.shade.markers[0].classList.contains("on") &&
        near(parseFloat(cells.d2.shade.markers[0].style.top), railTopAt(90) + RAIL / 2),
        cells.d2.shade.markers[0].style.top);
  {
    const summaryOf = (states) => {
      const summary = rendered({}, { ...hass, states: { ...hass.states, ...states } })._summary;
      return findAll(summary, (el) => el._text !== undefined).map((el) => String(el._text)).join("");
    };
    check("the summary counts a move under way", summaryOf(den(ago(60_000))).includes("1 moving"), summaryOf(den(ago(60_000))));
    check("the summary does not count an unconfirmed move", !summaryOf(den(ago(10 * 60_000))).includes("moving"),
          summaryOf(den(ago(10 * 60_000))));
  }
  const missed = (updated) => ({ ...at(100, 100),
    "cover.front_bedroom_1_bottom_rail": { state:"open", last_updated: updated, attributes:{ current_position:100, target_position:0 } } });
  check("a two-rail blind closing reads Closing",
        statusOf(missed(ago(30_000))).d1.status.textContent.replace(/ /g, " ") === "Closing · Bottom 100%",
        statusOf(missed(ago(30_000))).d1.status.textContent);
  check("a two-rail blind not heard closing reads Not confirmed",
        statusOf(missed(ago(4 * 60_000))).d1.status.textContent === "Not confirmed");

  // Writing the target the hub already holds restarts the window: the cover's state does not
  // change, so its last_updated would not.
  {
    const h = { ...hass, states: { ...hass.states, ...den(ago(10 * 60_000)) } };
    const c = rendered({}, h);
    const cell = c._cells.find((x) => x.blind.deviceId === "d2");
    c._setRail(cell.rails[0], 30);
    c._patch();
    check("sending a missed move again shows it moving", cell.status.textContent === "Closing · 90%", cell.status.textContent);
    clearTimeout(c._settleTimer);
  }

  // A rail whose move is not confirmed is drawn where it was sent, and sending it there again is
  // how to start a new move: the keys, a drag and a slider can all send the position it is drawn
  // at. A rail whose move is confirmed is not sent where it already is.
  {
    const writes = [];
    const h = { ...hass, states: { ...hass.states, ...den(ago(10 * 60_000)) },
      callService: (d, sv, data) => { writes.push([d, sv, data]); return Promise.resolve(); } };
    const valuesOf = () => JSON.stringify(writes.map((x) => [x[2].entity_id, x[2].value]));
    const DEN = "number.den_1_bottom_rail_position";
    let c = rendered({}, h);
    let cell = c._cells.find((x) => x.blind.deviceId === "d2");
    c._move(cell.rails, 0, 30);
    check("a missed move can be sent again to where it is drawn", valuesOf() === JSON.stringify([[DEN, 30]]), valuesOf());
    c._move(cell.rails, 0, 30);
    check("...once, not again while that send is under way", writes.length === 1, valuesOf());
    clearTimeout(c._settleTimer);

    writes.length = 0;
    c = rendered({}, h);
    cell = c._cells.find((x) => x.blind.deviceId === "d2");
    for (const k of ["ArrowUp", "ArrowDown"]) c._onKey(cell.shade, 0, { key:k, preventDefault() {} });
    c._sendKeys(cell.shade);
    check("...by the arrow keys, there and back", valuesOf() === JSON.stringify([[DEN, 30]]), valuesOf());
    clearTimeout(c._settleTimer);

    writes.length = 0;
    c = rendered({ hide_picture:true }, h);
    const [slider] = c._cells.find((x) => x.blind.deviceId === "d2").sliders;
    const { input } = slider;
    input._on.pointerdown();
    for (const v of ["40", "30"]) { input.value = v; input._on.input(); }
    input._on.pointerup();
    check("...and by a slider dragged away and back, which fires no `change`", valuesOf() === JSON.stringify([[DEN, 30]]), valuesOf());
    writes.length = 0;
    input._on.pointerdown();
    input._on.pointerup();
    check("...though a tap on it still sends nothing", writes.length === 0, valuesOf());
    clearTimeout(c._settleTimer);

    writes.length = 0;
    const atRest = { ...h, states: hass.states };
    c = rendered({ hide_picture:true }, atRest);
    const [still] = c._cells.find((x) => x.blind.deviceId === "d2").sliders;
    still.input._on.pointerdown();
    for (const v of ["80", "90"]) { still.input.value = v; still.input._on.input(); }
    still.input._on.pointerup();
    c._move(c._cells.find((x) => x.blind.deviceId === "d2").rails, 0, 90);
    check("a rail at rest is not sent where it already is", writes.length === 0, valuesOf());
  }

  // A write that fails is taken back: the rail is drawn where the hub has it, the rail it carried
  // along is drawn back too, and a missed move reads Not confirmed again rather than moving --
  // nothing reached the hub.
  {
    const failing = (states) => rendered({}, { ...hass, states: { ...hass.states, ...states },
      callService: () => Promise.reject(new Error("hub busy")) });
    const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
    const c = failing(den(ago(10 * 60_000)));
    const cell = c._cells.find((x) => x.blind.deviceId === "d2");
    c._move(cell.rails, 0, 60);
    c._patch();
    check("a write to a missed move shows it moving while it is sent", cell.status.textContent === "Closing · 90%",
          cell.status.textContent);
    await settle();
    check("...and once it fails, Not confirmed again, with no Stop",
          cell.status.textContent === "Not confirmed" && cell.stop.hidden === true && !c._pending.size && !c._sent.size,
          `${cell.status.textContent} stop hidden ${cell.stop.hidden} sent ${c._sent.size}`);
    clearTimeout(c._settleTimer);

    const two = failing({});   // Front_Bedroom_1: bottom 60, middle 80
    const fbCell = two._cells.find((x) => x.blind.deviceId === "d1");
    two._move(fbCell.rails, 0, 90);
    check("a rail raised past the other carries it, drawn there while the write is sent",
          two._railValue(fbCell.rails[1]) === 90, String(two._railValue(fbCell.rails[1])));
    await settle();
    check("...and a failed write takes the carried rail back as well",
          !two._pending.size && two._railValue(fbCell.rails[1]) === 80 && fbCell.stop.hidden === true &&
          fbCell.status.textContent.replace(/\s/g, " ") === "Middle 80% · Bottom 60%",
          `${fbCell.status.textContent} pending ${[...two._pending.keys()]}`);
    check("...with nothing left counting as sent", !two._sent.size, String([...two._sent.keys()]));
    clearTimeout(two._settleTimer);
  }

  // In the list layout the status line is hidden at rest, the sliders saying where the rails are;
  // it still says when a move is not confirmed, which no slider shows.
  {
    const listed = statusOf(den(ago(10 * 60_000)), { hide_picture:true }).d2.status;
    check("list: a move not confirmed is said, not hidden as at rest",
          listed.textContent === "Not confirmed" && !listed.classList.contains("rest"), listed.className);
    check("list: a blind at rest keeps its status hidden", statusOf({}, { hide_picture:true }).d2.status.classList.contains("rest"));
  }

  // The window closes on time even if no state changes by then.
  {
    const h = { ...hass, states: { ...hass.states, ...den(ago(MOVE_WINDOW_MS - 300)) } };
    const c = rendered({}, h);
    const cell = c._cells.find((x) => x.blind.deviceId === "d2");
    check("a move inside its window reads Closing", cell.status.textContent === "Closing · 90%", cell.status.textContent);
    await new Promise((resolve) => setTimeout(resolve, 600));
    check("the card redraws when the move window closes", cell.status.textContent === "Not confirmed", cell.status.textContent);
    clearTimeout(c._settleTimer);
  }

  cells = statusOf({ "cover.den_1_bottom_rail": { state:"unavailable", attributes:{} } });
  check("an unavailable blind says so", cells.d2.status.textContent === "Unavailable");
  check("an unavailable blind cannot be dragged", cells.d2.shade.disabled === true);
}

// ---- writing ------------------------------------------------------------------------------
{
  calls.length = 0;
  const c = rendered();
  const cell = c._cells.find(x => x.blind.deviceId === "d1");
  const [bottomRail, middleRail] = cell.rails;
  c._setRail(middleRail, 30);
  check("a rail is written through its number entity",
        JSON.stringify(calls.at(-1)) === JSON.stringify(["number","set_value",{ entity_id:"number.front_bedroom_1_middle_rail_position", value:30 }]),
        JSON.stringify(calls.at(-1)));
  c._patch();
  check("the chosen position is drawn while the hub takes it up", c._railValue(middleRail) === 30);
  // The hub takes it up: its target becomes the chosen value, and the pending entry retires.
  c.hass = { ...hass, states: { ...hass.states,
    "cover.front_bedroom_1_middle_rail": { state:"closing", attributes:{ current_position:80, target_position:30 } } } };
  check("the pending choice retires once the hub reports it as the target", !c._pending.has("number.front_bedroom_1_middle_rail_position"));
  check("...and the rail is still drawn at the target", c._railValue(middleRail) === 30);

  // Stop: the hub's stop is per blind, so one call, on the rail that is moving.
  calls.length = 0;
  cell.stop._on.click();
  check("stop sends one stop_cover", calls.length === 1 && calls[0][1] === "stop_cover", JSON.stringify(calls));
  check("stop targets the MOVING rail's own cover", calls[0]?.[2]?.entity_id === "cover.front_bedroom_1_middle_rail",
        JSON.stringify(calls[0]));
  calls.length = 0;
  c.hass = hass;
  c._stop([bottomRail, middleRail]);
  check("with nothing moving, stop goes to the bottom rail", calls[0]?.[2]?.entity_id === "cover.front_bedroom_1_bottom_rail",
        JSON.stringify(calls[0]));

  // Without a number entity the cover's own set_cover_position is used.
  calls.length = 0;
  c._setRail({ key:"bottom", label:"Bottom rail", coverId:"cover.x", numberId:null }, 40);
  check("a rail with no slider falls back to set_cover_position",
        JSON.stringify(calls[0]) === JSON.stringify(["cover","set_cover_position",{ entity_id:"cover.x", position:40 }]));
}

// ---- the shade picture --------------------------------------------------------------
// The picture's geometry is the part no amount of reading catches: a sign error puts the
// fabric at the wrong end of the window, and a band that starts below where it ends draws
// nothing at all. These pin the arithmetic that _drawShade and _clampRail perform.

check("the CSS headrail and the JS constant agree",
      HEAD === Number(/const SHADE_HEAD_PCT = ([\d.]+);/.exec(cardSource)[1]), String(HEAD));
check("the CSS rail and the JS constant agree",
      RAIL === Number(/const SHADE_RAIL_PCT = ([\d.]+);/.exec(cardSource)[1]), String(RAIL));

const pictureCard = () => { const c = new Card(); c._hass = hass; c.setConfig({ type:"custom:norman-shades-card" }); c._hass = hass; return c; };
const twoRail = pictureCard();
const twoRailBlind = twoRail._collectBlinds().find(b => b.middleCover);
const oneRail = pictureCard();
const oneRailBlind = oneRail._collectBlinds().find(b => !b.middleCover);
const oneRailCarried = () => oneRail._carried(oneRail._railsOf(oneRailBlind), 0, 50);
const shadeFor = (c, blind, values) => {
  const shade = c._buildShade(blind, c._railsOf(blind));
  // Drive the drawing off explicit values rather than whatever the fake hub reports.
  shade.dragValues = Object.fromEntries(values.map((v, i) => [i, v]));
  c._drawShade(shade);
  return shade;
};

const open = shadeFor(twoRail, twoRailBlind, [100, 100]);
check("open: the middle rail tucks under the headrail", near(top(open.railEls[1]), HEAD), open.railEls[1].style.top);
check("open: the bottom rail tucks under the middle rail", near(top(open.railEls[0]), HEAD + RAIL), open.railEls[0].style.top);
check("open: no fabric hangs", open.bands.every(b => height(b) === 0), open.bands.map(b => b.style.height).join(" "));

const closed = shadeFor(twoRail, twoRailBlind, [0, 0]);
check("closed: the bottom rail rests on the sill", near(top(closed.railEls[0]) + RAIL, 100), closed.railEls[0].style.top);
check("closed: the middle rail rests on the bottom rail", near(top(closed.railEls[1]) + RAIL, top(closed.railEls[0])));

const mixed = shadeFor(twoRail, twoRailBlind, [20, 80]);
const [lower, upper] = mixed.bands;
check("mixed: the upper band starts at the headrail", near(top(upper), HEAD), upper.style.top);
check("mixed: the upper band ends on the middle rail", near(top(upper) + height(upper), top(mixed.railEls[1])));
check("mixed: the lower band hangs from the middle rail", near(top(lower), top(mixed.railEls[1]) + RAIL));
check("mixed: the lower band ends on the bottom rail", near(top(lower) + height(lower), top(mixed.railEls[0])));
check("mixed: the middle rail sits above the bottom rail", top(mixed.railEls[1]) < top(mixed.railEls[0]));
check("mixed: each grab zone is centred on its rail",
      mixed.zones.every((z, i) => near(top(z), top(mixed.railEls[i]) + RAIL / 2)));

// Which fabric covers the window. On the blind the light-filtering sheer hangs above the
// middle rail and the blackout below it, so the app's Best privacy (bottom 0, middle 100)
// draws the blackout across the window and everything down draws the sheer.
const TRAVEL = 100 - HEAD - 2 * RAIL;
const covering = (values) => shadeFor(twoRail, twoRailBlind, values).bands
  .map((b) => ({ kind: b.className.includes("sheer") ? "sheer" : b.className.includes("blackout") ? "blackout" : "?", h: height(b) }))
  .filter((b) => b.h > 0.05)
  .map((b) => `${b.kind}:${Math.round(b.h)}`)
  .join(" ");
check("closed (0/0) is covered by the SHEER fabric", covering([0, 0]) === `sheer:${Math.round(TRAVEL)}`, covering([0, 0]));
check("Best privacy (0/100) is covered by the BLACKOUT fabric", covering([0, 100]) === `blackout:${Math.round(TRAVEL)}`, covering([0, 100]));
check("open (100/100) leaves the opening clear", covering([100, 100]) === "", covering([100, 100]));
check("part-open: sheer above the middle rail, blackout below",
      covering([20, 80]) === `blackout:${Math.round(TRAVEL * 0.6)} sheer:${Math.round(TRAVEL * 0.2)}`, covering([20, 80]));
check("the sheer is drawn see-through", /\.fabric\.sheer \{[^}]*backdrop-filter/.test(cardSource));

// Either rail can be moved anywhere. The middle rail hangs above the bottom one, so a rail
// taken past the other carries it along -- on the blind, and so in the picture.
{
  const rails2 = twoRail._railsOf(twoRailBlind);   // bottom 60, middle 80 from the fake hub
  check("carry: the bottom rail raised past the middle takes it up", twoRail._carried(rails2, 0, 95) === 95);
  check("carry: the middle rail lowered past the bottom takes it down", twoRail._carried(rails2, 1, 30) === 30);
  check("carry: a move that passes nothing leaves the other rail alone",
        twoRail._carried(rails2, 0, 10) === 80 && twoRail._carried(rails2, 1, 90) === 60);
  check("carry: a single-rail blind has nothing to carry", oneRailCarried() === null);

  const s2 = twoRail._buildShade(twoRailBlind, rails2);
  twoRail._dragTo(s2, 1, 30);
  check("dragging the middle rail below the bottom rail draws both moving",
        s2.dragValues[1] === 30 && s2.dragValues[0] === 30, JSON.stringify(s2.dragValues));
  twoRail._dragTo(s2, 1, 70);
  check("dragging back up puts the bottom rail back where it was", s2.dragValues[0] === undefined, JSON.stringify(s2.dragValues));

  // Released: ONE write, for the rail that was moved. The integration carries the other in
  // the same hub command; two writes could cross in flight and undo each other.
  const writes = [];
  const record = (d, sv, data) => { writes.push([d, sv, data]); return Promise.resolve(); };
  const c = new Card(); c._hass = { ...hass, callService: record };
  c.setConfig({ type:"custom:norman-shades-card" });
  c._hass = { ...hass, callService: record };
  const r = c._railsOf(twoRailBlind);
  c._move(r, 1, 20);
  check("moving the middle rail past the bottom rail writes once", writes.length === 1, JSON.stringify(writes));
  check("...to the middle rail", writes[0]?.[2]?.entity_id === "number.front_bedroom_1_middle_rail_position" && writes[0][2].value === 20,
        JSON.stringify(writes[0]));
  check("...and draws the bottom rail carried along", c._railValue(r[0]) === 20 && c._railValue(r[1]) === 20);
  writes.length = 0;
  c._move(r, 1, 20);
  check("moving a rail to where it already is writes nothing", writes.length === 0, JSON.stringify(writes));
}

// Arrow keys on one rail, then on the other before KEY_COMMIT_MS is up: a blind gathers one
// rail's keys at a time, so the first rail's move is sent when the second rail's keys begin.
// And a drag on a blind while keys are being gathered: on the same rail the drag takes the
// keys' move over and sends one move on release; on the other rail the keys' move goes first.
// Either way no key timer goes off mid-drag, and a release never sends the blind to 0.
{
  const recorder = () => {
    const writes = [];
    const card = rendered({}, { ...hass, callService: (d, sv, data) => { writes.push([d, sv, data]); return Promise.resolve(); } });
    return { card, writes, cell: (id) => card._cells.find((x) => x.blind.deviceId === id) };
  };
  let prevented = 0;
  const key = (k) => ({ key:k, preventDefault() { prevented += 1; } });
  const valuesOf = (writes) => JSON.stringify(writes.map((x) => [x[2].entity_id, x[2].value ?? x[2].position]));
  const MIDDLE = "number.front_bedroom_1_middle_rail_position", BOTTOM = "number.front_bedroom_1_bottom_rail_position";
  const DEN = "number.den_1_bottom_rail_position";

  const two = recorder();   // bottom 60, middle 80
  const { shade } = two.cell("d1");
  two.card._onKey(shade, 1, key("ArrowDown"));
  two.card._onKey(shade, 0, key("ArrowDown"));
  check("keys on the other rail first send the move gathered on this one",
        valuesOf(two.writes) === JSON.stringify([[MIDDLE, 70]]), valuesOf(two.writes));
  check("...which stays drawn while the other rail's keys are gathered",
        two.card._shadeValue(shade, 1) === 70 && shade.dragValues[0] === 50, JSON.stringify(shade.dragValues));

  // A mouse drag on a blind: the press, a move, and the release, in the opening's pixels.
  const drag = (card, target, index, from, to) => {
    target.opening.getBoundingClientRect = () => ({ top:0, left:0, width:100, height:100 });
    const at = (value) => card._railTop(target, index, value) + RAIL / 2;
    const pointer = (y) => ({ pointerId:1, pointerType:"mouse", button:0, clientX:50, clientY:y, target:target.zones[index], preventDefault() {} });
    return {
      press: () => target.element._on.pointerdown(pointer(at(from))),
      move: () => target.element._on.pointermove(pointer(at(to))),
      release: () => target.element._on.pointerup(pointer(at(to))),
      cancel: () => target.element._on.pointercancel(pointer(at(to))),
    };
  };
  // Keys take Den_1 from 90 to 80, then a drag of the same rail from there to 50.
  const one = recorder();
  const den = one.cell("d2").shade;
  one.card._onKey(den, 0, key("ArrowDown"));
  const dragDen = drag(one.card, den, 0, 80, 50);
  dragDen.press();
  dragDen.move();
  check("a drag of the rail the keys are moving takes their move over: nothing is sent as it starts",
        one.writes.length === 0, valuesOf(one.writes));

  // Keys on the middle rail, then a drag of the bottom rail: the keys' move goes as the drag starts.
  const other = recorder();
  const otherShade = other.cell("d1").shade;
  other.card._onKey(otherShade, 1, key("ArrowDown"));
  const dragOther = drag(other.card, otherShade, 0, 60, 30);
  dragOther.press();
  dragOther.move();
  check("a drag of the other rail sends the keys' move as it starts",
        valuesOf(other.writes) === JSON.stringify([[MIDDLE, 70]]), valuesOf(other.writes));
  dragOther.release();
  check("...and its own on release", valuesOf(other.writes) === JSON.stringify([[MIDDLE, 70], [BOTTOM, 30]]),
        valuesOf(other.writes));

  // A drag that took the keys' move over and is then called off by the browser still sends it.
  const cancelled = recorder();
  const cancelledDen = cancelled.cell("d2").shade;
  cancelled.card._onKey(cancelledDen, 0, key("ArrowDown"));
  const dragCancelled = drag(cancelled.card, cancelledDen, 0, 80, 50);
  dragCancelled.press();
  dragCancelled.move();
  dragCancelled.cancel();
  check("a cancelled drag still sends the keys' move it took over",
        valuesOf(cancelled.writes) === JSON.stringify([[DEN, 80]]), valuesOf(cancelled.writes));

  // The middle rail's keys pressed mid-drag on the bottom rail are ignored: the drag owns the
  // blind's drawing until its release, which sends it. Keys work again once it is let go.
  const mid = recorder();
  const fbShade = mid.cell("d1").shade;
  const dragBottom = drag(mid.card, fbShade, 0, 60, 30);
  dragBottom.press();
  dragBottom.move();
  prevented = 0;
  mid.card._onKey(fbShade, 1, key("ArrowDown"));
  check("keys on the other rail mid-drag leave the drag as it is",
        near(fbShade.dragValues[0], 30) && fbShade.dragValues[1] === undefined && !fbShade.keyMove,
        JSON.stringify(fbShade.dragValues));
  check("...though they still do not scroll the page", prevented === 1);
  dragBottom.release();
  check("...and the release sends the drag", valuesOf(mid.writes) === JSON.stringify([[BOTTOM, 30]]), valuesOf(mid.writes));
  mid.card._onKey(fbShade, 1, key("ArrowDown"));

  await new Promise((resolve) => setTimeout(resolve, KEY_COMMIT_MS + 100));
  check("...then the other rail's, once the keys stop", valuesOf(two.writes) === JSON.stringify([[MIDDLE, 70], [BOTTOM, 50]]),
        valuesOf(two.writes));
  check("no key move goes off mid-drag", one.writes.length === 0, valuesOf(one.writes));
  dragDen.release();
  check("...and the release sends one move, from where the keys left the rail to where it was dragged",
        valuesOf(one.writes) === JSON.stringify([[DEN, 50]]), valuesOf(one.writes));
  check("keys after a drag are gathered again", valuesOf(mid.writes) === JSON.stringify([[BOTTOM, 30], [MIDDLE, 70]]),
        valuesOf(mid.writes));
  check("nothing more goes once the keys' move is taken over or sent",
        valuesOf(other.writes) === JSON.stringify([[MIDDLE, 70], [BOTTOM, 30]]) &&
        valuesOf(cancelled.writes) === JSON.stringify([[DEN, 80]]),
        `${valuesOf(other.writes)} ${valuesOf(cancelled.writes)}`);
}

// A key held with Alt, Ctrl or Meta is a browser or system shortcut (Alt+Left is Back): it moves
// nothing and the browser keeps it. A plain arrow key tells a screen reader the new value at
// once, rather than when its move is sent KEY_COMMIT_MS later.
{
  const c = rendered();
  const { shade } = c._cells.find((x) => x.blind.deviceId === "d2");   // Den_1 at 90
  for (const modifier of ["altKey", "ctrlKey", "metaKey"]) {
    let prevented = false;
    c._onKey(shade, 0, { key:"ArrowLeft", [modifier]:true, preventDefault() { prevented = true; } });
    check(`an arrow key held with ${modifier.replace("Key", "")} is left to the browser`,
          !prevented && !shade.keyMove && shade.dragValues[0] === undefined, JSON.stringify(shade.dragValues));
  }
  c._onKey(shade, 0, { key:"ArrowUp", preventDefault() {} });
  check("an arrow key tells a screen reader the new value at once",
        shade.zones[0].attrs["aria-valuenow"] === "100" && shade.zones[0].attrs["aria-valuetext"] === "100% open",
        `${shade.zones[0].attrs["aria-valuenow"]} ${shade.zones[0].attrs["aria-valuetext"]}`);
  clearTimeout(shade.keyTimer);
}

// The tabs sit apart on a two-rail blind, so both can be reached when the rails are together.
check("the middle rail's tab is left of the bottom rail's",
      twoRail._tabX(twoRail._railsOf(twoRailBlind), 1) < 50 && twoRail._tabX(twoRail._railsOf(twoRailBlind), 0) > 50);
{
  check("rails together are marked stacked, so the middle tab reaches past the bottom rail",
        shadeFor(twoRail, twoRailBlind, [100, 100]).element.classList.contains("stacked"));
  check("rails apart are not", !shadeFor(twoRail, twoRailBlind, [20, 80]).element.classList.contains("stacked"));
}

// A single-rail blind has one band and one rail, with its tab in the middle.
const single = shadeFor(oneRail, oneRailBlind, [40]);
check("single-rail: one band only", single.bands.length === 1, String(single.bands.length));
check("single-rail: the tab is centred", oneRail._tabX(oneRail._railsOf(oneRailBlind), 0) === 50);
check("single-rail: closed rests on the sill", near(top(shadeFor(oneRail, oneRailBlind, [0]).railEls[0]) + RAIL, 100));
check("single-rail: open tucks under the headrail", near(top(shadeFor(oneRail, oneRailBlind, [100]).railEls[0]), HEAD));
check("each rail is a keyboard slider",
      [...single.zones, ...mixed.zones].every(z => z.attrs.role === "slider" && z.tabIndex === 0));

// The pleat. A cellular shade reads as a shade because it is visibly divided into cells, so
// the fabric is a repeating gradient on one tunable pitch.
check("the fabric is built from a repeating cell", /repeating-linear-gradient\(\s*to top/.test(cardSource));
check("the cell pitch is a single tunable token", /--n-pleat:\s*\d+px/.test(cardSource) && cardSource.includes("var(--n-pleat)"));

// hide_picture swaps the windows for a slider per rail.
{
  const c = rendered({ hide_picture:true });
  check("hide_picture removes every window", byClass(c.shadowRoot, "win").length === 0);
  const sliders = c._cells.flatMap(x => x.sliders);
  check("hide_picture gives a slider per rail", sliders.length === 3, String(sliders.length));
  const fbSliders = c._cells.find(x => x.blind.deviceId === "d1").sliders;
  check("the list shows the top rail first", fbSliders[0].rail.key === "middle" && fbSliders[1].rail.key === "bottom");
  // Each slider is named for its blind, as the picture's rails are, so a screen reader's list of
  // controls does not read "Bottom rail position" once per blind.
  const sliderNames = c._cells.flatMap((x) => x.sliders.map((slider) => slider.input.attrs["aria-label"])).sort();
  const railNames = rendered()._cells.flatMap((x) => x.shade.zones.map((zone) => zone.attrs["aria-label"])).sort();
  check("each slider is named for its blind, as the picture's rails are",
        JSON.stringify(sliderNames) === JSON.stringify(["Den_1", "Front_Bedroom_1 Bottom rail", "Front_Bedroom_1 Middle rail"]) &&
        JSON.stringify(sliderNames) === JSON.stringify(railNames),
        `${JSON.stringify(sliderNames)} vs ${JSON.stringify(railNames)}`);
  check("a slider shows its rail's position", fbSliders[0].input.value === "80" && fbSliders[0].value.textContent === "80%");
  calls.length = 0;
  fbSliders[1].input.value = "20";
  fbSliders[1].input._on.change();
  check("moving a slider writes that rail", calls[0]?.[2]?.entity_id === "number.front_bedroom_1_bottom_rail_position" && calls[0][2].value === 20,
        JSON.stringify(calls[0]));
}
{
  // A slider is left alone while it is held, and must let go however the press ends: a tap on
  // the thumb or a drag back to the start fires no `change`, nor does a touch the browser takes
  // for a scroll (pointercancel).
  const c = rendered({ hide_picture:true });
  const { input, value } = c._cells.find((x) => x.blind.deviceId === "d2").sliders[0];
  const hubAt = (position) => ({ ...hass, states: { ...hass.states,
    "cover.den_1_bottom_rail": { state:"open", attributes:{ current_position:position, target_position:position } },
    "number.den_1_bottom_rail_position": { state:String(position) } } });
  input._on.pointerdown();
  c.hass = hubAt(50);
  check("a held slider is not moved by the hub", input.value === "90", input.value);
  input._on.pointerup?.();
  check("a tap that changes nothing catches up with the hub on release", input.value === "50" && value.textContent === "50%",
        `${input.value} ${value.textContent}`);
  input._on.pointerdown();
  input._on.pointercancel?.();
  c.hass = hubAt(20);
  check("after a touch taken for a scroll the slider follows the hub again", input.value === "20", input.value);
  input._on.pointerdown();
  input._on.lostpointercapture?.();
  c.hass = hubAt(30);
  check("...and after the pointer is otherwise let go", input.value === "30", input.value);

  // A pointer's move is sent on release; arrow keys, which fire `change` on every step, are
  // gathered into one write the way the picture's are.
  calls.length = 0;
  input._on.pointerdown();
  input.value = "70";
  input._on.input();
  input._on.pointerup?.();
  input._on.change();
  check("a slider dragged and let go is sent at once", JSON.stringify(calls.map((x) => x[2].value)) === "[70]",
        JSON.stringify(calls));
  calls.length = 0;
  for (const step of ["60", "50", "40"]) {
    input._on.keydown?.({ key:"ArrowLeft" });
    input.value = step;
    input._on.input();
    input._on.change();
  }
  check("arrow keys on a slider are not sent one by one", calls.length === 0, JSON.stringify(calls));
  c.hass = hubAt(70);
  check("...nor moved by the hub while they are gathered", input.value === "40", input.value);
  await new Promise((resolve) => setTimeout(resolve, KEY_COMMIT_MS + 100));
  check("...but sent once, when they stop",
        JSON.stringify(calls) === JSON.stringify([["number", "set_value", { entity_id:"number.den_1_bottom_rail_position", value:40 }]]),
        JSON.stringify(calls));
}
{
  // A blind going unavailable while its slider is held. Chromium fires `change` on a held range
  // input that is disabled, which would send the half-dragged value; so the slider is disabled
  // only once the press ends, and a `change` on a blind that is unavailable sends nothing.
  const recorder = () => {
    const writes = [];
    const at = (states = {}) => ({ ...hass, states: { ...hass.states, ...states },
      callService: (d, sv, data) => { writes.push([d, sv, data]); return Promise.resolve(); } });
    const card = rendered({ hide_picture:true }, at());
    return { card, writes, at, input: card._cells.find((x) => x.blind.deviceId === "d2").sliders[0].input };
  };
  const valuesOf = (writes) => JSON.stringify(writes.map((x) => x[2].value));
  const held = recorder();
  const { input } = held;
  input._on.pointerdown();
  input.value = "60";
  input._on.input();
  held.card.hass = held.at({ "cover.den_1_bottom_rail": { state:"unavailable", attributes:{} },
                             "number.den_1_bottom_rail_position": { state:"unavailable" } });
  check("a held slider is not disabled under the pointer when its blind goes unavailable", input.disabled === false,
        String(input.disabled));
  input._on.pointerup();
  input._on.change();
  check("...its `change` then sends nothing", held.writes.length === 0, JSON.stringify(held.writes));
  check("...and once let go it is disabled", input.disabled === true, String(input.disabled));
  held.card.hass = held.at();
  check("...until the blind is back, where the hub has it", input.disabled === false && input.value === "90",
        `${input.disabled} ${input.value}`);

  // Arrow keys, then a press on the same slider before their move is sent: the press holds the
  // keys' move back. A press that moves the slider sends its own `change` alone; one that does
  // not sends the keys' move when it ends.
  const keysThenPress = () => {
    const r = recorder();
    r.input._on.keydown({ key:"ArrowLeft" });
    r.input.value = "80";
    r.input._on.input();
    r.input._on.change();
    r.input._on.pointerdown();
    return r;
  };
  const dragged = keysThenPress();
  const tapped = keysThenPress();
  await new Promise((resolve) => setTimeout(resolve, KEY_COMMIT_MS + 100));
  check("a press on a slider holds back the move its keys gathered", !dragged.writes.length && !tapped.writes.length,
        `${valuesOf(dragged.writes)} ${valuesOf(tapped.writes)}`);
  dragged.input.value = "40";
  dragged.input._on.input();
  dragged.input._on.pointerup();
  dragged.input._on.change();
  check("...a press that moves it sends only its own", valuesOf(dragged.writes) === "[40]", valuesOf(dragged.writes));
  tapped.input._on.pointerup();
  check("...and one that does not sends the keys' move", valuesOf(tapped.writes) === "[80]", valuesOf(tapped.writes));
}

// A Shutter: no rails, one cover whose tilt is its louvers' whole turn: 0 shut (Position 7),
// 50 horizontal (3) and 100 turned as far as they go the other way (0), in the hub's eight stops.
{
  const sCalls = [];
  const louvers = (tilt, raw) => ({ state: tilt === 0 ? "closed" : "open",
    attributes: { current_tilt_position: tilt, target_tilt: tilt, louver_position: raw } });
  const sHass = {
    entities: {
      "cover.study_shutter_louvers": { platform:"norman", device_id:"s1", translation_key:"louvers" },
      "sensor.study_shutter_battery": { platform:"norman", device_id:"s1", translation_key:"battery_level" },
    },
    devices: { s1:{ name:"Study Shutter", area_id:"a3" } },
    areas: { a3:{ name:"Study" } },
    states: { "cover.study_shutter_louvers": louvers(25, 5), "sensor.study_shutter_battery": { state:"80" } },
    callService: (d, s, data) => { sCalls.push([d, s, data]); return Promise.resolve(); },
  };
  const c = new Card();
  c._hass = sHass;
  c.setConfig({ type:"custom:norman-shades-card" });
  c._hass = sHass;
  const [shutter] = c._collectBlinds();
  check("a Shutter is found by its louvers cover",
        shutter?.bottomCover === "cover.study_shutter_louvers" && shutter.louvers === true, JSON.stringify(shutter));
  const rails = c._railsOf(shutter);
  check("a Shutter has one control, its louvers", rails.length === 1 && rails[0].louvers && rails[0].label === "Louvers");
  check("the louvers read the cover's tilt", c._railValue(rails[0]) === 25, String(c._railValue(rails[0])));

  const shade = c._buildShade(shutter, rails);
  const angle = () => shade.louverEls[0].style.transform;
  c._drawShade(shade);
  check("a Shutter is drawn with louvers and a tilt rod, not fabric",
        shade.louverEls.length > 1 && shade.bands.length === 0 && String(shade.railEls[0].className) === "rod");
  check("half-open louvers are turned half way", shade.louverEls.every((l) => l.style.transform === "rotateX(39deg)"), angle());
  sHass.states["cover.study_shutter_louvers"] = louvers(0, 7);
  c._drawShade(shade);
  check("shut louvers lie flat", angle() === "rotateX(0deg)", angle());
  check("...and the window says so", shade.element.classList.contains("shut"));
  sHass.states["cover.study_shutter_louvers"] = louvers(50, 3);
  c._drawShade(shade);
  check("horizontal louvers, at 50, are nearly edge-on", angle() === "rotateX(78deg)", angle());
  sHass.states["cover.study_shutter_louvers"] = louvers(83, 1);
  c._drawShade(shade);
  check("louvers turned past horizontal lean the other way, half shut again", angle() === "rotateX(-39deg)", angle());
  sHass.states["cover.study_shutter_louvers"] = louvers(100, 0);
  c._drawShade(shade);
  check("...and at 100, Position 0, stop a step short of shut", angle() === "rotateX(-19.5deg)" &&
        !shade.element.classList.contains("shut"), angle());
  shade.dragValues = { 0: 58 };
  c._drawShade(shade);
  check("a drag between two stops turns them between the two", angle() === "rotateX(-68.824deg)", angle());
  shade.dragValues = {};

  sCalls.length = 0;
  c._move(rails, 0, 67);
  check("moving the louvers sets the cover's tilt",
        sCalls[0]?.[1] === "set_cover_tilt_position" && sCalls[0][2].entity_id === "cover.study_shutter_louvers" &&
        sCalls[0][2].tilt_position === 67, JSON.stringify(sCalls[0]));

  const rod = shade.zones[0];
  check("the tilt rod is a keyboard slider", rod.attrs.role === "slider" && rod.tabIndex === 0);
  let prevented = false;
  c._onKey(shade, 0, { key: "ArrowUp", preventDefault: () => { prevented = true; } });
  check("an arrow key moves the louvers one of the hub's stops", prevented && shade.dragValues[0] === 83,
        JSON.stringify(shade.dragValues));
  c._onKey(shade, 0, { key: "PageDown", preventDefault: () => {} });
  check("...Page Down three, back past horizontal", shade.dragValues[0] === 38, JSON.stringify(shade.dragValues));
  c._onKey(shade, 0, { key: "End", preventDefault: () => {} });
  check("...and End all the way, to Position 0", shade.dragValues[0] === 100, JSON.stringify(shade.dragValues));
  check("...which the rod says in the status's words", rod.attrs["aria-valuetext"] === "Tilt 100%",
        rod.attrs["aria-valuetext"]);
  clearTimeout(shade.keyTimer);
  shade.keyMove = null;
  shade.dragValues = {};

  const at = (shown, current = shown) => c._statusOf(rails, [{ current, target: shown, shown, moving: current !== shown }], false);
  check("a Shutter reads Closed shut, Open horizontal, and its tilt elsewhere, on either side",
        at(0) === "Closed" && at(50) === "Open" && at(25) === "Tilt 25%" && at(83) === "Tilt 83%" && at(100) === "Tilt 100%",
        [at(0), at(50), at(25), at(83), at(100)].join(" | "));
  check("louvers turning towards horizontal are opening, from either side, and away from it closing",
        at(50, 100) === "Opening · 100%" && at(50, 0) === "Opening · 0%" && at(100, 50) === "Closing · 50%" &&
        at(0, 13) === "Closing · 13%", [at(50, 100), at(50, 0), at(100, 50), at(0, 13)].join(" | "));

  sCalls.length = 0;
  const room = c._buildRoomControls("Study", [shutter, den]);
  room.children[1]._on?.click?.();
  // Every blind shown goes: a whole room of the hub's takes one MotorStop, harmless to louvers,
  // and the integration leaves a Shutter out of the stops it sends blind by blind.
  check("room stop names the Shutter with the rest; the integration knows it takes no stop",
        sCalls.length === 1 && sCalls[0][1] === "room_command" && sCalls[0][2].command === "stop" &&
        JSON.stringify(sCalls[0][2].blinds) === JSON.stringify(["cover.study_shutter_louvers", "cover.den_1_bottom_rail"]),
        JSON.stringify(sCalls));
  sCalls.length = 0;
  room.children[0]._on?.click?.();
  check("room open turns the Shutter's louvers too",
        sCalls[0]?.[1] === "open_cover" && sCalls[0][2].entity_id.includes("cover.study_shutter_louvers"), JSON.stringify(sCalls));

  const list = new Card();
  list._hass = sHass;
  list.setConfig({ type:"custom:norman-shades-card", hide_picture:true });
  list._hass = sHass;
  const slider = list._buildSlider(shutter, rails, rails[0]);
  check("the list layout's louver slider moves one of the hub's eight stops at a time",
        slider.input.max === "7" && slider.input.step === "1", `${slider.input.max} ${slider.input.step}`);
  sHass.states["cover.study_shutter_louvers"] = louvers(38, 4);
  list._patchSlider(slider, false);
  check("...its thumb on the louvers' stop", slider.input.value === "3" && slider.value.textContent === "38%",
        `${slider.input.value} ${slider.value.textContent}`);
  sCalls.length = 0;
  slider.input.value = "6";
  slider.input._on.input();
  slider.input._on.change();
  check("...and a stop picked sends its tilt", sCalls[0]?.[1] === "set_cover_tilt_position" &&
        sCalls[0][2].tilt_position === 83, JSON.stringify(sCalls));
  check("...and is named for its Shutter, as the tilt rod is",
        slider.input.attrs["aria-label"] === "Study Shutter louvers" && rod.attrs["aria-label"] === "Study Shutter louvers",
        slider.input.attrs["aria-label"]);
}

// Roller shades, Roman shades, PerfectSheers and SmartDrapes: told apart by their device's
// model_id (the hub's ModuleType/ModuleDetail), and drawn as themselves rather than as a
// cellular shade.
{
  const pCalls = [];
  const drape = (position, tilt, stack) => ({ state: position ? "open" : "closed",
    attributes: { current_position: position, target_position: position, current_tilt_position: tilt, target_tilt: tilt, stack } });
  const pHass = {
    entities: {
      "cover.kitchen_1_bottom_rail": { platform:"norman", device_id:"k1", translation_key:"bottom_rail" },
      "number.kitchen_1_bottom_rail_position": { platform:"norman", device_id:"k1", translation_key:"bottom_rail_position" },
      "cover.roman_1_bottom_rail": { platform:"norman", device_id:"m1", translation_key:"bottom_rail" },
      "cover.sheer_1_bottom_rail": { platform:"norman", device_id:"h1", translation_key:"bottom_rail" },
      "cover.living_1_bottom_rail": { platform:"norman", device_id:"l1", translation_key:"bottom_rail" },
      "number.living_1_bottom_rail_position": { platform:"norman", device_id:"l1", translation_key:"bottom_rail_position" },
      "cover.patio_1_bottom_rail": { platform:"norman", device_id:"p1", translation_key:"bottom_rail" },
      "cover.den_1_bottom_rail": { platform:"norman", device_id:"c1", translation_key:"bottom_rail" },
    },
    devices: {
      k1:{ name:"Kitchen_1", area_id:"a4", model_id:"48/1" },
      m1:{ name:"Roman_1", area_id:"a4", model_id:"48/2" },
      h1:{ name:"Sheer_1", area_id:"a4", model_id:"49/3" },
      l1:{ name:"Living_1", area_id:"a4", model_id:"80/1" },
      p1:{ name:"Patio_1", area_id:"a4", model_id:"80/1" },
      c1:{ name:"Den_1", area_id:"a4", model_id:"32/2" },
    },
    areas: { a4:{ name:"Downstairs" } },
    states: {
      "cover.kitchen_1_bottom_rail": { state:"open", attributes:{ current_position:60, target_position:60 } },
      "number.kitchen_1_bottom_rail_position": { state:"60" },
      "cover.roman_1_bottom_rail": { state:"open", attributes:{ current_position:60 } },
      "cover.sheer_1_bottom_rail": drape(0, 100),
      "cover.living_1_bottom_rail": drape(100, 100, "left"),
      "number.living_1_bottom_rail_position": { state:"100" },
      "cover.patio_1_bottom_rail": drape(50, 0, "split"),
      "cover.den_1_bottom_rail": { state:"open", attributes:{ current_position:60 } },
    },
    callService: (d, s, data) => { pCalls.push([d, s, data]); return Promise.resolve(); },
  };
  const c = new Card();
  c._hass = pHass;
  c.setConfig({ type:"custom:norman-shades-card" });
  c._hass = pHass;
  const found = Object.fromEntries(c._collectBlinds().map((b) => [b.name, b]));
  check("a roller shade (48/1) is recognised from its model_id", found.Kitchen_1?.product === "roller", String(found.Kitchen_1?.product));
  check("a SmartDrape (80/1) is recognised, with the side it stacks to",
        found.Living_1?.product === "drape" && found.Living_1.stack === "left", JSON.stringify(found.Living_1));
  check("a Roman shade (48/2) and a PerfectSheer (49/3) are recognised",
        found.Roman_1?.product === "roman" && found.Sheer_1?.product === "perfectsheer",
        `${found.Roman_1?.product} ${found.Sheer_1?.product}`);
  check("a cellular shade keeps the cellular picture", found.Den_1?.product === null);
  pHass.states["cover.living_1_bottom_rail"] = drape(100, 100, "sideways");
  check("an unknown stack side is drawn gathering left",
        c._collectBlinds().find((b) => b.name === "Living_1").stack === "left");
  pHass.states["cover.living_1_bottom_rail"] = drape(100, 100, "left");

  // The roller: plain fabric off a roll that grows as the shade winds up.
  const kitchen = found.Kitchen_1;
  const kRails = c._railsOf(kitchen);
  const roller = c._buildShade(kitchen, kRails);
  c._drawShade(roller);
  check("a roller shade is drawn with a roll and plain fabric, not a headrail and pleats",
        roller.roll && String(roller.roll.className) === "roll" && String(roller.bands[0].className) === "fabric roller" &&
        String(roller.element.className) === "win roller");
  const rollAt = (value) => { roller.dragValues = { 0: value }; c._drawShade(roller); return height(roller.roll); };
  check("the roll is thickest with the shade up and thinnest with it down",
        near(rollAt(100), HEAD - 0.5) && near(rollAt(0), 4) && rollAt(50) > 4 && rollAt(50) < HEAD - 0.5,
        `${rollAt(100)} ${rollAt(0)}`);
  roller.dragValues = { 0: 0 };
  c._drawShade(roller);
  check("the fabric comes off the roll's underside", near(top(roller.bands[0]), 0.5 + 4 / 2), String(top(roller.bands[0])));
  check("...and the bottom bar still closes onto the sill",
        near(top(roller.railEls[0]) + RAIL, 100), String(top(roller.railEls[0])));
  roller.dragValues = {};

  // The SmartDrape: drawn sideways from the side it gathers to.
  const living = found.Living_1;
  const lRails = c._railsOf(living);
  const drapeShade = c._buildShade(living, lRails);
  check("a SmartDrape is drawn as vanes with a leading edge, not fabric bands",
        drapeShade.drape && drapeShade.bands.length === 0 && drapeShade.parts.length === 1 &&
        drapeShade.parts[0].vanes.length === 14 && String(drapeShade.element.className) === "win drape");
  const lead = () => parseFloat(drapeShade.parts[0].lead.style.left);
  c._drawShade(drapeShade);
  check("open, it is gathered to the left", near(lead(), 16), String(lead()));
  drapeShade.dragValues = { 0: 0 };
  c._drawShade(drapeShade);
  check("drawn, its edge reaches the far side", near(lead(), 100), String(lead()));
  drapeShade.dragValues = {};
  const vaneTurn = () => drapeShade.parts[0].vanes[0].style.transform;
  c._drawShade(drapeShade);
  check("open vanes are turned nearly edge-on", vaneTurn() === "rotateY(75deg)", vaneTurn());
  pHass.states["cover.living_1_bottom_rail"] = drape(100, 0, "left");
  c._drawShade(drapeShade);
  check("closed vanes lie flat", vaneTurn() === "rotateY(0deg)", vaneTurn());
  const zone = drapeShade.zones[0];
  check("its edge is a horizontal keyboard slider",
        zone.attrs.role === "slider" && zone.attrs["aria-orientation"] === "horizontal" && zone.dataset.side === "left");
  c._onKey(drapeShade, 0, { key: "ArrowRight", preventDefault: () => {} }, "left");
  check("ArrowRight draws a left-stacking drape across (closes it)", drapeShade.dragValues[0] === 90, JSON.stringify(drapeShade.dragValues));
  clearTimeout(drapeShade.keyTimer);
  c._onKey(drapeShade, 0, { key: "ArrowLeft", preventDefault: () => {} }, "left");
  check("...and ArrowLeft gathers it back", drapeShade.dragValues[0] === 100, JSON.stringify(drapeShade.dragValues));
  clearTimeout(drapeShade.keyTimer);
  drapeShade.dragValues = {};
  pCalls.length = 0;
  c._move(lRails, 0, 40);
  check("moving the drape writes its position slider",
        pCalls[0]?.[1] === "set_value" && pCalls[0][2].entity_id === "number.living_1_bottom_rail_position" && pCalls[0][2].value === 40,
        JSON.stringify(pCalls[0]));

  // A split drape: half to each side, both edges on the one position.
  const patio = found.Patio_1;
  const split = c._buildShade(patio, c._railsOf(patio));
  c._drawShade(split);
  const [left, right] = split.parts;
  check("a split drape has an edge per half, on the one position",
        split.parts.length === 2 && left.vanes.length === 7 && right.vanes.length === 7 &&
        split.zones.every((z) => z.dataset.index === "0"));
  const leftEdge = parseFloat(left.lead.style.left), rightEdge = parseFloat(right.lead.style.left);
  check("half drawn, its edges stand the same way off each side", near(leftEdge, 100 - rightEdge) && leftEdge < 50,
        `${leftEdge} ${rightEdge}`);
  split.dragValues = { 0: 0 };
  c._drawShade(split);
  check("drawn, its halves meet in the middle",
        near(parseFloat(left.lead.style.left), 50) && near(parseFloat(right.lead.style.left), 50));
  split.dragValues = {};
  c._onKey(split, 0, { key: "ArrowRight", preventDefault: () => {} }, "right");
  check("ArrowRight on the right half gathers it (opens)", split.dragValues[0] === 60, JSON.stringify(split.dragValues));
  check("...and both halves tell a screen reader so at once",
        split.zones.every((z) => z.attrs["aria-valuenow"] === "60" && z.attrs["aria-valuetext"] === "60% open"),
        JSON.stringify(split.zones.map((z) => z.attrs["aria-valuenow"])));
  clearTimeout(split.keyTimer);

  // The Roman shade: a flat panel that folds up into a stack above its hem.
  const roman = c._buildShade(found.Roman_1, c._railsOf(found.Roman_1));
  check("a Roman shade is drawn as a panel with a fold per section under a headrail",
        String(roman.element.className) === "win roman" && String(roman.bands[0].className) === "fabric roman" &&
        roman.folds.length === SECTIONS && roman.folds.every((f) => String(f.className) === "fabric fold"));
  const SECTION = (100 - HEAD - RAIL) / SECTIONS;
  const romanAt = (value) => {
    roman.dragValues = { 0: value };
    c._drawShade(roman);
    const hem = top(roman.railEls[0]);
    const folds = roman.folds.map((f) => ({ top: top(f), height: height(f) }));
    const stack = folds.reduce((sum, f) => sum + f.height, 0);
    const cut = Number(/inset\(0 0 ([\d.]+)% 0\)/.exec(roman.bands[0].style.clipPath)?.[1]);
    // The panel runs a hair on under the top fold; that hair is not flat panel.
    const flat = Math.max(0, (100 - HEAD - RAIL) * (1 - cut / 100) - (value > 0 ? LAP : 0));
    return { hem, folds, stack, flat };
  };
  const down = romanAt(0);
  check("lowered, it is all flat panel down to the sill, with no folds",
        near(down.hem + RAIL, 100) && near(down.stack, 0) && near(down.flat, 100 - HEAD - RAIL), JSON.stringify(down));
  const up = romanAt(100);
  check("fully up, its folds pack tight under the headrail, the panel all folded away",
        near(up.hem, HEAD + STACK) && up.folds.every((f) => near(f.height, STACK / SECTIONS)) && near(up.flat, 0) &&
        near(Math.min(...up.folds.map((f) => f.top)), HEAD), JSON.stringify(up));
  const part = romanAt(30);
  check("part way, the folds hang loose, half a section deep, the one still forming on top",
        near(part.folds[0].height, SECTION / 2) && near(part.folds[1].height, SECTION / 2) &&
        part.folds[2].height > 0 && part.folds[2].height < SECTION / 2 && near(part.folds[3].height, 0),
        JSON.stringify(part.folds));
  check("...stacked from the hem up, meeting the flat panel",
        near(part.folds[0].top + part.folds[0].height, part.hem) && near(HEAD + part.flat + part.stack, part.hem),
        JSON.stringify(part));
  check("...and no cloth is lost: each fold takes a section of the panel",
        [10, 30, 60, 67, 80, 100].every((v) => { const r = romanAt(v); return near(r.flat + (r.stack / c._romanFolds(v).depth) * SECTION, 100 - HEAD - RAIL); }));
  check("the hem rises evenly, so a drag keeps it under the pointer",
        near(romanAt(50).hem, (romanAt(0).hem + romanAt(100).hem) / 2) && near(c._travelPct(roman), 100 - HEAD - STACK - RAIL));
  check("the CSS draws a seam at each batten, a section apart",
        new RegExp(`\\.fabric\\.roman \\{[^}]*calc\\(100% / ${SECTIONS} - 1\\.5px\\)`).test(cardSource));
  roman.dragValues = {};

  // The PerfectSheer: vanes between sheers, sliding up into a cassette.
  const sheerRails = c._railsOf(found.Sheer_1);
  const sheer = c._buildShade(found.Sheer_1, sheerRails);
  check("a PerfectSheer is drawn as eleven vanes in a cloth, clipped under its cassette",
        String(sheer.element.className) === "win perfectsheer" && String(sheer.bands[0].className) === "clip" &&
        sheer.bands[0].children[0] === sheer.cloth && sheer.vanes.length === 11);
  const vaneBand = () => sheer.vanes[0].style.transform;
  c._drawShade(sheer);
  check("fully down with its vanes open, they narrow to bands", vaneBand() === "scaleY(0.42)", vaneBand());
  pHass.states["cover.sheer_1_bottom_rail"] = drape(0, 0);
  c._drawShade(sheer);
  check("...and closed, they meet", vaneBand() === "scaleY(1)", vaneBand());
  pHass.states["cover.sheer_1_bottom_rail"] = drape(0, 100);
  sheer.dragValues = { 0: 60 };
  c._drawShade(sheer);
  check("raised, its vanes are drawn closed, whatever the tilt says", vaneBand() === "scaleY(1)", vaneBand());
  const clothBottom = () => HEAD + ((top(sheer.cloth) + height(sheer.cloth)) / 100) * (100 - HEAD);
  check("its cloth ends at the bottom rail", near(clothBottom(), top(sheer.railEls[0])), `${clothBottom()} ${top(sheer.railEls[0])}`);
  sheer.dragValues = { 0: 100 };
  c._drawShade(sheer);
  check("fully up, all of it is rolled into the cassette", near(clothBottom(), HEAD) && near(height(sheer.cloth), ((100 - HEAD - RAIL) / (100 - HEAD)) * 100),
        `${clothBottom()} ${height(sheer.cloth)}`);
  sheer.dragValues = {};
}

// ---- languages ------------------------------------------------------------------------
{
  // The card's words live in norman-strings.js, one block per language the integration ships
  // (custom_components/norman/translations), shared with the sidebar panel. Read both, so a
  // language added to one and not the other, or a key missing from one language, fails here.
  const fs = await import("node:fs");
  const stringsUrl = new URL("./norman-strings.js", url);
  stringsUrl.searchParams.set("v", "test");
  const { STRINGS } = await import(stringsUrl.href);
  check("the card imports its words at its own ?v= stamp, never unstamped",
        /import\(\s*new URL\(`\.\/norman-strings\.js\?v=\$\{encodeURIComponent\(CARD_VERSION\)\}`/.test(cardSource));
  const shipped = fs.readdirSync(new URL("../translations/", url))
    .filter((f) => f.endsWith(".json")).map((f) => f.replace(/\.json$/, "")).sort();
  check("the card speaks every language the integration ships",
        JSON.stringify(Object.keys(STRINGS).sort()) === JSON.stringify(shipped),
        `${Object.keys(STRINGS).sort()} vs ${shipped}`);
  const english = Object.keys(STRINGS.en).sort();
  for (const [language, words] of Object.entries(STRINGS)) {
    const keys = Object.keys(words).sort();
    const missing = english.filter((k) => !keys.includes(k));
    const extra = keys.filter((k) => !english.includes(k));
    check(`${language}: has every key, and no others`, !missing.length && !extra.length,
          `missing ${missing.join(",")} extra ${extra.join(",")}`);
    const placeholders = (text) => (text.match(/\{\w+\}/g) || []).sort().join();
    const differ = english.filter((k) => keys.includes(k) && placeholders(words[k]) !== placeholders(STRINGS.en[k]));
    check(`${language}: fills the same placeholders as English`, !differ.length, differ.join(","));
  }

  const inLanguage = (language) => ({ ...hass, locale: { language } });
  const textOf = (c) => {
    const seen = [];
    findAll(c.shadowRoot, (el) => {
      if (el._text) seen.push(String(el._text));
      for (const k of ["title", "aria-label", "aria-valuetext"]) if (el.attrs?.[k]) seen.push(String(el.attrs[k]));
      return false;
    });
    return seen.join(" | ");
  };
  for (const language of shipped) {
    for (const cfg of [{}, { hide_picture:true }]) {
      const text = textOf(rendered(cfg, inLanguage(language)));
      check(`${language} ${cfg.hide_picture ? "list" : "grid"}: no unfilled placeholder, 'undefined' or 'NaN'`,
            !/\{\w+\}|undefined|NaN/.test(text), text.split(" | ").filter((t) => /\{\w+\}|undefined|NaN/.test(t)).join(" ; "));
    }
  }
  const de = textOf(rendered({}, inLanguage("de")));
  check("German counts its blinds and batteries", de.includes("2 Rollos") && de.includes("1 Batterie schwach"), de.slice(0, 200));
  check("German writes a space before %", de.includes("Batterie 84 %") && de.includes("90 % offen"), de.slice(0, 400));
  check("German labels the presets", de.includes("Privatsphäre") && de.includes("Beste Aussicht – alle Räume"));
  check("German names the refresh as the integration does",
        de.includes("Den_1 aktualisieren") && de.includes("Alle Rollos in Den aktualisieren") && de.includes("Alle Rollos aktualisieren"),
        de.split(" | ").filter((t) => t.includes("aktualisieren")).join(" ; "));
  check("a regional tag uses its base language", textOf(rendered({}, inLanguage("de-CH"))).includes("2 Rollos"));
  check("Japanese follows the app's words", textOf(rendered({}, inLanguage("ja"))).includes("プライバシー重視"));
  check("zh-TW is Traditional Chinese", textOf(rendered({}, inLanguage("zh-TW"))).includes("2 個窗簾"));
  check("zh-CN is Simplified Chinese", textOf(rendered({}, inLanguage("zh-CN"))).includes("2 个窗帘"));
  check("an unsupported language falls back to English", textOf(rendered({}, inLanguage("pt-BR"))).includes("2 shades"));
  check("a counted word follows the language's plural rule", (() => {
    const c = rendered({}, inLanguage("fr"));
    return c._t("some_open", { count: 1 }) === "1 ouvert" && c._t("some_open", { count: 2 }) === "2 ouverts";
  })());

  // Switching language in the profile arrives as a new hass; the card redraws in it.
  const c = new Card();
  c.setConfig({ type:"custom:norman-shades-card" });
  c.hass = inLanguage("en");
  const before = textOf(c);
  c.hass = inLanguage("fr");
  const after = textOf(c);
  check("a change of language redraws the card", before.includes("2 shades") && after.includes("2 stores") && !after.includes("2 shades"),
        after.slice(0, 160));

  // The editor's labels, in its plain-input form (ha-form is not loaded here).
  const Editor = els.get("norman-shades-card-editor");
  const editor = new Editor();
  editor.hass = inLanguage("es");
  editor.setConfig({ type:"custom:norman-shades-card" });
  const labels = findAll(editor.shadowRoot, (el) => el.tagName === "span").map((el) => el.textContent);
  check("the editor's labels are translated", labels.includes("Ocultar los niveles de batería"), JSON.stringify(labels));
  check("the editor offers hide_refresh", labels.at(-1) === "Ocultar los botones de actualizar", JSON.stringify(labels));

  // The panel's one message, for when the card itself failed to load.
  const Panel = els.get("norman-panel");
  const p = new Panel();
  p.hass = inLanguage("ja");
  const error = console.error;
  console.error = () => {};
  p._fail(new Error("test"));
  console.error = error;
  const errorEl = byClass(p.shadowRoot, "error")[0];
  check("the panel says the card would not load straight away, in English",
        (errorEl?.textContent || "").startsWith("Norman Shades couldn't load"), errorEl?.textContent);
  await p._failed;
  check("...then in the user's language, from the card's words",
        (errorEl?.textContent || "").startsWith("Norman ブラインドを読み込めませんでした"), errorEl?.textContent);
}

// ---- the visual editor -------------------------------------------------------------------
{
  // Home Assistant hands the editor its config back after every change, and ha-form's title
  // field reports one per keystroke. The form must take the new values in place: a rebuilt
  // form takes the focus out of the field being typed in.
  const Editor = els.get("norman-shades-card-editor");
  const get = customElements.get;
  els.set("ha-form", class extends HTMLElement {});
  customElements.get = (name) => els.get(name);
  try {
    const editor = new Editor();
    editor.hass = hass;
    editor.setConfig({ type:"custom:norman-shades-card" });
    const form = editor._form;
    check("the editor draws Home Assistant's form once it is loaded",
          Boolean(form) && editor.shadowRoot.children.length === 1 && editor.shadowRoot.children[0] === form);
    editor.setConfig({ type:"custom:norman-shades-card", title:"U" });
    editor.setConfig({ type:"custom:norman-shades-card", title:"Up" });
    check("a config handed back is given to the same form, not a new one",
          editor._form === form && editor.shadowRoot.children.length === 1 && editor.shadowRoot.children[0] === form &&
          form.data.title === "Up", JSON.stringify(form.data));
    editor.hass = { ...hass, locale:{ language:"de" } };
    check("a change of language still redraws the form in it",
          editor._form !== form && editor.shadowRoot.children[0] === editor._form &&
          editor._form.computeLabel({ name:"hide_battery" }) === "Batteriestände ausblenden");
  } finally {
    customElements.get = get;
    els.delete("ha-form");
  }

  // `title: ""` is a heading left blank on purpose: a change to another option keeps it. Emptying
  // the title field itself leaves it out, for the hub's name, as an option turned off is.
  {
    const editor = new Editor();
    editor.hass = hass;
    const reported = () => editor._events?.at(-1)?.detail?.config;
    editor.setConfig({ type:"custom:norman-shades-card", title:"" });
    editor._changed({ ...editor._config, hide_battery:true });
    check("the editor keeps a blank title when another option changes",
          reported()?.title === "" && reported().hide_battery === true, JSON.stringify(reported()));
    editor.setConfig({ type:"custom:norman-shades-card", title:"Up" });
    editor._changed({ ...editor._config, title:"" });
    check("...and leaves it out once the title field itself is emptied", reported() && !("title" in reported()),
          JSON.stringify(reported()));
    editor._changed({ ...editor._config, hide_battery:false });
    check("...as it does an option turned off", reported() && !("hide_battery" in reported()), JSON.stringify(reported()));
  }

  // Without ha-form the editor's plain inputs still show the config they are handed.
  const plain = new Editor();
  plain.hass = hass;
  plain.setConfig({ type:"custom:norman-shades-card" });
  plain.setConfig({ type:"custom:norman-shades-card", hide_battery:true, title:"Up" });
  const inputs = findAll(plain.shadowRoot, (el) => el.tagName === "input");
  check("the plain editor follows a new config",
        inputs.length === 9 && inputs[0].value === "Up" && inputs[3].checked === true,
        JSON.stringify(inputs.map((i) => i.value ?? i.checked)));
}

// ---- the sidebar panel's header, the battery, and redraws --------------------------------
{
  // In the panel the header stays at the top as the page scrolls (CSS), so it keeps to one line:
  // the menu button, the hub's name and the refresh. The whole-house presets and scene groups get
  // a row of their own beneath it. On a dashboard they stay in the header, as before.
  const childClasses = (el) => (el?.children || []).map((child) => String(child.className));
  const c = new Card();
  c.setAttribute("panel", "");
  c._hass = hass; c.setConfig({ type:"custom:norman-shades-card" }); c.hass = hass;
  const [header] = byClass(c.shadowRoot, "header");
  const [tools] = byClass(c.shadowRoot, "tools");
  check("in the panel the header holds the menu, the name, the refresh and the settings",
        JSON.stringify(childClasses(header)) === '["icon-btn menu","titles","icon-group home-refresh","icon-group home-settings"]',
        JSON.stringify(childClasses(header)));
  check("...and the presets and the scene groups have a row of their own",
        JSON.stringify(childClasses(tools)) === '["segmented home-buttons","segmented home-scenes"]',
        JSON.stringify(childClasses(tools)));
  check("...the settings hidden while no window has anything to choose", byClass(c.shadowRoot, "home-settings")[0]?.hidden === true);
  const dashboard = rendered();
  check("on a dashboard the presets stay in the header",
        !byClass(dashboard.shadowRoot, "tools").length &&
          childClasses(byClass(dashboard.shadowRoot, "header")[0]).includes("segmented home-buttons"));
  const plainPanel = new Card();
  plainPanel.setAttribute("panel", "");
  plainPanel._hass = hass; plainPanel.setConfig({ type:"custom:norman-shades-card", hide_home_controls:true }); plainPanel.hass = hass;
  check("with the house controls hidden, and no colors to choose, there is no empty row",
        byClass(plainPanel.shadowRoot, "tools")[0]?.hidden === true);

  // The battery opens its details, so it is a button: reachable by keyboard, announced as one.
  const [battery] = byClass(dashboard.shadowRoot, "battery");
  check("the battery is a button", battery?.tagName === "button" && battery.type === "button" && !battery.attrs.role,
        `${battery?.tagName} ${battery?.attrs?.role}`);
  check("...that says what it is", /^Battery \d+%$/.test(battery?.attrs?.["aria-label"] || ""), battery?.attrs?.["aria-label"]);

  // A wide card puts its rooms in columns (CSS); one section, the headings hidden, keeps the width.
  check("the rooms' body is marked when it holds one section",
        byClass(rendered({ hide_room_names:true }).shadowRoot, "body")[0]?.classList.contains("single") === true &&
          byClass(rendered().shadowRoot, "body")[0]?.classList.contains("single") === false);

  // Home Assistant sets hass on every state change in the house. One the card does not draw
  // from leaves it alone: it does not regroup its blinds.
  const quiet = rendered();
  let regrouped = 0;
  const collect = quiet._collectBlinds.bind(quiet);
  quiet._collectBlinds = () => { regrouped += 1; return collect(); };
  quiet.hass = { ...quiet._hass, states: { ...quiet._hass.states, "sensor.outdoor_temperature": { state:"21" } } };
  check("a change elsewhere in the house does not regroup the blinds", regrouped === 0, String(regrouped));
  quiet.hass = { ...quiet._hass, states: { ...quiet._hass.states,
    "sensor.den_1_battery": { state:"11" } } };
  check("...one of its own entities does", regrouped === 1, String(regrouped));
  quiet.hass = { ...quiet._hass, entities: { ...quiet._hass.entities } };
  check("...and so does a new entity registry", regrouped === 2, String(regrouped));
}

// ---- the sidebar page's view ---------------------------------------------------------------
// The view itself is drawn with WebGL, which only a browser has (scripts/check_layout.mjs opens
// one). Here: which photograph it picks, where it puts the sun and the moon, and what the card
// and the panel do with it.
{
  const fs = await import("node:fs");
  const viewUrl = new URL("file://" + process.cwd() + "/custom_components/norman/www/norman-view.js");
  viewUrl.searchParams.set("v", "test");
  const View = await import(viewUrl.href);
  const scenes = JSON.parse(fs.readFileSync(new URL("./view/scenes.json", viewUrl), "utf8"));
  const pick = (place, state, elevation, rising = false) =>
    View.pickScene(scenes, place, View.conditionOf(state), elevation, rising);

  check("an unavailable weather entity says nothing about the weather",
        View.conditionOf("unavailable") === null && View.conditionOf(undefined) === null);
  check("wind does not show in a photograph: a windy day is clear, a windy cloudy one cloudy",
        View.conditionOf("windy") === "clear" && View.conditionOf("windy-variant") === "cloudy");

  // The part of the day, from the sun.
  const phases = [[40, false, "day"], [40, true, "day"], [10, false, "golden"], [10, true, "dawn"], [2, false, "sunset"],
    [2, true, "dawn"], [-3, false, "dusk"], [-3, true, "dusk"], [-9, false, "twilight"], [-20, true, "night"]];
  check("the sun's height, and whether it is rising, give the part of the day",
        phases.every(([el, rising, phase]) => View.phaseOf(el, rising) === phase),
        JSON.stringify(phases.map(([el, rising]) => View.phaseOf(el, rising))));

  check("a clear afternoon is the place's own day", pick("coast", "sunny", 40).key === "coast-day" && pick("lake", "sunny", 40).key === "lake-day");
  check("partly cloudy changes the middle of the day only",
        pick("coast", "partlycloudy", 40).key === "coast-partly" && pick("coast", "partlycloudy", 2).key === "coast-sunset");
  check("the weather decides before the hour: rain is the rain photograph by day and by night",
        pick("lake", "rainy", 40).key === "lake-rain" && pick("lake", "pouring", -30).key === "lake-rain");
  check("a clear night is the night sky, whatever Home Assistant calls it",
        pick("coast", "clear-night", -30).key === "coast-night" && pick("coast", "sunny", -30).key === "coast-night");
  check("with no weather entity the sun alone decides", pick("lake", undefined, 10, true).key === "lake-dawn");
  check("the coast borrows the lake's snow", pick("coast", "snowy", 20).key === "lake-snow");
  check("an unknown place is still given a photograph", Boolean(scenes[pick("desert", "sunny", 40).key]));
  const dim = (state, elevation) => pick("coast", state, elevation).dim;
  check("a daytime photograph of weather is darkened once the sun is down",
        dim("cloudy", 30) === 0 && dim("cloudy", -3) > 0 && dim("cloudy", -20) > dim("cloudy", -3));
  check("...one taken at night is not", dim("lightning", -20) === 0 && scenes["coast-storm"].tone === "night");
  check("...and neither is the hour's own photograph", dim("sunny", -20) === 0 && dim("sunny", -3) === 0);
  {
    const lost = [];
    for (const place of View.PLACES) {
      for (const state of [undefined, "sunny", "clear-night", "partlycloudy", "cloudy", "fog", "rainy", "pouring", "hail",
        "lightning", "lightning-rainy", "snowy", "snowy-rainy", "windy", "windy-variant", "exceptional", "unavailable"]) {
        for (let elevation = -40; elevation <= 70; elevation += 2.5) {
          for (const rising of [true, false]) {
            const { key, dim: darkened } = pick(place, state, elevation, rising);
            if (!scenes[key] || !(darkened >= 0 && darkened < 1)) lost.push(`${place} ${state} ${elevation}`);
          }
        }
      }
    }
    check("every place, weather and height of the sun has a photograph", lost.length === 0, lost.slice(0, 5).join("; "));
  }

  // The sun and the moon, against positions worked out with another library (astral) for Big Sur.
  const BIG_SUR = [36.27, -121.81];
  const closeTo = (value, wanted, within) => Math.abs((((value - wanted + 540) % 360) + 360) % 360 - 180) <= within;
  {
    const morning = View.sunPosition(new Date("2026-11-16T18:00:00Z"), ...BIG_SUR);
    const evening = View.sunPosition(new Date("2026-11-16T02:00:00Z"), ...BIG_SUR);
    check("the sun is where it should be in the morning, rising",
          closeTo(morning.azimuth, 149.52, 0.2) && closeTo(morning.elevation, 28.83, 0.2) && morning.rising === true,
          JSON.stringify(morning));
    check("...and after sunset, going down",
          closeTo(evening.azimuth, 255.85, 0.2) && closeTo(evening.elevation, -12.51, 0.2) && evening.rising === false,
          JSON.stringify(evening));
    const moon = View.moonPosition(new Date("2026-11-16T02:00:00Z"), ...BIG_SUR);
    // Seen from the ground the moon stands up to a degree lower than from the Earth's centre.
    check("the moon is where it should be", closeTo(moon.azimuth, 193.87, 0.5) && closeTo(moon.elevation, 32.89, 1.2), JSON.stringify(moon));
    const newMoon = View.moonPosition(new Date("2026-11-09T07:02:00Z"), ...BIG_SUR).phase;
    const fullMoon = View.moonPosition(new Date("2026-11-24T14:53:00Z"), ...BIG_SUR).phase;
    check("its phase is new at new moon and full at full moon",
          Math.min(newMoon, 1 - newMoon) < 0.01 && Math.abs(fullMoon - 0.5) < 0.01, `${newMoon} ${fullMoon}`);
    // The light on it: from behind at new moon, from the viewer's side at full, and from the side
    // the sun went down on for an evening crescent in the west.
    const lightAt = (iso) => {
      const date = new Date(iso);
      return View.moonLight(View.sunPosition(date, ...BIG_SUR), View.moonPosition(date, ...BIG_SUR));
    };
    const crescent = lightAt("2026-11-12T02:00:00Z");
    check("a new moon is lit from behind and a full moon from the front",
          lightAt("2026-11-09T07:02:00Z")[2] < -0.99 && lightAt("2026-11-24T14:53:00Z")[2] > 0.99);
    check("an evening crescent is lit from below, on the side the sun set",
          crescent[2] < 0 && crescent[1] < 0 && crescent[0] > 0, JSON.stringify(crescent));
  }

  // Where windows look: a room's windows share one strip of the photograph, as openings in one
  // wall, each on the part behind it. Laid out as the card lays them out on a desktop: windows
  // 92 by 121 pixels, 40 apart, three to a row.
  {
    const living = new View.LivingView(mk("div"));
    const box = (left, top) => ({ left, top, width: 92, height: 121, right: left + 92, bottom: top + 121 });
    const pane = (group, left, top = 0) => ({ group, canvas: { getBoundingClientRect: () => box(left, top), width: 0, height: 0 } });
    living.setPanes([pane(0, 0), pane(0, 132), pane(0, 264), pane(1, 600), pane(2, 900), pane(2, 1032),
      pane(3, 0, 400), pane(3, 132, 400), pane(3, 264, 400), pane(3, 0, 600)]);
    const slots = living._panes.map((p) => p.slot);
    const near = (a, b) => Math.abs(a - b) < 1e-6;
    const [first, middle, last] = slots;
    check("three windows in a room look out on the whole strip between them, side by side",
          near(first[0], 0) && near(last[0] + last[1], 1) && near(first[1], middle[1]) &&
          middle[0] > first[0] + first[1] && last[0] > middle[0] + middle[1], JSON.stringify(slots.slice(0, 3)));
    check("...each on as much of it as its width, the wall between hiding the rest",
          near(first[1], 92 / 356) && near(middle[0], 132 / 356), JSON.stringify(first));
    check("a window alone in its room looks out on the middle of the strip, its full height",
          near(slots[3][0] + slots[3][1] / 2, 0.5) && near(slots[3][2], 1), JSON.stringify(slots[3]));
    check("two windows share it, the strip as tall as a window",
          near(slots[4][2], 1) && near(slots[4][0] + slots[5][0] + slots[5][1], 1), JSON.stringify(slots.slice(4, 6)));
    const sunset = scenes["coast-sunset"];
    const horizon = (sunset.motion.horizon - sunset.strip[1]) / sunset.strip[3];
    const [, top, , band] = View.lookOf(sunset, first);
    check("a row of windows looks out at the horizon, a little above the middle of each",
          near(top + 0.45 * band, horizon) || top === 0 || near(top + band, 1), `${top} ${band} ${horizon}`);
    check("a room's windows all look out at the same height", JSON.stringify(View.lookOf(sunset, middle)[1]) === JSON.stringify(top));
    const upper = View.lookOf(sunset, slots[6]);
    const lower = View.lookOf(sunset, slots[9]);
    check("a room with a second row of windows looks out through it lower down, as a lower window would",
          near(upper[1], 0) && near(lower[1] + lower[3], 1) && near(upper[0], lower[0]), `${upper} ${lower}`);
    check("a window that is not drawn looks out on nothing",
          (() => { living.setPanes([{ group: 0, canvas: { getBoundingClientRect: () => ({ width: 0, height: 0 }) } }]); return living._panes[0].slot === null; })());
    living.destroy();
  }
  check("the page behind takes a photograph's colours, deepened under white words",
        /^radial-gradient\(.*rgb\(\d+, \d+, \d+\).*linear-gradient\(to bottom, rgb/.test(View.groundOf(["#7ec0d6", "#207797", "#1b5c70"])),
        View.groundOf(["#7ec0d6", "#207797", "#1b5c70"]));
  {
    const lightness = (css) => css.match(/rgb\((\d+), (\d+), (\d+)\)/g).map((rgb) => rgb.match(/\d+/g).map(Number))
      .map(([r, g, b]) => 0.2126 * r + 0.7152 * g + 0.0722 * b);
    const day = lightness(View.groundOf(["#ffffff", "#ffffff", "#ffffff"]));
    const night = lightness(View.groundOf(["#ffffff", "#ffffff", "#ffffff"], 0.6));
    check("...never so light that white words are lost on it, even from a white photograph", Math.max(...day) <= 112.5,
          JSON.stringify(day));
    check("...and darker when a daytime photograph is shown after dark", night.every((value, i) => value < day[i]), JSON.stringify(night));

    // In Home Assistant's light theme the same colours are paled, under the light theme's dark
    // words: its own colours, read from the card's styles.
    const lightDay = lightness(View.groundOf(["#7ec0d6", "#207797", "#1b5c70"], 0, true));
    const lightNight = lightness(View.groundOf(["#7ec0d6", "#207797", "#1b5c70"], 0.6, true));
    const black = lightness(View.groundOf(["#000000", "#000000", "#000000"], 0.6, true));
    const mean = (values) => values.reduce((sum, value) => sum + value, 0) / values.length;
    check("in the light theme the page's colours are paled, and a little dimmer after dark but still pale",
          Math.min(...lightDay) >= 176 && mean(lightNight) < mean(lightDay) - 3 && Math.min(...lightNight) >= 176,
          JSON.stringify([lightDay, lightNight]));
    check("...never so dark that the dark words are lost on it, even from a black photograph", Math.min(...black) >= 176,
          JSON.stringify(black));
    const cardSource = fs.readFileSync(new URL("./norman-shades-card.js", viewUrl), "utf8");
    const lightTokens = cardSource.slice(cardSource.indexOf(":host([panel][view][light]) {"));
    const token = (name) => lightTokens.match(new RegExp(`--${name}: ([^;]+);`))[1];
    const rgbHex = (hex) => [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16));
    const colourOf = (css) => (css.startsWith("#") ? [...rgbHex(css), 1] : css.match(/[\d.]+/g).map(Number));
    const linear = (c) => ((c /= 255) <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    const lum = ([r, g, b]) => 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
    const contrastOn = ([r, g, b, a], ground) => {
      const [high, low] = [lum([r, g, b].map((v, i) => v * a + ground[i] * (1 - a))), lum(ground)].sort((p, q) => q - p);
      return (high + 0.05) / (low + 0.05);
    };
    const words = { fg: colourOf(token("n-fg")), muted: colourOf(token("n-muted")), faint: colourOf(token("n-faint")) };
    const worst = { fg: 99, muted: 99, faint: 99 };
    for (const scene of Object.values(scenes)) {
      for (const dim of [0, 0.34, 0.6]) {
        const stops = View.groundOf(scene.colours, dim, true).match(/rgb\((\d+), (\d+), (\d+)\)/g).map((rgb) => rgb.match(/\d+/g).map(Number));
        for (const [kind, colour] of Object.entries(words)) {
          for (const ground of stops) worst[kind] = Math.min(worst[kind], contrastOn(colour, ground));
        }
      }
    }
    check("...where for every photograph, by day and after dark, the words stand out: 7:1, and 4.5:1 for the grey ones",
          worst.fg >= 7 && worst.muted >= 4.5 && worst.faint >= 4.5, JSON.stringify(worst));
  }
  check("every scene has its colours for the page", Object.values(scenes).every((scene) =>
        Array.isArray(scene.colours) && scene.colours.length === 3 && scene.colours.every((c) => /^#[0-9a-f]{6}$/.test(c))));

  // --- the card over the view ---
  const weatherState = (state, temperature) => ({ state, attributes: { temperature } });
  const WORDS = { partlycloudy: "Partly cloudy", rainy: "Rainy" };
  const withWeather = (state, temperature, h = hass) => ({ ...h, formatEntityState: (s) => WORDS[s.state] ?? s.state,
    states: { ...h.states, "weather.forecast_home": weatherState(state, temperature) } });
  const fakeView = (over = {}) => ({
    weatherEntity: "weather.forecast_home",
    scene: { by: "Vashishtha Jogi", where: "Pfeiffer Beach, Big Sur", license: "CC0" },
    panes: null, listeners: [],
    subscribe(listener) { this.listeners.push(listener); return () => { this.listeners = this.listeners.filter((l) => l !== listener); }; },
    setPanes(panes) { this.panes = panes; },
    changed() { for (const listener of this.listeners) listener(); },
    ...over,
  });
  const overView = (h, view, cfg = {}) => {
    const c = new Card();
    c.setAttribute("panel", ""); c.setAttribute("view", "");
    c.setConfig({ type:"custom:norman-shades-card", ...cfg });
    if (view) c.view = view;
    c.hass = h;
    return c;
  };
  const textIn = (c, name) => byClass(c.shadowRoot, name)[0]?.textContent;
  const classes = (el) => (el?.children || []).map((child) => String(child.className));

  const view = fakeView();
  const c = overView(withWeather("partlycloudy", 66.6), view);
  const [header] = byClass(c.shadowRoot, "header");
  const [hero] = byClass(c.shadowRoot, "hero");
  check("over the view the header keeps the menu, the name, the refresh and the settings",
        JSON.stringify(classes(header)) === '["icon-btn menu","titles","icon-group home-refresh","icon-group home-settings"]',
        JSON.stringify(classes(header)));
  check("...and the counts move under the weather, the forecast beside them",
        JSON.stringify(classes(byClass(c.shadowRoot, "titles")[0])) === '["header-text"]' &&
          JSON.stringify(classes(hero)) === '["now","hours"]' &&
          JSON.stringify(classes(byClass(hero, "now")[0])) === '["temp","cond","summary"]',
        JSON.stringify([classes(hero), classes(byClass(hero, "now")[0])]));
  check("it says the temperature, rounded, and the weather in Home Assistant's words",
        textIn(c, "temp") === "67°" && textIn(c, "cond") === "Partly cloudy", `${textIn(c, "temp")} ${textIn(c, "cond")}`);
  const views = byClass(c.shadowRoot, "view");
  check("every window looks out on the photograph: a canvas under its glazing bars",
        views.length === 2 && views.every((v) => v.children[0].tagName === "canvas" && v.children[0].className === "photo" &&
          v.children[0].attrs["aria-hidden"] === "true"), JSON.stringify(views.map(classes)));
  check("the view is handed each window's canvas", view.panes?.length === 2 &&
        view.panes.every((pane, index) => pane.canvas === views[index].children[0]));
  check("...each with the room it is in", JSON.stringify(view.panes.map((pane) => pane.group)) === "[0,1]",
        JSON.stringify(view.panes.map((pane) => pane.group)));
  check("the photograph is not credited on the page: NOTICE credits it, linked from the options",
        byClass(c.shadowRoot, "credit").length === 0);
  check("each room says how many of its shades are open", byClass(c.shadowRoot, "room-line").length === 2 &&
        byClass(c.shadowRoot, "room-line").every((line) => line.children.map((part) => part.textContent).join("") === "open"),
        JSON.stringify(byClass(c.shadowRoot, "room-line").map((line) => line.children.map((part) => part.textContent))));

  // Windows in one room are handed as one room: two, then three.
  {
    const oneRoom = { ...withWeather("rainy", 50), devices: { ...hass.devices, d2: { ...hass.devices.d2, area_id: "a1" } } };
    const two = fakeView();
    overView(oneRoom, two);
    check("two windows in a room are handed as one room", JSON.stringify(two.panes.map((pane) => pane.group)) === "[0,0]",
          JSON.stringify(two.panes.map((pane) => pane.group)));
    const three = fakeView();
    overView({ ...oneRoom,
      entities: { ...oneRoom.entities, "cover.office_bottom_rail": { platform:"norman", device_id:"d3", translation_key:"bottom_rail" } },
      devices: { ...oneRoom.devices, d3: { name:"Office", area_id:"a1" } },
      states: { ...oneRoom.states, "cover.office_bottom_rail": { state:"open", attributes:{ current_position:10 } } } }, three);
    check("...and so are three", JSON.stringify(three.panes.map((pane) => pane.group)) === "[0,0,0]",
          JSON.stringify(three.panes.map((pane) => pane.group)));
  }

  // The weather follows its entity, and a change elsewhere in the house still leaves the card alone.
  c.hass = withWeather("rainy", 51.2);
  check("the weather follows its entity", textIn(c, "temp") === "51°" && textIn(c, "cond") === "Rainy");
  let regrouped = 0;
  const collect = c._collectBlinds.bind(c);
  c._collectBlinds = () => { regrouped += 1; return collect(); };
  c.hass = { ...c._hass, states: { ...c._hass.states, "sensor.outdoor_temperature": { state:"21" } } };
  check("...and a change elsewhere in the house does not redraw the card", regrouped === 0, String(regrouped));
  c.hass = withWeather("unavailable", undefined);
  const hidden = (name) => byClass(c.shadowRoot, name)[0]?.hidden;
  check("an unavailable weather entity hides the temperature and the weather", hidden("temp") === true && hidden("cond") === true);
  c.hass = { ...withWeather("rainy", 51.2), states: { ...hass.states } };
  check("...as does a weather entity that is gone", hidden("temp") === true && hidden("cond") === true);

  // Before the view has loaded the card is already built for it, and takes it when it comes.
  {
    const early = overView(withWeather("partlycloudy", 60), null);
    check("before the view arrives the card is built for it, the weather waiting",
          byClass(early.shadowRoot, "photo").length === 2 && byClass(early.shadowRoot, "temp")[0].hidden === true);
    const late = fakeView();
    early.view = late;
    check("...and takes it when it comes", late.panes?.length === 2 && textIn(early, "temp") === "60°");
    early.view = null;
    check("a view taken away stops being heard from", late.listeners.length === 0);
  }

  // Without the view, nothing of it is drawn.
  {
    const plain = new Card();
    plain.setAttribute("panel", "");
    plain.setConfig({ type:"custom:norman-shades-card" }); plain.hass = withWeather("rainy", 50);
    const dashboard = new Card();
    dashboard.setAttribute("view", "");
    dashboard.setConfig({ type:"custom:norman-shades-card" }); dashboard.hass = withWeather("rainy", 50);
    const none = (card) => ["photo", "hero", "room-line"].every((name) => byClass(card.shadowRoot, name).length === 0);
    check("the plain sidebar page draws nothing of the view", none(plain) && byClass(plain.shadowRoot, "sun").length === 2);
    check("...and neither does a card on a dashboard", none(dashboard));
  }

  // --- the panel and its view ---
  // The panel reads the view's index with fetch, which Node will not do for a file: stand in for it.
  const Panel = els.get("norman-panel");
  const fetchWas = globalThis.fetch;
  const warn = console.warn;
  const settle = async (done) => { for (let i = 0; i < 200 && !done(); i += 1) await new Promise((resolve) => setTimeout(resolve, 5)); };
  try {
    globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => JSON.parse(fs.readFileSync(new URL(url), "utf8")) });
    const p = new Panel();
    p.hass = { ...withWeather("snowy", 28), states: { ...withWeather("snowy", 28).states, "sun.sun": { state: "above_horizon", attributes: { elevation: 30, azimuth: 200, rising: false } } } };
    p.panel = { url_path:"norman-shades", config:{ config_entry_id:"home", view:"lake", view_motion:false, weather_entity:"weather.forecast_home", _panel_custom:{} } };
    check("a panel with a view is marked for it at once", p.hasAttribute("view"));
    await settle(() => p._card && p._view);
    const hosted = p._card;
    check("the panel makes the view the integration asked for", p._view instanceof View.LivingView && p._view.place === "lake" &&
          p._view.motion === false && p._view.weatherEntity === "weather.forecast_home");
    check("...and keeps the view's settings out of the card's config",
          JSON.stringify(hosted?._config) === '{"type":"custom:norman-shades-card","config_entry_id":"home"}', JSON.stringify(hosted?._config));
    check("...marks the card, and hands it the view", hosted?.hasAttribute("view") && hosted.view === p._view);
    // Home Assistant's theme: this hass says nothing of it, as its light theme says darkMode false.
    const lumas = (css) => css.match(/rgb\((\d+), (\d+), (\d+)\)/g).map((rgb) => rgb.match(/\d+/g).map(Number))
      .map(([r, g, b]) => 0.2126 * r + 0.7152 * g + 0.0722 * b);
    check("in Home Assistant's light theme the panel, the card and the view's colours take the light look",
          p.hasAttribute("light") && hosted.hasAttribute("light") && p._view.light === true &&
            lumas(p._view._ground).every((l) => l >= 176), p._view._ground);
    const lightGround = p._view._ground;
    const heroWas = byClass(hosted.shadowRoot, "hero")[0];
    p.hass = { ...p.hass, themes: { darkMode: true } };
    check("...and Home Assistant turning dark turns them dark at once, the card not drawn again",
          !p.hasAttribute("light") && !hosted.hasAttribute("light") && p._view.light === false &&
            lumas(p._view._ground).every((l) => l <= 112.5) &&
            p._view._grounds.every((layer) => layer.style.transitionDuration === "0s") &&
            heroWas !== undefined && byClass(hosted.shadowRoot, "hero")[0] === heroWas, p._view._ground);
    p.hass = { ...p.hass, themes: { darkMode: false } };
    check("...and light again, as it was", p.hasAttribute("light") && hosted.hasAttribute("light") && p._view._ground === lightGround);
    check("the view follows the weather: snow at the lake", p._view.scene?.place === "lake" && p._view.scene.when === "snow",
          JSON.stringify(p._view.scene && [p._view.scene.place, p._view.scene.when]));
    check("a weather entity is found when none is named", (() => {
      const found = new View.LivingView(mk("div"));
      found.scenes = scenes;
      found.configure({ place: "coast", motion: false, weatherEntity: null });
      found.hass = { states: { "weather.zurich": weatherState("fog", 9), "weather.home": weatherState("rainy", 12), "light.kitchen": { state: "on" } } };
      return found.weatherEntity === "weather.home" && found.scene.when === "rain";
    })());
    p.panel = { url_path:"norman-shades", config:{ config_entry_id:"home", view:"coast", view_motion:true, _panel_custom:{} } };
    check("another place reaches the view without a new one being made", p._view.place === "coast" && p._view.motion === true &&
          hosted.view === p._view && p._view.scene.when === "snow" && p._view.scene.place === "lake");
    p.panel = { url_path:"norman-shades", config:{ config_entry_id:"home", view:"coast", view_motion:true, hide_weather:true, _panel_custom:{} } };
    check("the weather turned off goes to the card, which is drawn again without it",
          JSON.stringify(hosted._config) === '{"type":"custom:norman-shades-card","config_entry_id":"home","hide_weather":true}' &&
            byClass(hosted.shadowRoot, "hero").length === 1 && byClass(hosted.shadowRoot, "summary").length === 1 &&
            ["temp", "cond", "hours"].every((name) => byClass(hosted.shadowRoot, name).length === 0) &&
            hosted.view === p._view && p._view.place === "coast", JSON.stringify(hosted._config));
    p.panel = { url_path:"norman-shades", config:{ config_entry_id:"home", view:"coast", view_motion:true, _panel_custom:{} } };
    check("...and turned on again, the weather is back",
          ["temp", "cond", "hours"].every((name) => byClass(hosted.shadowRoot, name).length === 1));
    const viewWas = p._view;
    p.panel = { url_path:"norman-shades", config:{ config_entry_id:"home", view:"none", _panel_custom:{} } };
    check("the view turned off leaves the plain page", !p.hasAttribute("view") && !hosted.hasAttribute("view") && p._view === null &&
          hosted.view === null && byClass(hosted.shadowRoot, "hero").length === 0);
    check("...and the view is let go of", viewWas !== null && hosted._viewOff === null);

    // Without its photographs the page is the plain card, which works as it always has.
    globalThis.fetch = async () => { throw new Error("offline"); };
    console.warn = () => {};
    const q = new Panel();
    q.hass = withWeather("snowy", 28);
    q.panel = { url_path:"norman-shades", config:{ view:"coast", _panel_custom:{} } };
    await settle(() => q._card && q._viewFailed);
    check("when the view cannot load, the page is the plain card", q._viewFailed === true && !q.hasAttribute("view") &&
          !q._card.hasAttribute("view") && byClass(q._card.shadowRoot, "hero").length === 0 &&
          byClass(q._card.shadowRoot, "header-text")[0]?.textContent === "Lakehouse Shades");
  } finally {
    globalThis.fetch = fetchWas;
    console.warn = warn;
  }
}

// ---- each blind's color ------------------------------------------------------------------------
// The integration keeps a color on each blind as a select (select.py): a fabric for a shade, a
// paint or a stain for a Shutter. The card draws each window in it, and in the sidebar panel
// lets each be chosen; a dashboard card draws them but offers no choosing.
{
  const fs = await import("node:fs");
  const selectPy = fs.readFileSync(new URL("../select.py", url), "utf8");
  const listed = (name) => [...new RegExp(`^${name} = \\(([^)]*)\\)`, "ms").exec(selectPy)[1].matchAll(/"(\w+)"/g)]
    .map((match) => match[1]);
  const FABRICS = listed("SHADE_COLORS");
  const PAINTS = listed("SHUTTER_COLORS");
  const colorHass = (colors, base = hass) => {
    const reg = { ...base.entities };
    const states = { ...base.states };
    for (const [device, slug, key, color] of colors) {
      reg[`select.${slug}_${key}`] = { platform:"norman", device_id:device, translation_key:key };
      states[`select.${slug}_${key}`] = { state:color };
    }
    return { ...base, entities:reg, states };
  };
  const painted = (c) => byClass(c.shadowRoot, "win").map((win) => win.dataset.color ?? "");
  const panelCard = (h) => {
    const c = new Card();
    c.setAttribute("panel", "");
    c.setConfig({ type:"custom:norman-shades-card" });
    c.hass = h;
    return c;
  };
  // A kind's parts, by their classes: its pick over each window, its name beneath, its bar.
  const ofKind = (root, part, kind) => byClass(root, part).filter((x) => String(x.className).split(" ").includes(kind));
  const fbColor = "select.front_bedroom_1_shade_color";
  const denColor = "select.den_1_shade_color";
  const h1 = colorHass([["d1", "front_bedroom_1", "shade_color", "navy"], ["d2", "den_1", "shade_color", "ivory"]]);

  const dash = rendered({}, h1);
  check("each blind is found with its color", JSON.stringify(dash._collectBlinds().map((b) => b.color)) ===
        JSON.stringify([fbColor, denColor]), JSON.stringify(dash._collectBlinds().map((b) => b.color)));
  check("a window is drawn in its blind's color, the default as it always was",
        JSON.stringify(painted(dash)) === '["","navy"]', JSON.stringify(painted(dash)));
  check("a dashboard card draws the colors but offers no choosing",
        byClass(dash.shadowRoot, "pick").length === 0 && byClass(dash.shadowRoot, "home-settings").length === 0);
  dash.hass = colorHass([["d1", "front_bedroom_1", "shade_color", "sage"], ["d2", "den_1", "shade_color", "plaid"]]);
  check("a color changed in Home Assistant is drawn, and one the card does not know is the default",
        JSON.stringify(painted(dash)) === '["","sage"]', JSON.stringify(painted(dash)));
  {
    // Hiding the color tidies the device page; the shade keeps its color. A disabled one is gone.
    const hiddenColor = colorHass([["d1", "front_bedroom_1", "shade_color", "navy"]]);
    hiddenColor.entities[fbColor] = { ...hiddenColor.entities[fbColor], hidden: true };
    check("a hidden color still colors its shade", JSON.stringify(painted(rendered({}, hiddenColor))) === '["","navy"]');
    const disabled = { ...hiddenColor, entities: { ...hiddenColor.entities } };
    delete disabled.entities[fbColor];
    check("...and a blind whose color is disabled is drawn in the default",
          JSON.stringify(painted(rendered({}, disabled))) === '["",""]');
  }

  const pc = panelCard(h1);
  check("in the panel the settings show once a blind has a color, with an item for the colors",
        byClass(pc.shadowRoot, "home-settings")[0]?.hidden === false && pc._choiceItems.colors.hidden === false);
  check("...and none for the divided lights while no window has them", pc._choiceItems.lights.hidden === true);
  const picks = ofKind(pc.shadowRoot, "pick", "colors");
  check("each window has a color select over it, set to its color", picks.length === 2 &&
        picks[0].value === "ivory" && picks[1].value === "navy", JSON.stringify(picks.map((pick) => pick.value)));
  check("...offering the select's fabrics, in its order", JSON.stringify(picks[1].children.map((option) => option.value)) ===
        JSON.stringify(FABRICS) && FABRICS.length === 11, JSON.stringify(picks[1].children.map((option) => option.value)));
  check("...each in the user's words", picks[1].children.map((option) => option.textContent).join(",") ===
        "White,Ivory,Linen,Sand,Taupe,Gray,Slate,Charcoal,Navy,Sage,Terracotta");
  check("...named for its blind", picks[1].attrs["aria-label"] === "Color of Front_Bedroom_1", picks[1].attrs["aria-label"]);
  check("...with the color's name to say beneath it", ofKind(pc.shadowRoot, "choice-name", "colors")[1]?.lastChild.textContent === "Navy");
  check("choosing waits for the settings", !pc._card.classList.contains("coloring"));
  const settings = pc._settingsButton;
  check("...a button at the top beside the refresh, which opens a menu",
        byClass(byClass(pc.shadowRoot, "header")[0], "settings")[0] === settings && settings.attrs["aria-label"] === "Settings" &&
          settings.attrs["aria-haspopup"] === "menu" && pc._settingsMenu.hidden === true);
  settings._on.click();
  const colorItem = pc._choiceItems.colors;
  check("...the menu open, with the colors in it", pc._settingsMenu.hidden === false && settings.attrs["aria-expanded"] === "true" &&
        colorItem.children[1].textContent === "Shade colors" && colorItem.attrs.role === "menuitem");
  pc._settingsMenu._on.keydown({ key:"Escape", target:colorItem, preventDefault() {} });
  check("...which Escape closes", pc._settingsMenu.hidden === true && settings.attrs["aria-expanded"] === "false");
  settings._on.click();
  colorItem._on.click();
  check("the colors item turns the page to choosing them, and closes the menu",
        pc._card.classList.contains("coloring") && pc._settingsMenu.hidden === true);

  calls.length = 0;
  picks[1].value = "sand";
  picks[1]._on.change();
  check("a color chosen for a window goes to its blind's select", calls.length === 1 &&
        JSON.stringify(calls[0]) === JSON.stringify(["select", "select_option", { entity_id:fbColor, option:"sand" }]),
        JSON.stringify(calls));
  check("...and the window is drawn in it at once, its name with it",
        painted(pc)[1] === "sand" && ofKind(pc.shadowRoot, "choice-name", "colors")[1].lastChild.textContent === "Sand");
  pc.hass = { ...h1, states: { ...h1.states, "sensor.den_1_battery": { state:"13" } } };
  check("...and stays drawn in it while Home Assistant takes it up", painted(pc)[1] === "sand", painted(pc)[1]);
  pc.hass = colorHass([["d1", "front_bedroom_1", "shade_color", "sand"], ["d2", "den_1", "shade_color", "ivory"]]);
  check("...until the select says so itself", painted(pc)[1] === "sand" && pc._choicePending.size === 0);

  calls.length = 0;
  const [bar] = ofKind(pc.shadowRoot, "choice-bar", "colors");
  const [every] = byClass(bar, "choice-every");
  const everySelect = every.children.find((child) => child.tagName === "select");
  check("the bar colors every shade at once, from the same fabrics",
        JSON.stringify(everySelect.children.slice(1).map((option) => option.value)) === JSON.stringify(FABRICS) &&
          everySelect.children[0].value === "" && everySelect.children[0].disabled === true);
  everySelect.value = "charcoal";
  everySelect._on.change();
  check("...in one call to every select", calls.length === 1 && JSON.stringify(calls[0]) ===
        JSON.stringify(["select", "select_option", { entity_id:[denColor, fbColor], option:"charcoal" }]), JSON.stringify(calls));
  check("...every window drawn in it at once, and the bar ready for another",
        JSON.stringify(painted(pc)) === '["charcoal","charcoal"]' && everySelect.value === "", JSON.stringify(painted(pc)));

  let prevented = false;
  let threw = false;
  try {
    byClass(pc.shadowRoot, "win")[1]._on.pointerdown({ pointerType:"mouse", button:0, pointerId:1, clientX:5, clientY:5,
      target:{ classList:{ contains:() => false } }, preventDefault() { prevented = true; } });
  } catch {
    threw = true;
  }
  check("while colors are chosen a press on a window does not take hold of a rail", !prevented && !threw);
  const done = byClass(bar, "chip").find((chip) => chip !== every);
  done._on.click();
  check("Done ends the choosing", !pc._card.classList.contains("coloring"));

  // A Shutter's colors are paints and stains, and "every shade" leaves it alone.
  const withShutter = colorHass([["d1", "front_bedroom_1", "shade_color", "sage"], ["d3", "study_shutter", "shutter_color", "walnut"]]);
  withShutter.entities["cover.study_shutter_louvers"] = { platform:"norman", device_id:"d3", translation_key:"louvers" };
  withShutter.devices = { ...hass.devices, d3: { name:"Study Shutter", area_id:"a2", model_id:"1/0" } };
  withShutter.states["cover.study_shutter_louvers"] = { state:"open", attributes:{ current_tilt_position:50, target_tilt:50 } };
  const sc = panelCard(withShutter);
  const shutterWin = byClass(sc.shadowRoot, "win").find((win) => win.classList.contains("shutter"));
  check("a Shutter is drawn in its paint or stain", shutterWin?.dataset.color === "walnut", String(shutterWin?.dataset.color));
  const shutterPick = ofKind(shutterWin, "pick", "colors")[0];
  check("...offered the select's paints and stains", JSON.stringify(shutterPick?.children.map((option) => option.value)) ===
        JSON.stringify(PAINTS) && shutterPick.children.map((option) => option.textContent).join(",") ===
        "White,Ivory,Gray,Black,Oak,Walnut", JSON.stringify(shutterPick?.children.map((option) => option.value)));
  calls.length = 0;
  sc._setChoosing("colors");
  const scEvery = byClass(ofKind(sc.shadowRoot, "choice-bar", "colors")[0], "choice-every")[0].children.find((child) => child.tagName === "select");
  scEvery.value = "linen";
  scEvery._on.change();
  check("...and left alone when every shade is colored", calls.length === 1 &&
        JSON.stringify(calls[0][2].entity_id) === JSON.stringify(fbColor) && shutterWin.dataset.color === "walnut",
        JSON.stringify(calls));
  check("a blind without a color to choose has nothing over its window",
        byClass(sc.shadowRoot, "win").filter((win) => !byClass(win, "pick").length).length === 1);
  const german = panelCard({ ...h1, locale:{ language:"de" } });
  check("the colors are in the user's language", ofKind(german.shadowRoot, "choice-name", "colors")[1]?.lastChild.textContent === "Marineblau" &&
        ofKind(german.shadowRoot, "pick", "colors")[1].attrs["aria-label"] === "Farbe von Front_Bedroom_1");
  const listPanel = new Card();
  listPanel.setAttribute("panel", "");
  listPanel.setConfig({ type:"custom:norman-shades-card", hide_picture:true });
  listPanel.hass = h1;
  check("with sliders instead of windows there is nothing to color", byClass(listPanel.shadowRoot, "home-settings")[0]?.hidden === true);
}

// ---- each window's divided lights ----------------------------------------------------------------
// The integration keeps each window's divided lights as a select too (select.py): the glazing bars
// the card draws across its glass, two over two as it always was. In the sidebar panel they are
// chosen as the colors are; a dashboard card draws them but offers no choosing.
{
  const fs = await import("node:fs");
  const selectPy = fs.readFileSync(new URL("../select.py", url), "utf8");
  const PATTERNS = [.../^WINDOW_LIGHTS = \(([^)]*)\)/ms.exec(selectPy)[1].matchAll(/"(\w+)"/g)].map((match) => match[1]);
  const lightsHass = (lights, base = hass) => {
    const reg = { ...base.entities };
    const states = { ...base.states };
    for (const [device, slug, pattern] of lights) {
      reg[`select.${slug}_divided_lights`] = { platform:"norman", device_id:device, translation_key:"window_lights" };
      states[`select.${slug}_divided_lights`] = { state:pattern };
    }
    return { ...base, entities:reg, states };
  };
  const panelCard = (h) => {
    const c = new Card();
    c.setAttribute("panel", "");
    c.setConfig({ type:"custom:norman-shades-card" });
    c.hass = h;
    return c;
  };
  const ofKind = (root, part, kind) => byClass(root, part).filter((x) => String(x.className).split(" ").includes(kind));
  // Each window's glazing bars, read back from those laid in it: upright ones by where they stand
  // across the glass, the others by how far down.
  const barsOf = (c) => byClass(c.shadowRoot, "bars").map((bars) => bars.children
    .map((bar) => (bar.className === "mullion" ? `down ${bar.style.left}` : `across ${bar.style.top}`)).join(", "));
  const fbLights = "select.front_bedroom_1_divided_lights";
  const denLights = "select.den_1_divided_lights";

  check("with no divided lights chosen every window is two over two, as it always was",
        JSON.stringify(barsOf(rendered())) === JSON.stringify(["down 50%, across 50%", "down 50%, across 50%"]), JSON.stringify(barsOf(rendered())));
  const h2 = lightsHass([["d1", "front_bedroom_1", "six_over_six"], ["d2", "den_1", "none"]]);
  const dash = rendered({}, h2);
  check("each blind is found with its divided lights", JSON.stringify(dash._collectBlinds().map((b) => b.lights)) ===
        JSON.stringify([fbLights, denLights]), JSON.stringify(dash._collectBlinds().map((b) => b.lights)));
  check("each window is drawn with its own: none, and six over six",
        JSON.stringify(barsOf(dash)) === JSON.stringify(["", "down 33.33%, down 66.67%, across 25%, across 50%, across 75%"]),
        JSON.stringify(barsOf(dash)));
  check("...the meeting rail heavier than the bars across each sash", byClass(dash.shadowRoot, "bars")[1].children
        .filter((bar) => bar.className === "transom").map((bar) => bar.style.height).join(" ") === "2% 2.8% 2%");
  dash.hass = lightsHass([["d1", "front_bedroom_1", "prairie"], ["d2", "den_1", "stained_glass"]]);
  check("divided lights changed in Home Assistant are drawn, and ones the card does not know are the default",
        JSON.stringify(barsOf(dash)) === JSON.stringify(["down 50%, across 50%", "down 13%, down 87%, across 12%, across 88%"]),
        JSON.stringify(barsOf(dash)));
  check("a dashboard card offers no choosing", byClass(dash.shadowRoot, "pick").length === 0);
  {
    // "Over none" divides the upper sash alone: its bars reach down to the meeting rail.
    const sashes = rendered({}, lightsHass([["d1", "front_bedroom_1", "six_over_none"], ["d2", "den_1", "four_over_four"]]));
    const [den, front] = byClass(sashes.shadowRoot, "bars");
    const reach = (bars) => bars.children.map((bar) => (bar.className === "mullion"
      ? `down ${bar.style.left} ${bar.style.top}+${bar.style.height}` : `across ${bar.style.top} ${bar.style.left}+${bar.style.width}`)).join(", ");
    check("six over none divides the upper sash alone, three across and two down, above the meeting rail",
          reach(front) === "down 33.33% 0%+50%, down 66.67% 0%+50%, across 25% 0%+100%, across 50% 0%+100%", reach(front));
    check("four over four divides both sashes, two across and two down each",
          reach(den) === "down 50% 0%+100%, across 25% 0%+100%, across 50% 0%+100%, across 75% 0%+100%", reach(den));
  }
  {
    const hidden = lightsHass([["d1", "front_bedroom_1", "none"]]);
    hidden.entities[fbLights] = { ...hidden.entities[fbLights], hidden: true };
    check("hidden divided lights still divide the glass", barsOf(rendered({}, hidden))[1] === "", JSON.stringify(barsOf(rendered({}, hidden))));
  }

  const pc = panelCard(lightsHass([["d1", "front_bedroom_1", "six_over_six"], ["d2", "den_1", "two_over_two"]]));
  const lightsItem = pc._choiceItems.lights;
  check("in the panel the settings menu has the divided lights once a window has them, and not the colors",
        lightsItem.hidden === false && lightsItem.children[1].textContent === "Divided lights" && pc._choiceItems.colors.hidden === true);
  const picks = ofKind(pc.shadowRoot, "pick", "lights");
  check("each window has a select of divided lights over it, set to its own", picks.length === 2 &&
        picks[0].value === "two_over_two" && picks[1].value === "six_over_six", JSON.stringify(picks.map((pick) => pick.value)));
  check("...offering the select's patterns, in its order, in the user's words",
        JSON.stringify(picks[1].children.map((option) => option.value)) === JSON.stringify(PATTERNS) && PATTERNS.length === 11 &&
          picks[1].children.map((option) => option.textContent).join(",") === "None,One over one,Two side by side,Two over none," +
          "Two over two,Three over none,Four over none,Four over four,Six over none,Six over six,Prairie");
  check("...named for its blind", picks[1].attrs["aria-label"] === "Divided lights of Front_Bedroom_1", picks[1].attrs["aria-label"]);
  pc._settingsButton._on.click();
  lightsItem._on.click();
  check("the divided lights item turns the page to choosing them, not colors",
        pc._card.classList.contains("lighting") && pc._card.classList.contains("choosing") && !pc._card.classList.contains("coloring"));
  calls.length = 0;
  picks[0].value = "none";
  picks[0]._on.change();
  check("divided lights chosen for a window go to its blind's select, drawn at once and named",
        JSON.stringify(calls[0]) === JSON.stringify(["select", "select_option", { entity_id:denLights, option:"none" }]) &&
          barsOf(pc)[0] === "" && ofKind(pc.shadowRoot, "choice-name", "lights")[0].lastChild.textContent === "None", JSON.stringify(calls));
  calls.length = 0;
  const [bar] = ofKind(pc.shadowRoot, "choice-bar", "lights");
  const [every] = byClass(bar, "choice-every");
  const everySelect = every.children.find((child) => child.tagName === "select");
  everySelect.value = "one_over_one";
  everySelect._on.change();
  check("...and for every window at once, in one call", calls.length === 1 && JSON.stringify(calls[0]) ===
        JSON.stringify(["select", "select_option", { entity_id:[denLights, fbLights], option:"one_over_one" }]) &&
          JSON.stringify(barsOf(pc)) === JSON.stringify(["across 50%", "across 50%"]), JSON.stringify([calls, barsOf(pc)]));
  byClass(bar, "chip").find((chip) => chip !== every)._on.click();
  check("Done ends the choosing", !pc._card.classList.contains("lighting") && !pc._card.classList.contains("choosing"));
  const german = panelCard({ ...lightsHass([["d1", "front_bedroom_1", "two_over_two"]]), locale:{ language:"de" } });
  check("the divided lights are in the user's language",
        ofKind(german.shadowRoot, "pick", "lights")[0]?.children.map((option) => option.textContent)[4] === "Sprossenkreuz");
}

// ---- the forecast ---------------------------------------------------------------------------------
// Over the view the card subscribes to the weather entity's forecast, as Home Assistant's own
// weather card does, and shows now and the hours ahead beside the weather.
{
  const subscriptions = [];
  let refuse = false;
  const connection = {
    subscribeMessage(callback, message) {
      if (refuse) return Promise.reject(new Error("not supported"));
      const sub = { callback, message, closed: false };
      subscriptions.push(sub);
      return Promise.resolve(() => { sub.closed = true; return Promise.resolve(); });
    },
  };
  const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
  const at = (hours) => new Date(Date.now() + hours * 3600e3).toISOString();
  const hourly = [
    { datetime: at(-0.5), condition: "sunny", temperature: 58 },
    ...Array.from({ length: 10 }, (_, i) => ({ datetime: at(i + 1), condition: i === 2 ? "rainy" : "partlycloudy",
      temperature: 61 + i, precipitation_probability: i === 2 ? 40 : 10 })),
  ];
  const WORDS = { partlycloudy: "Partly cloudy", rainy: "Rainy", sunny: "Sunny" };
  const withForecast = (features, extra = {}) => ({ ...hass, connection,
    formatEntityState: (state, value) => WORDS[value ?? state.state] ?? value ?? state.state,
    states: { ...hass.states, "weather.forecast_home": { state:"partlycloudy",
      attributes:{ temperature:66.6, supported_features:features } } }, ...extra });
  // The sun is down from five and a half hours on.
  const fakeView = () => ({ weatherEntity:"weather.forecast_home", scene:null, listeners:[],
    subscribe(listener) { this.listeners.push(listener); return () => {}; }, setPanes() {},
    sunAt: (date) => ({ elevation: date.getTime() > Date.now() + 5.5 * 3600e3 ? -10 : 20 }) });
  const overView = (h, view) => {
    const c = new Card();
    c.setAttribute("panel", ""); c.setAttribute("view", "");
    c.setConfig({ type:"custom:norman-shades-card" });
    c.view = view;
    c.hass = h;
    return c;
  };
  const textOf = (cell, name) => byClass(cell, name)[0]?.textContent;
  const iconOf = (cell) => cell.children.find((child) => child.tagName === "ha-icon")?.attrs.icon;

  const view = fakeView();
  const c = overView(withForecast(3), view);
  check("the forecast waits until the card is on the page", subscriptions.length === 0);
  c.connectedCallback();
  await tick();
  check("...then asks for the weather entity's hourly forecast", subscriptions.length === 1 &&
        JSON.stringify(subscriptions[0].message) ===
          JSON.stringify({ type:"weather/subscribe_forecast", forecast_type:"hourly", entity_id:"weather.forecast_home" }),
        JSON.stringify(subscriptions.map((sub) => sub.message)));
  const [hours] = byClass(c.shadowRoot, "hours");
  check("...and shows nothing until it comes", hours.hidden === true && hours.attrs["aria-label"] === "Forecast");
  subscriptions[0].callback({ type:"hourly", forecast:hourly });
  const cells = hours.children;
  check("now and the seven hours after it", hours.hidden === false && cells.length === 8 && textOf(cells[0], "when") === "Now",
        String(cells.length));
  check("now is the weather entity's own", textOf(cells[0], "deg") === "67°" && iconOf(cells[0]) === "mdi:weather-partly-cloudy");
  check("an hour already begun is left out", textOf(cells[1], "deg") === "61°" && /^\d{1,2} (AM|PM)$/.test(textOf(cells[1], "when")),
        `${textOf(cells[1], "when")} ${textOf(cells[1], "deg")}`);
  check("a chance of rain worth saying is said, and a small one is not",
        textOf(cells[3], "wet") === "40%" && iconOf(cells[3]) === "mdi:weather-rainy" && textOf(cells[2], "wet") === "");
  check("...and said to a screen reader with the hour's weather",
        / Rainy, 63°, 40% chance of rain or snow$/.test(textOf(cells[3], "said")), textOf(cells[3], "said"));
  check("an hour after dark has the night's icon", iconOf(cells[6]) === "mdi:weather-night-partly-cloudy" &&
        iconOf(cells[5]) === "mdi:weather-partly-cloudy", `${iconOf(cells[5])} ${iconOf(cells[6])}`);
  const before = cells[1];
  c.hass = { ...c._hass, states: { ...c._hass.states, "sensor.outdoor": { state:"1" } } };
  check("a change elsewhere leaves the forecast as it was", hours.children[1] === before);

  c.disconnectedCallback();
  await tick();
  check("off the page, the card stops hearing it", subscriptions[0].closed === true && c._forecast === null);
  c.connectedCallback();
  await tick();
  check("...and hears it again when it is back", subscriptions.length === 2 && !subscriptions[1].closed);

  // Another weather entity: the old forecast stops and the new one is asked for.
  c.hass = { ...c._hass, states: { ...c._hass.states, "weather.home": { state:"rainy", attributes:{ temperature:50, supported_features:1 } } } };
  view.weatherEntity = "weather.home";
  for (const listener of view.listeners) listener();
  await tick();
  check("another weather entity: the old forecast stops, the new one's daily forecast is asked for",
        subscriptions[1].closed === true && subscriptions.length === 3 &&
          subscriptions[2].message.entity_id === "weather.home" && subscriptions[2].message.forecast_type === "daily",
        JSON.stringify(subscriptions.map((sub) => [sub.message.entity_id, sub.message.forecast_type, sub.closed])));
  const day = (days) => new Date(Date.now() + days * 86400e3).toISOString();
  subscriptions[2].callback({ type:"daily", forecast:[
    { datetime: day(0), condition:"rainy", temperature:52, templow:41 },
    { datetime: day(1), condition:"sunny", temperature:71, templow:45, precipitation_probability:0 },
    { datetime: day(2), condition:"rainy", temperature:55, templow:44, precipitation_probability:80 },
  ] });
  const daily = byClass(c.shadowRoot, "hours")[0].children;
  check("a daily forecast shows the days after today, each with its low",
        daily.length === 3 && textOf(daily[1], "low") === "45°" && /^[A-Z][a-z]{2}$/.test(textOf(daily[1], "when")) &&
          textOf(daily[2], "wet") === "80%", JSON.stringify(daily.map((cell) => [textOf(cell, "when"), textOf(cell, "deg")])));

  // A 24-hour clock, from the user's profile.
  {
    const clock = overView(withForecast(2, { locale:{ language:"en", time_format:"24" } }), fakeView());
    clock.connectedCallback();
    await tick();
    subscriptions.at(-1).callback({ type:"hourly", forecast:hourly });
    const when = textOf(byClass(clock.shadowRoot, "hours")[0].children[1], "when");
    check("the hours follow the user's 24-hour clock", /^\d{2}$/.test(when), when);
    clock.disconnectedCallback();
  }
  // No forecast to give: nothing is asked for, and nothing shows.
  {
    const count = subscriptions.length;
    const none = overView(withForecast(0), fakeView());
    none.connectedCallback();
    await tick();
    check("an entity with no forecast is not asked for one", subscriptions.length === count &&
          byClass(none.shadowRoot, "hours")[0].hidden === true);
    refuse = true;
    const refused = overView(withForecast(2), fakeView());
    refused.connectedCallback();
    await tick();
    await tick();
    check("a forecast refused leaves the strip hidden", byClass(refused.shadowRoot, "hours")[0].hidden === true);
    refuse = false;
  }
  check("a card on a dashboard has no forecast", byClass(rendered().shadowRoot, "hours").length === 0);
  // Turned off in the integration's options, the panel passes hide_weather: no temperature, no
  // conditions and no forecast strip, and nothing is asked for; the house's counts stay.
  {
    const count = subscriptions.length;
    const off = new Card();
    off.setAttribute("panel", ""); off.setAttribute("view", "");
    off.setConfig({ type:"custom:norman-shades-card", hide_weather:true });
    off.view = fakeView();
    off.hass = withForecast(3);
    off.connectedCallback();
    await tick();
    check("with the weather turned off there is no temperature, conditions or forecast, and no forecast is asked for",
          ["temp", "cond", "hours"].every((name) => byClass(off.shadowRoot, name).length === 0) &&
            subscriptions.length === count && off._forecast === null);
    const [hero] = byClass(off.shadowRoot, "hero");
    const [now] = byClass(off.shadowRoot, "now");
    const said = findAll(byClass(off.shadowRoot, "summary")[0], (el) => el._text !== undefined).map((el) => String(el._text)).join("");
    check("...while the house's counts stay at the top, alone",
          hero?.children.length === 1 && hero.children[0] === now && now.children.length === 1 &&
            now.children[0].className === "summary" && said.includes("2 shades"), said);
    off.disconnectedCallback();
  }
}

// ---- the rooms bar --------------------------------------------------------------------------------
// On a phone the sidebar page has a bar at the foot of the screen that goes to each room.
{
  const narrowPanel = (h, cfg = {}) => {
    const c = new Card();
    c.setAttribute("panel", "");
    c.setConfig({ type:"custom:norman-shades-card", ...cfg });
    c.narrow = true;
    c.hass = h;
    return c;
  };
  const labelOf = (tab) => tab.children.find((child) => child.tagName === "span").textContent;
  const moving = { ...hass, states: { ...hass.states,
    "cover.front_bedroom_1_bottom_rail": { state:"open", attributes:{ current_position:60, target_position:90 } },
    "number.front_bedroom_1_bottom_rail_position": { state:"60" } } };
  const p = narrowPanel(moving);
  const [bar] = byClass(p.shadowRoot, "rooms-bar");
  const tabs = byClass(bar, "room-tab");
  check("the rooms bar goes to the top of the page and to each room", bar?.hidden === false && bar.tagName === "nav" &&
        bar.attrs["aria-label"] === "Rooms" && JSON.stringify(tabs.map(labelOf)) === '["Home","Den","Front Bedroom"]',
        JSON.stringify(tabs.map(labelOf)));
  check("...the top of the page marked to begin with", tabs[0].attrs["aria-current"] === "true" &&
        tabs[1].attrs["aria-current"] === undefined && tabs[0].attrs["aria-label"] === "Back to the top");
  const dots = (tab) => byClass(tab, "dot").filter((dot) => !dot.hidden).map((dot) => dot.className);
  check("a room with a low battery has a dot for it, and says so", JSON.stringify(dots(tabs[1])) === '["dot warn"]' &&
        tabs[1].attrs["aria-label"] === "Den · 1 low battery", `${JSON.stringify(dots(tabs[1]))} ${tabs[1].attrs["aria-label"]}`);
  check("...and one with a shade moving", JSON.stringify(dots(tabs[2])) === '["dot live"]' &&
        tabs[2].attrs["aria-label"] === "Front Bedroom · 1 moving", `${JSON.stringify(dots(tabs[2]))} ${tabs[2].attrs["aria-label"]}`);
  p.hass = hass;
  check("...the dot gone once it stops", JSON.stringify(dots(tabs[2])) === "[]" && tabs[2].attrs["aria-label"] === "Front Bedroom");

  let scrolled = null;
  const room = p._roomLines.find((line) => line.name === "Front Bedroom");
  room.section.scrollIntoView = (options) => { scrolled = options; };
  p._header.getBoundingClientRect = () => ({ top: 0, bottom: 68, height: 68 });
  tabs[2]._on.click();
  check("a room's button scrolls to it, clear of the header", scrolled?.block === "start" &&
        room.section.style.scrollMarginTop === "78px" && tabs[2].attrs["aria-current"] === "true" &&
        tabs[0].attrs["aria-current"] === undefined, JSON.stringify([scrolled, room.section.style.scrollMarginTop]));
  let top = null;
  p._card.scrollIntoView = (options) => { top = options; };
  tabs[0]._on.click();
  check("...and Home to the top of the page", top?.block === "start" && tabs[0].attrs["aria-current"] === "true");

  // As the page scrolls: the last room whose top has passed a third of the way down.
  p._spyHeld = 0;
  const [den, fb] = p._roomLines;
  const box = { scrollTop: 400, clientHeight: 844, scrollHeight: 3000, getBoundingClientRect: () => ({ top: 0, bottom: 844 }) };
  den.section.getBoundingClientRect = () => ({ top: 300 });
  fb.section.getBoundingClientRect = () => ({ top: 900 });
  p._spy(box);
  check("the room in view is marked as the page scrolls", tabs[1].attrs["aria-current"] === "true");
  den.section.getBoundingClientRect = () => ({ top: -400 });
  fb.section.getBoundingClientRect = () => ({ top: 200 });
  p._spy(box);
  check("...and the next as it comes up", tabs[2].attrs["aria-current"] === "true" && tabs[1].attrs["aria-current"] === undefined);
  den.section.getBoundingClientRect = () => ({ top: 500 });
  fb.section.getBoundingClientRect = () => ({ top: 1200 });
  box.scrollTop = 0;
  p._spy(box);
  check("...and the top of the page above the first", tabs[0].attrs["aria-current"] === "true");
  den.section.getBoundingClientRect = () => ({ top: -900 });
  fb.section.getBoundingClientRect = () => ({ top: 600 });
  box.scrollTop = 3000 - 844;
  p._spy(box);
  check("...and the last room at the very end, short as it may be", tabs[2].attrs["aria-current"] === "true");

  const single = narrowPanel({ ...hass, devices: { ...hass.devices, d2: { ...hass.devices.d2, area_id: "a1" } } });
  check("with one room there is no bar", byClass(single.shadowRoot, "rooms-bar")[0]?.hidden === true);
  const noHeadings = narrowPanel(hass, { hide_room_names: true });
  check("...nor with the room headings hidden", byClass(noHeadings.shadowRoot, "rooms-bar")[0]?.hidden === true);
  check("a card on a dashboard has no rooms bar", byClass(rendered().shadowRoot, "rooms-bar").length === 0);
  const german = narrowPanel({ ...hass, locale: { language: "de" } });
  const germanTabs = byClass(byClass(german.shadowRoot, "rooms-bar")[0], "room-tab");
  check("the bar is in the user's language", labelOf(germanTabs[0]) === "Zuhause" &&
        germanTabs[0].attrs["aria-label"] === "Zurück nach oben" &&
        byClass(german.shadowRoot, "rooms-bar")[0].attrs["aria-label"] === "Räume");
}

console.log(fail===0 ? "\nALL PASS" : `\n${fail} FAILED`);
process.exit(fail?1:0);
