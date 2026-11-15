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
 * Assistant hides its sidebar (phones), shows the button that opens it, in a header that stays
 * at the top as the page scrolls.
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

// The one thing the panel says itself: that the card would not load. It says it in the card's
// words (norman-strings.js, the module the card imports at the same stamp), in the user's
// language, with English to fall back on should those not load either.
const LOAD_FAILED = "Norman Shades couldn't load. Reload the page; if it keeps happening, check the browser console.";
const stringsReady = import(
  new URL(`./norman-strings.js?v=${encodeURIComponent(PANEL_VERSION)}`, import.meta.url).href
).catch(() => null);

// No background on the host: Home Assistant paints one behind every panel (from 2026.11 the
// theme's --ha-panel-background, before that the page's --primary-background-color), and an
// opaque host would cover a theme's gradient or image with a flat colour.
//
// The safe areas -- a phone's notch, status bar and home indicator -- are the panel's own: it
// registers with handle_safe_area (frontend.py), so Home Assistant does not pad around it. Its
// own variables where it sets them, the browser's otherwise. The card's header pads itself by
// the top one (--n-safe-top), so its colour reaches under the status bar as it stays put; the
// page keeps clear of the rest.
const STYLES = `
  :host {
    --n-safe-top: var(--safe-area-inset-top, env(safe-area-inset-top, 0px));
    --n-safe-right: var(--safe-area-content-inset-right, var(--safe-area-inset-right, env(safe-area-inset-right, 0px)));
    --n-safe-bottom: var(--safe-area-inset-bottom, env(safe-area-inset-bottom, 0px));
    --n-safe-left: var(--safe-area-content-inset-left, var(--safe-area-inset-left, env(safe-area-inset-left, 0px)));
    display: block;
    height: 100%;
    overflow-y: auto;
    box-sizing: border-box;
  }
  .page {
    box-sizing: border-box;
    max-width: 1280px;
    min-height: 100%;
    margin: 0 auto;
    padding: 16px calc(16px + var(--n-safe-right)) calc(16px + var(--n-safe-bottom)) calc(16px + var(--n-safe-left));
  }
  /* On a phone the card is the page, edge to edge, so the page takes the card's colour. */
  :host([narrow]) { background: var(--ha-card-background, var(--card-background-color, var(--primary-background-color))); }
  :host([narrow]) .page { padding: 0 var(--n-safe-right) var(--n-safe-bottom) var(--n-safe-left); }
  .error { padding: calc(32px + var(--n-safe-top)) 16px 32px; color: var(--error-color, #db4437); }
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
    // The card redraws for a new config itself once it has hass; it is handed hass here in
    // case it has none yet.
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
    message.textContent = LOAD_FAILED;
    this._page.append(message);
    // eslint-disable-next-line no-console
    console.error("norman: the sidebar panel could not load the card", err);
    // In the user's language once the words are here; settled, for anyone waiting on it.
    this._failed = stringsReady.then((strings) => {
      if (strings) message.textContent = strings.translate(strings.languageOf(this._hass), "panel_load_failed");
    });
  }
}

if (!customElements.get("norman-panel")) {
  customElements.define("norman-panel", NormanPanel);
}
