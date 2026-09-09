/**
 * Norman shades card.
 *
 * Groups every Norman blind by room and gives each rail a percentage slider in 10% steps,
 * with the blind's battery level alongside. Written as a plain custom element with no build
 * step and no external dependencies, so the file that ships is the file that runs.
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
   * A literal "Shades" is treated as unset. Until 0.30 `getStubConfig()` returned
   * `title: "Shades"`, so every card added from the picker had that string written into
   * its saved dashboard config -- it was the default, not a choice anyone made. Honouring
   * it would mean the hub name only ever appeared for people who added a card after 0.30,
   * which is the opposite of the point. Anyone who genuinely wants the word can set
   * `title: Shades ` or any other spelling; `title: ""` still gives a blank heading.
   */
  _headingText() {
    const configured = this._config.title;
    if (configured !== undefined && configured !== "Shades") return configured;
    return this._hubName() ?? "Shades";
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
      ha-card { padding: 8px 0 12px; }
      .header {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: var(--ha-card-header-font-size, 24px);
        font-weight: var(--ha-card-header-font-weight, 400);
        color: var(--ha-card-header-color, var(--primary-text-color));
        padding: 12px 16px 8px;
      }
      .header-text {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .home-buttons ha-icon-button { --mdc-icon-button-size: 34px; --mdc-icon-size: 21px; }
      .room { padding: 4px 0 8px; }
      .room-name {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.85rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--secondary-text-color);
        padding: 10px 16px 4px;
      }
      .room-name-text {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      /* The room's buttons sit slightly smaller than a rail's, so the heading stays a
         heading and the per-rail controls remain the primary ones. */
      .room-buttons ha-icon-button { --mdc-icon-button-size: 28px; --mdc-icon-size: 17px; }
      .room-presets ha-icon-button { --mdc-icon-button-size: 28px; --mdc-icon-size: 16px; }
      /* A hairline between the two groups: the left set fans out over Home Assistant's
         cover entities, the right set sends the hub's own room verbs. */
      .room-presets { border-left: 1px solid var(--divider-color); margin-left: 4px; padding-left: 4px; }
      .blind {
        padding: 8px 16px 10px;
        border-top: 1px solid var(--divider-color);
      }
      .room .blind:first-of-type { border-top: none; }
      .blind.unavailable { opacity: 0.5; }
      .blind-head {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 2px;
      }
      .blind-name {
        flex: 1;
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
      }
      .battery ha-icon { --mdc-icon-size: 18px; }
      .battery.low { color: var(--warning-color, #ff9800); }
      .battery.critical { color: var(--error-color, #f44336); }
      .rail {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 3px 0;
      }
      .rail-label {
        width: 82px;
        flex: none;
        font-size: 0.8rem;
        color: var(--secondary-text-color);
      }
      .rail input[type="range"] {
        flex: 1;
        min-width: 0;
        accent-color: var(--primary-color);
        cursor: pointer;
      }
      .rail input[type="range"]:disabled { cursor: not-allowed; }
      .rail-value {
        width: 46px;
        flex: none;
        text-align: right;
        font-variant-numeric: tabular-nums;
        font-size: 0.85rem;
      }
      .buttons { display: flex; gap: 0; flex: none; }
      .buttons ha-icon-button { --mdc-icon-button-size: 32px; --mdc-icon-size: 19px; }
      .buttons ha-icon-button[disabled] { opacity: 0.4; }
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

        if (!this._config.hide_room_controls) {
          label.appendChild(this._buildRoomControls(roomName, list));
        }
        if (!this._config.hide_room_presets) {
          label.appendChild(this._buildRoomPresets(roomName));
        }
        room.appendChild(label);
      }

      for (const blind of list) {
        room.appendChild(this._buildBlind(blind));
      }
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
    controls.className = "buttons room-buttons";

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
    controls.className = "buttons home-buttons";

    for (const [icon, command, label] of [
      ["mdi:blinds-horizontal", "best_privacy", "Best privacy — every room"],
      ["mdi:weather-sunny", "best_view", "Best view — every room"],
      ["mdi:star", "favorite", "Favorite — every room"],
    ]) {
      const button = document.createElement("ha-icon-button");
      const inner = document.createElement("ha-icon");
      inner.setAttribute("icon", icon);
      button.appendChild(inner);
      button.title = label;
      button.setAttribute("aria-label", label);
      button.addEventListener("click", () => {
        // No `room`: the action omits RoomID, which the hub reads as every blind.
        this._hass.callService("norman", "room_command", { command });
      });
      controls.appendChild(button);
    }
    return controls;
  }

  _buildRoomPresets(roomName) {
    const presets = document.createElement("div");
    presets.className = "buttons room-presets";

    for (const [icon, command, label] of [
      ["mdi:blinds-horizontal", "best_privacy", "Best privacy"],
      ["mdi:weather-sunny", "best_view", "Best view"],
      ["mdi:star", "favorite", "Favorite"],
    ]) {
      const button = document.createElement("ha-icon-button");
      const inner = document.createElement("ha-icon");
      inner.setAttribute("icon", icon);
      button.appendChild(inner);
      button.title = `${label} — ${roomName}`;
      button.setAttribute("aria-label", button.title);
      button.addEventListener("click", () => {
        this._hass.callService("norman", "room_command", { room: roomName, command });
      });
      presets.appendChild(button);
    }
    return presets;
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

    const rails = this._railsOf(blind).map((rail) => this._buildRail(rail));
    for (const { element } of rails) row.appendChild(element);

    this._cells.push({ blind, row, batteryEl, rails });
    return row;
  }

  _buildRail(rail) {
    const element = document.createElement("div");
    element.className = "rail";

    const label = document.createElement("div");
    label.className = "rail-label";
    label.textContent = rail.label;

    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = "0";
    slider.max = "100";
    slider.step = String(STEP);

    const value = document.createElement("div");
    value.className = "rail-value";

    // Open / stop / close for THIS rail. Each rail is its own cover entity, so the middle
    // rail of a two-rail blind gets the same controls as the bottom rail rather than the
    // buttons silently driving the bottom one.
    const buttons = document.createElement("div");
    buttons.className = "buttons";
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
      value.textContent = `${clampToStep(slider.value)}%`;
    });
    slider.addEventListener("change", () => {
      this._dragging.delete(target);
      this._setRail(rail, clampToStep(slider.value));
    });

    element.append(label, slider, value, buttons);
    return { rail, element, slider, value, buttons: railButtons };
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

      if (cell.batteryEl) {
        const level = this._numberOf(cell.blind.battery);
        cell.batteryEl.className = `battery ${batteryClass(level)}`;
        cell.batteryEl.firstChild.setAttribute("icon", batteryIcon(level));
        const shown = level === null ? "—" : `${Math.round(level)}%`;
        cell.batteryEl.lastChild.textContent = shown;
        cell.batteryEl.title = level === null ? "Battery level unknown" : `Battery ${shown}`;
        cell.batteryEl.setAttribute("aria-label", cell.batteryEl.title);
      }

      for (const { rail, slider, value, buttons } of cell.rails) {
        const target = rail.numberId || rail.coverId;
        const current = this._railValue(rail);
        slider.disabled = unavailable;
        // A rail with no cover entity (a slider-only rail) has nothing to open or stop.
        for (const button of buttons) button.disabled = unavailable || !rail.coverId;
        value.textContent = current === null ? "—" : `${Math.round(current)}%`;
        // Never move a slider the user is holding.
        if (!this._dragging.has(target)) {
          slider.value = String(clampToStep(current === null ? 0 : current));
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
