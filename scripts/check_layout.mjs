// Render the Norman Shades card, and its sidebar panel, in a real browser and check the layout.
//
//     node scripts/check_layout.mjs
//
// scripts/check_card.mjs runs the card against stand-ins for the DOM, which cannot see layout:
// whether the windows fit a phone, whether a wide screen uses its width, whether a touch lands
// on a finger-sized target. This opens the files that ship (custom_components/norman/www) in
// Google Chrome or Chromium, headless, at exact screen sizes -- a phone held each way, a
// desktop -- with touch, reduced motion and a phone's safe areas emulated, and measures them.
//
// No dependencies: Node 22's own WebSocket drives the browser over the DevTools protocol. The
// browser is found on the PATH (google-chrome, chromium...), in the usual macOS place, or at
// CHROME_PATH. CI runs this in the Layout job, on the Chrome that GitHub's Ubuntu runners have.
//
//     node scripts/check_layout.mjs --screenshots <dir>
//
// also saves a picture of every view it measures, to look at what the checks see.
//
//     node scripts/check_layout.mjs --serve [port]
//
// only serves the harness, to open in a browser of your own: the address it prints shows the
// sidebar page over its view, against the fake house, with no Home Assistant running. The
// harness's query (scripts/layout/harness.html) chooses the place, the weather and the hour.

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { delimiter, extname, join, normalize, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const WWW = join(ROOT, "custom_components", "norman", "www");
const HARNESS = join(ROOT, "scripts", "layout", "harness.html");

const shotsAt = process.argv.indexOf("--screenshots");
const SHOTS = shotsAt > 0 ? process.argv[shotsAt + 1] : null;
const serveAt = process.argv.indexOf("--serve");

let fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok || detail === "" ? "" : `  -> ${detail}`}`);
  if (!ok) fail += 1;
};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ---- the browser ------------------------------------------------------------------------

function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const names = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"];
  for (const dir of (process.env.PATH || "").split(delimiter)) {
    for (const name of names) if (dir && existsSync(join(dir, name))) return join(dir, name);
  }
  for (const app of [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
  ]) {
    if (existsSync(app)) return app;
  }
  return null;
}

// What www/ holds, by extension: the modules, and the view's photographs and their index.
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json",
  ".webp": "image/webp",
  ".jpg": "image/jpeg",
};

// Serves the shipped www/ files at /norman/, as Home Assistant does, and the harness page.
function serve(port = 0) {
  const server = createServer(async (request, response) => {
    const path = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
    let file = null;
    if (path === "/" || path === "/harness.html") file = HARNESS;
    else if (path.startsWith("/norman/")) {
      // Only what is inside www/, whatever the path says.
      const wanted = normalize(join(WWW, path.slice("/norman/".length)));
      if (wanted.startsWith(WWW + sep)) file = wanted;
    }
    try {
      const type = file && TYPES[extname(file)];
      if (!type) throw new Error("not found");
      const body = await readFile(file);
      response.writeHead(200, { "content-type": type, "cache-control": "no-store" });
      response.end(body);
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}

class DevTools {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.next = 0;
    this.pending = new Map();
  }

  async open() {
    await new Promise((resolve, reject) => {
      this.socket.onopen = resolve;
      this.socket.onerror = () => reject(new Error("could not reach the browser's DevTools"));
    });
    this.socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      const waiter = message.id && this.pending.get(message.id);
      if (!waiter) return;
      this.pending.delete(message.id);
      if (message.error) waiter.reject(new Error(`${waiter.method}: ${message.error.message}`));
      else waiter.resolve(message.result);
    };
  }

  send(method, params = {}, sessionId = undefined) {
    const id = (this.next += 1);
    this.socket.send(JSON.stringify({ id, method, params, sessionId }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject, method }));
  }
}

async function launch(chromePath) {
  const profile = await mkdtemp(join(tmpdir(), "norman-layout-"));
  const args = [
    "--headless=new",
    "--remote-debugging-port=0",
    `--user-data-dir=${profile}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-gpu",
    "--hide-scrollbars",
    "--mute-audio",
    // A CI runner's kernel can refuse the sandbox's namespaces, and its /dev/shm is small. The
    // page is this repository's own, served from this machine.
    ...(process.env.CI ? ["--no-sandbox", "--disable-dev-shm-usage"] : []),
    "about:blank",
  ];
  const chrome = spawn(chromePath, args, { stdio: ["ignore", "ignore", "pipe"] });
  const url = await new Promise((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => reject(new Error(`the browser did not start:\n${output}`)), 30000);
    chrome.stderr.on("data", (chunk) => {
      output += chunk;
      const match = /DevTools listening on (ws:\/\/\S+)/.exec(output);
      if (match) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    });
    chrome.on("exit", (code) => reject(new Error(`the browser exited (${code}) before it was ready:\n${output}`)));
  });
  const devtools = new DevTools(url);
  await devtools.open();
  const { targetId } = await devtools.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await devtools.send("Target.attachToTarget", { targetId, flatten: true });
  const page = (method, params) => devtools.send(method, params, sessionId);
  await page("Page.enable");
  await page("Runtime.enable");
  const close = async () => {
    chrome.kill();
    await rm(profile, { recursive: true, force: true }).catch(() => {});
  };
  return { page, close };
}

// ---- the checks ---------------------------------------------------------------------------

if (serveAt > 0) {
  const served = await serve(Number(process.argv[serveAt + 1]) || 0);
  const address = `http://127.0.0.1:${served.address().port}/harness.html`;
  console.log(`The sidebar page with its view:  ${address}?mode=panel&view=coast`);
  console.log(`On a phone's width, at the lake: ${address}?mode=panel&narrow=1&view=lake&weather=snowy`);
  console.log("Ctrl+C stops it.");
  await new Promise(() => {});
}

const chromePath = findChrome();
if (!chromePath) {
  console.error("No Chrome or Chromium found. Install one, or point CHROME_PATH at it.");
  process.exit(1);
}
const server = await serve();
const base = `http://127.0.0.1:${server.address().port}`;
const { page, close } = await launch(chromePath);

const js = async (expression) => {
  const { result, exceptionDetails } = await page("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (exceptionDetails) throw new Error(exceptionDetails.exception?.description || exceptionDetails.text);
  return result.value;
};

// Open the harness at a screen size, a pointer and a motion preference, and wait for the card.
async function view({ name, width, height, query, touch = false, reducedMotion = false, reducedTransparency = false }) {
  await page("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: touch });
  await page("Emulation.setTouchEmulationEnabled", { enabled: touch, maxTouchPoints: touch ? 5 : 1 });
  await page("Emulation.setEmulatedMedia", {
    features: [
      { name: "prefers-reduced-motion", value: reducedMotion ? "reduce" : "no-preference" },
      { name: "prefers-reduced-transparency", value: reducedTransparency ? "reduce" : "no-preference" },
    ],
  });
  await page("Page.navigate", { url: `${base}/harness.html?${query}` });
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if ((await js("document.title").catch(() => "")) === "ready") {
      if (SHOTS) {
        await mkdir(SHOTS, { recursive: true });
        const { data } = await page("Page.captureScreenshot", { format: "png" });
        await writeFile(join(SHOTS, `${name}.png`), Buffer.from(data, "base64"));
      }
      return;
    }
    await sleep(50);
  }
  throw new Error(`the card never drew for ${query} at ${width}x${height}`);
}

async function shot(name) {
  if (!SHOTS) return;
  await mkdir(SHOTS, { recursive: true });
  const { data } = await page("Page.captureScreenshot", { format: "png" });
  await writeFile(join(SHOTS, `${name}.png`), Buffer.from(data, "base64"));
}

// Wait for a smooth scroll to come to rest.
const scrollSettles = async () => {
  let last = -1;
  for (let i = 0; i < 60; i += 1) {
    const now = await js("layout.scroller().scrollTop");
    if (now === last) return now;
    last = now;
    await sleep(60);
  }
  return last;
};

// The rooms bar: where it is, its buttons, and which is marked.
const roomsBar = `(() => {
  const bar = layout.$(".rooms-bar");
  const tabs = [...bar.querySelectorAll(".room-tab")];
  return { shown: layout.visible(bar), bar: layout.box(bar), height: innerHeight, width: innerWidth,
    labels: tabs.map((tab) => tab.querySelector("span").textContent), heights: tabs.map((tab) => layout.box(tab).height),
    current: tabs.findIndex((tab) => tab.getAttribute("aria-current") === "true"), position: layout.style(bar).position };
})()`;

const scrollTo = async (y) => {
  await js(`layout.scroller().scrollTop = ${y}`);
  await js("new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
};

try {
  // --- a phone, upright, in the sidebar panel ---------------------------------------------------
  await view({ name: "phone", width: 390, height: 844, query: "mode=panel&narrow=1", touch: true });
  check("phone: the pointer is a finger", await js("matchMedia('(pointer: coarse)').matches"));
  const overflowing = await js("layout.overflowing()");
  check("phone: nothing is drawn past the screen's edges", overflowing.length === 0, overflowing.join(", "));
  check("phone: the page does not scroll sideways", await js("document.documentElement.scrollWidth <= innerWidth"));
  const columns = await js("new Set(layout.$$('.tile').map((tile) => Math.round(layout.box(tile).left))).size");
  check("phone: two windows to a row", columns === 2, String(columns));
  check("phone: the whole-house presets keep their words",
    await js("layout.$$('.home-buttons .chip span').every((word) => layout.visible(word) && layout.box(word).width > 0)"));
  const header = await js(`(() => {
    const header = layout.$(".header");
    return { position: layout.style(header).position, children: [...header.children].map((child) => child.className) };
  })()`);
  check("phone: the panel's header keeps to one line, with the settings, its presets in a row beneath",
    header.position === "sticky" && header.children.join("|") === "icon-btn menu|titles|icon-group home-refresh|icon-group home-settings" &&
      (await js("Boolean(layout.$('.tools .home-buttons'))")),
    JSON.stringify(header));
  await scrollTo(900);
  const stuck = await js(`({ top: layout.box(layout.$(".header")).top, menu: layout.visible(layout.$(".icon-btn.menu")),
    scrolled: layout.scroller().scrollTop })`);
  check("phone: the header, and its menu button, stay at the top as the page scrolls",
    stuck.scrolled > 0 && Math.abs(stuck.top) < 1 && stuck.menu, JSON.stringify(stuck));
  await scrollTo(0);
  const roomButtons = await js("layout.$$('.room-buttons .icon-btn').map((button) => layout.box(button))");
  check("phone: a room's open, stop and close are finger-sized",
    roomButtons.length > 0 && roomButtons.every((b) => b.width >= 44 && b.height >= 40),
    JSON.stringify(roomButtons[0]));
  const chipHeights = await js("layout.$$('.chip').filter(layout.visible).map((chip) => layout.box(chip).height)");
  check("phone: the presets and scene buttons are finger-sized",
    chipHeights.length > 0 && chipHeights.every((h) => h >= 38), JSON.stringify(chipHeights));
  check("phone: the battery is a button with a finger-sized reach", await js(`(() => {
    const battery = layout.$(".battery");
    const reach = layout.style(battery, "::after");
    return battery.tagName === "BUTTON" && reach.content !== "none" && parseFloat(reach.top) <= -12;
  })()`));
  const zones = await js(`layout.$$(".win:not(.drape):not(.shutter) .zone").map((zone) => {
    const rail = zone.closest(".win").querySelectorAll(".rail")[Number(zone.dataset.index)];
    return { zone: layout.box(zone), tab: layout.box(rail.querySelector(".tab")) };
  })`);
  const centre = (box) => (box.left + box.right) / 2;
  check("phone: a touch starts a drag only in a finger-sized box around a rail's pull tab",
    zones.length >= 10 && zones.every(({ zone, tab }) => zone.width <= 60 && zone.height >= 40 &&
      Math.abs(centre(zone) - centre(tab)) < 3 && zone.top <= tab.top + 1 && zone.bottom >= tab.bottom - 1),
    JSON.stringify(zones.find(({ zone, tab }) => zone.width > 60 || Math.abs(centre(zone) - centre(tab)) >= 3)));
  const rod = await js("({ zone: layout.box(layout.$('.rod-zone')), rod: layout.box(layout.$('.win.shutter .rod')) })");
  check("phone: ...and around a Shutter's tilt rod",
    rod.zone.width <= 50 && Math.abs(centre(rod.zone) - centre(rod.rod)) < 3, JSON.stringify(rod));
  check("phone: a swipe up or down a SmartDrape's edge scrolls the page",
    await js("layout.$$('.win.drape .zone').every((zone) => layout.style(zone).touchAction === 'pan-y')"));
  // The rooms bar, at the foot of the screen.
  const bar = await js(roomsBar);
  check("phone: the rooms bar sits at the foot of the screen, inside its edges",
    bar.shown && bar.position === "sticky" && Math.abs(bar.bar.bottom - (bar.height - 12)) < 1.5 &&
      bar.bar.left >= 0 && bar.bar.right <= bar.width, JSON.stringify(bar));
  check("phone: ...with the top of the page and every room, finger-sized",
    JSON.stringify(bar.labels) === '["Home","Bedroom","Guest Room","Kitchen","Living Room","Study"]' &&
      bar.heights.every((h) => h >= 44), JSON.stringify(bar.labels));
  check("phone: ...the top of the page marked to begin with", bar.current === 0, String(bar.current));
  await scrollTo(1400);
  await sleep(100);
  const scrolledBar = await js(roomsBar);
  check("phone: the rooms bar stays at the foot of the screen as the page scrolls, the room in view marked",
    Math.abs(scrolledBar.bar.bottom - (scrolledBar.height - 12)) < 1.5 && scrolledBar.current > 0, JSON.stringify(scrolledBar));
  await scrollTo(0);
  await js("layout.$$('.room-tab')[3].click()");
  await sleep(1000);
  await scrollSettles();
  const kitchen = await js(`(() => {
    const room = layout.$$(".room").find((one) => one.querySelector(".room-name").textContent === "Kitchen");
    return { room: layout.box(room).top, header: layout.box(layout.$(".header")).bottom,
      current: layout.$$(".room-tab").findIndex((tab) => tab.getAttribute("aria-current") === "true") };
  })()`);
  check("phone: a room's button scrolls to the room, just below the header, and marks it",
    kitchen.room >= kitchen.header && kitchen.room - kitchen.header <= 14 && kitchen.current === 3, JSON.stringify(kitchen));
  await shot("phone-rooms-bar");
  await scrollTo(100000);
  await sleep(100);
  const last = await js(`({ tile: Math.max(...layout.$$(".tile").map((tile) => layout.box(tile).bottom)),
    bar: layout.box(layout.$(".rooms-bar")).top,
    current: layout.$$(".room-tab").findIndex((tab) => tab.getAttribute("aria-current") === "true") })`);
  check("phone: at the end of the page the last room is clear of the bar, and marked",
    last.tile <= last.bar && last.current === 5, JSON.stringify(last));
  await scrollTo(0);

  // --- the same phone, the list layout ------------------------------------------------------------
  await view({ name: "phone-list", width: 390, height: 844, query: "mode=panel&narrow=1&layout=list", touch: true });
  const rows = await js("layout.$$('.slider').map((row) => layout.box(row).height)");
  check("phone list: each slider row is finger-sized", rows.length > 0 && rows.every((h) => h >= 44), JSON.stringify(rows));
  check("phone list: nothing is drawn past the screen's edges", (await js("layout.overflowing()")).length === 0);

  // --- a phone with a notch, as Home Assistant's app shows it ---------------------------------------
  await view({ name: "phone-notch", width: 390, height: 844, query: "mode=panel&narrow=1&safe_top=47&safe_bottom=34", touch: true });
  check("notch: the header pads itself below the status bar",
    (await js("parseFloat(layout.style(layout.$('.header')).paddingTop)")) === 12 + 47);
  await scrollTo(100000);
  const end = await js(`(() => {
    const tiles = layout.$$(".tile").map((tile) => layout.box(tile).bottom);
    return { last: Math.max(...tiles), height: innerHeight, header: layout.box(layout.$(".header")).top };
  })()`);
  check("notch: the last row clears the home indicator", end.last <= end.height - 34, JSON.stringify(end));
  check("notch: the header still meets the top edge, its colour under the status bar", Math.abs(end.header) < 1,
    JSON.stringify(end));
  const notchBar = await js(roomsBar);
  check("notch: the rooms bar clears the home indicator", notchBar.bar.bottom <= notchBar.height - 34 - 11,
    JSON.stringify(notchBar.bar));

  // --- the same phone on its side ------------------------------------------------------------------
  await view({ name: "landscape", width: 844, height: 390, query: "mode=panel&narrow=1", touch: true });
  check("landscape: the hub's name is not cut short",
    await js("(() => { const name = layout.$('.header-text'); return name.scrollWidth <= name.clientWidth; })()"));
  const landscapeRooms = await js("new Set(layout.$$('.room').map((room) => Math.round(layout.box(room).left))).size");
  check("landscape: the rooms sit side by side", landscapeRooms === 2, String(landscapeRooms));
  check("landscape: nothing is drawn past the screen's edges", (await js("layout.overflowing()")).length === 0);

  // --- a desktop, in the sidebar panel -------------------------------------------------------------
  await view({ name: "desktop", width: 1280, height: 800, query: "mode=panel" });
  check("desktop: the pointer is a mouse", !(await js("matchMedia('(pointer: coarse)').matches")));
  const desk = await js(`(() => {
    const card = layout.box(layout.$("ha-card"));
    const rooms = layout.$$(".room").map((room) => layout.box(room));
    const tiles = layout.$$(".tile").map((tile) => layout.box(tile).width);
    return { card: card.width, columns: new Set(rooms.map((room) => Math.round(room.left))).size,
      widest: Math.max(...rooms.map((room) => room.width)), tile: Math.min(...tiles) };
  })()`);
  check("desktop: the rooms sit side by side, three across", desk.columns >= 3, JSON.stringify(desk));
  check("desktop: each room keeps its buttons beside its blinds", desk.widest < desk.card / 2, JSON.stringify(desk));
  check("desktop: the windows grow past their phone size", desk.tile >= 150, JSON.stringify(desk));
  const lines = await js(`layout.$$(".status").filter(layout.visible).map((status) => ({
    text: status.textContent, lines: Math.round(layout.box(status).height / parseFloat(layout.style(status).lineHeight)) }))`);
  check("desktop: a blind's one-rail status fits on one line",
    lines.filter(({ text }) => /% open$|^Open$|^Closed$/.test(text)).every(({ lines: n }) => n === 1),
    JSON.stringify(lines.filter(({ lines: n }) => n > 1)));
  check("desktop: the hub's name is not cut short",
    await js("(() => { const name = layout.$('.header-text'); return name.scrollWidth <= name.clientWidth; })()"));
  check("desktop: a wide screen has no rooms bar", !(await js("layout.visible(layout.$('.rooms-bar'))")));

  // --- a desktop, the room headings hidden -----------------------------------------------------------
  await view({ name: "desktop-no-headings", width: 1280, height: 800, query: "mode=panel&hide_room_names=1" });
  const single = await js("({ room: layout.box(layout.$('.room')).width, card: layout.box(layout.$('ha-card')).width })");
  check("desktop: with the headings hidden the one section keeps the whole width",
    single.room > single.card - 40, JSON.stringify(single));

  // --- a dashboard card on a phone ---------------------------------------------------------------------
  await view({ name: "dashboard-phone", width: 390, height: 844, query: "mode=card", touch: true });
  check("dashboard: the card's header scrolls with the page, its presets in it",
    (await js("layout.style(layout.$('.header')).position")) !== "sticky" &&
      (await js("Boolean(layout.$('.header .home-buttons')) && !layout.$('.tools')")));
  check("dashboard: nothing is drawn past the screen's edges", (await js("layout.overflowing()")).length === 0);
  await view({ name: "dashboard-landscape", width: 844, height: 390, query: "mode=card", touch: true });
  check("dashboard landscape: the buttons wrap before the hub's name is cut short",
    await js("(() => { const name = layout.$('.header-text'); return name.scrollWidth <= name.clientWidth; })()"));

  // --- less motion, less transparency ------------------------------------------------------------------
  await view({ name: "phone-reduced-motion", width: 390, height: 844, query: "mode=panel&narrow=1", reducedMotion: true, reducedTransparency: true });
  check("reduced motion: the shades do not slide",
    (await js("parseFloat(layout.style(layout.$('.fabric')).transitionDuration)")) < 0.001);
  check("reduced motion: a moving rail's tab shows it in the accent colour, not a pulse",
    (await js("layout.style(layout.$('.rail.moving .tab')).backgroundColor")) === "rgb(3, 169, 244)");
  check("reduced transparency: a sheer fabric is not blurred",
    (await js("layout.style(layout.$('.fabric.sheer')).backdropFilter")) === "none");

  // --- the sidebar page with its view, on a phone ---------------------------------------------------
  // The photograph in the windows moves only with WebGL 2, which this browser may not have (CI's
  // has no GPU): it is then shown still, and everything measured here is the same either way.
  // Behind the page are its colours, a gradient in the stage.
  const photographShows = `(() => {
    const view = layout.card.view, stage = layout.panel(".stage");
    const ground = [...stage.children].some((layer) => layer.style.opacity === "1" && /gradient/.test(layer.style.background));
    return { ground, still: Boolean(view && !view._drawing && view._paneStill), moving: Boolean(view && view._drawing) };
  })()`;
  // A window's canvas has its picture once the middle of it is painted.
  const windowsPainted = `(async () => {
    const painted = (canvas) => canvas.width > 50 &&
      canvas.getContext("2d").getImageData(canvas.width >> 1, canvas.height >> 1, 1, 1).data[3] === 255;
    for (let i = 0; i < 80 && !layout.$$(".photo").slice(0, 3).every(painted); i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    return layout.$$(".photo").slice(0, 3).map(painted);
  })()`;
  await view({ name: "view-phone", width: 390, height: 844, query: "mode=panel&narrow=1&view=coast&elevation=3&theme=dark", touch: true });
  const over = await js(`(() => {
    const stage = layout.panel(".stage");
    return { marked: layout.root.hasAttribute("view") && layout.card.hasAttribute("view"),
      stage: layout.box(stage), panel: layout.box(layout.root),
      host: layout.style(layout.root).overflowY, scroll: layout.style(layout.panel(".scroll")).overflowY };
  })()`);
  const shows = await js(photographShows);
  check("view: the photograph's colours fill the panel behind the page",
    over.marked && shows.ground && (shows.still || shows.moving) &&
      over.stage.width === over.panel.width && over.stage.height === over.panel.height,
    JSON.stringify({ over, shows }));
  check("view: the page scrolls over them, in a box of its own",
    over.host === "hidden" && over.scroll === "auto", JSON.stringify(over));
  const viewOverflow = await js("layout.overflowing()");
  check("view: nothing is drawn past the screen's edges", viewOverflow.length === 0, viewOverflow.join(", "));
  const viewColumns = await js("new Set(layout.$$('.grid')[0].querySelectorAll('.tile').values().map((tile) => Math.round(layout.box(tile).left))).size");
  check("view: three windows to a row", viewColumns === 3, String(viewColumns));
  const hero = await js(`({ temp: layout.$(".hero .temp").textContent, cond: layout.$(".hero .cond").textContent,
    counts: layout.$(".hero .summary").textContent, shown: layout.visible(layout.$(".hero .temp")) })`);
  check("view: the temperature, the weather and the counts are at the top of the page",
    hero.temp === "67°" && hero.cond === "Sunny" && /^12 shades/.test(hero.counts) && hero.shown, JSON.stringify(hero));
  const painted = await js(windowsPainted);
  check("view: each window looks out on the photograph", painted.length === 3 && painted.every(Boolean), JSON.stringify(painted));
  const room = await js(`[...layout.$$(".grid")[0].querySelectorAll(".photo")].map((canvas) =>
    layout.card.view._panes.find((pane) => pane.canvas === canvas).slot)`);
  check("view: a room's windows look out on one view between them, each on the part behind it",
    room.length === 3 && room.every((slot, i) => i === 0 || slot[0] > room[i - 1][0] + room[i - 1][1]) &&
      room[0][0] < 0.01 && room[2][0] + room[2][1] > 0.99, JSON.stringify(room));
  check("view: the drawn sky and hills are gone from the windows",
    await js("layout.$$('.sun, .hills').every((drawn) => layout.style(drawn).display === 'none')"));
  const glass = await js(`({ room: layout.style(layout.$(".room")).backgroundColor, card: layout.style(layout.$("ha-card")).backgroundColor,
    header: layout.style(layout.$(".header")).backgroundColor })`);
  check("view: each room is a pane of dark glass, and the card itself has no backing",
    /^rgba\(.*, 0\.\d+\)$/.test(glass.room) && glass.card === "rgba(0, 0, 0, 0)" && glass.header === "rgba(0, 0, 0, 0)",
    JSON.stringify(glass));
  const viewButtons = await js(`({ room: layout.$$(".room-buttons .icon-btn").map((button) => layout.box(button)),
    chips: layout.$$(".chip").filter(layout.visible).map((chip) => layout.box(chip).height),
    presets: new Set(layout.$$(".home-buttons .chip").map((chip) => Math.round(layout.box(chip).top))).size })`);
  check("view: the buttons are finger-sized",
    viewButtons.room.length > 0 && viewButtons.room.every((b) => b.width >= 44 && b.height >= 44) &&
      viewButtons.chips.every((h) => h >= 44), JSON.stringify(viewButtons.chips));
  check("view: the three whole-house presets share one row", viewButtons.presets === 1, String(viewButtons.presets));
  const longName = await js(`(() => {
    const tile = layout.$$(".tile").find((one) => one.querySelector(".name").textContent.length > 30);
    const name = layout.box(tile.querySelector(".name")), status = layout.box(tile.querySelector(".status"));
    return { lines: Math.round((name.height - 6) / parseFloat(layout.style(tile.querySelector(".name")).lineHeight)),
      clear: name.bottom <= status.top + 0.5 };
  })()`);
  check("view: a name too long for its window takes a second line, clear of the state beneath",
    longName.lines === 2 && longName.clear, JSON.stringify(longName));
  const hours = await js(`(() => {
    const strip = layout.$(".hours");
    const cells = [...strip.children].filter(layout.visible);
    return { shown: layout.visible(strip), strip: layout.box(strip), temp: layout.box(layout.$(".hero .temp")),
      counts: layout.box(layout.$(".hero .summary")), width: innerWidth, cells: cells.length,
      first: cells[0]?.querySelector(".when").textContent, degrees: cells.map((cell) => cell.querySelector(".deg").textContent),
      tops: new Set(cells.map((cell) => Math.round(layout.box(cell).top))).size,
      fits: cells.every((cell) => [...cell.children].filter((part) => !part.classList.contains("said"))
        .every((part) => part.scrollWidth <= Math.ceil(layout.box(cell).width) + 1)) };
  })()`);
  check("view: the forecast is under the weather, across the screen",
    hours.shown && hours.strip.top >= hours.counts.bottom && hours.strip.left >= 0 && hours.strip.right <= hours.width &&
      hours.strip.width > hours.width * 0.85, JSON.stringify(hours));
  check("view: ...now and five hours on a phone, in one row, each with its temperature",
    hours.cells === 6 && hours.first === "Now" && hours.tops === 1 && hours.degrees.every((d) => /^-?\d+°$/.test(d)) &&
      hours.fits, JSON.stringify(hours));

  // Choosing colors: the button in the whole-house row turns each window into one big button.
  const tinted = await js(`(() => {
    const east = layout.$$(".tile").find((tile) => tile.querySelector(".name").textContent === "Bedroom East");
    const win = east.querySelector(".win");
    return { color: win.dataset.color, cloth: layout.style(win).getPropertyValue("--n-cloth").trim(),
      blackout: layout.style(win.querySelector(".fabric.blackout")).backgroundImage.includes("rgb(44, 58, 86)"),
      sheer: layout.style(win.querySelector(".fabric.sheer")).backgroundImage.includes("rgb(44, 58, 86)") };
  })()`);
  check("view: a shade is drawn in its color, its blackout navy and its sheer still white",
    tinted.color === "navy" && tinted.cloth === "#2c3a56" && tinted.blackout && !tinted.sheer, JSON.stringify(tinted));
  // The page's settings: a button beside the refresh at the top, whose menu holds the colors and
  // the divided lights; the whole-house row keeps only the presets and the scene groups.
  const settings = await js(`(() => {
    const button = layout.$(".header .icon-btn.settings"), refresh = layout.$(".header .home-refresh .icon-btn");
    const [b, r] = [layout.box(button), layout.box(refresh)];
    return { shown: layout.visible(button), beside: Math.abs(b.top - r.top) < 1 && b.left > r.right && b.left - r.right <= 8,
      size: [b.width, b.height], closed: !layout.visible(layout.$(".settings-menu")),
      row: [...layout.$(".tools").querySelectorAll(".chip")].map((chip) => chip.textContent.trim()) };
  })()`);
  check("view: the settings button is at the top, beside the refresh, finger-sized, its menu closed",
    settings.shown && settings.beside && settings.size.every((side) => side >= 44) && settings.closed, JSON.stringify(settings));
  check("view: ...and the whole-house row holds no colors or divided lights",
    !settings.row.includes("Shade colors") && !settings.row.includes("Divided lights") && settings.row.includes("Privacy"),
    JSON.stringify(settings.row));
  await js("layout.$('.header .icon-btn.settings').click()");
  await sleep(100);
  const menu = await js(`(() => {
    const box = layout.box(layout.$(".settings-menu"));
    const items = [...layout.$$(".settings-menu .menu-item")].filter(layout.visible);
    return { open: layout.visible(layout.$(".settings-menu")), within: box.left >= 0 && box.right <= innerWidth,
      below: box.top >= layout.box(layout.$(".header .icon-btn.settings")).bottom,
      items: items.map((item) => item.textContent.trim()), tall: items.every((item) => layout.box(item).height >= 44),
      focused: layout.card.shadowRoot.activeElement === items[0],
      expanded: layout.$(".header .icon-btn.settings").getAttribute("aria-expanded") };
  })()`);
  check("view: the settings open a menu beneath the button, on the screen, its first item focused",
    menu.open && menu.within && menu.below && menu.focused && menu.expanded === "true", JSON.stringify(menu));
  check("view: ...of the shade colors and the divided lights, each finger-sized",
    JSON.stringify(menu.items) === '["Shade colors","Divided lights"]' && menu.tall, JSON.stringify(menu.items));
  await shot("view-phone-settings");
  await js("document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, composed: true }))");
  await sleep(50);
  check("view: a press anywhere else closes the menu", await js("!layout.visible(layout.$('.settings-menu'))"));
  await js("layout.$('.header .icon-btn.settings').click()");
  await sleep(50);
  await js(`layout.$(".settings-menu").dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }))`);
  const moved = await js(`layout.card.shadowRoot.activeElement?.textContent.trim()`);
  await js(`layout.$(".settings-menu").dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))`);
  await sleep(50);
  const escaped = await js(`({ closed: !layout.visible(layout.$(".settings-menu")),
    focus: layout.card.shadowRoot.activeElement === layout.$(".header .icon-btn.settings") })`);
  check("view: ...the arrow keys go between its items, and Escape closes it, back to the button",
    moved === "Divided lights" && escaped.closed && escaped.focus, JSON.stringify({ moved, escaped }));
  await js("layout.$('.header .icon-btn.settings').click()");
  await sleep(50);
  await js("layout.$('.settings-menu .menu-item.colors').click()");
  await sleep(150);
  const choosing = await js(`(() => {
    const picks = layout.$$(".pick").filter(layout.visible);
    const wins = picks.map((pick) => [layout.box(pick), layout.box(pick.closest(".win"))]);
    const names = layout.$$(".choice-name").filter(layout.visible);
    return { bar: layout.visible(layout.$(".choice-bar.colors")), tools: layout.visible(layout.$(".tools")), picks: picks.length,
      onlyColors: picks.every((pick) => pick.classList.contains("colors")),
      covered: wins.every(([pick, win]) => Math.abs(pick.width - win.width) < 1 && Math.abs(pick.height - win.height) < 1),
      names: names.map((name) => name.textContent), statuses: layout.$$(".tile .status").filter(layout.visible).length,
      badges: layout.$$(".color-badge").filter(layout.visible).length,
      buttons: [...layout.$(".choice-bar.colors").querySelectorAll(".chip")].map((chip) => layout.box(chip).height) };
  })()`);
  check("view: choosing colors puts a select over every window, and the bar with Done in the row's place",
    choosing.bar && !choosing.tools && choosing.picks === 12 && choosing.onlyColors && choosing.covered && choosing.badges === 12,
    JSON.stringify(choosing));
  check("view: ...each window's color named beneath it, in place of its state",
    choosing.names.length === 12 && choosing.names.includes("Navy") && choosing.names.includes("Oak") &&
      choosing.statuses === 0, JSON.stringify(choosing.names));
  check("view: ...the bar's buttons finger-sized", choosing.buttons.length === 2 && choosing.buttons.every((h) => h >= 44),
    JSON.stringify(choosing.buttons));
  const choosingOverflow = await js("layout.overflowing()");
  check("view: ...and nothing drawn past the screen's edges", choosingOverflow.length === 0, choosingOverflow.join(", "));
  await shot("view-phone-colors");
  await js(`(() => {
    const pick = layout.$$(".tile").find((tile) => tile.querySelector(".name").textContent === "Kitchen Sink").querySelector(".pick.colors");
    pick.value = "charcoal";
    pick.dispatchEvent(new Event("change"));
  })()`);
  const chosen = await js(`({ call: JSON.stringify(layout.calls.at(-1)),
    drawn: layout.$$(".tile").find((tile) => tile.querySelector(".name").textContent === "Kitchen Sink").querySelector(".win").dataset.color })`);
  check("view: a color chosen goes to the blind's select and is drawn at once",
    chosen.call === '["select","select_option",{"entity_id":"select.kitchen_sink_shade_color","option":"charcoal"}]' &&
      chosen.drawn === "charcoal", JSON.stringify(chosen));
  await js("[...layout.$('.choice-bar.colors').querySelectorAll('.chip')].at(-1).click()");
  await sleep(100);
  check("view: Done brings the whole-house row back, and the focus to the settings button",
    await js(`layout.visible(layout.$('.tools')) && !layout.visible(layout.$('.choice-bar.colors')) &&
      !layout.$$('.pick').some(layout.visible) && layout.card.shadowRoot.activeElement === layout.$('.header .icon-btn.settings')`));

  // Choosing divided lights: the same, with the shades drawn away so each window shows its glass.
  const divisions = await js(`(() => {
    const barsIn = (name) => layout.$$(".tile").find((tile) => tile.querySelector(".name").textContent === name).querySelectorAll(".bars > *").length;
    return { centre: barsIn("Living Centre"), door: barsIn("Kitchen Door"), skylight: barsIn("Guest Skylight Over The Reading Nook"),
      sink: barsIn("Kitchen Sink") };
  })()`);
  check("view: each window is drawn with its divided lights: six over six, prairie, none and two over two",
    divisions.centre === 5 && divisions.door === 4 && divisions.skylight === 0 && divisions.sink === 2, JSON.stringify(divisions));
  await js("layout.$('.header .icon-btn.settings').click()");
  await sleep(50);
  await js("layout.$('.settings-menu .menu-item.lights').click()");
  await sleep(150);
  const lighting = await js(`(() => {
    const picks = layout.$$(".pick").filter(layout.visible);
    const wins = picks.map((pick) => [layout.box(pick), layout.box(pick.closest(".win"))]);
    const sink = layout.$$(".tile").find((tile) => tile.querySelector(".name").textContent === "Kitchen Sink");
    return { bar: layout.visible(layout.$(".choice-bar.lights")), tools: layout.visible(layout.$(".tools")), picks: picks.length,
      onlyLights: picks.every((pick) => pick.classList.contains("lights")),
      covered: wins.every(([pick, win]) => Math.abs(pick.width - win.width) < 1 && Math.abs(pick.height - win.height) < 1),
      names: layout.$$(".choice-name").filter(layout.visible).map((name) => name.textContent),
      fabric: layout.style(sink.querySelector(".fabric")).visibility, glass: layout.style(sink.querySelector(".bars .mullion")).visibility,
      badges: layout.$$(".color-badge").filter(layout.visible).length };
  })()`);
  check("view: choosing divided lights puts a select over every window, the shades drawn away from the glass",
    lighting.bar && !lighting.tools && lighting.picks === 12 && lighting.onlyLights && lighting.covered &&
      lighting.fabric === "hidden" && lighting.glass === "visible" && lighting.badges === 0, JSON.stringify(lighting));
  check("view: ...each window's divided lights named beneath it",
    lighting.names.length === 12 && lighting.names.includes("Six over six") && lighting.names.includes("Prairie") &&
      lighting.names.includes("None"), JSON.stringify(lighting.names));
  const lightingOverflow = await js("layout.overflowing()");
  check("view: ...and nothing drawn past the screen's edges", lightingOverflow.length === 0, lightingOverflow.join(", "));
  await shot("view-phone-lights");
  await js(`(() => {
    const pick = layout.$$(".tile").find((tile) => tile.querySelector(".name").textContent === "Kitchen Sink").querySelector(".pick.lights");
    pick.value = "one_over_one";
    pick.dispatchEvent(new Event("change"));
  })()`);
  const divided = await js(`({ call: JSON.stringify(layout.calls.at(-1)),
    bars: layout.$$(".tile").find((tile) => tile.querySelector(".name").textContent === "Kitchen Sink").querySelectorAll(".bars > *").length })`);
  check("view: divided lights chosen go to the blind's select and are drawn at once",
    divided.call === '["select","select_option",{"entity_id":"select.kitchen_sink_divided_lights","option":"one_over_one"}]' &&
      divided.bars === 1, JSON.stringify(divided));
  await js("[...layout.$('.choice-bar.lights').querySelectorAll('.chip')].at(-1).click()");
  await sleep(100);
  check("view: Done draws the shades back and brings the row back",
    await js(`layout.visible(layout.$('.tools')) && !layout.$$('.pick').some(layout.visible) &&
      layout.style(layout.$('.fabric')).visibility === "visible"`));
  await scrollTo(700);
  // The header's glass fades in as the page scrolls under it.
  await sleep(400);
  const viewStuck = await js(`({ top: layout.box(layout.$(".header")).top, menu: layout.visible(layout.$(".icon-btn.menu")),
    marked: layout.card.hasAttribute("scrolled"), backing: layout.style(layout.$(".header")).backgroundColor,
    stage: layout.box(layout.panel(".stage")).top })`);
  check("view: the header stays at the top as the page scrolls, on glass, and the colours stay put",
    Math.abs(viewStuck.top) < 1 && viewStuck.menu && viewStuck.marked && viewStuck.backing !== "rgba(0, 0, 0, 0)" &&
      viewStuck.stage === 0, JSON.stringify(viewStuck));
  await scrollTo(100000);
  const pageEnd = await js(`({ credit: Boolean(layout.$(".credit")), last: layout.box(layout.$$(".body > .room").at(-1)).bottom,
    height: innerHeight })`);
  check("view: the last room closes the page, with no credit under it (NOTICE credits the photographs)",
    !pageEnd.credit && pageEnd.last <= pageEnd.height, JSON.stringify(pageEnd));

  // --- with its view, in Home Assistant's light theme -------------------------------------------------
  // The page above is in the dark theme: deep colours, dark glass, white words. In the light theme
  // the colours are pale, the glass light and the words dark, each word clear on the colours
  // behind it. Then Home Assistant switches theme, from the profile or with an automatic theme as
  // the device's own setting changes, and the page follows at once, without being drawn again.
  const look = `(() => {
    const ground = [...layout.panel(".stage").children].find((layer) => layer.style.opacity === "1");
    return { scheme: layout.style(layout.root).colorScheme, light: layout.root.hasAttribute("light") && layout.card.hasAttribute("light"),
      ground: (ground?.style.background.match(/rgb\\(\\d+, \\d+, \\d+\\)/g) || []).map((rgb) => rgb.match(/\\d+/g).map(Number)),
      words: [".header-text", ".hero .temp", ".hero .cond", ".hero .summary"].map((s) => layout.style(layout.$(s)).color),
      room: layout.style(layout.$(".room")).backgroundColor, chip: layout.style(layout.$(".tools .chip")).backgroundColor };
  })()`;
  const luma = ([r, g, b]) => 0.2126 * r + 0.7152 * g + 0.0722 * b;
  // WCAG's contrast between a word's colour, laid over a colour of the ground, and that colour.
  const contrastOn = (word, ground) => {
    const [r, g, b, a = 1] = word.match(/[\d.]+/g).map(Number);
    const linear = (c) => ((c /= 255) <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    const lum = ([x, y, z]) => 0.2126 * linear(x) + 0.7152 * linear(y) + 0.0722 * linear(z);
    const shown = [r, g, b].map((value, i) => value * a + ground[i] * (1 - a));
    const [high, low] = [lum(shown), lum(ground)].sort((p, q) => q - p);
    return (high + 0.05) / (low + 0.05);
  };
  await view({ name: "view-phone-light", width: 390, height: 844, query: "mode=panel&narrow=1&view=coast&elevation=30", touch: true });
  const lit = await js(look);
  check("view, light theme: pale colours behind the page, and the browser's own parts light",
    lit.light && lit.scheme === "light" && lit.ground.length === 4 && lit.ground.every((rgb) => luma(rgb) >= 176), JSON.stringify(lit));
  const worstWords = lit.words.map((word) => Math.min(...lit.ground.map((ground) => contrastOn(word, ground))));
  check("view, light theme: dark words, each clear on every colour behind it",
    lit.words.every((word) => word === "rgb(20, 26, 36)") && worstWords.every((c) => c >= 7),
    JSON.stringify({ words: lit.words, worstWords }));
  check("view, light theme: the whole-house row and each room on light glass, their buttons tinted",
    lit.room === "rgba(255, 255, 255, 0.5)" && lit.chip === "rgba(20, 26, 36, 0.05)", JSON.stringify(lit));
  await scrollTo(700);
  // The header's glass fades in as the page scrolls under it.
  await sleep(400);
  const litStuck = await js(`({ header: layout.style(layout.$(".header")).backgroundColor,
    bar: layout.style(layout.$(".rooms-bar")).backgroundColor,
    current: layout.style(layout.$('.room-tab[aria-current="true"]')).backgroundColor,
    currentWords: layout.style(layout.$('.room-tab[aria-current="true"]')).color })`);
  check("view, light theme: the header and the rooms bar on light glass, the room in view marked dark",
    litStuck.header === "rgba(248, 250, 252, 0.8)" && litStuck.bar === "rgba(248, 250, 252, 0.8)" &&
      litStuck.current === "rgba(20, 26, 36, 0.88)" && litStuck.currentWords === "rgb(255, 255, 255)", JSON.stringify(litStuck));
  await shot("view-phone-light-scrolled");
  await scrollTo(0);
  await js("window.heroBefore = layout.$('.hero'); layout.setTheme(true)");
  await js("new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
  const darkened = await js(look);
  const redrawn = await js("layout.$('.hero') !== window.heroBefore");
  check("view: Home Assistant turning dark turns the page dark at once, without drawing it again",
    !darkened.light && darkened.scheme === "dark" && darkened.ground.length === 4 &&
      darkened.ground.every((rgb) => luma(rgb) <= 112.5) && darkened.words[1] === "rgb(255, 255, 255)" &&
      darkened.room === "rgba(13, 17, 25, 0.44)" && !redrawn, JSON.stringify({ darkened, redrawn }));
  await shot("view-phone-turned-dark");
  await js("layout.setTheme(false)");
  await js("new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
  const relit = await js(look);
  check("view: ...and turning light again, the light page is back as it was",
    relit.light && relit.scheme === "light" && JSON.stringify(relit.ground) === JSON.stringify(lit.ground) &&
      relit.words[1] === "rgb(20, 26, 36)", JSON.stringify(relit));

  // --- with its view, with a notch ------------------------------------------------------------------
  await view({ name: "view-phone-notch", width: 390, height: 844, touch: true,
    query: "mode=panel&narrow=1&view=lake&weather=rainy&safe_top=47&safe_bottom=34" });
  check("view, notch: the header pads itself below the status bar",
    (await js("parseFloat(layout.style(layout.$('.header')).paddingTop)")) === 12 + 47);
  await scrollTo(100000);
  const viewEnd = await js(`({ last: layout.box(layout.$$(".body > .room").at(-1)).bottom, height: innerHeight })`);
  check("view, notch: the end of the page clears the home indicator", viewEnd.last <= viewEnd.height - 34, JSON.stringify(viewEnd));
  const viewNotchBar = await js(roomsBar);
  check("view, notch: the rooms bar clears the home indicator, on glass",
    viewNotchBar.shown && viewNotchBar.bar.bottom <= viewNotchBar.height - 34 - 11, JSON.stringify(viewNotchBar.bar));

  // --- with its view, on a desktop --------------------------------------------------------------------
  await view({ name: "view-desktop", width: 1280, height: 800, query: "mode=panel&view=lake&weather=snowy&temperature=28" });
  const viewDesk = await js(`(() => {
    const rooms = layout.$$(".room").map((room) => layout.box(room));
    return { columns: new Set(rooms.map((room) => Math.round(room.left))).size,
      tops: new Set(rooms.slice(0, 3).map((room) => Math.round(room.top))).size,
      tools: layout.box(layout.$(".tools")).width, card: layout.box(layout.$("ha-card")).width,
      tile: Math.min(...layout.$$(".tile").map((tile) => layout.box(tile).width)),
      hero: layout.$(".hero .temp").textContent + " " + layout.$(".hero .cond").textContent };
  })()`);
  check("view, desktop: the rooms sit side by side, three across, their tops in line",
    viewDesk.columns === 3 && viewDesk.tops === 1, JSON.stringify(viewDesk));
  check("view, desktop: the whole-house row is only as wide as its buttons", viewDesk.tools < viewDesk.card * 0.75, JSON.stringify(viewDesk));
  check("view, desktop: the windows keep a size a hand can use", viewDesk.tile >= 100, JSON.stringify(viewDesk));
  check("view, desktop: the weather follows the weather entity", viewDesk.hero === "28° Snowy", viewDesk.hero);
  check("view, desktop: nothing is drawn past the screen's edges", (await js("layout.overflowing()")).length === 0);
  const deskHours = await js(`(() => {
    const strip = layout.$(".hours");
    return { strip: layout.box(strip), temp: layout.box(layout.$(".hero .temp")),
      cells: [...strip.children].filter(layout.visible).length, rooms: layout.visible(layout.$(".rooms-bar")) };
  })()`);
  check("view, desktop: the forecast sits beside the weather, now and seven hours",
    deskHours.strip.left > deskHours.temp.right && deskHours.strip.top < deskHours.temp.bottom && deskHours.cells === 8,
    JSON.stringify(deskHours));
  check("view, desktop: no rooms bar", !deskHours.rooms);

  // --- with its view, a forecast by the day, and none -------------------------------------------------
  await view({ name: "view-daily", width: 390, height: 844, query: "mode=panel&narrow=1&view=coast&forecast=daily", touch: true });
  const days = await js(`[...layout.$(".hours").children].filter(layout.visible).map((cell) =>
    [cell.querySelector(".when").textContent, cell.querySelector(".deg").textContent])`);
  check("view: a daily forecast shows the days ahead, each with its high and low",
    days.length === 6 && days[0][0] === "Now" && days.slice(1).every(([when, deg]) => /^[A-Z][a-z]{2}$/.test(when) && /^\d+°\d+°$/.test(deg)),
    JSON.stringify(days));
  check("view, daily: nothing is drawn past the screen's edges", (await js("layout.overflowing()")).length === 0);
  await view({ name: "view-no-forecast", width: 390, height: 844, query: "mode=panel&narrow=1&view=coast&forecast=none", touch: true });
  check("view: a weather entity with no forecast shows the weather alone",
    await js("!layout.visible(layout.$('.hours')) && layout.visible(layout.$('.hero .temp'))"));

  // --- with its view, a house with no weather entity ----------------------------------------------------
  await view({ name: "view-no-weather", width: 390, height: 844, query: "mode=panel&narrow=1&view=coast&weather=none", touch: true });
  const bare = await js(`({ temp: layout.visible(layout.$(".hero .temp")), cond: layout.visible(layout.$(".hero .cond")),
    counts: layout.visible(layout.$(".hero .summary")) })`);
  check("view: without a weather entity the page keeps its counts and says no weather",
    !bare.temp && !bare.cond && bare.counts && (await js(photographShows).then((s) => s.still || s.moving)), JSON.stringify(bare));

  // --- with its view, the weather turned off in the options -------------------------------------------
  // The page says no weather even with a weather entity: under the hub's name only the counts.
  for (const [name, width, height, narrow] of [["view-weather-off-phone", 390, 844, 1], ["view-weather-off-desktop", 1280, 800, 0]]) {
    await view({ name, width, height, query: `mode=panel&narrow=${narrow}&view=coast&hide_weather=1`, touch: Boolean(narrow) });
    const off = await js(`({ built: ["temp", "cond", "hours"].filter((name) => layout.$(".hero ." + name)),
      counts: layout.visible(layout.$(".hero .summary")), overflowing: layout.overflowing().length })`);
    check(`${name}: no temperature, conditions or forecast, the counts kept, nothing past the edges`,
      off.built.length === 0 && off.counts && off.overflowing === 0, JSON.stringify(off));
  }

  // --- with its view, held still ------------------------------------------------------------------------
  await view({ name: "view-still", width: 390, height: 844, query: "mode=panel&narrow=1&view=coast&motion=0", touch: true });
  const held = await js(photographShows);
  check("view: with motion turned off the windows show the photograph still",
    held.still && !held.moving && (await js(windowsPainted)).every(Boolean), JSON.stringify(held));
  await view({ name: "view-reduced-motion", width: 390, height: 844, query: "mode=panel&narrow=1&view=coast", touch: true,
    reducedMotion: true, reducedTransparency: true });
  const reduced = await js(photographShows);
  check("view, reduced motion: the windows show the photograph still", reduced.still && !reduced.moving, JSON.stringify(reduced));
  check("view, reduced transparency: the glass is solid, not blurred", await js(`(() => {
    const room = layout.style(layout.$(".room"));
    return room.backdropFilter === "none" && Number(room.backgroundColor.split(",")[3].replace(")", "")) >= 0.85;
  })()`));
} catch (error) {
  console.error(error);
  fail += 1;
} finally {
  await close();
  server.close();
}

console.log(fail === 0 ? "\nALL PASS" : `\n${fail} FAILED`);
process.exit(fail ? 1 : 0);
