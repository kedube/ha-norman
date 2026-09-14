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

// The card's own text, for the few checks that pin a design constant shared between the
// CSS and the JS rather than any runtime behaviour.
const cardSource = await import("node:fs").then((fs) => fs.readFileSync(url, "utf8"));

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
// only a fallback for an entity that somehow has no key. This branch once matched on the
// id unconditionally, unlike every other branch, so a "last seen" sensor a user had
// renamed to *_battery would have displaced the real reading.
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

// --- room-wide controls (opt-in via room_controls) -----------------------------------
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
const roomTargets = calls[0]?.[2] || [];
check("room open includes BOTH rails of a two-rail blind",
      Array.isArray(roomTargets) && roomTargets.length === 2 &&
      roomTargets.includes("cover.front_bedroom_1_bottom_rail") &&
      roomTargets.includes("cover.front_bedroom_1_middle_rail"),
      JSON.stringify(roomTargets));

calls.length = 0;
const denRoom = roomCard._buildRoomControls("Den", [den]);
denRoom.children[2]._on?.click?.();
check("single-rail room close targets its one cover",
      calls.length === 1 && JSON.stringify(calls[0][2]) === JSON.stringify(["cover.den_1_bottom_rail"]),
      JSON.stringify(calls));
check("room close uses close_cover", calls[0]?.[1] === "close_cover", String(calls[0]?.[1]));

calls.length = 0;
const multi = roomCard._buildRoomControls("Everything", [fb, den]);
multi.children[1]._on?.click?.();
check("a room with 2 blinds sends one call covering all 3 rails",
      calls.length === 1 && calls[0][2].length === 3, JSON.stringify(calls));
check("room stop uses stop_cover", calls[0]?.[1] === "stop_cover");
check("room buttons are labelled with the room name",
      String(fbRoom.children[0].title).includes("Front Bedroom"), String(fbRoom.children[0].title));

// On by default: the user asked for whole-room control, so it must not need a setting.
const plain = new Card();
plain._hass = hass; plain.setConfig({ type:"custom:norman-shades-card" }); plain._hass = hass;
check("room controls are ON by default", !plain._config.hide_room_controls);

// Full render path: the option must reach the heading through _build(), not just the builder.
const countRoomButtons = (cfg) => {
  const c = new Card();
  c._hass = hass; c.setConfig({ type:"custom:norman-shades-card", ...cfg }); c._hass = hass;
  c._body = mk("body"); c._cells = [];
  c._build(c._roomsOf(c._collectBlinds()));
  let n = 0;
  const walk = (el) => {
    if (el?.className && String(el.className).includes("room-buttons")) n += el.children.length;
    (el?.children || []).forEach(walk);
  };
  walk(c._body);
  return n;
};
check("_build attaches room controls by default", countRoomButtons({}) === 6,
      String(countRoomButtons({})));
check("_build attaches none when opted out", countRoomButtons({ hide_room_controls:true }) === 0);
check("hiding room headings also hides room controls",
      countRoomButtons({ hide_room_names:true }) === 0);

// --- the app's room presets (opt-in via room_presets) --------------------------------
calls.length = 0;
const presetCard = new Card();
presetCard._hass = hass;
presetCard.setConfig({ type:"custom:norman-shades-card", room_presets:true });
presetCard._hass = hass;
const presets = presetCard._buildRoomPresets("Office");
check("room presets render 3 buttons", presets.children.length === 3, String(presets.children.length));

presets.children[0]._on?.click?.();
check("privacy calls norman.room_command",
      calls.length === 1 && calls[0][0] === "norman" && calls[0][1] === "room_command",
      JSON.stringify(calls));

// The service takes {room, command}, not entity_id -- these are hub room verbs.
calls.length = 0;
const svcCalls = [];
presetCard._hass = { ...hass, callService: (d,s2,data) => svcCalls.push([d,s2,data]) };
const p2 = presetCard._buildRoomPresets("Office");
p2.children[0]._on?.click?.();
p2.children[1]._on?.click?.();
p2.children[2]._on?.click?.();
check("presets send best_privacy / best_view / favorite for the room",
      JSON.stringify(svcCalls.map(c => c[2].command)) ===
        JSON.stringify(["best_privacy","best_view","favorite"]),
      JSON.stringify(svcCalls.map(c => c[2])));
check("presets pass the room name, not entity ids",
      svcCalls.every(c => c[2].room === "Office" && !("entity_id" in c[2])),
      JSON.stringify(svcCalls[0]?.[2]));

// Off by default: it needs the room names to match the hub's, so it is opt-in.
const noPresets = new Card();
noPresets._hass = hass; noPresets.setConfig({ type:"custom:norman-shades-card" }); noPresets._hass = hass;
check("room presets are OFF by default", !noPresets._config.room_presets);

const countPresetButtons = (cfg) => {
  const c = new Card();
  c._hass = hass; c.setConfig({ type:"custom:norman-shades-card", ...cfg }); c._hass = hass;
  c._body = mk("body"); c._cells = [];
  c._build(c._roomsOf(c._collectBlinds()));
  let n = 0;
  const walk = (el) => {
    if (el?.className && String(el.className).includes("room-presets")) n += el.children.length;
    (el?.children || []).forEach(walk);
  };
  walk(c._body);
  return n;
};
check("_build attaches presets by default", countPresetButtons({}) === 6,
      String(countPresetButtons({})));
check("_build drops presets when hidden", countPresetButtons({ hide_room_presets:true }) === 0,
      String(countPresetButtons({ hide_room_presets:true })));

// --- the redesigned rail bar ----------------------------------------------------------
// The bar carries its own label and value, fills to the position, and while the blind
// travels shows where it is heading. Every visual is driven from _patch, so a rail that
// renders but never updates would pass the structural checks above and still be broken.
{
  const c = new Card();
  c._hass = hass; c.setConfig({ type:"custom:norman-shades-card" }); c._hass = hass;
  c._render();
  const cell = c._cells.find(x => x.blind.deviceId === "d1");
  const [b, m] = cell.rails;
  check("the bar carries the rail label inside it",
        b.bar.children.some(ch => ch.className === "bar-label" && ch.textContent === "Bottom rail"));
  check("the fill width follows the position", b.fill.style.width === "60%" && m.fill.style.width === "80%",
        JSON.stringify([b.fill.style.width, m.fill.style.width]));
  check("a rail at rest shows just its value", b.value.textContent === "60%", b.value.textContent);
  check("a rail at rest is not marked moving", !b.bar._moving);

  // The hub reports target_position ahead of current_position for the whole travel.
  const travelling = { ...hass, states: { ...hass.states,
    "cover.front_bedroom_1_bottom_rail": { state:"opening", attributes:{ current_position:60, target_position:100 } } } };
  c.hass = travelling;
  check("a moving rail shows current → target", b.value.textContent === "60% → 100%", b.value.textContent);
  check("the target marker sits at the target", b.targetMark.style.left === "100%", String(b.targetMark.style.left));
  check("the fill stays at the CURRENT position while moving", b.fill.style.width === "60%", b.fill.style.width);
  // The middle rail is not moving and must be unaffected.
  check("an idle rail beside a moving one is unchanged", m.value.textContent === "80%", m.value.textContent);

  // A pending write shows the chosen value alone: the hub's target is still the old one,
  // and "80% → 60%" would read as the blind going the wrong way.
  c._pending.set("number.front_bedroom_1_bottom_rail_position", 30);
  c._patch();
  check("a pending write shows the chosen value, not an arrow", b.value.textContent === "30%", b.value.textContent);
  c._pending.clear();

  // Dragging: the fill must follow the thumb before the value is committed.
  b.slider.value = "20";
  b.slider._on.input();
  check("dragging moves the fill with the thumb", b.fill.style.width === "20%", b.fill.style.width);
}

// --- presets are labelled chips -------------------------------------------------------
{
  const c = new Card();
  c._hass = hass; c.setConfig({ type:"custom:norman-shades-card" }); c._hass = hass;
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

// --- a room's blinds sit in one group -------------------------------------------------
{
  const c = new Card();
  c._hass = hass; c.setConfig({ type:"custom:norman-shades-card" }); c._hass = hass;
  c._render();
  let groups = 0, blindsInGroups = 0;
  const walk = (el) => {
    if (el?.className === "group") { groups++; blindsInGroups += el.children.length; }
    (el?.children || []).forEach(walk);
  };
  walk(c.shadowRoot);
  check("each room wraps its blinds in one group", groups === 2, String(groups));
  check("every blind is inside a group", blindsInGroups === 2, String(blindsInGroups));
}

// --- the header names the hub -------------------------------------------------------
const headerTextOf = (cfg, h = hass) => {
  const c = new Card();
  c._hass = h; c.setConfig({ type:"custom:norman-shades-card", ...cfg }); c._hass = h;
  c._render();
  let found = null;
  const walk = (el) => {
    if (el?.className === "header-text") found = el.textContent;
    (el?.children || []).forEach(walk);
  };
  walk(c.shadowRoot);
  return found;
};

{
  const c = new Card(); c._hass = hass; c.setConfig({ type:"custom:norman-shades-card" }); c._hass = hass;
  check("_hubName returns the hub device's name", c._hubName() === "Norman Hub", String(c._hubName()));
}
check("with no title the header shows the hub name",
      headerTextOf({}) === "Norman Hub", String(headerTextOf({})));
check("an explicit title still wins",
      headerTextOf({ title:"Upstairs" }) === "Upstairs", String(headerTextOf({ title:"Upstairs" })));
// A user who deliberately blanks the title should get a blank header, not the hub name.
check("an explicit empty title is respected",
      headerTextOf({ title:"" }) === "", JSON.stringify(headerTextOf({ title:"" })));
// name_by_user is what Home Assistant shows everywhere else, so it must win here too.
{
  const renamed = { ...hass, devices: { ...hass.devices, hub:{ name:"Norman Hub", name_by_user:"Hallway Hub", area_id:null } } };
  check("a user-renamed hub wins over the app's name",
        headerTextOf({}, renamed) === "Hallway Hub", String(headerTextOf({}, renamed)));
}
// No hub device (an older install, or entities still loading) must not print "null".
{
  const noHub = { ...hass, devices: { d1:hass.devices.d1, d2:hass.devices.d2 } };
  check("with no hub device the header falls back to Shades",
        headerTextOf({}, noHub) === "Shades", String(headerTextOf({}, noHub)));
}
// The header is built once, so a later rename has to be patched in by _update.
{
  const c = new Card(); c._hass = hass; c.setConfig({ type:"custom:norman-shades-card" }); c._hass = hass;
  c._render();
  const renamed = { ...hass, devices: { ...hass.devices, hub:{ name:"Renamed Hub", area_id:null } } };
  c.hass = renamed;
  let text = null;
  const walk = (el) => { if (el?.className === "header-text") text = el.textContent; (el?.children||[]).forEach(walk); };
  walk(c.shadowRoot);
  check("the header follows a hub rename", text === "Renamed Hub", String(text));
}
// A configured title always wins, whatever it says. Cards added before v0.30 carry
// title:"Shades" from the old getStubConfig(), and they keep it: the card cannot tell a
// saved default from a deliberate choice, and overriding a configured title is worse.
check("a configured title always wins, even 'Shades'",
      headerTextOf({ title:"Shades" }) === "Shades",
      String(headerTextOf({ title:"Shades" })));
// The heading must fill in once the device registry loads, not stay stuck at first render.
{
  const empty = { ...hass, devices: {} };
  const c = new Card();
  c._hass = empty; c.setConfig({ type:"custom:norman-shades-card" }); c.hass = empty;
  let text = null;
  const walk = (el) => { if (el?.className === "header-text") text = el.textContent; (el?.children||[]).forEach(walk); };
  walk(c.shadowRoot);
  check("before the registry loads the header falls back", text === "Shades", String(text));
  c.hass = hass;
  text = null; walk(c.shadowRoot);
  check("the header fills in once devices arrive", text === "Norman Hub", String(text));
}
check("the stub config does not hardcode a title",
      Card.getStubConfig().title === undefined, JSON.stringify(Card.getStubConfig()));

// --- house-wide controls (opt-in via home_controls) ----------------------------------
const homeCalls = [];
const homeCard = new Card();
homeCard._hass = { ...hass, callService: (d,s2,data) => homeCalls.push([d,s2,data]) };
homeCard.setConfig({ type:"custom:norman-shades-card" });
homeCard._hass = { ...hass, callService: (d,s2,data) => homeCalls.push([d,s2,data]) };
const home = homeCard._buildHomeControls();
check("home controls render 3 buttons (no stop)", home.children.length === 3, String(home.children.length));

home.children[0]._on?.click?.();
home.children[1]._on?.click?.();
home.children[2]._on?.click?.();
check("home buttons call norman.room_command",
      homeCalls.length === 3 && homeCalls.every(c => c[0]==="norman" && c[1]==="room_command"),
      JSON.stringify(homeCalls));
check("home controls send best_privacy / best_view / favorite",
      JSON.stringify(homeCalls.map(c => c[2].command)) === JSON.stringify(["best_privacy","best_view","favorite"]),
      JSON.stringify(homeCalls.map(c => c[2].command)));
// The house buttons are the room buttons at a wider scope, so they must present the same
// three verbs in the same order -- a user who learns the room row can read the header row.
const presetOrder = [];
const orderCard = new Card();
orderCard._hass = { ...hass, callService: (d,s2,data) => presetOrder.push(data.command) };
orderCard.setConfig({ type:"custom:norman-shades-card" });
orderCard._hass = { ...hass, callService: (d,s2,data) => presetOrder.push(data.command) };
const presetRow = orderCard._buildRoomPresets("Den");
[...presetRow.children].forEach(b => b._on?.click?.());
check("house buttons match the room buttons in order",
      JSON.stringify(presetOrder) === JSON.stringify(homeCalls.map(c => c[2].command)),
      JSON.stringify(presetOrder));
// They are the app's named presets, not open/close: a down arrow would promise both
// fabrics down, but best_privacy leaves the middle rail fully open.
const homeIcons = [...home.children].map(b => b.children[0]?.getAttribute?.("icon"));
check("house buttons are not labelled as open/close arrows",
      !homeIcons.includes("mdi:arrow-up") && !homeIcons.includes("mdi:arrow-down"),
      JSON.stringify(homeIcons));
// The absence of `room` is what makes it house-wide; sending one would scope it to a room.
check("home controls omit the room entirely",
      homeCalls.every(c => !("room" in c[2])), JSON.stringify(homeCalls[0]?.[2]));

const noHome = new Card();
noHome._hass = hass; noHome.setConfig({ type:"custom:norman-shades-card" }); noHome._hass = hass;
// The user asked for these buttons, so they ship on; hide_* is the escape hatch.
check("home controls are ON by default", !noHome._config.hide_home_controls);

// The header must appear for the buttons even when no title is configured.
const headerButtons = (cfg) => {
  const c = new Card();
  c._hass = hass; c.setConfig({ type:"custom:norman-shades-card", ...cfg }); c._hass = hass;
  c._render();
  let n = 0;
  const walk = (el) => {
    if (el?.className && String(el.className).includes("home-buttons")) n += el.children.length;
    (el?.children || []).forEach(walk);
  };
  walk(c.shadowRoot);
  return n;
};
check("home controls render with no title set", headerButtons({}) === 3,
      String(headerButtons({})));
check("home controls render alongside a title", headerButtons({ title:"Shades" }) === 3,
      String(headerButtons({ title:"Shades" })));
check("home controls drop out when hidden",
      headerButtons({ hide_home_controls:true }) === 0,
      String(headerButtons({ hide_home_controls:true })));

// ---- the shade picture --------------------------------------------------------------
// The picture's geometry is the part no amount of reading catches: a sign error puts the
// fabric at the wrong end of the window, and a band that starts below where it ends draws
// nothing at all. These pin the arithmetic that _drawShade and _clampRail perform.

const pictureCard = () => {
  const c = new Card();
  c._hass = hass; c.setConfig({ type:"custom:norman-shades-card" }); c._hass = hass;
  return c;
};

// A two-rail blind: rails[0] is the bottom rail, rails[1] the middle.
const twoRail = pictureCard();
const twoRailBlind = twoRail._collectBlinds().find(b => b.middleCover);
check("two-rail blind is found for the picture", !!twoRailBlind);

// Render a whole card and assert nothing shows a stray "undefined". The geometry checks
// below call _buildShade directly with the right arguments, which is exactly how a caller
// passing the WRONG ones slipped through: _buildBlind hands it the built-rail wrappers,
// whose .label is undefined, and the readouts printed "undefined: 40%".
const renderedText = (cfg = {}) => {
  const c = new Card();
  c._hass = hass; c.setConfig({ type:"custom:norman-shades-card", ...cfg }); c._hass = hass;
  c._render();
  const seen = [];
  const walk = (el) => {
    if (el?._text) seen.push(String(el._text));
    for (const k of ["title", "aria-label"]) if (el?.attrs?.[k]) seen.push(String(el.attrs[k]));
    (el?.children || []).forEach(walk);
  };
  walk(c.shadowRoot);
  return seen.join(" | ");
};
check("a rendered card shows no stray 'undefined'",
      !renderedText().includes("undefined"),
      renderedText().split(" | ").filter(s => s.includes("undefined")).join(" ; "));
check("a rendered card shows no stray 'NaN'",
      !renderedText().includes("NaN"),
      renderedText().split(" | ").filter(s => s.includes("NaN")).join(" ; "));
check("the readouts name each rail on a two-rail blind",
      renderedText().includes("Bottom rail") && renderedText().includes("Middle rail"));

const shadeFor = (card, blind, values) => {
  const rails = card._railsOf(blind);
  const shade = card._buildShade(blind, rails);
  // Drive the drawing off explicit values rather than whatever the fake hub reports.
  shade.dragValues = Object.fromEntries(values.map((v, i) => [i, v]));
  card._drawShade(shade);
  return shade;
};

// Fully open: every rail sits at the head, so no fabric is showing.
// The headbox depth is a design constant; read it rather than restating it, so moving the
// headbox does not require editing arithmetic in three places.
const HEAD = Number(/--n-head:\s*([\d.]+)%/.exec(cardSource)[1]);
check("the CSS headbox and the JS constant agree",
      HEAD === Number(/const SHADE_HEAD_PCT = ([\d.]+);/.exec(cardSource)[1]),
      String(HEAD));

const open = shadeFor(twoRail, twoRailBlind, [100, 100]);
check("open: bottom rail sits at the head", open.railEls[0].style.top === `${HEAD}%`,
      open.railEls[0].style.top);
check("open: no fabric hangs", open.bands.every(b => parseFloat(b.style.height) === 0),
      open.bands.map(b => b.style.height).join(" "));

// Fully closed: the bottom rail reaches the sill.
const closed = shadeFor(twoRail, twoRailBlind, [0, 0]);
check("closed: bottom rail reaches the sill", closed.railEls[0].style.top === "100%",
      closed.railEls[0].style.top);

// Bottom 20 / middle 80: two contiguous bands, neither inverted.
const mixed = shadeFor(twoRail, twoRailBlind, [20, 80]);
const sheerTop = parseFloat(mixed.bands[1].style.top);
const sheerH = parseFloat(mixed.bands[1].style.height);
const blackTop = parseFloat(mixed.bands[0].style.top);
const blackH = parseFloat(mixed.bands[0].style.height);
check("mixed: sheer band starts at the head", Math.abs(sheerTop - HEAD) < 0.01, String(sheerTop));
check("mixed: bands are contiguous (no gap, no overlap)",
      Math.abs((sheerTop + sheerH) - blackTop) < 0.01,
      `${sheerTop}+${sheerH} vs ${blackTop}`);
check("mixed: no band has negative height", sheerH >= 0 && blackH >= 0,
      `${sheerH} ${blackH}`);
check("mixed: the middle rail sits above the bottom rail",
      parseFloat(mixed.railEls[1].style.top) < parseFloat(mixed.railEls[0].style.top),
      `${mixed.railEls[1].style.top} vs ${mixed.railEls[0].style.top}`);
check("mixed: each rail sits on its band's bottom edge",
      Math.abs(parseFloat(mixed.railEls[1].style.top) - (sheerTop + sheerH)) < 0.01 &&
      Math.abs(parseFloat(mixed.railEls[0].style.top) - (blackTop + blackH)) < 0.01);

// The pleat. A cellular shade reads as a shade because it is visibly DIVIDED into cells:
// a hard fold line at the top of each, then a ramp to a lit lip at the bottom. Earlier
// versions lost that -- soft, closely-spaced stops averaged out to a flat grey panel at
// the size the card actually renders -- so the structure is pinned here.
const fabricCss = (() => {
  const i = cardSource.indexOf(".shade-band {", cardSource.indexOf("--n-cell:"));
  return cardSource.slice(i, cardSource.indexOf(".shade-band.sheer", i));
})();
check("the fabric is built from a repeating cell",
      fabricCss.includes("repeating-linear-gradient"));
check("each cell has a hard fold line at its top",
      /var\(--n-fold\) 0 1px/.test(fabricCss), fabricCss.slice(0, 160));
check("the cell height is a single tunable token",
      /--n-cell:\s*\d+px/.test(cardSource) && fabricCss.includes("var(--n-cell)"));
// The cell is the reference's own 6px tile. An earlier version of this check demanded
// >=8px on the theory that 6px would turn to mush at card width; that was a guess, and
// the reference's 6px is what actually looks like a shade. Pin it to the source value.
const cellPx = Number(/--n-cell:\s*(\d+)px/.exec(cardSource)[1]);
check("the cell matches the reference tile's 6px pitch", cellPx === 6, String(cellPx));
// Both fabrics must keep the same cell rhythm, or the join reads as a rendering fault
// rather than as two fabrics meeting.
const sheerCss = cardSource.slice(
  cardSource.indexOf(".shade-band.sheer {"),
  cardSource.indexOf("/* A rail is an extruded bar"),
);
check("the sheer fabric keeps the same cell height",
      sheerCss.includes("var(--n-cell)"), sheerCss.slice(0, 200));
check("the sheer fabric has its own fold line",
      /rgba\([^)]+\) 0 1px/.test(sheerCss));

// The opening must be DARK -- darker than the fabric, by a wide margin.
// This is the graphic's core distinction: an open window is a hole you see through, a
// closed one is a pale fabric panel. An earlier version tinted the opening from the text
// colour at 6% alpha, which rendered LIGHTER than the fabric in a light theme, so "open"
// and "closed" looked the same. A rough luminance of the darkest colour in each token is
// enough to catch that inversion.
const darkestIn = (css) => {
  let worst = 255;
  for (const [, hex] of css.matchAll(/#([0-9a-f]{6})\b/gi)) {
    const n = parseInt(hex, 16);
    const l = 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255);
    worst = Math.min(worst, l);
  }
  return worst;
};
const lightestIn = (css) => {
  let best = 0;
  for (const [, hex] of css.matchAll(/#([0-9a-f]{6})\b/gi)) {
    const n = parseInt(hex, 16);
    const l = 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255);
    best = Math.max(best, l);
  }
  return best;
};
const openingCss = /--n-opening:([^;]+);/.exec(cardSource)[1];
check("the opening is defined with explicit dark colours, not a theme tint",
      /#[0-9a-f]{6}/i.test(openingCss), openingCss.trim());
const openingLum = lightestIn(openingCss);
check("the opening is dark", openingLum < 110, String(Math.round(openingLum)));
// The fabric's DARKEST tone must still be clearly lighter than the opening's lightest.
const fabricLum = darkestIn(fabricCss);
check("the fabric is clearly lighter than the opening",
      fabricLum - openingLum > 60,
      `fabric ${Math.round(fabricLum)} vs opening ${Math.round(openingLum)}`);

// Which fabric covers the window, per the app's own presets. This is the substantive
// correctness question in the picture: a closed blind drawn as the sheer fabric tells the
// user the window is see-through when it is not.
const covering = (values) => {
  const s = shadeFor(twoRail, twoRailBlind, values);
  return s.bands
    .map((b, i) => ({ cls: String(b.className), h: parseFloat(b.style.height) || 0 }))
    .filter((b) => b.h > 0.05)
    .map((b) => (b.cls.includes("sheer") ? "sheer" : "blackout") + ":" + Math.round(b.h))
    .join(" ");
};
// The full travel, derived rather than restated, so moving the headbox does not require
// editing these expectations.
const FULL = Math.round(100 - HEAD);
// Fully closed: the blackout fabric covers the whole opening.
check("closed (0/0) is covered by the BLACKOUT fabric",
      covering([0, 0]) === `blackout:${FULL}`, covering([0, 0]));
// "Best privacy" is bottom 0 / middle 100 -- the blackout stacks away at the head and the
// sheer covers the window: "closed for privacy, sheer fabric still open".
check("Best privacy (0/100) is covered by the SHEER fabric",
      covering([0, 100]) === `sheer:${FULL}`, covering([0, 100]));
// Both rails up: nothing covers the opening at all.
check("open (100/100) leaves the opening clear", covering([100, 100]) === "",
      covering([100, 100]));
// Part-way: the blackout hangs from the head to the middle rail, the sheer below it.
// Part-open: the blackout hangs head->middle (20% of travel) and the sheer middle->bottom
// (60% of travel), both as a share of the travel rather than of the whole picture.
check("part-open draws blackout above the middle rail and sheer below",
      covering([20, 80]) ===
        `sheer:${Math.round((100 - HEAD) * 0.6)} blackout:${Math.round((100 - HEAD) * 0.2)}`,
      covering([20, 80]));

// Clamping: the rails are physically stacked and must never cross.
const clampShade = shadeFor(twoRail, twoRailBlind, [20, 80]);
check("clamp: the bottom rail cannot rise above the middle",
      twoRail._clampRail(clampShade, 0, 95) === 80,
      String(twoRail._clampRail(clampShade, 0, 95)));
check("clamp: the middle rail cannot drop below the bottom",
      twoRail._clampRail(clampShade, 1, 5) === 20,
      String(twoRail._clampRail(clampShade, 1, 5)));
check("clamp: a legal drag is left alone",
      twoRail._clampRail(clampShade, 0, 10) === 10,
      String(twoRail._clampRail(clampShade, 0, 10)));

// A single-rail blind has nothing to clamp against and one band only.
const oneRail = pictureCard();
const oneRailBlind = oneRail._collectBlinds().find(b => !b.middleCover);
const single = shadeFor(oneRail, oneRailBlind, [40]);
check("single-rail: one band only", single.bands.length === 1, String(single.bands.length));
check("single-rail: nothing to clamp against",
      oneRail._clampRail(single, 0, 90) === 90,
      String(oneRail._clampRail(single, 0, 90)));

// hide_picture must actually drop the picture, since it is the card's largest element.
const hidden = new Card();
hidden._hass = hass;
hidden.setConfig({ type:"custom:norman-shades-card", hide_picture:true });
hidden._hass = hass;
hidden._render();
let pictures = 0;
const countPictures = (el) => {
  if (el?.className && String(el.className).split(" ").includes("shade")) pictures += 1;
  (el?.children || []).forEach(countPictures);
};
countPictures(hidden.shadowRoot);
check("hide_picture removes every picture", pictures === 0, String(pictures));

console.log(fail===0 ? "\nALL PASS" : `\n${fail} FAILED`);
process.exit(fail?1:0);
