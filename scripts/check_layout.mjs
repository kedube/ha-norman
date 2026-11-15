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

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { basename, delimiter, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const WWW = join(ROOT, "custom_components", "norman", "www");
const HARNESS = join(ROOT, "scripts", "layout", "harness.html");

const shotsAt = process.argv.indexOf("--screenshots");
const SHOTS = shotsAt > 0 ? process.argv[shotsAt + 1] : null;

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

// Serves the shipped www/ files at /norman/, as Home Assistant does, and the harness page.
function serve() {
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, "http://localhost").pathname;
    let file = null;
    if (path === "/" || path === "/harness.html") file = HARNESS;
    else if (path.startsWith("/norman/") && path.endsWith(".js")) file = join(WWW, basename(path));
    try {
      if (!file) throw new Error("not found");
      const body = await readFile(file);
      response.writeHead(200, {
        "content-type": file.endsWith(".html") ? "text/html; charset=utf-8" : "text/javascript; charset=utf-8",
        "cache-control": "no-store",
      });
      response.end(body);
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
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
  check("phone: the panel's header keeps to one line, its presets in a row beneath",
    header.position === "sticky" && header.children.join("|") === "icon-btn menu|titles|icon-group home-refresh" &&
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
} catch (error) {
  console.error(error);
  fail += 1;
} finally {
  await close();
  server.close();
}

console.log(fail === 0 ? "\nALL PASS" : `\n${fail} FAILED`);
process.exit(fail ? 1 : 0);
