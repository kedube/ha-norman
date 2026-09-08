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

// The bottom-rail cover is the blind's primary entity and its unique id is the bare
// peripheral id; the middle rail appends "_middle". Sliders and sensors hang off the same
// peripheral id, which is what lets the card assemble a blind from its parts.
const MIDDLE_SUFFIX = "_middle";

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
    return { type: "custom:norman-shades-card", title: "Shades" };
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
      const uniqueId = String(entry.unique_id ?? "");
      const blind = blindFor(entry.device_id, entityId);

      if (domain === "cover") {
        if (uniqueId.endsWith(MIDDLE_SUFFIX)) blind.middleCover = entityId;
        else blind.bottomCover = entityId;
      } else if (domain === "number") {
        if (uniqueId.endsWith("_middle_rail_position")) blind.middleNumber = entityId;
        else if (uniqueId.endsWith("_bottom_rail_position")) blind.bottomNumber = entityId;
      } else if (domain === "sensor" && uniqueId.endsWith("_battery_level")) {
        blind.battery = entityId;
      }
    }

    // A device with no cover is the hub, not a blind.
    return [...blinds.values()].filter((blind) => blind.bottomCover);
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
        font-size: var(--ha-card-header-font-size, 24px);
        font-weight: var(--ha-card-header-font-weight, 400);
        color: var(--ha-card-header-color, var(--primary-text-color));
        padding: 12px 16px 8px;
      }
      .room { padding: 4px 0 8px; }
      .room-name {
        font-size: 0.85rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--secondary-text-color);
        padding: 10px 16px 4px;
      }
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
      .buttons { display: flex; gap: 2px; }
      .buttons ha-icon-button { --mdc-icon-button-size: 34px; --mdc-icon-size: 20px; }
      .empty { padding: 16px; color: var(--secondary-text-color); }
    `;

    const card = document.createElement("ha-card");
    card.appendChild(style);

    if (this._config.title) {
      const header = document.createElement("div");
      header.className = "header";
      header.textContent = this._config.title;
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

      if (!this._config.hide_room_names) {
        const label = document.createElement("div");
        label.className = "room-name";
        label.textContent = roomName;
        room.appendChild(label);
      }

      for (const blind of list) {
        room.appendChild(this._buildBlind(blind));
      }
      this._body.appendChild(room);
    }
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
      batteryEl.addEventListener("click", () => this._showMore(blind.battery));
      head.appendChild(batteryEl);
    }

    const buttons = document.createElement("div");
    buttons.className = "buttons";
    for (const [icon, service] of [
      ["mdi:arrow-up", "open_cover"],
      ["mdi:stop", "stop_cover"],
      ["mdi:arrow-down", "close_cover"],
    ]) {
      const button = document.createElement("ha-icon-button");
      const inner = document.createElement("ha-icon");
      inner.setAttribute("icon", icon);
      button.appendChild(inner);
      button.addEventListener("click", () =>
        this._hass.callService("cover", service, { entity_id: blind.bottomCover }),
      );
      buttons.appendChild(button);
    }
    head.appendChild(buttons);
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

    const target = rail.numberId || rail.coverId;
    slider.addEventListener("pointerdown", () => this._dragging.add(target));
    slider.addEventListener("input", () => {
      value.textContent = `${clampToStep(slider.value)}%`;
    });
    slider.addEventListener("change", () => {
      this._dragging.delete(target);
      this._setRail(rail, clampToStep(slider.value));
    });

    element.append(label, slider, value);
    return { rail, element, slider, value };
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
        cell.batteryEl.lastChild.textContent = level === null ? "—" : `${Math.round(level)}%`;
      }

      for (const { rail, slider, value } of cell.rails) {
        const target = rail.numberId || rail.coverId;
        const current = this._railValue(rail);
        slider.disabled = unavailable;
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
