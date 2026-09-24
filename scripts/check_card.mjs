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
  constructor(){ this.children=[]; }
  attachShadow(){ this.shadowRoot = mk('root'); return this.shadowRoot; }
  appendChild(c){ this.children.push(c); return c; }
  addEventListener(){}
  dispatchEvent(e){ (this._events ||= []).push(e); }
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
    addEventListener(ev,fn){ (this._on ||= {})[ev] = fn; },
    setAttribute(k,v){ this.attrs[k]=String(v); }, getAttribute(k){ return this.attrs[k]; },
    remove(){}, querySelector(){ return null; }, querySelectorAll(){ return []; },
    get firstChild(){ return this.children[0]; },
    get lastChild(){ return this.children[this.children.length-1]; },
    set textContent(v){ this._text = String(v); }, get textContent(){ return this._text; },
    set innerHTML(v){ if(v==="") this.children=[]; },
  };
  el.classList = classListOf(el);
  return el;
};
globalThis.document = { createElement: mk };
globalThis.console.info = () => {};

const url = new URL("file://" + process.cwd() + "/custom_components/norman/www/norman-shades-card.js");
url.searchParams.set("v", "test");
await import(url.href);

// The card's own text, for the few checks that pin a design constant shared between the
// CSS and the JS rather than any runtime behaviour.
const cardSource = await import("node:fs").then((fs) => fs.readFileSync(url, "utf8"));

// The headrail depth and rail thickness are design constants shared by the CSS and the JS;
// read them rather than restating them.
const HEAD = Number(/--n-head:\s*([\d.]+)%/.exec(cardSource)[1]);
const RAIL = Number(/--n-rail:\s*([\d.]+)%/.exec(cardSource)[1]);
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
  // Noise that must be ignored:
  "button.den_1_jog_up": { platform:"norman", device_id:"d2", translation_key:"jog_up" },
  "sensor.norman_hub_wi_fi_network": { platform:"norman", device_id:"hub", translation_key:"wifi_ssid" },
  "light.kitchen": { platform:"hue", device_id:"d9" },
};
const hass = {
  entities,
  devices: { d1:{ name:"Front_Bedroom_1", area_id:"a1" }, d2:{ name:"Den_1", area_id:"a2" }, hub:{ name:"Norman Hub", area_id:null } },
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
  },
};
card._hass = hass;
card.setConfig({ type:"custom:norman-shades-card" });
card._hass = hass;

const blinds = card._collectBlinds();
let fail = 0;
const check = (label, cond, extra="") => { console.log(`${cond?"PASS":"FAIL"}  ${label}${extra&&!cond?"  -> "+extra:""}`); if(!cond) fail++; };

check("finds exactly 2 blinds (hub excluded)", blinds.length===2, JSON.stringify(blinds.map(b=>b.name)));
const fb = blinds.find(b=>b.deviceId==="d1");
const den = blinds.find(b=>b.deviceId==="d2");
check("two-rail: bottom cover", fb?.bottomCover==="cover.front_bedroom_1_bottom_rail", String(fb?.bottomCover));
check("two-rail: MIDDLE cover found", fb?.middleCover==="cover.front_bedroom_1_middle_rail", String(fb?.middleCover));
check("two-rail: bottom slider", fb?.bottomNumber==="number.front_bedroom_1_bottom_rail_position", String(fb?.bottomNumber));
check("two-rail: MIDDLE slider found", fb?.middleNumber==="number.front_bedroom_1_middle_rail_position", String(fb?.middleNumber));
check("two-rail: battery found", fb?.battery==="sensor.front_bedroom_1_battery", String(fb?.battery));
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

fbRoom.children[0]._on?.click?.();
check("room open sends ONE call", calls.length === 1, JSON.stringify(calls));
const roomTargets = calls[0]?.[2]?.entity_id || [];
check("room open includes BOTH rails of a two-rail blind",
      Array.isArray(roomTargets) && roomTargets.length === 2 &&
      roomTargets.includes("cover.front_bedroom_1_bottom_rail") &&
      roomTargets.includes("cover.front_bedroom_1_middle_rail"),
      JSON.stringify(roomTargets));

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
check("a room with 2 blinds sends one call covering all 3 rails",
      calls.length === 1 && calls[0][2].entity_id.length === 3, JSON.stringify(calls));
check("room stop uses stop_cover", calls[0]?.[1] === "stop_cover");
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
  const presets = c._buildRoomPresets("Office");
  check("room presets render 3 buttons", presets.children.length === 3, String(presets.children.length));
  [...presets.children].forEach(b => b._on?.click?.());
  check("presets call norman.room_command",
        svcCalls.every(x => x[0] === "norman" && x[1] === "room_command"), JSON.stringify(svcCalls));
  check("presets send best_privacy / best_view / favorite for the room",
        JSON.stringify(svcCalls.map(x => x[2].command)) === JSON.stringify(["best_privacy","best_view","favorite"]),
        JSON.stringify(svcCalls.map(x => x[2])));
  check("presets pass the room name, not entity ids",
        svcCalls.every(x => x[2].room === "Office" && !("entity_id" in x[2])),
        JSON.stringify(svcCalls[0]?.[2]));
}
check("_build attaches presets by default", countIn({}, "room-presets") === 6,
      String(countIn({}, "room-presets")));
check("_build drops presets when hidden", countIn({ hide_room_presets:true }, "room-presets") === 0);
{
  // The presets fold out of the heading: hidden until its button is pressed.
  const c = rendered();
  const [tray] = byClass(c.shadowRoot, "tray");
  const [more] = byClass(c.shadowRoot, "more");
  check("a room's presets start folded away", tray?.hidden === true, String(tray?.hidden));
  more._on.click();
  check("the room's presets button folds them out", tray.hidden === false && more.attrs["aria-expanded"] === "true");
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
  check("_hubName returns the hub device's name", c._hubName() === "Norman Hub", String(c._hubName()));
}
check("with no title the header shows the hub name", headerTextOf({}) === "Norman Hub", String(headerTextOf({})));
check("an explicit title still wins", headerTextOf({ title:"Upstairs" }) === "Upstairs");
// A user who deliberately blanks the title should get a blank header, not the hub name.
check("an explicit empty title is respected", headerTextOf({ title:"" }) === "", JSON.stringify(headerTextOf({ title:"" })));
{
  const renamed = { ...hass, devices: { ...hass.devices, hub:{ name:"Norman Hub", name_by_user:"Hallway Hub", area_id:null } } };
  check("a user-renamed hub wins over the app's name", headerTextOf({}, renamed) === "Hallway Hub");
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
  const empty = { ...hass, devices: {} };
  const c = new Card();
  c._hass = empty; c.setConfig({ type:"custom:norman-shades-card" }); c.hass = empty;
  check("before the registry loads the header falls back", byClass(c.shadowRoot, "header-text")[0].textContent === "Shades");
  c.hass = hass;
  check("the header fills in once devices arrive", byClass(c.shadowRoot, "header-text")[0].textContent === "Norman Hub");
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
check("home controls render by default", countIn({}, "home-buttons") === 3);
check("home controls render alongside a title", countIn({ title:"Shades" }, "home-buttons") === 3);
check("home controls drop out when hidden", countIn({ hide_home_controls:true }, "home-buttons") === 0);

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
  // The battery icon carries the level; the number is printed only when it needs attention.
  const [fbBattery, denBattery] = ["d1", "d2"].map(id => c._cells.find(x => x.blind.deviceId === id).batteryEl);
  check("a healthy battery shows its icon, not a number", fbBattery.lastChild.textContent === "" && fbBattery.title === "Battery 84%");
  check("a low battery shows its number", denBattery.lastChild.textContent === "12%" && denBattery.className.includes("critical"));
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
  const c = rendered();
  c.hass = { ...hass, devices: { ...hass.devices, d2:{ name:"Den_1", name_by_user:"Den window", area_id:"a2" } } };
  check("a renamed blind is renamed on the card",
        c._cells.some(x => x.blind.name === "Den window"), JSON.stringify(c._cells.map(x => x.blind.name)));
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
const [sheer, blackout] = mixed.bands;
check("mixed: the upper band starts at the headrail", near(top(blackout), HEAD), blackout.style.top);
check("mixed: the upper band ends on the middle rail", near(top(blackout) + height(blackout), top(mixed.railEls[1])));
check("mixed: the lower band hangs from the middle rail", near(top(sheer), top(mixed.railEls[1]) + RAIL));
check("mixed: the lower band ends on the bottom rail", near(top(sheer) + height(sheer), top(mixed.railEls[0])));
check("mixed: the middle rail sits above the bottom rail", top(mixed.railEls[1]) < top(mixed.railEls[0]));
check("mixed: each grab zone is centred on its rail",
      mixed.zones.every((z, i) => near(top(z), top(mixed.railEls[i]) + RAIL / 2)));

// Which fabric covers the window, per the app's own presets. A closed blind drawn as the
// sheer fabric tells the user the window is see-through when it is not.
const TRAVEL = 100 - HEAD - 2 * RAIL;
const covering = (values) => shadeFor(twoRail, twoRailBlind, values).bands
  .map((b) => ({ kind: b.className.includes("sheer") ? "sheer" : b.className.includes("blackout") ? "blackout" : "?", h: height(b) }))
  .filter((b) => b.h > 0.05)
  .map((b) => `${b.kind}:${Math.round(b.h)}`)
  .join(" ");
check("closed (0/0) is covered by the BLACKOUT fabric", covering([0, 0]) === `blackout:${Math.round(TRAVEL)}`, covering([0, 0]));
check("Best privacy (0/100) is covered by the SHEER fabric", covering([0, 100]) === `sheer:${Math.round(TRAVEL)}`, covering([0, 100]));
check("open (100/100) leaves the opening clear", covering([100, 100]) === "", covering([100, 100]));
check("part-open: blackout above the middle rail, sheer below",
      covering([20, 80]) === `sheer:${Math.round(TRAVEL * 0.6)} blackout:${Math.round(TRAVEL * 0.2)}`, covering([20, 80]));

// Clamping: the rails are physically stacked and must never cross.
const clampShade = shadeFor(twoRail, twoRailBlind, [20, 80]);
check("clamp: the bottom rail cannot rise above the middle", twoRail._clampRail(clampShade, 0, 95) === 80);
check("clamp: the middle rail cannot drop below the bottom", twoRail._clampRail(clampShade, 1, 5) === 20);
check("clamp: a legal drag is left alone", twoRail._clampRail(clampShade, 0, 10) === 10);

// Rails pressed together can only part, so the drag's direction picks the rail.
const stackedOpen = shadeFor(twoRail, twoRailBlind, [100, 100]);
check("stacked open: a drag down takes the BOTTOM rail", twoRail._railFor(stackedOpen, 1, -1) === 0);
const stackedShut = shadeFor(twoRail, twoRailBlind, [0, 0]);
check("stacked closed: a drag up takes the MIDDLE rail", twoRail._railFor(stackedShut, 0, 1) === 1);
check("apart, the pressed rail keeps the drag", twoRail._railFor(clampShade, 0, 1) === 0 && twoRail._railFor(clampShade, 1, -1) === 1);

// A single-rail blind has one band, one rail, and nothing to clamp against.
const oneRail = pictureCard();
const oneRailBlind = oneRail._collectBlinds().find(b => !b.middleCover);
const single = shadeFor(oneRail, oneRailBlind, [40]);
check("single-rail: one band only", single.bands.length === 1, String(single.bands.length));
check("single-rail: nothing to clamp against", oneRail._clampRail(single, 0, 90) === 90);
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
  check("a slider shows its rail's position", fbSliders[0].input.value === "80" && fbSliders[0].value.textContent === "80%");
  calls.length = 0;
  fbSliders[1].input.value = "20";
  fbSliders[1].input._on.change();
  check("moving a slider writes that rail", calls[0]?.[2]?.entity_id === "number.front_bedroom_1_bottom_rail_position" && calls[0][2].value === 20,
        JSON.stringify(calls[0]));
}

console.log(fail===0 ? "\nALL PASS" : `\n${fail} FAILED`);
process.exit(fail?1:0);
