/**
 * Norman Shades panel.
 *
 * The Norman Shades card as a full-screen Home Assistant panel. The integration puts it in the
 * sidebar (frontend.py, the "Show Norman Shades in the sidebar" option), so every blind is one
 * click away with no dashboard to build.
 *
 * Home Assistant hands a panel element `hass`, `narrow`, `route` and `panel`; `panel.config`
 * carries the card's config (`config_entry_id` when there is more than one hub). The panel
 * hosts one norman-shades-card and passes them on. The card fills the page and, where Home
 * Assistant hides its sidebar (phones), shows the button that opens it.
 *
 * Like the card, a plain custom element with no build step.
 */

const PANEL_VERSION = new URL(import.meta.url).searchParams.get("v") || "unknown";

// The card is usually here already as a Lovelace resource: the same URL is the same module, so
// importing it again costs nothing. If a stale resource of another version defined the element
// first, that one is used rather than defining it twice.
const cardReady = customElements.get("norman-shades-card")
  ? Promise.resolve()
  : import(new URL(`./norman-shades-card.js?v=${encodeURIComponent(PANEL_VERSION)}`, import.meta.url).href).catch(
      (err) => {
        if (!customElements.get("norman-shades-card")) throw err;
      },
    );

const STYLES = `
  :host {
    display: block;
    height: 100%;
    overflow-y: auto;
    box-sizing: border-box;
    background: var(--primary-background-color);
  }
  .page { box-sizing: border-box; max-width: 1280px; min-height: 100%; margin: 0 auto; padding: 16px; }
  /* On a phone the card is the page, edge to edge, so the page takes the card's colour. */
  :host([narrow]) { background: var(--ha-card-background, var(--card-background-color, var(--primary-background-color))); }
  :host([narrow]) .page { padding: 0; }
  .error { padding: 32px 16px; color: var(--error-color, #db4437); }
`;

class NormanPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = STYLES;
    this._page = document.createElement("div");
    this._page.className = "page";
    this.shadowRoot.append(style, this._page);
    this._card = null;
    this._hass = null;
    this._narrow = false;
    this._panel = null;
    cardReady.then(
      () => this._mount(),
      (err) => this._fail(err),
    );
  }

  set hass(hass) {
    this._hass = hass;
    if (this._card) this._card.hass = hass;
  }

  get hass() {
    return this._hass;
  }

  set narrow(narrow) {
    this._narrow = Boolean(narrow);
    this.toggleAttribute("narrow", this._narrow);
    if (this._card) this._card.narrow = this._narrow;
  }

  get narrow() {
    return this._narrow;
  }

  set panel(panel) {
    const before = JSON.stringify(this._cardConfig());
    this._panel = panel;
    if (!this._card || JSON.stringify(this._cardConfig()) === before) return;
    // A new config clears the card; handing it hass again draws it straight away.
    this._card.setConfig(this._cardConfig());
    if (this._hass) this._card.hass = this._hass;
  }

  get panel() {
    return this._panel;
  }

  // The card's config: whatever the integration put in the panel's config, minus Home
  // Assistant's own bookkeeping.
  _cardConfig() {
    const { _panel_custom: _ignored, ...config } = (this._panel && this._panel.config) || {};
    return { type: "custom:norman-shades-card", ...config };
  }

  _mount() {
    const card = document.createElement("norman-shades-card");
    card.setAttribute("panel", "");
    card.setConfig(this._cardConfig());
    card.narrow = this._narrow;
    if (this._hass) card.hass = this._hass;
    this._page.append(card);
    this._card = card;
  }

  _fail(err) {
    const message = document.createElement("div");
    message.className = "error";
    message.textContent =
      "The Norman Shades card couldn't load. Reload the page; if it keeps happening, check the browser console.";
    this._page.append(message);
    // eslint-disable-next-line no-console
    console.error("norman: the sidebar panel could not load the card", err);
  }
}

if (!customElements.get("norman-panel")) {
  customElements.define("norman-panel", NormanPanel);
}
