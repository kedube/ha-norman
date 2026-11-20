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
 * With the integration's view option on, `panel.config` also names a place (`view`), and each
 * window the card draws looks out on it: a photograph for the hour and the weather
 * (norman-view.js, loaded only then). The page behind the card takes the photograph's colours,
 * and the card lies over them as glass: deep colours, dark glass and white words in Home
 * Assistant's dark theme, pale colours, light glass and dark words in its light theme, switching
 * as Home Assistant does. `view_motion` and `weather_entity` go to the view too;
 * `hide_weather`, there when the weather option is off, is the card's own and goes to it.
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

  /* ---- the view --------------------------------------------------------------------------
     The photograph's colours fill the panel and stay put (the stage, painted by the view);
     the page scrolls over them in a box of its own, so they do not bounce with the scroll on
     a phone. Without the view the box is no box at all, and the host scrolls as it always
     has. Dark, or light ([light]) as Home Assistant's theme is; under the view's colours, the
     colour of the page until they come. */
  .stage { display: none; }
  .scroll { display: contents; }
  :host([view]) {
    --n-page: #0a0d13;
    position: relative;
    overflow: hidden;
    background: var(--n-page);
    color-scheme: dark;
  }
  :host([view][light]) { --n-page: #eef1f5; color-scheme: light; }
  :host([view]) .stage {
    display: block;
    position: absolute;
    inset: 0;
    overflow: hidden;
    isolation: isolate;
    background: var(--n-page);
  }
  :host([view]) .scroll {
    display: block;
    position: absolute;
    inset: 0;
    overflow-x: hidden;
    overflow-y: auto;
    overscroll-behavior: contain;
  }
  :host([view]) .page {
    max-width: 1320px;
    padding: 0 calc(16px + var(--n-safe-right)) calc(24px + var(--n-safe-bottom)) calc(16px + var(--n-safe-left));
  }
  :host([view][narrow]) .page {
    padding: 0 calc(12px + var(--n-safe-right)) calc(20px + var(--n-safe-bottom)) calc(12px + var(--n-safe-left));
  }
`;

// What the integration's view option puts in the panel's config, beside the card's own.
const VIEW_KEYS = ["view", "view_motion", "weather_entity"];

class NormanPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = STYLES;
    // The view paints the photograph's colours in the stage; the page scrolls over it.
    this._stage = document.createElement("div");
    this._stage.className = "stage";
    this._stage.setAttribute("aria-hidden", "true");
    this._scroll = document.createElement("div");
    this._scroll.className = "scroll";
    this._page = document.createElement("div");
    this._page.className = "page";
    this._scroll.append(this._page);
    this.shadowRoot.append(style, this._stage, this._scroll);
    // Once the page has scrolled, the card's header takes a frosted backing (the card's styles).
    this._scroll.addEventListener(
      "scroll",
      () => this._card?.toggleAttribute("scrolled", this._scroll.scrollTop > 2),
      { passive: true },
    );
    this._card = null;
    this._hass = null;
    this._narrow = false;
    this._panel = null;
    // The view (norman-view.js): null without the option, and until its module has loaded.
    this._view = null;
    this._viewLoading = null;
    this._connected = false;
    cardReady.then(
      () => this._mount(),
      (err) => this._fail(err),
    );
  }

  connectedCallback() {
    this._connected = true;
    if (typeof ResizeObserver === "function") {
      this._resize ??= new ResizeObserver(() => this._view?.resize());
      this._resize.observe(this);
    }
    this._view?.connect();
  }

  disconnectedCallback() {
    this._connected = false;
    this._resize?.disconnect();
    this._view?.disconnect();
  }

  set hass(hass) {
    this._hass = hass;
    this._syncTheme();
    if (this._view) this._view.hass = hass;
    if (this._card) this._card.hass = hass;
  }

  // Home Assistant's theme, light or dark, taken as the card takes it for its own look: from
  // hass, which Home Assistant hands on again whenever its theme changes, including when the
  // device's own setting flips an automatic one. The panel, the card and the view each have a
  // look for both (their styles turn on [light]).
  _syncTheme() {
    const light = !this._hass?.themes?.darkMode;
    this.toggleAttribute("light", light);
    this._card?.toggleAttribute("light", light);
    if (this._view) this._view.light = light;
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
    const redraw = this._syncView();
    if (!this._card || (!redraw && JSON.stringify(this._cardConfig()) === before)) return;
    // The card redraws for a new config itself once it has hass; it is handed hass here in
    // case it has none yet.
    this._card.setConfig(this._cardConfig());
    if (this._hass) this._card.hass = this._hass;
  }

  get panel() {
    return this._panel;
  }

  // The card's config: whatever the integration put in the panel's config, minus Home
  // Assistant's own bookkeeping and what is the view's.
  _cardConfig() {
    const { _panel_custom: _ignored, ...config } = (this._panel && this._panel.config) || {};
    for (const key of VIEW_KEYS) delete config[key];
    return { type: "custom:norman-shades-card", ...config };
  }

  // The view the integration asked for: the place, whether it moves and the weather entity to
  // follow. Null without one.
  _viewConfig() {
    const config = (this._panel && this._panel.config) || {};
    if (!config.view || config.view === "none") return null;
    return { place: config.view, motion: config.view_motion !== false, weatherEntity: config.weather_entity || null };
  }

  /**
   * Bring the view in line with the panel's config: mark the panel and the card (their styles
   * turn on it), load the view's module the first time it is wanted, and hand it its settings.
   * Returns whether the card has to be redrawn, as it does when the view comes or goes: over
   * the view it draws its windows and its heading differently.
   */
  _syncView() {
    const wanted = this._viewFailed ? null : this._viewConfig();
    const flipped = Boolean(wanted) !== this.hasAttribute("view");
    this.toggleAttribute("view", Boolean(wanted));
    this._card?.toggleAttribute("view", Boolean(wanted));
    if (!wanted) {
      if (this._view && this._card) this._card.view = null;
      this._view?.destroy();
      this._view = null;
      return flipped;
    }
    if (this._view) {
      this._view.configure(wanted);
    } else if (!this._viewLoading) {
      this._viewLoading = import(
        new URL(`./norman-view.js?v=${encodeURIComponent(PANEL_VERSION)}`, import.meta.url).href
      ).then(({ LivingView }) => this._startView(LivingView), (err) => this._viewUnavailable(err));
    }
    return flipped;
  }

  // The view's module is here: make the view, unless the option went off while it loaded.
  async _startView(LivingView) {
    this._viewLoading = null;
    const wanted = this._viewConfig();
    if (!wanted) return;
    const view = new LivingView(this._stage);
    view.configure(wanted);
    view.light = this.hasAttribute("light");
    if (this._hass) view.hass = this._hass;
    try {
      await view.load();
    } catch (err) {
      view.destroy();
      this._viewUnavailable(err);
      return;
    }
    if (!this._viewConfig()) {
      view.destroy();
      return;
    }
    this._view = view;
    if (this._hass) view.hass = this._hass;
    if (this._card) this._card.view = view;
    if (this._connected) view.connect();
  }

  // Without its photographs the page is the plain card again, which works as it always has.
  _viewUnavailable(err) {
    this._viewLoading = null;
    this._viewFailed = true;
    // eslint-disable-next-line no-console
    console.warn("norman: the view could not load, so the page is shown without it", err);
    if (this._syncView() && this._card) {
      this._card.setConfig(this._cardConfig());
      if (this._hass) this._card.hass = this._hass;
    }
  }

  _mount() {
    const card = document.createElement("norman-shades-card");
    card.setAttribute("panel", "");
    // Before its first draw: over the view the card is built differently.
    card.toggleAttribute("view", this.hasAttribute("view"));
    card.toggleAttribute("light", this.hasAttribute("light"));
    card.setConfig(this._cardConfig());
    card.narrow = this._narrow;
    if (this._view) card.view = this._view;
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
