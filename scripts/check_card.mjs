// Exercise the Norman shades card outside a browser.
//
//     node scripts/check_card.mjs
//
// The card assembles a blind from its entities using the *frontend* entity registry, which
// is a reduced view: it carries translation_key but NOT unique_id (see
// EntityRegistryEntry._as_display_dict in homeassistant/helpers/entity_registry.py). Reading
// a field that is not there fails silently -- the entity is simply never found -- so this
// harness feeds the card a hass object shaped exactly like the real one and asserts that the
// middle rail, both sliders and the battery are all located.
//
// CI has no Node, so this is a local tool; tests/test_repo_consistency.py pins the same
// contract in Python.

const els = new Map();
globalThis.window = globalThis;
globalThis.HTMLElement = class {
  constructor(){ this.children=[]; }
  attachShadow(){ this.shadowRoot = mk('root'); return this.shadowRoot; }
  appendChild(c){ this.children.push(c); return c; }
  addEventListener(){}
  dispatchEvent(){}
};
globalThis.customElements = { get: () => undefined, define: (n,c) => els.set(n,c) };
const mk = (tag) => {
  const el = {
    tagName: tag, children: [], style: {}, dataset: {}, attrs: {}, _text: "",
    className: "", classList: { add(){}, remove(){}, toggle(){} },
    appendChild(c){ this.children.push(c); return c; },
    append(...c){ this.children.push(...c); },
    addEventListener(ev,fn){ (this._on ||= {})[ev] = fn; },
    setAttribute(k,v){ this.attrs[k]=v; }, getAttribute(k){ return this.attrs[k]; },
    remove(){}, querySelector(){ return null; }, querySelectorAll(){ return []; },
    get firstChild(){ return this.children[0]; },
    get lastChild(){ return this.children[this.children.length-1]; },
    set textContent(v){ this._text = String(v); }, get textContent(){ return this._text; },
    set innerHTML(v){ if(v==="") this.children=[]; },
  };
  return el;
};
globalThis.document = { createElement: mk };
globalThis.console.info = () => {};

const url = new URL("file://" + process.cwd() + "/custom_components/norman/www/norman-shades-card.js");
url.searchParams.set("v", "test");
await import(url.href);

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

const rails = card._railsOf(fb);
check("two-rail renders TWO rail rows", rails.length===2, JSON.stringify(rails.map(r=>r.label)));
check("rail labels are Bottom/Middle", rails[0].label==="Bottom rail" && rails[1].label==="Middle rail");
check("single-rail renders ONE rail row", card._railsOf(den).length===1);
check("rail values read from number entity", card._railValue(rails[0])===60 && card._railValue(rails[1])===80);

const rooms = card._roomsOf(blinds);
check("groups into 2 rooms", rooms.length===2, JSON.stringify(rooms.map(r=>r[0])));
check("rooms sorted alphabetically", rooms[0][0]==="Den" && rooms[1][0]==="Front Bedroom");

// --- per-rail open/stop/close -------------------------------------------------------
// Regression: the buttons used to live in the blind header and always targeted the bottom
// rail, so a two-rail blind had no way to open or stop its middle rail from the card.
const calls = [];
hass.callService = (domain, service, data) => { calls.push([domain, service, data.entity_id]); };

card._cells = [];   // normally set up by _render(); we call _buildBlind directly
card._buildBlind(fb);
card._buildBlind(den);
const cellFb = card._cells.find(c => c.blind.deviceId === "d1");
const cellDen = card._cells.find(c => c.blind.deviceId === "d2");

check("two-rail: both rails built", cellFb?.rails.length === 2, String(cellFb?.rails.length));
check("each rail has 3 buttons", cellFb?.rails.every(r => r.buttons?.length === 3),
      JSON.stringify(cellFb?.rails.map(r => r.buttons?.length)));

// Fire every button on the MIDDLE rail and confirm it targets the middle cover.
const middle = cellFb.rails[1];
for (const b of middle.buttons) b._on?.click?.();
const middleTargets = calls.map(c => c[2]);
check("middle rail buttons target the MIDDLE cover",
      middleTargets.length === 3 && middleTargets.every(t => t === "cover.front_bedroom_1_middle_rail"),
      JSON.stringify(calls));
check("middle rail sends open/stop/close",
      JSON.stringify(calls.map(c => c[1])) === JSON.stringify(["open_cover","stop_cover","close_cover"]),
      JSON.stringify(calls.map(c => c[1])));

calls.length = 0;
const bottom = cellFb.rails[0];
for (const b of bottom.buttons) b._on?.click?.();
check("bottom rail buttons target the BOTTOM cover",
      calls.length === 3 && calls.every(c => c[2] === "cover.front_bedroom_1_bottom_rail"),
      JSON.stringify(calls));

calls.length = 0;
check("single-rail blind has one rail with buttons",
      cellDen?.rails.length === 1 && cellDen.rails[0].buttons.length === 3);
for (const b of cellDen.rails[0].buttons) b._on?.click?.();
check("single-rail buttons target its own cover",
      calls.length === 3 && calls.every(c => c[2] === "cover.den_1_bottom_rail"),
      JSON.stringify(calls));

check("buttons are labelled per rail",
      middle.buttons[0].title === "open middle rail" || middle.buttons[0].title === "Open middle rail",
      String(middle.buttons[0].title));

console.log(fail===0 ? "\nALL PASS" : `\n${fail} FAILED`);
process.exit(fail?1:0);
