/**
 * Norman Shades view.
 *
 * What the windows on the sidebar page (norman-panel.js) look out on: a real photograph of a
 * coast or a lake, chosen by the weather and the height of the sun, with its own sky and water
 * set moving. A room's windows look out on one strip of the photograph, as through openings in
 * one wall, each on the part behind it. Behind the page itself there is no photograph, only its
 * colours, in the stage the panel gives the view: deepened in Home Assistant's dark theme, and
 * paled in its light one.
 *
 * Nothing is painted over the photograph to make it move. Its own pixels are slid a little and
 * blended with themselves, and only where a map made for each photograph says there is sky or
 * water, so clouds drift, water runs and the land stays still. A curtain of rain, a bolt of
 * lightning or a sky of stars that is in the photograph falls, flickers or twinkles. What is
 * added is small and in the air: rain and snow at several distances, fog, a moon, shooting stars
 * and birds. The birds are the Light Control card's (norman-birds.js), and shooting stars and
 * twinkling follow that card too.
 *
 * It needs WebGL 2. Without it, with motion turned off (the integration's option, or the
 * device's own "reduce motion"), or if drawing fails, the windows show the photograph still:
 * the view never leaves a window blank.
 *
 * The photographs (www/view, built by scripts/build_view.py) are CC0 or in the public domain,
 * each cut to a small strip; scenes.json lists each one's author and source. Like the card, a
 * plain module with no build step; it defines no element, and is imported by the panel only
 * when the view is switched on.
 */

const VIEW_VERSION = new URL(import.meta.url).searchParams.get("v") || "unknown";

// /norman/ is served with long-lived cache headers, so every URL carries a stamp: the index the
// release's, and each picture a hash of its own files (scenes.json), which only changes when
// the picture does. A browser keeps the pictures it has across releases.
const fileUrl = (name, stamp) =>
  new URL(`./view/${name}?v=${encodeURIComponent(stamp)}`, import.meta.url).href;

const RAD = Math.PI / 180;
const TAU = Math.PI * 2;
// Every photograph is taken to span this many degrees from side to side, looking this way: out
// over the water, where the sun goes down on the coast the photographs are of.
const FIELD_DEG = 60;
const VIEW_AZIMUTH = 252;
// How long one photograph takes to fade into the next, in seconds.
const FADE_S = 1.8;
// The strip of each photograph that ships is two wide by one high (scripts/build_view.py).
const STRIP_SHAPE = 2;
// The moon's radius, in widths of the whole photograph: larger than the real one, which would
// be a speck in a window.
const MOON_RADIUS = 0.017;
// Where the horizon sits in a row of windows, down from the top of what they show: a little
// above the middle, at the eye level of someone standing at a window.
const HORIZON_AT = 0.45;

/**
 * What a window looks out on in a scene, as a share of the scene's strip: left, top, width and
 * height. `slot` is where the window sits among its room's (LivingView): its left and width,
 * the share of the strip's height it shows, and its row and the room's rows. A room with one
 * row of windows looks out at the horizon; one with more looks out higher and lower down.
 */
export function lookOf(scene, slot) {
  const [left, width, band, row, rows] = slot;
  const [, stripTop, , stripHeight] = scene.strip;
  const top =
    rows > 1
      ? (row / (rows - 1)) * (1 - band)
      : clamp((scene.motion.horizon - stripTop) / stripHeight - HORIZON_AT * band, 0, 1 - band);
  return [left, top, width, band];
}

/** The top of the sky a window's room shows, as a share of the scene's strip: its first row's. */
const skyTopOf = (scene, slot) => (slot[4] > 1 ? 0 : lookOf(scene, slot)[1]);

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const lerp = (a, b, t) => a + (b - a) * t;
const smooth = (a, b, value) => {
  const t = clamp((value - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
};

// ---- which photograph ------------------------------------------------------------------------

export const PLACES = ["coast", "lake"];

// Home Assistant's weather states, as the kinds of weather there are photographs of. Wind does
// not show in a photograph, so a windy day is a clear one, and a windy, cloudy day a cloudy one.
const WEATHER = {
  sunny: "clear",
  "clear-night": "clear",
  windy: "clear",
  partlycloudy: "partly",
  cloudy: "cloudy",
  "windy-variant": "cloudy",
  exceptional: "cloudy",
  fog: "fog",
  rainy: "rain",
  pouring: "rain",
  hail: "rain",
  lightning: "storm",
  "lightning-rainy": "storm",
  snowy: "snow",
  "snowy-rainy": "snow",
};

/** The weather a weather entity's state amounts to, or null when it says nothing (unavailable). */
export const conditionOf = (state) => WEATHER[state] ?? null;

/**
 * The part of the day, from how high the sun is and whether it is on its way up.
 *
 * Night ends astronomical twilight's worth before sunrise; the hour either side of sunrise and
 * sunset has photographs of its own, and the low sun of a morning and of an evening differ.
 */
export const phaseOf = (elevation, rising) => {
  if (elevation < -13) return "night";
  if (elevation < -6) return "twilight";
  if (elevation < -0.8) return "dusk";
  if (elevation < 5) return rising ? "dawn" : "sunset";
  if (elevation < 15) return rising ? "dawn" : "golden";
  return "day";
};

/**
 * The photograph for a place, the weather and the sun: its key in `scenes`, and how far to
 * darken it (0 to 1).
 *
 * The weather decides first: rain is the rain photograph at any hour. Under a clear sky the
 * part of the day decides, and a partly cloudy sky only changes the middle of the day, since
 * the photographs of a sunrise or a sunset have their clouds already. A place with no
 * photograph of some weather borrows the other place's (only the lake has snow).
 *
 * A photograph of weather was taken by day, so once the sun is down it is shown darker; one
 * taken at night (`tone: "night"`) is left as it is.
 */
export function pickScene(scenes, place, condition, elevation, rising) {
  const phase = phaseOf(elevation, rising);
  const find = (where, when) =>
    Object.keys(scenes).find((key) => scenes[key].place === where && scenes[key].when === when);
  let when = phase;
  if (condition === "partly") when = phase === "day" ? "partly" : phase;
  else if (condition && condition !== "clear") when = condition;
  const others = PLACES.filter((other) => other !== place);
  const key =
    find(place, when) ??
    others.map((other) => find(other, when)).find(Boolean) ??
    find(place, phase) ??
    Object.keys(scenes)[0];
  let dim = 0;
  if (key && when !== phase && scenes[key].tone !== "night") {
    dim = elevation < -8 ? 0.6 : elevation < -1 ? 0.34 : 0;
  }
  return { key: key ?? null, dim };
}

// ---- the sun and the moon ------------------------------------------------------------------
// Low-precision positions, good to a fraction of a degree: the series the Astronomical Almanac
// prints for the purpose. The sun is only worked out here when Home Assistant has no sun.sun.

const daysSince2000 = (date) => (date.getTime() - Date.UTC(2000, 0, 1, 12)) / 86400000;
const OBLIQUITY = 23.439 * RAD;

const sunLongitude = (days) => {
  const anomaly = (357.528 + 0.9856003 * days) * RAD;
  return (280.46 + 0.9856474 * days + 1.915 * Math.sin(anomaly) + 0.02 * Math.sin(2 * anomaly)) * RAD;
};

/** A point on the sky by its ecliptic longitude and latitude, as seen from a place on Earth. */
function horizontal(longitude, latitude, date, placeLatitude, placeLongitude) {
  const rightAscension = Math.atan2(
    Math.sin(longitude) * Math.cos(OBLIQUITY) - Math.tan(latitude) * Math.sin(OBLIQUITY),
    Math.cos(longitude),
  );
  const declination = Math.asin(
    Math.sin(latitude) * Math.cos(OBLIQUITY) +
      Math.cos(latitude) * Math.sin(OBLIQUITY) * Math.sin(longitude),
  );
  const siderealTime = (280.46061837 + 360.98564736629 * daysSince2000(date) + placeLongitude) * RAD;
  const hourAngle = siderealTime - rightAscension;
  const phi = placeLatitude * RAD;
  const elevation = Math.asin(
    Math.sin(phi) * Math.sin(declination) + Math.cos(phi) * Math.cos(declination) * Math.cos(hourAngle),
  );
  const azimuth = Math.atan2(
    -Math.cos(declination) * Math.sin(hourAngle),
    Math.sin(declination) * Math.cos(phi) - Math.cos(declination) * Math.cos(hourAngle) * Math.sin(phi),
  );
  return {
    azimuth: (azimuth / RAD + 360) % 360,
    elevation: elevation / RAD,
    // Before it crosses the meridian a body is on its way up.
    rising: Math.sin(hourAngle) < 0,
  };
}

/** Where the sun is: `{ azimuth, elevation }` in degrees, and whether it is rising. */
export function sunPosition(date, latitude, longitude) {
  return horizontal(sunLongitude(daysSince2000(date)), 0, date, latitude, longitude);
}

/**
 * Where the moon is, and its phase: `{ azimuth, elevation }` in degrees as seen from the
 * ground, and `phase` from 0 (new) through 0.5 (full) to 1.
 */
export function moonPosition(date, latitude, longitude) {
  const days = daysSince2000(date);
  const t = days / 36525;
  const sin = (degrees) => Math.sin(degrees * RAD);
  const moonLongitude =
    218.32 +
    481267.881 * t +
    6.29 * sin(135.0 + 477198.87 * t) -
    1.27 * sin(259.3 - 413335.36 * t) +
    0.66 * sin(235.7 + 890534.22 * t) +
    0.21 * sin(269.9 + 954397.74 * t) -
    0.19 * sin(357.5 + 35999.05 * t) -
    0.11 * sin(186.5 + 966404.03 * t);
  const moonLatitude =
    5.13 * sin(93.3 + 483202.02 * t) +
    0.28 * sin(228.2 + 960400.89 * t) -
    0.28 * sin(318.3 + 6003.15 * t) -
    0.17 * sin(217.6 - 407332.21 * t);
  const seen = horizontal(moonLongitude * RAD, moonLatitude * RAD, date, latitude, longitude);
  // The moon is close enough that standing on the Earth's surface lowers it by up to a degree.
  const elevation = seen.elevation - 0.9508 * Math.cos(seen.elevation * RAD);
  const elongation = moonLongitude * RAD - sunLongitude(days);
  return { azimuth: seen.azimuth, elevation, phase: (((elongation / TAU) % 1) + 1) % 1 };
}

/**
 * Which way the sunlight falls on the moon, for whoever is looking at it: x to the right, y up
 * the sky, z toward the viewer. At new moon the light comes from behind it (z is -1).
 */
export function moonLight(sun, moon) {
  const direction = ({ azimuth, elevation }) => [
    Math.sin(azimuth * RAD) * Math.cos(elevation * RAD),
    Math.cos(azimuth * RAD) * Math.cos(elevation * RAD),
    Math.sin(elevation * RAD),
  ];
  const toSun = direction(sun);
  const toMoon = direction(moon);
  // To the moon's right along the horizon, and up the sky from it.
  const right = [Math.cos(moon.azimuth * RAD), -Math.sin(moon.azimuth * RAD), 0];
  const up = [
    toMoon[1] * right[2] - toMoon[2] * right[1],
    toMoon[2] * right[0] - toMoon[0] * right[2],
    toMoon[0] * right[1] - toMoon[1] * right[0],
  ].map((value) => -value);
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  return [dot(toSun, right), dot(toSun, up), -dot(toSun, toMoon)];
}

// ---- drawing ---------------------------------------------------------------------------------

const VERTEX = `#version 300 es
in vec2 aPos; out vec2 vSt;
void main() { vSt = vec2(aPos.x * .5 + .5, .5 - aPos.y * .5); gl_Position = vec4(aPos, 0., 1.); }`;

// One pass draws a window's whole view: the photograph (two of them while one fades into the
// next), then what is in the air. Each window is a viewport of the same pass. Places are in the
// whole photograph's coordinates, though only its strip is loaded.
const FRAGMENT = `#version 300 es
precision highp float;
in vec2 vSt; out vec4 o;
uniform sampler2D uImgA, uMaskA, uImgB, uMaskB, uNoise, uMoonTex;
uniform vec4 uRectA, uRectB;          // this viewport in each whole photograph: origin, size
uniform vec4 uTexA, uTexB;            // where each strip (its picture and its map) sits in its whole photograph
uniform vec4 uSkyA, uSkyB;            // the sky's drift: velocity (widths a second), period, horizon
uniform vec4 uWatA, uWatB;            // the water's drift: velocity, period, where the water begins
uniform vec4 uFallRectA, uFallRectB;  // a curtain of rain in the picture: its box
uniform vec4 uFallA, uFallB;          // its speed, period, lean, soft edge
uniform vec4 uFxA, uFxB;              // twinkling, fog, storm, shape (width / height)
uniform vec4 uMoonA, uMoonB;          // the moon: where, radius (widths), brightness
uniform vec4 uGlareA, uGlareB;        // the sun just above the picture: where along the top, strength
uniform vec3 uMoonLit;
uniform float uMix, uTime, uDim, uDpr, uStars;
uniform vec2 uView;
uniform vec4 uAir;                    // rain, snow, lightning now, splashes
uniform vec3 uAmb;                    // the light that rain and snow catch
uniform vec4 uMet[6]; uniform int uMetN;
const vec3 LUMA = vec3(.2126, .7152, .0722);

float hash11(float n) { return fract(sin(n) * 43758.5453123); }
vec2 hash22(vec2 p) {
  vec3 a = fract(vec3(p.xyx) * vec3(.1031, .1030, .0973));
  a += dot(a, a.yzx + 33.33);
  return fract((a.xx + a.yz) * a.zy);
}
vec2 toSegment(vec2 p, vec2 a, vec2 b) {
  vec2 ab = b - a;
  float t = clamp(dot(p - a, ab) / max(dot(ab, ab), 1e-6), 0., 1.);
  return vec2(length(p - a - ab * t), t);
}

/* The picture slid along a drift and blended with itself half a turn later, so it flows without
   ever tearing. The gradients are the undisplaced picture's, so the two samples share a mip. */
vec3 flow(sampler2D img, vec2 tuv, vec2 trav, float ph, vec2 gx, vec2 gy) {
  float p0 = fract(ph), p1 = fract(ph + .5);
  return mix(textureGrad(img, tuv - trav * (p0 - .5), gx, gy).rgb,
             textureGrad(img, tuv - trav * (p1 - .5), gx, gy).rgb, abs(1. - 2. * p0));
}

vec3 scene(sampler2D img, sampler2D msk, vec4 rect, vec4 tex, vec4 sky, vec4 wat, vec4 fallRect,
           vec4 fall, vec4 fx, vec4 moon, vec4 glare) {
  vec2 uv = rect.xy + vSt * rect.zw;
  float asp = fx.w;
  vec2 tuv = (uv - tex.xy) / tex.zw, gx = dFdx(tuv), gy = dFdy(tuv);
  vec3 m = texture(msk, tuv).rgb;
  vec3 c = texture(img, tuv).rgb;
  float n = texture(uNoise, uv * vec2(1.7, 1.7 / asp)).r;
  vec3 cs = c, cw = c;
  if (m.r > .004 && sky.z > 0.) {            // clouds and fog: slower at the horizon than overhead
    float k = m.r * mix(.35, 1., clamp(abs(sky.w - uv.y) * 2.4, 0., 1.));
    cs = flow(img, tuv, sky.xy * vec2(1., asp) * sky.z * k / tex.zw, uTime / sky.z + n, gx, gy);
  }
  if (fall.x > 0.) {                         // rain that is in the picture, falling
    vec2 e = smoothstep(vec2(0.), vec2(fall.w), uv - fallRect.xy) *
             smoothstep(vec2(0.), vec2(fall.w), fallRect.zw - uv);
    float fw = e.x * e.y * m.b;
    // One timing for the whole curtain: it slides down along its own streaks, so the blend never shows.
    if (fw > .004) {
      cs = mix(cs, flow(img, tuv, vec2(fall.z, 1.) * fall.x * vec2(1., asp) * fall.y / tex.zw,
                        uTime / fall.y, gx, gy), fw);
    }
  }
  if (m.g > .004 && wat.z > 0.) {            // water: more the nearer it is
    float k = m.g * mix(.3, 1., clamp((uv.y - wat.w) / max(1. - wat.w, .08), 0., 1.));
    cw = flow(img, tuv, wat.xy * vec2(1., asp) * wat.z * k / tex.zw, uTime / wat.z + n * 2.3, gx, gy);
  }
  c = m.g > m.r ? cw : cs;
  if (uAir.w > 0. && m.g > .2) {             // rain pitting the water
    float d = clamp((uv.y - wat.w) / max(1. - wat.w, .08), 0., 1.);
    vec2 g = vec2(uv.x * 120. / (.35 + d), pow(d, .6) * 24.);
    vec2 r = hash22(floor(g) + floor(uTime * 11.) * 17.);
    c += uAmb * .45 * step(.955, r.x) * smoothstep(.24, .05, length(fract(g) - .2 - .6 * r)) *
         m.g * uAir.w * (.3 + .7 * d);
  }
  if (fx.x > 0. && m.b > .3) {               // stars twinkle, each in its own time, more near the horizon
    float star = smoothstep(.035, .15, dot(c, LUMA) - dot(textureLod(img, tuv, 1.8).rgb, LUMA)) * m.b;
    vec2 h = hash22(floor(uv * vec2(720., 720. / asp)));
    float tw = 1. + (.24 + .3 * clamp(uv.y / max(sky.w, .01), 0., 1.)) *
               sin(uTime * (1.4 + 3.2 * h.x) + 6.283 * h.y);
    c *= mix(1., tw, star * fx.x);
  }
  if (fx.z > 0.) {                           // lightning: the picture holds the flash; between flashes it is dark
    float F = uAir.z, lit = smoothstep(.1, .55, dot(c, LUMA));
    vec3 around = textureLod(img, tuv, 4.8).rgb;
    vec3 dark = mix(c, around, smoothstep(.04, .2, dot(c - around, LUMA))) * mix(.74, .13, lit);
    c = mix(c, mix(dark, c * (1. + .18 * F), clamp(F, 0., 1.)), fx.z);
  }
  if (fx.y > 0.) {                           // fog: veils of the picture's own haze, drifting through
    vec3 haze = textureLod(img, tuv, 4.8).rgb;
    float w1 = texture(uNoise, uv * vec2(.9, 1.6 / asp) + vec2(uTime * .011, uTime * .002)).g;
    float w2 = texture(uNoise, uv * vec2(2.1, 3.4 / asp) + vec2(-uTime * .017, uTime * .004)).b;
    float w = w1 * .62 + w2 * .38;
    c = mix(c, haze, smoothstep(.4, .74, w) * fx.y) * (1. + (w - .5) * .16 * fx.y);
  }
  if (glare.y > 0.) {                        // the sun, just above the top of the picture
    float gx2 = uv.x - glare.x;
    c += vec3(1., .93, .8) * glare.y * exp(-gx2 * gx2 / .07) *
         exp(-max(uv.y, 0.) / (.5 * max(sky.w, .2))) * (.3 + .7 * m.b);
  }
  if (moon.w > 0.) {                         // the moon, lit from the side the sun is on
    vec2 d = (uv - moon.xy) * vec2(1., 1. / asp) / moon.z;
    float r = length(d);
    if (r < 7.) {
      float px = rect.z / uView.x / moon.z;
      vec3 nrm = vec3(d.x, -d.y, sqrt(max(0., 1. - r * r)));
      float day = smoothstep(-.06, .16, dot(nrm, uMoonLit));
      vec3 face = texture(uMoonTex, vec2(atan(nrm.x, nrm.z) / 6.2832 + .5,
                                         .5 - asin(clamp(nrm.y, -1., 1.)) / 3.1416)).rgb;
      c += face * (day * 1.5 + .03) * vec3(1., .98, .93) *
           (1. - smoothstep(1. - 1.5 * px, 1. + .5 * px, r)) * m.b * moon.w;
      c += vec3(.86, .9, 1.) * .05 * moon.w * exp(-r * r / 9.) * (.25 + .75 * m.b);
    }
  }
  if (uMetN > 0 && m.b > .02) {              // shooting stars: a streak that grows, brightest at its head
    float S = uView.x / rect.z;
    vec2 q = uv * vec2(1., 1. / asp) * S;
    for (int i = 0; i < 2; i++) {
      if (i >= uMetN) break;
      vec4 path = uMet[i * 3], mm = uMet[i * 3 + 1], tint = uMet[i * 3 + 2];
      vec2 a = path.xy * vec2(1., 1. / asp) * S, b = path.zw * vec2(1., 1. / asp) * S;
      float age = mm.x, wd = mm.z * uDpr;
      vec2 head = mix(a, b, age), tail = mix(a, b, max(0., age - mix(.3, .42, mm.w)));
      vec2 s = toSegment(q, tail, head);
      float life = smoothstep(0., .12, age) * (1. - smoothstep(.78, 1., age));
      life *= 1. + mm.w * 1.6 * exp(-pow((age - .82) / .07, 2.));
      vec3 add = tint.rgb * exp(-pow(s.x / wd, 2.)) * s.y * s.y * mm.y * life;
      add += tint.rgb * mm.w * exp(-pow(length(q - head) / (wd * 2.4), 2.)) * mm.y * life * .16;
      if (tint.w > 0.) {
        vec2 t2 = toSegment(q, mix(a, b, .15), head);
        add += vec3(.42, .85, .55) * exp(-pow(t2.x / (wd * 1.8), 2.)) * smoothstep(0., .3, t2.y) * tint.w * .13;
      }
      c += add * m.b * uStars;
    }
  }
  return c;
}

/* Rain at one distance: short bright strokes on a lattice that runs down the picture, each
   column at its own pace. */
float rainLayer(vec2 p, float H, float cw, float len, float speed, float wid, float lean, float seed, float dens) {
  float x = p.x + p.y * lean, c = floor(x / cw), h = hash11(c * 12.9898 + seed);
  float Y = (p.y / H - uTime * speed * (.8 + .4 * h)) / (len * 5.) + h * 13.7, r = floor(Y);
  vec2 q = hash22(vec2(c, r) + seed);
  if (q.x > dens) return 0.;
  float v = (Y - r - .1 - .6 * fract(q.x * 7.3)) * 5.;
  return smoothstep(wid, wid * .3, abs(x - (c + .2 + .6 * q.y) * cw)) * smoothstep(0., .25, v) * smoothstep(1., .7, v);
}
/* Snow at one distance: flakes on a falling lattice, each swaying in its own time, the wind
   carrying them all sideways. */
float snowLayer(vec2 p, float H, float cell, float rad, float speed, float seed, float dens, float soft) {
  vec2 q = p / (cell * H);
  q.x += (uTime * .03 + .25 * sin(uTime * .21 + seed)) / cell;
  float c = floor(q.x);
  q.y -= uTime * speed / cell * (.75 + .5 * hash11(c * 3.17 + seed)) + hash11(c + seed) * 9.;
  vec2 id = vec2(c, floor(q.y)), r = hash22(id + seed);
  if (r.x > dens) return 0.;
  vec2 ctr = vec2(.5 + .28 * sin(uTime * (.7 + 1.3 * r.y) + r.x * 40.), .25 + .5 * r.y);
  float size = rad * (.6 + .8 * fract(r.x * 11.3));
  return smoothstep(size, size * soft, length((fract(q) - ctr) * cell * H));
}

void main() {
  vec3 col = scene(uImgA, uMaskA, uRectA, uTexA, uSkyA, uWatA, uFallRectA, uFallA, uFxA, uMoonA, uGlareA);
  if (uMix > 0.) {
    col = mix(col, scene(uImgB, uMaskB, uRectB, uTexB, uSkyB, uWatB, uFallRectB, uFallB, uFxB, uMoonB, uGlareB), uMix);
  }
  vec2 p = vSt * uView;
  float H = uView.y, k = H / (800. * uDpr);
  if (uAir.x > 0.) {       // rain in the air, near to far: it shows against the dark and is lost against the bright
    // In a small window the strokes are finer, and fewer.
    float lean = .07 + .03 * sin(uTime * .31), r = 0., thin = clamp(k * 2.2, .4, 1.) * uDpr;
    r += rainLayer(p, H, 46. * k * uDpr, .075, 3.4, 1.5 * thin, lean, 11., .5) * .28;
    r += rainLayer(p, H, 15. * k * uDpr, .030, 1.5, 1.05 * thin, lean, 23., .6) * .34;
    if (k > .55) r += rainLayer(p, H, 6.5 * k * uDpr, .012, .6, .8 * uDpr, lean, 37., .7) * .26;
    col += (uAmb - col) * clamp(r * uAir.x * (k > .55 ? 1. : .7), 0., .7);
  }
  if (uAir.y > 0.) {       // snow, near to far
    float s = 0.;
    s = max(s, snowLayer(p, H, .26, 5.5 * k * uDpr, .78, 3., .22, .15) * .30);
    s = max(s, snowLayer(p, H, .075, 2.5 * k * uDpr, .42, 17., .62, .35) * .70);
    s = max(s, snowLayer(p, H, .036, 1.35 * k * uDpr, .2, 29., .72, .4) * .66);
    if (k > .55) s = max(s, snowLayer(p, H, .019, .85 * k * uDpr, .095, 41., .7, .4) * .46);
    col += (uAmb - col) * s * uAir.y;
  }
  col = mix(col, vec3(.02, .039, .086), uDim);
  o = vec4(col, 1.);
}`;

// Birds are triangles, laid out in pixels of the whole photograph and drawn over each viewport.
const BIRD_VERTEX = `#version 300 es
in vec2 aPos; in vec4 aCol; in float aHaze;
uniform vec4 uRect; uniform vec2 uVirt;
out vec4 vCol; out float vHaze;
void main() {
  vec2 st = (aPos / uVirt - uRect.xy) / uRect.zw;
  vCol = aCol; vHaze = aHaze;
  gl_Position = vec4(st.x * 2. - 1., 1. - st.y * 2., 0., 1.);
}`;
const BIRD_FRAGMENT = `#version 300 es
precision highp float;
in vec4 vCol; in float vHaze; out vec4 o;
uniform vec3 uHaze; uniform float uDim;
void main() { o = vec4(mix(mix(vCol.rgb, uHaze, vHaze), vec3(.02, .039, .086), uDim), vCol.a); }`;

// The night that a daytime photograph of weather is darkened toward (the shaders' vec3).
const NIGHT_CSS = "#050a16";

// ---- what crosses the sky --------------------------------------------------------------------

// Where and how fast each kind of bird flies. The spans and speeds are the Light Control card's;
// the distances are near, since a photograph's sky is a narrow strip of the real one and a
// window a small one: a bird passes close by.
const SPECIES = {
  songbird: { span: 0.25, speed: [7.5, 10], depth: [4, 9], band: [0.25, 1.05] },
  swallow: { span: 0.32, speed: [10, 13], depth: [5, 13], band: [0.45, 1.12] },
  crow: { span: 0.95, speed: [8.5, 10.5], depth: [9, 30], band: [0.2, 0.95] },
  gull: { span: 1.25, speed: [8.5, 11], depth: [9, 35], band: [0.15, 1.04] },
  goose: { span: 1.6, speed: [12, 14.5], depth: [20, 60], band: [0.1, 0.7] },
  hawk: { span: 1.25, speed: [6, 7.5], depth: [18, 45], band: [0.1, 0.6] },
  bat: { span: 0.3, speed: [4.5, 6.5], depth: [4, 9], band: [0.3, 1.0] },
};

// The most birds drawn at once, and the numbers each of their corners takes: x, y, red, green,
// blue, opacity, haze.
const MAX_BIRDS = 12;
const CORNER_FLOATS = 7;

const add3 = (a, b, k = 1) => [a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k];
const cross3 = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit3 = (a) => {
  const length = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / length, a[1] / length, a[2] / length];
};

/** Random numbers that repeat for a seed, so a view's life is the same each time it is drawn. */
const seeded = (seed) => () => {
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const hash = (n) => {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
};

/** A path through the air, walked by distance. */
class Route {
  constructor(points) {
    this.points = points;
    this.distances = [0];
    for (let i = 1; i < points.length; i += 1) {
      const [a, b] = [points[i - 1], points[i]];
      this.distances.push(this.distances[i - 1] + Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]));
    }
    this.length = this.distances[this.distances.length - 1];
  }

  at(distance) {
    const along = clamp(distance, 0, this.length);
    let i = 1;
    while (i < this.distances.length - 1 && this.distances[i] < along) i += 1;
    const share = (along - this.distances[i - 1]) / (this.distances[i] - this.distances[i - 1] || 1);
    return [0, 1, 2].map((axis) => lerp(this.points[i - 1][axis], this.points[i][axis], share));
  }
}

const bezier = (p0, p1, p2, p3, steps = 48) =>
  Array.from({ length: steps + 1 }, (_, i) => {
    const t = i / steps;
    const u = 1 - t;
    return [0, 1, 2].map(
      (axis) => u * u * u * p0[axis] + 3 * u * u * t * p1[axis] + 3 * u * t * t * p2[axis] + t * t * t * p3[axis],
    );
  });

/** How a small bird strays from its path: a songbird bounds, a swallow swerves, a bat flutters. */
function wander(kind, t, bird) {
  const s = bird.seed;
  if (kind === "songbird") {
    const length = 0.7 + s[1] * 0.25;
    const at = (((t + s[0] * 10) % length) + length) % length;
    const rise = at < 0.36 ? at / 0.36 : 1 - (at - 0.36) / (length - 0.36);
    return { across: 0, up: 0.22 * smooth(0, 1, rise) };
  }
  if (kind === "swallow") {
    return {
      across: 1.8 * Math.sin(t * (3.4 + s[2] * 2) + s[3] * TAU),
      up: 1.3 * Math.sin(t * (2.6 + s[4] * 2) + s[5] * TAU),
    };
  }
  if (kind === "bat") {
    return {
      across: 0.9 * Math.sin(t * (7 + s[2] * 5) + s[3] * TAU) + 0.5 * Math.sin(t * (13 + s[4] * 4)),
      up: 0.6 * Math.sin(t * (8 + s[5] * 5) + s[1] * TAU) + 0.3 * Math.sin(t * (17 + s[2] * 3)),
    };
  }
  return { across: 0, up: 0 };
}

/**
 * The light the birds are seen in, by the kind of photograph, as the Light Control card lights
 * its own: the way to the sun (y up, z away from the viewer), its colour, and the sky's light
 * from six sides.
 */
const birdLights = (daylight) => {
  const ambient = (k, tint = [1, 1, 1]) => daylight.ambient.map((side) => side.map((v, i) => v * k * tint[i]));
  return {
    day: { dir: unit3([-0.35, 0.75, 0.25]), color: [5.2, 4.7, 4], ambient: ambient(1) },
    morning: { dir: unit3([0.5, 0.45, -0.7]), color: [4.6, 4.1, 3.5], ambient: ambient(0.95) },
    golden: { dir: unit3([-0.35, 0.2, 0.9]), color: [5.4, 3.6, 1.9], ambient: ambient(0.75, [1.1, 0.95, 0.85]) },
    sunset: { dir: unit3([-0.2, 0.06, 0.98]), color: [3.4, 1.8, 0.9], ambient: ambient(0.5, [1.15, 0.9, 0.9]) },
    dusk: { dir: unit3([-0.2, 0.05, 0.98]), color: [0.3, 0.32, 0.5], ambient: ambient(0.22, [0.85, 0.95, 1.2]) },
    overcast: { dir: unit3([0, 1, 0.1]), color: [0.9, 0.9, 0.9], ambient: ambient(1.5) },
  };
};

/**
 * What crosses the sky, and when: flights of birds and shooting stars. The timing is the Light
 * Control card's: a flight every half minute to a minute or so by day, a shooting star once or
 * twice a minute under a starry sky, one in ten of them a fireball.
 */
class Sky {
  constructor(seed) {
    this.random = seeded(seed);
    this.flights = [];
    this.meteors = [];
    this.next = {};
    this.rows = [];
    this.last = { side: 0, x: -1, angle: 999 };
    this.pending = [];
  }

  /** Whether something on a channel is due now; it then schedules the next. */
  due(channel, now, on, first, every) {
    if (!on) {
      this.next[channel] = undefined;
      return false;
    }
    if (this.next[channel] === undefined) {
      this.next[channel] = now + lerp(first[0], first[1], this.random());
      return false;
    }
    if (now < this.next[channel]) return false;
    this.next[channel] = now + lerp(every[0], every[1], this.random());
    return true;
  }

  flock(kind) {
    const r = this.random;
    const { span } = SPECIES[kind];
    const bird = (back, across, up) => ({
      back,
      across,
      up,
      span: span * (0.9 + 0.2 * r()),
      phase: r() * TAU,
      seed: Array.from({ length: 6 }, () => r()),
    });
    const loose = (count, spread) =>
      Array.from({ length: count }, (_, i) =>
        bird(i ? r() * spread * 1.5 : 0, i ? (r() - 0.5) * spread : 0, i ? (r() - 0.5) * spread * 0.4 : 0),
      );
    if (kind === "goose") {
      // A skein: each bird behind and to one side of the one ahead.
      return Array.from({ length: 5 + Math.floor(r() * 5) }, (_, i) => {
        const rank = Math.ceil(i / 2);
        const side = i % 2 ? 1 : -1;
        return bird(rank * 1.5 + (r() - 0.5) * 0.3, side * rank * 1.3, (r() - 0.5) * 0.3);
      });
    }
    if (kind === "songbird") return loose(r() < 0.6 ? 1 : r() < 0.75 ? 2 : 3, 2);
    if (kind === "swallow") return loose(2 + Math.floor(r() * 2), 3);
    if (kind === "crow") return loose(r() < 0.6 ? 1 : 2, 6);
    if (kind === "gull") return loose(1 + Math.floor(r() * 3), 7);
    if (kind === "bat") return loose(1 + Math.floor(r() * 3), 4);
    return [bird(0, 0, 0)];
  }

  /**
   * A flight across the part of the photograph that shows. `view` is that part, in the
   * photograph's own coordinates: its left and right edges, the top of the sky that shows, the
   * horizon and the shape.
   */
  flight(now, kind, view) {
    const r = this.random;
    const species = SPECIES[kind];
    const reach = Math.tan((FIELD_DEG / 2) * RAD);
    const side = this.last.side && r() < 0.65 ? -this.last.side : r() < 0.5 ? -1 : 1;
    this.last.side = side;
    // A place in the picture, at a distance, as a point in the air: x across, y away, z up.
    const air = (x, y, distance) => [
      (x - 0.5) * 2 * reach * distance,
      distance,
      ((view.horizon - y) / view.aspect) * 2 * reach * distance,
    ];
    const distance = lerp(species.depth[0], species.depth[1], r() * r() * 0.6 + r() * 0.4);
    const distanceOut = distance * lerp(0.8, 1.3, r());
    const margin = 0.06 + species.span / distance;
    const sky = Math.max(view.horizon - view.top, 0.05);
    const yIn = view.top + sky * lerp(species.band[0], species.band[1], r());
    const yOut = clamp(yIn + (r() - 0.5) * 0.16 * sky, view.top + 0.03 * sky, view.top + sky * 1.15);
    const from = air(side < 0 ? view.right + margin : view.left - margin, yIn, distance);
    const to = air(side < 0 ? view.left - margin : view.right + margin, yOut, distanceOut);
    const bend = kind === "hawk" ? 0.55 : 0.22;
    const between = (share) =>
      add3(
        [0, 1, 2].map((axis) => lerp(from[axis], to[axis], share)),
        [0, (r() - 0.5) * bend * distance, (r() - 0.5) * 0.07 * distance],
      );
    const route = new Route(bezier(from, between(0.33), between(0.66), to));
    const birds = this.flock(kind);
    const speed = lerp(species.speed[0], species.speed[1], r());
    const behind = Math.max(...birds.map((bird) => bird.back));
    this.flights.push({ kind, start: now, speed, route, birds, end: now + (route.length + behind) / speed });
  }

  meteor(now, fireball, view, follow) {
    const r = this.random;
    let from;
    let angle;
    if (follow) {
      // Now and then two come close together, from the same part of the sky.
      angle = follow.angle + (r() - 0.5) * 0.12;
      from = [
        clamp(follow.origin[0] + (r() - 0.5) * 0.25, 0.05, 0.95),
        clamp(follow.origin[1] + (r() - 0.5) * 0.12, 0.02, 0.45),
      ];
    } else {
      // Not where, or the way, the last one went.
      let tries = 0;
      do {
        from = [lerp(0.08, 0.92, r()), lerp(0.03, 0.42, r())];
        const style = r();
        const tilt = style < 0.12 ? lerp(70, 86, r()) : style < 0.45 ? lerp(40, 70, r()) : lerp(8, 40, r());
        angle = (r() < 0.5 ? -1 : 1) * tilt * RAD;
        tries += 1;
      } while (tries <= 8 && (Math.abs(from[0] - this.last.x) < 0.25 || Math.abs(angle - this.last.angle) < 0.5));
    }
    const length = lerp(0.18, 0.5, r());
    const to = [from[0] + Math.sin(angle) * length * 0.75, from[1] + Math.cos(angle) * length];
    const tint = r();
    let color = tint < 0.6 ? [0.88, 0.93, 1] : tint < 0.8 ? [1, 0.9, 0.74] : [0.82, 1, 0.88];
    if (fireball) color = r() < 0.5 ? [0.7, 1, 0.76] : [1, 0.78, 0.55];
    // Shares of the sky that shows, turned into the photograph's coordinates.
    const x = (share) => view.left + share * (view.right - view.left);
    const y = (share) => view.top + share * Math.max(view.horizon - view.top, 0.05) * 0.98;
    const meteor = {
      start: now,
      duration: fireball ? lerp(1.3, 1.9, r()) : lerp(0.45, 0.8, r()) + length * 1.2,
      origin: from,
      angle,
      from: [x(from[0]), y(from[1])],
      to: [x(to[0]), y(to[1])],
      brightness: fireball ? 3.4 : 1.1 + 1.4 * r() * r(),
      width: fireball ? 2.4 : lerp(0.9, 1.6, r()),
      color,
      fireball,
      // A fireball, and the odd bright one, leaves a train that glows for a moment.
      train: fireball ? 2.6 : r() < 0.15 ? 0.9 : 0,
    };
    this.meteors.push(meteor);
    if (this.meteors.length > 2) this.meteors.shift();
    if (follow) return;
    this.last.x = from[0];
    this.last.angle = angle;
    if (!fireball && r() < 0.14) {
      const at = now + lerp(0.3, 1.1, r());
      this.pending.push({ at, run: () => this.meteor(at, false, view, meteor) });
    }
  }

  /**
   * Move on to `now`. `conditions` says what this sky allows: the kinds of bird, how starry it
   * is, how high the sun is, and anything asked for by name.
   */
  step(now, conditions, view) {
    const r = this.random;
    if (now < (this.clock ?? -1) - 0.5) {
      // The clock went back: start afresh.
      this.flights = [];
      this.meteors = [];
      this.next = {};
      this.pending = [];
    }
    this.clock = now;
    const { birds, stars, sun, requests } = conditions;
    if (this.due("flight", now, birds.length > 0, [7, 20], sun > 2 ? [28, 80] : [16, 45])) {
      this.flight(now, birds[Math.floor(r() * birds.length)], view);
    }
    if (this.due("meteor", now, stars > 0.45, [5, 16], [22, 75])) this.meteor(now, r() < 0.1, view);
    for (const want of requests) {
      if (want === "meteor" || want === "fireball") this.meteor(now, want === "fireball", view);
      else if (SPECIES[want]) this.flight(now, want, view);
    }
    requests.length = 0;
    const due = this.pending.filter((item) => item.at <= now);
    this.pending = this.pending.filter((item) => item.at > now);
    for (const item of due) item.run();
    this.flights = this.flights.filter((flight) => now < flight.end + 1);
    this.meteors = this.meteors.filter((meteor) => now < meteor.start + meteor.duration + meteor.train);
  }

  /** The shooting stars now, as the shader takes them: twelve numbers each. Returns how many. */
  meteorData(now, out) {
    let count = 0;
    for (const meteor of this.meteors) {
      const age = (now - meteor.start) / meteor.duration;
      if (age < 0) continue;
      const train =
        meteor.train > 0
          ? clamp(1 - (now - meteor.start - meteor.duration * 0.7) / meteor.train, 0, 1) * smooth(0.3, 0.7, age)
          : 0;
      if (age > 1 && train <= 0) continue;
      out.set(
        [
          ...meteor.from,
          ...meteor.to,
          Math.min(age, 1),
          age < 1 ? meteor.brightness * 0.62 : 0,
          meteor.width * 0.8,
          meteor.fireball ? 1 : 0,
          ...meteor.color,
          train,
        ],
        count * 12,
      );
      count += 1;
    }
    return count;
  }

  /**
   * Lay every bird in flight as triangles, farthest first: CORNER_FLOATS numbers for each
   * corner, in `out`. `kit` is norman-birds.js. Returns how many corners.
   */
  birds(now, kit, lens, light, out) {
    const drawn = [];
    for (const flight of this.flights) {
      const small = SPECIES[flight.kind].span < 0.4;
      const t = now - flight.start;
      for (const bird of flight.birds) {
        const travelled = t * flight.speed - bird.back;
        if (travelled < 0 || travelled > flight.route.length) continue;
        const where = (time) => {
          const along = clamp(time * flight.speed - bird.back, 0, flight.route.length);
          const a = flight.route.at(along - 0.6);
          const b = flight.route.at(along + 0.6);
          const flat = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
          const left = [-(b[1] - a[1]) / flat, (b[0] - a[0]) / flat, 0];
          const stray = wander(flight.kind, time, bird);
          return add3(add3(flight.route.at(along), left, bird.across + stray.across), [0, 0, 1], bird.up + stray.up);
        };
        const step = 1 / 30;
        const [before, here, after] = [where(t - step), where(t), where(t + step)];
        const ahead = unit3([after[0] - before[0], after[1] - before[1], after[2] - before[2]]);
        const level = Math.hypot(ahead[0], ahead[1]);
        if (level < 1e-3) continue;
        const pitch = clamp(Math.atan2(ahead[2], level), -0.5, 0.5);
        const heading = [
          (ahead[0] / level) * Math.cos(pitch),
          (ahead[1] / level) * Math.cos(pitch),
          Math.sin(pitch),
        ];
        const levelRight = [ahead[1] / level, -ahead[0] / level, 0];
        const levelUp = cross3(levelRight, heading);
        // A bird banks into a turn, by how hard it is turning.
        const sideways =
          ((after[0] - 2 * here[0] + before[0]) * levelRight[0] +
            (after[1] - 2 * here[1] + before[1]) * levelRight[1]) /
          (step * step);
        const bank = clamp(Math.atan(sideways / 9.8), -1, 1);
        const right = add3(
          levelRight.map((v) => v * Math.cos(bank)),
          levelUp,
          -Math.sin(bank),
        );
        const up = add3(
          levelUp.map((v) => v * Math.cos(bank)),
          levelRight,
          Math.sin(bank),
        );
        const pose = kit.posture(flight.kind, t, bird.phase, bird.seed);
        pose.tail = Math.max(pose.tail, Math.abs(bank) * 0.7);
        const size = bird.span * (small ? 1.5 : 1);
        const at = add3(here, up, pose.bob * size);
        const middle = lens.point(at);
        if (!middle || size * middle.scale > lens.height * 0.25) continue;
        const fade = smooth(0, 3, travelled) * smooth(0, 3, flight.route.length - travelled);
        const haze = 0.5 * (1 - Math.exp(-middle.distance / 300));
        const row = (this.rows[drawn.length] ??= new Float32Array(kit.BIRD_FLOATS));
        const frame = { at, forward: heading, right, up };
        if (!kit.layBird(row, flight.kind, size, frame, pose, lens, light, fade, haze)) continue;
        drawn.push({ depth: middle.depth, row });
      }
    }
    drawn.sort((a, b) => b.depth - a.depth);
    let n = 0;
    for (const { row } of drawn) {
      // A row, as norman-birds.js writes it: the count of triangles, the bird's opacity and
      // haze, then each triangle's corners and their packed colours.
      const [triangles, alpha, haze] = [row[3], row[5], row[6]];
      for (let i = 0; i < triangles; i += 1) {
        const offset = (2 + i * 3) * 4;
        for (let corner = 0; corner < 3; corner += 1) {
          if (n + CORNER_FLOATS > out.length) return n / CORNER_FLOATS;
          const packed = row[offset + 9 + corner];
          out[n++] = row[offset + corner * 2];
          out[n++] = row[offset + corner * 2 + 1];
          out[n++] = ((packed / 65536) | 0) / 255;
          out[n++] = (((packed / 256) | 0) % 256) / 255;
          out[n++] = (packed % 256) / 255;
          out[n++] = alpha;
          out[n++] = haze;
        }
      }
    }
    return n / CORNER_FLOATS;
  }
}

/**
 * Lightning, as how bright the flash is at a moment: a few quick strokes close together, then
 * dark for a while.
 */
function lightning(t) {
  let flash = 0;
  const beat = Math.floor(t / 2.4);
  for (let i = beat - 1; i <= beat; i += 1) {
    if (hash(i * 7.13) > 0.66) continue;
    const start = (i + 0.1 + 0.8 * hash(i * 3.31)) * 2.4;
    const strokes = 1 + Math.floor(hash(i * 5.7) * 3);
    for (let k = 0; k < strokes; k += 1) {
      const since = t - (start + k * (0.07 + 0.13 * hash(i + k * 9.1)));
      if (since < 0 || since >= 1.6) continue;
      flash += (0.55 + 0.45 * hash(i * 2.3 + k)) * (0.78 * Math.exp(-since / 0.06) + 0.22 * Math.exp(-since / 0.4));
    }
  }
  return Math.min(flash, 1.5);
}

const loadImage = (url) =>
  new Promise((resolve, reject) => {
    const image = new Image();
    image.decoding = "async";
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`could not load ${url}`));
    image.src = url;
  });

// The width, in pixels, of the strip the birds are laid out at: about what a row of three
// windows shows. They are drawn at whatever size each window shows them.
const BIRD_STRIP_PX = 360;

/**
 * The WebGL side: one canvas, never on the page, where each window's view is drawn before it
 * is copied to the window's own canvas.
 */
class Painter {
  constructor(canvas, scenes) {
    const gl = canvas.getContext("webgl2", { antialias: true, alpha: false, powerPreference: "low-power" });
    if (!gl) throw new Error("no WebGL 2");
    this.gl = gl;
    this.canvas = canvas;
    this.scenes = scenes;
    this.cache = new Map();
    this.current = null;
    this.incoming = null;
    this.queued = null;
    this.wanted = null;
    this.mix = 0;
    this.fadeAt = 0;
    this.t = 0;
    this.used = 0;
    this.dim = 0;
    this.panes = [];
    this.sky = new Sky(20261116);
    this.requests = [];
    this.heaven = { sunElevation: 40, sunAzimuth: 180, moonElevation: -90, moonLight: [0, 0, 1] };
    this.meteors = new Float32Array(24);
    this.corners = new Float32Array(CORNER_FLOATS * 3 * 80 * MAX_BIRDS);
    this.kit = null;
    this.lights = null;
    this.lost = false;
    this.build();
    canvas.addEventListener("webglcontextlost", (event) => {
      // Asking for it back; until then the windows show the photograph still (LivingView).
      event.preventDefault();
      this.lost = true;
    });
    canvas.addEventListener("webglcontextrestored", () => {
      const showing = this.current;
      this.cache.clear();
      this.current = this.incoming = this.queued = null;
      this.build();
      this.lost = false;
      if (showing) this.show(showing.key, true);
    });
  }

  /** Everything the context holds, made at the start and again if the context is lost and restored. */
  build() {
    const { gl } = this;
    const shader = (type, source) => {
      const made = gl.createShader(type);
      gl.shaderSource(made, source);
      gl.compileShader(made);
      if (!gl.getShaderParameter(made, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(made));
      return made;
    };
    const program = (vertex, fragment) => {
      const made = gl.createProgram();
      gl.attachShader(made, shader(gl.VERTEX_SHADER, vertex));
      gl.attachShader(made, shader(gl.FRAGMENT_SHADER, fragment));
      gl.bindAttribLocation(made, 0, "aPos");
      gl.linkProgram(made);
      if (!gl.getProgramParameter(made, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(made));
      const uniforms = {};
      for (let i = 0, n = gl.getProgramParameter(made, gl.ACTIVE_UNIFORMS); i < n; i += 1) {
        const name = gl.getActiveUniform(made, i).name.replace(/\[0\]$/, "");
        uniforms[name] = gl.getUniformLocation(made, name);
      }
      return { program: made, uniforms };
    };
    this.picture = program(VERTEX, FRAGMENT);
    this.bird = program(BIRD_VERTEX, BIRD_FRAGMENT);

    this.quad = gl.createVertexArray();
    gl.bindVertexArray(this.quad);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

    this.birdArray = gl.createVertexArray();
    gl.bindVertexArray(this.birdArray);
    this.birdBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.birdBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, this.corners.byteLength, gl.DYNAMIC_DRAW);
    const stride = CORNER_FLOATS * 4;
    for (const [name, size, offset] of [["aPos", 2, 0], ["aCol", 4, 8], ["aHaze", 1, 24]]) {
      const location = gl.getAttribLocation(this.bird.program, name);
      gl.enableVertexAttribArray(location);
      gl.vertexAttribPointer(location, size, gl.FLOAT, false, stride, offset);
    }
    gl.bindVertexArray(null);

    this.noise = this.noiseTexture();
    this.blank = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.blank);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 255]));
    this.moon = this.blank;
    loadImage(fileUrl("moon.jpg", VIEW_VERSION)).then(
      (image) => {
        this.moon = this.texture(image, true, true);
      },
      () => {},
    );
  }

  /** Smooth, repeating noise in three channels: the sky's uneven timing and the veils of fog. */
  noiseTexture() {
    const { gl } = this;
    const size = 256;
    const data = new Uint8Array(size * size * 4);
    const random = seeded(7);
    for (let channel = 0; channel < 3; channel += 1) {
      const field = new Float32Array(size * size);
      for (let octave = 0, weight = 1, grid = 4; octave < 5; octave += 1, weight *= 0.5, grid *= 2) {
        const lattice = Float32Array.from({ length: grid * grid }, () => random());
        const value = (x, y) => lattice[(y % grid) * grid + (x % grid)];
        for (let y = 0; y < size; y += 1) {
          for (let x = 0; x < size; x += 1) {
            const fx = (x / size) * grid;
            const fy = (y / size) * grid;
            const [x0, y0] = [Math.floor(fx), Math.floor(fy)];
            const [tx, ty] = [fx - x0, fy - y0];
            const [sx, sy] = [tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)];
            field[y * size + x] +=
              weight *
              lerp(
                lerp(value(x0, y0), value(x0 + 1, y0), sx),
                lerp(value(x0, y0 + 1), value(x0 + 1, y0 + 1), sx),
                sy,
              );
          }
        }
      }
      let low = Infinity;
      let high = -Infinity;
      for (const v of field) {
        low = Math.min(low, v);
        high = Math.max(high, v);
      }
      for (let i = 0; i < size * size; i += 1) {
        data[i * 4 + channel] = Math.round(((field[i] - low) / (high - low)) * 255);
      }
    }
    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, size, size, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    return texture;
  }

  texture(image, mipmaps, repeatAcross) {
    const { gl } = this;
    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    if (mipmaps) gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mipmaps ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, repeatAcross ? gl.REPEAT : gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return texture;
  }

  /**
   * Give the graphics memory back now, not whenever the browser gets round to it: a browser
   * allows a page only so many WebGL contexts.
   */
  release() {
    this.lost = true;
    this.cache.clear();
    this.current = this.incoming = this.queued = null;
    this.gl.getExtension("WEBGL_lose_context")?.loseContext();
  }

  /** Give the painter the birds (norman-birds.js), once they have loaded. */
  setBirds(kit) {
    this.kit = kit;
    this.lights = birdLights(kit.DAYLIGHT);
  }

  /** Everything one scene needs: the strip of its photograph, and the same part of its map. */
  load(key) {
    let entry = this.cache.get(key);
    if (!entry) {
      const scene = this.scenes[key];
      entry = { key, scene, used: 0 };
      entry.ready = Promise.all([`${key}.webp`, `${key}-mask.jpg`].map((name) => loadImage(fileUrl(name, scene.rev)))).then(
        ([picture, mask]) => {
          if (this.lost) throw new Error("the drawing context was lost");
          entry.picture = this.texture(picture, true);
          entry.mask = this.texture(mask, false);
          return entry;
        },
      );
      entry.ready.catch(() => this.cache.delete(key));
      this.cache.set(key, entry);
    }
    this.used += 1;
    entry.used = this.used;
    return entry.ready;
  }

  /** Keep the scenes in use and the one before; let the rest go. */
  trim() {
    const keep = new Set([this.current, this.incoming].filter(Boolean));
    const old = [...this.cache.values()]
      .filter((entry) => entry.picture && !keep.has(entry))
      .sort((a, b) => b.used - a.used)
      .slice(1);
    for (const entry of old) {
      for (const texture of [entry.picture, entry.mask]) this.gl.deleteTexture(texture);
      this.cache.delete(entry.key);
    }
  }

  /**
   * Ask for a scene. It fades in once its pictures have loaded; a later request replaces an
   * earlier one that is still waiting. Resolves when it has been taken up, with whether it
   * was: false when something newer was asked for meanwhile.
   */
  async show(key, instant = false) {
    this.wanted = key;
    const entry = await this.load(key);
    if (this.wanted !== key) return false;
    if (!this.current || instant) {
      this.current = entry;
      this.incoming = this.queued = null;
      this.mix = 0;
      this.trim();
    } else if (this.incoming) {
      // One fade at a time; this one follows.
      this.queued = entry;
    } else if (this.current !== entry) {
      this.incoming = entry;
      this.fadeAt = this.t;
      this.mix = 0;
    }
    return true;
  }

  /**
   * Size the canvas: a place for each window that shows, in rows. It only ever grows, so
   * scrolling does not keep reallocating it.
   */
  layout(panes) {
    this.panes = panes;
    const live = panes.filter((pane) => pane.visible && pane.w && pane.slot);
    const across = Math.max(1024, ...live.map((pane) => pane.w));
    let x = 0;
    let y = 0;
    let rowHeight = 0;
    let used = 0;
    for (const pane of live) {
      if (x + pane.w > across && x > 0) {
        x = 0;
        y += rowHeight;
        rowHeight = 0;
      }
      pane.atlasX = x;
      pane.atlasY = y;
      x += pane.w;
      used = Math.max(used, x);
      rowHeight = Math.max(rowHeight, pane.h);
    }
    const width = Math.max(this.canvas.width, used, 2);
    const height = Math.max(this.canvas.height, y + rowHeight, 2);
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
  }

  /** The part of a scene's whole photograph a window shows. */
  rect(entry, pane) {
    const [left, top, width, height] = entry.scene.strip;
    const [x, y, w, h] = lookOf(entry.scene, pane.slot);
    return [left + x * width, top + y * height, w * width, h * height];
  }

  /**
   * Where the moon hangs and the sun's glare falls in a scene's photograph, for a window.
   *
   * The moon is there on the nights it really is up, with its real phase, and sinks to the
   * horizon as it really rises and sets. But it hangs in the part of the sky the windows show,
   * as the Light Control card hangs its own: toward the right of the strip, where it is inside
   * the last window of a room of two or of three, and a little over halfway up from the horizon
   * to the top of what the window's room shows.
   */
  heavens(entry, pane) {
    const { motion, strip } = entry.scene;
    const { sunElevation, sunAzimuth, moonElevation } = this.heaven;
    const out = { moon: [0, 0, 0, 0], glare: [0, 0, 0, 0] };
    if (motion.moon && moonElevation > -1.5) {
      const top = strip[1] + skyTopOf(entry.scene, pane.slot) * strip[3];
      const high = motion.horizon - (motion.horizon - top) * 0.56;
      out.moon = [
        strip[0] + strip[2] * 0.82,
        lerp(motion.horizon, high, smooth(0, 12, moonElevation)),
        MOON_RADIUS,
        smooth(4, -5, sunElevation) * smooth(-1.5, 0.5, moonElevation),
      ];
    }
    if (motion.glare && sunElevation > 15 && sunElevation < 36) {
      const across = 0.5 + ((((sunAzimuth - VIEW_AZIMUTH + 540) % 360) - 180) / FIELD_DEG);
      out.glare = [across, motion.glare * 0.34 * smooth(36, 17, sunElevation), 0, 0];
    }
    return out;
  }

  uniforms(tag, entry, pane, heavens) {
    const { gl } = this;
    const u = this.picture.uniforms;
    const { scene } = entry;
    const { motion } = scene;
    const unit = tag === "A" ? 0 : 2;
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(gl.TEXTURE_2D, entry.picture);
    gl.uniform1i(u[`uImg${tag}`], unit);
    gl.activeTexture(gl.TEXTURE0 + unit + 1);
    gl.bindTexture(gl.TEXTURE_2D, entry.mask);
    gl.uniform1i(u[`uMask${tag}`], unit + 1);
    gl.uniform4fv(u[`uRect${tag}`], this.rect(entry, pane));
    gl.uniform4fv(u[`uTex${tag}`], scene.strip);
    gl.uniform4f(u[`uSky${tag}`], ...motion.sky, motion.horizon);
    gl.uniform4f(u[`uWat${tag}`], ...motion.water, motion.water_top);
    const fall = motion.fall || [0, 0, 0, 0, 0, 1, 0, 0.05];
    gl.uniform4f(u[`uFallRect${tag}`], fall[0], fall[1], fall[2], fall[3]);
    gl.uniform4f(u[`uFall${tag}`], fall[4], fall[5], fall[6], fall[7]);
    gl.uniform4f(u[`uFx${tag}`], motion.stars || 0, motion.fog || 0, motion.storm || 0, scene.aspect);
    gl.uniform4fv(u[`uMoon${tag}`], heavens.moon);
    gl.uniform4fv(u[`uGlare${tag}`], heavens.glare);
  }

  /** Draw a frame at time `t` (seconds) in every window that shows. Returns whether it drew. */
  render(t) {
    const { gl } = this;
    if (this.lost || !this.current) return false;
    // Kept small enough for the shaders' arithmetic; the fade below allows for the wrap.
    this.t = t % 4096;
    if (this.incoming) {
      this.mix = this.t < this.fadeAt ? 1 : smooth(0, FADE_S, this.t - this.fadeAt);
      if (this.mix >= 1) {
        this.current = this.incoming;
        this.incoming = null;
        this.mix = 0;
        this.trim();
        if (this.queued && this.queued !== this.current) {
          this.incoming = this.queued;
          this.fadeAt = this.t;
        }
        this.queued = null;
      }
    }
    const showing = this.panes.filter((pane) => pane.visible && pane.w && pane.slot && pane.context);
    const [a, b, mix] = [this.current, this.incoming, this.mix];
    const motionA = a.scene.motion;
    const motionB = b ? b.scene.motion : motionA;
    const blend = (x, y) => lerp(x || 0, y || 0, mix);
    const storm = blend(motionA.storm, motionB.storm);
    const flash = storm > 0 ? lightning(this.t) : 0;
    const ambientA = motionA.ambient || [0.8, 0.84, 0.9];
    const ambientB = motionB.ambient || [0.8, 0.84, 0.9];
    // Rain and snow catch less light after dark, and all of a flash.
    const lit = (1 - 0.75 * this.dim) * (1 + (storm > 0 ? 2.2 * flash : 0));
    const ambient = [0, 1, 2].map((i) => Math.min(1, lerp(ambientA[i], ambientB[i], mix) * lit));

    // The sky's life is worked out once, in the strip of the scene that shows most, in the sky
    // every window that shows has: from the lowest of their rooms' tops down to the horizon.
    const lead = mix > 0.5 && b ? b : a;
    const leadMotion = lead.scene.motion;
    const strip = lead.scene.strip;
    const skyTop = showing.length ? Math.max(...showing.map((pane) => skyTopOf(lead.scene, pane.slot))) : 0;
    const view = {
      left: strip[0],
      right: strip[0] + strip[2],
      top: strip[1] + skyTop * strip[3],
      horizon: leadMotion.horizon,
      aspect: lead.scene.aspect,
    };
    const { sunElevation } = this.heaven;
    const starry = (leadMotion.stars || 0) * (sunElevation < -9 ? 1 : 0);
    this.sky.step(
      this.t,
      {
        birds: this.kit && sunElevation > -7 ? leadMotion.birds || [] : [],
        stars: starry,
        sun: sunElevation,
        requests: this.requests,
      },
      view,
    );
    const meteorCount = this.sky.meteorData(this.t, this.meteors);
    const meteorsShow = blend(motionA.stars, motionB.stars) * (1 - smooth(-9, -3, sunElevation)) > 0;

    // Birds, laid out in pixels of the whole photograph at the size a row of windows shows it.
    let cornerCount = 0;
    const virtual = [BIRD_STRIP_PX / strip[2], BIRD_STRIP_PX / strip[2] / lead.scene.aspect];
    if (this.kit && this.sky.flights.length) {
      const focal = virtual[0] / (2 * Math.tan((FIELD_DEG / 2) * RAD));
      const lens = {
        width: virtual[0],
        height: virtual[1],
        eye: [0, 0, 0],
        point: (p) =>
          p[1] < 1
            ? null
            : {
                x: virtual[0] / 2 + (p[0] / p[1]) * focal,
                y: leadMotion.horizon * virtual[1] - (p[2] / p[1]) * focal,
                depth: p[1],
                scale: focal / p[1],
                distance: Math.hypot(p[0], p[1], p[2]),
              },
      };
      const light = this.lights[leadMotion.light] || this.lights.day;
      cornerCount = this.sky.birds(this.t, this.kit, lens, light, this.corners);
      if (cornerCount) {
        gl.bindBuffer(gl.ARRAY_BUFFER, this.birdBuffer);
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, this.corners.subarray(0, cornerCount * CORNER_FLOATS));
      }
    }
    const haze = leadMotion.sky_color || [0.6, 0.65, 0.7];
    const rain = blend(motionA.rain, motionB.rain);
    const snow = blend(motionA.snow, motionB.snow);

    for (const pane of showing) {
      gl.viewport(pane.atlasX, this.canvas.height - pane.atlasY - pane.h, pane.w, pane.h);
      gl.useProgram(this.picture.program);
      gl.bindVertexArray(this.quad);
      gl.disable(gl.BLEND);
      const u = this.picture.uniforms;
      const heavensA = this.heavens(a, pane);
      this.uniforms("A", a, pane, heavensA);
      this.uniforms("B", b || a, pane, b ? this.heavens(b, pane) : heavensA);
      gl.activeTexture(gl.TEXTURE4);
      gl.bindTexture(gl.TEXTURE_2D, this.noise);
      gl.uniform1i(u.uNoise, 4);
      gl.activeTexture(gl.TEXTURE5);
      gl.bindTexture(gl.TEXTURE_2D, this.moon);
      gl.uniform1i(u.uMoonTex, 5);
      gl.uniform1f(u.uMix, b ? mix : 0);
      gl.uniform1f(u.uTime, this.t);
      gl.uniform1f(u.uDim, this.dim);
      gl.uniform1f(u.uDpr, pane.ratio);
      gl.uniform1f(u.uStars, meteorsShow ? 1 : 0);
      gl.uniform2f(u.uView, pane.w, pane.h);
      gl.uniform4f(u.uAir, rain, snow, flash, rain * 0.8);
      gl.uniform3fv(u.uAmb, ambient);
      gl.uniform3fv(u.uMoonLit, this.heaven.moonLight);
      gl.uniform4fv(u.uMet, this.meteors);
      gl.uniform1i(u.uMetN, meteorCount);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      if (cornerCount) {
        gl.useProgram(this.bird.program);
        gl.bindVertexArray(this.birdArray);
        gl.enable(gl.BLEND);
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
        gl.uniform4fv(this.bird.uniforms.uRect, this.rect(lead, pane));
        gl.uniform2fv(this.bird.uniforms.uVirt, virtual);
        gl.uniform3fv(this.bird.uniforms.uHaze, haze);
        gl.uniform1f(this.bird.uniforms.uDim, this.dim);
        gl.drawArrays(gl.TRIANGLES, 0, cornerCount);
      }
    }
    gl.bindVertexArray(null);
    // Each window takes its part of the canvas while this frame is still on it.
    for (const pane of showing) {
      pane.context.drawImage(this.canvas, pane.atlasX, pane.atlasY, pane.w, pane.h, 0, 0, pane.w, pane.h);
    }
    return true;
  }
}

// ---- the view --------------------------------------------------------------------------------

// The most device pixels drawn for each CSS pixel: past two the eye gains little and a phone's
// graphics chip pays for it nine times over instead of four.
const MAX_RATIO = 2;
// A frame slower than this on average (milliseconds) makes the view draw fewer pixels.
const SLOW_FRAME_MS = 24;
// A weather entity found by itself is looked for again this often while there is none.
const WEATHER_SEARCH_MS = 30000;

const prefersReducedMotion = () =>
  typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

// The page behind the windows takes the colours of the photograph in them (scenes.json, top to
// bottom): in Home Assistant's dark theme deepened toward DEEP, so that the page's words stay
// white on it, and in its light theme paled toward PALE, so that they stay dark on it.
const DEEP = [9, 12, 18];
const PALE = [246, 248, 251];
const NIGHT_RGB = [5, 10, 22];
const rgbOf = (hex) => [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16));
const toward = (from, to, share) => from.map((value, i) => Math.round(value + (to[i] - value) * share));
const lumaOf = ([red, green, blue]) => 0.2126 * red + 0.7152 * green + 0.0722 * blue;

/** A colour deepened at least `least` of the way, and further if it is still lighter than `most`. */
const deepened = (colour, least, most) => {
  const [light, deep] = [lumaOf(colour), lumaOf(DEEP)];
  return toward(colour, DEEP, Math.max(least, light > most ? (light - most) / (light - deep) : 0));
};

/** A colour paled at least `least` of the way, and further if it is still darker than `most`. */
const paled = (colour, least, most) => {
  const [dark, pale] = [lumaOf(colour), lumaOf(PALE)];
  return toward(colour, PALE, Math.max(least, dark < most ? (most - dark) / (pale - dark) : 0));
};

// How far each part of the ground goes toward DEEP or PALE, [at least, until it is this light
// or dark]: the glow high on the right, then the top, the middle and the foot of the page. The
// light ground pales the foot most, so the photograph's colour stays at the top of the page;
// the dark one deepens the foot most.
const STOPS = {
  dark: { shade: deepened, glow: [0.42, 112], top: [0.6, 96], middle: [0.78, 64], bottom: [0.9, 40], night: 0.85 },
  light: { shade: paled, glow: [0.22, 180], top: [0.4, 190], middle: [0.58, 204], bottom: [0.76, 218], night: 0.4 },
};

/**
 * The page's ground for a scene: its colours from top to bottom, and the most colourful of them
 * glowing high up on the right, where the light from a window would fall. In the dark theme
 * (`light` false) they are deepened, and a pale photograph (fog, snow) further, so that the white
 * words on the page always stand out; darker after dark, as the windows are. In the light theme
 * they are paled, and a dark photograph (night) further, so that its dark words do; after dark
 * a little greyer and dimmer, but never darker than they need.
 */
export function groundOf(colours, dim = 0, light = false) {
  const stops = STOPS[light ? "light" : "dark"];
  const [top, middle, bottom] = colours.map((hex) => toward(rgbOf(hex), NIGHT_RGB, dim * stops.night));
  const vividness = (colour) => Math.max(...colour) - Math.min(...colour);
  const glow = [top, middle].reduce((best, colour) => (vividness(colour) > vividness(best) ? colour : best));
  const css = (colour, [least, most]) => `rgb(${stops.shade(colour, least, most).join(", ")})`;
  return (
    `radial-gradient(110% 70% at 80% 0%, ${css(glow, stops.glow)}, transparent 75%), ` +
    `linear-gradient(to bottom, ${css(top, stops.top)}, ${css(middle, stops.middle)} 40%, ${css(bottom, stops.bottom)} 100%)`
  );
}

/**
 * The view, for the windows the card registers and the stage the panel gives it: the
 * photograph for the hour and the weather, moving where it can, in every window, and its
 * colours behind the page.
 *
 *   const view = new LivingView(stage);
 *   await view.load();
 *   view.configure({ place: "lake", motion: true, weatherEntity: null });
 *   view.hass = hass;                  // on every update from Home Assistant
 *   view.light = true;                 // the ground for Home Assistant's light theme, or false
 *   view.setPanes([{ canvas, group }])  // the card's windows, and the room each is in
 *   view.connect();                    // and disconnect() when the panel leaves the page
 */
export class LivingView {
  constructor(stage) {
    this.stage = stage;
    this.scenes = null;
    this.place = "coast";
    this.motion = true;
    // The time, for the moon and for a sun worked out here. A property so a check can set it.
    this.now = () => new Date();
    this._configuredWeather = null;
    this._weatherEntity = null;
    this._weatherSearchedAt = 0;
    this._hass = null;
    this._inputs = [];
    this._key = null;
    this._dim = 0;
    this._light = false;
    this._panes = [];
    this._listeners = new Set();
    this._connected = false;
    this._frame = 0;
    this._scale = 1;
    this._slow = { total: 0, frames: 0 };
    this._panesLive = true;
    this._painter = null;
    this._painterFailed = false;
    this._drawing = false;
    this._started = typeof performance === "object" ? performance.now() : 0;
    this._lastFrame = 0;
    this._ground = null;
    this._groundTop = 0;
    this._birdsAsked = false;

    // Two layers of the page's ground, one fading in over the other. They are the first things
    // in the stage, which is made a stacking context of its own: as they swap places by z-index
    // they stay under whatever else is there, and under the page.
    const layer = "position:absolute;inset:0;pointer-events:none;";
    this._grounds = [0, 1].map(() => {
      const ground = document.createElement("div");
      ground.style.cssText = `${layer}opacity:0;transition:opacity ${FADE_S}s ease;`;
      return ground;
    });
    stage.style.isolation = "isolate";
    stage.prepend(...this._grounds);
    // Drawn on out of sight, then copied to each window.
    this._canvas = document.createElement("canvas");

    this._onVisibility = () => this._run();
    this._onMotionPreference = () => this._applyMotion();
    this._tick = this._tick.bind(this);
  }

  /** Read the index of photographs. Rejects if it cannot be had; the page then has no view. */
  async load() {
    const response = await fetch(fileUrl("scenes.json", VIEW_VERSION));
    if (!response.ok) throw new Error(`scenes.json: ${response.status}`);
    this.scenes = await response.json();
    this._applyMotion();
    this._choose();
  }

  /** The place, whether it moves, and the weather entity to follow (null: find one). */
  configure({ place, motion, weatherEntity }) {
    this.place = PLACES.includes(place) ? place : PLACES[0];
    this.motion = motion !== false;
    if ((weatherEntity || null) !== this._configuredWeather) {
      this._configuredWeather = weatherEntity || null;
      this._weatherEntity = null;
      this._weatherSearchedAt = 0;
    }
    this._inputs = [];
    this._applyMotion();
    this._choose();
  }

  set hass(hass) {
    this._hass = hass;
    this._choose();
  }

  get hass() {
    return this._hass;
  }

  /**
   * Whether the page is in Home Assistant's light theme: its ground is then paled, not deepened.
   * The page's words and glass change with the theme at once, so the ground does too, unfaded.
   */
  set light(light) {
    if (Boolean(light) === this._light) return;
    this._light = Boolean(light);
    this._paintGround(true);
  }

  get light() {
    return this._light;
  }

  /** The photograph that shows, as scenes.json has it (its credit among the rest), or null. */
  get scene() {
    return this.scenes && this._key ? this.scenes[this._key] : null;
  }

  /** The weather entity the view follows: the one configured, else one it found, else null. */
  get weatherEntity() {
    return this._weatherEntity;
  }

  /** Where the sun is at `date`, seen from the house: for the forecast's hours after dark. */
  sunAt(date) {
    return sunPosition(date, this._hass?.config?.latitude ?? 0, this._hass?.config?.longitude ?? 0);
  }

  /** Call `listener` whenever the photograph or the weather entity changes. Returns the way to stop. */
  subscribe(listener) {
    this._listeners.add(listener);
    return () => this._listeners.delete(listener);
  }

  /** Ask for something that crosses the sky now and then, now: a kind of bird, "meteor" or "fireball". */
  request(what) {
    this._painter?.requests.push(what);
  }

  /**
   * The card's windows: `[{ canvas, group }]`, `group` naming the room a window is in. A room's
   * windows look out on one view between them, as through openings in one wall.
   */
  setPanes(panes) {
    this._paneResize?.disconnect();
    this._paneSight?.disconnect();
    this._panes = panes.map(({ canvas, group }) => ({
      canvas,
      group: group ?? 0,
      visible: true,
      w: 0,
      h: 0,
      ratio: 1,
      slot: null,
      context: null,
    }));
    if (typeof ResizeObserver === "function") {
      this._paneResize = new ResizeObserver(() => this.resize());
      for (const pane of this._panes) this._paneResize.observe(pane.canvas);
    }
    if (typeof IntersectionObserver === "function") {
      // Only the windows on the screen, and just off it, are drawn.
      this._paneSight = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            const pane = this._panes.find((candidate) => candidate.canvas === entry.target);
            if (pane) pane.visible = entry.isIntersecting;
          }
          this.resize();
        },
        { rootMargin: "60px" },
      );
      for (const pane of this._panes) this._paneSight.observe(pane.canvas);
    }
    this.resize();
  }

  /** The panel is on the page: start drawing, and following the clock. */
  connect() {
    if (this._connected) return;
    this._connected = true;
    document.addEventListener?.("visibilitychange", this._onVisibility);
    if (typeof matchMedia === "function") {
      this._motionQuery = matchMedia("(prefers-reduced-motion: reduce)");
      this._motionQuery.addEventListener?.("change", this._onMotionPreference);
    }
    // The sun moves on whether or not Home Assistant has anything new to say.
    this._clock = setInterval(() => {
      this._inputs = [];
      this._choose();
    }, 60000);
    this._applyMotion();
    this.resize();
    // Back on the page after leaving it: the photograph may have changed meanwhile.
    this._show(true);
  }

  /**
   * The panel has left the page: stop, and let go of the graphics memory. Home Assistant makes
   * a new panel each time the page is opened, and the old one's drawing context would otherwise
   * linger until the browser collected it. The windows keep their last picture, and a panel put
   * back on the page starts drawing afresh (connect).
   */
  disconnect() {
    if (!this._connected) return;
    this._connected = false;
    document.removeEventListener?.("visibilitychange", this._onVisibility);
    this._motionQuery?.removeEventListener?.("change", this._onMotionPreference);
    clearInterval(this._clock);
    if (this._frame) cancelAnimationFrame(this._frame);
    this._frame = 0;
    if (!this._painter) return;
    this._painter.release();
    this._painter = null;
    this._drawing = false;
    // A lost context stays with its canvas, so the next painter gets a canvas of its own.
    this._canvas = document.createElement("canvas");
  }

  /** The view is no longer wanted: stop, and take its ground out of the stage. */
  destroy() {
    this.disconnect();
    this._paneResize?.disconnect();
    this._paneSight?.disconnect();
    this._listeners.clear();
    for (const ground of this._grounds) ground.remove();
  }

  /** Measure the windows again: call when they may have changed size or place. */
  resize() {
    const ratio = Math.min(globalThis.devicePixelRatio || 1, MAX_RATIO) * this._scale;
    for (const pane of this._panes) {
      const box = pane.canvas.getBoundingClientRect?.();
      pane.box = box && box.width && box.height ? box : null;
      if (!pane.box) pane.slot = null;
      pane.ratio = ratio;
      pane.w = pane.box ? Math.max(1, Math.round(box.width * ratio)) : 0;
      pane.h = pane.box ? Math.max(1, Math.round(box.height * ratio)) : 0;
      if (!pane.w) continue;
      if (pane.canvas.width !== pane.w || pane.canvas.height !== pane.h) {
        pane.canvas.width = pane.w;
        pane.canvas.height = pane.h;
        pane.painted = null;
      }
      pane.context ??= pane.canvas.getContext?.("2d") ?? null;
    }
    this._placePanes();
    this._painter?.layout(this._livePanes());
    this._paintStillPanes();
  }

  /**
   * Where each window sits among its room's (`slot`, for lookOf): the strip spread behind a
   * room's windows as if they were openings in one wall, as wide as the windows reach and tall
   * enough to fill each.
   */
  _placePanes() {
    const rooms = new Map();
    for (const pane of this._panes) {
      if (!pane.box) continue;
      if (!rooms.has(pane.group)) rooms.set(pane.group, []);
      rooms.get(pane.group).push(pane);
    }
    for (const windows of rooms.values()) {
      const left = Math.min(...windows.map((pane) => pane.box.left));
      const reach = Math.max(...windows.map((pane) => pane.box.right)) - left;
      const rows = [];
      for (const pane of windows) if (!rows.some((top) => Math.abs(top - pane.box.top) < 4)) rows.push(pane.box.top);
      rows.sort((a, b) => a - b);
      for (const pane of windows) {
        const { box } = pane;
        // The strip's width on the screen, and the share of its height one window shows.
        const across = Math.max(reach, box.height * STRIP_SHAPE);
        const band = Math.min(1, (box.height * STRIP_SHAPE) / across);
        const row = rows.findIndex((top) => Math.abs(top - box.top) < 4);
        pane.slot = [(box.left - left + (across - reach) / 2) / across, box.width / across, band, row, rows.length];
      }
    }
  }

  // ---- choosing ------------------------------------------------------------------------------

  /** The weather entity to follow: the configured one if it exists, else Home Assistant's own, else any. */
  _findWeather(hass) {
    const states = hass.states || {};
    if (this._configuredWeather && states[this._configuredWeather]) return this._configuredWeather;
    if (this._weatherEntity && states[this._weatherEntity]) return this._weatherEntity;
    const now = Date.now();
    if (now - this._weatherSearchedAt < WEATHER_SEARCH_MS) return null;
    this._weatherSearchedAt = now;
    const found = Object.keys(states)
      .filter((entityId) => entityId.startsWith("weather."))
      .sort();
    return ["weather.forecast_home", "weather.home"].find((entityId) => found.includes(entityId)) ?? found[0] ?? null;
  }

  /** Where the sun is: Home Assistant's own sun where it has one, worked out here otherwise. */
  _sun(hass, now) {
    const sun = hass.states?.["sun.sun"];
    const elevation = Number(sun?.attributes?.elevation);
    const azimuth = Number(sun?.attributes?.azimuth);
    if (sun && !Number.isNaN(elevation) && !Number.isNaN(azimuth)) {
      return { elevation, azimuth, rising: sun.attributes.rising ?? azimuth < 180 };
    }
    return sunPosition(now, hass.config?.latitude ?? 0, hass.config?.longitude ?? 0);
  }

  _choose() {
    const hass = this._hass;
    if (!hass || !this.scenes) return;
    const weatherEntity = this._findWeather(hass);
    const states = hass.states || {};
    // Home Assistant sets hass on every change in the house; only these matter here.
    const inputs = [states["sun.sun"], weatherEntity && states[weatherEntity], hass.config, this.place];
    if (this._inputs.length && inputs.every((input, index) => input === this._inputs[index])) return;
    this._inputs = inputs;

    const now = this.now();
    const sun = this._sun(hass, now);
    const condition = weatherEntity ? conditionOf(states[weatherEntity].state) : null;
    const { key, dim } = pickScene(this.scenes, this.place, condition, sun.elevation, sun.rising);
    this._dim = dim;
    const moon = moonPosition(now, hass.config?.latitude ?? 0, hass.config?.longitude ?? 0);
    this._heaven = {
      sunElevation: sun.elevation,
      sunAzimuth: sun.azimuth,
      moonElevation: moon.elevation,
      moonLight: moonLight(sun, moon),
    };
    if (this._painter) this._painter.heaven = this._heaven;

    const changed = key !== this._key || weatherEntity !== this._weatherEntity;
    this._weatherEntity = weatherEntity;
    if (key !== this._key) {
      this._key = key;
      this._show(false);
    } else {
      this._syncNight();
    }
    if (changed) for (const listener of this._listeners) listener();
  }

  // ---- showing -------------------------------------------------------------------------------

  /** Whether the picture should be moving: the option, and the device's own preference. */
  _wantsMotion() {
    return this.motion && !prefersReducedMotion();
  }

  /** The windows drawn by the painter each frame; none once they have had to go still. */
  _livePanes() {
    return this._panesLive ? this._panes : [];
  }

  /** Start the moving picture if it is wanted and can be had, or go back to the still one. */
  _applyMotion() {
    if (this._wantsMotion() && !this._painter && !this._painterFailed && this.scenes) {
      try {
        this._painter = new Painter(this._canvas, this.scenes);
        if (this._heaven) this._painter.heaven = this._heaven;
        this._slow = { total: 0, frames: 0 };
        if (this._key) this._painter.show(this._key, true).catch(() => {});
        this.resize();
      } catch (error) {
        // No WebGL 2, or a shader this graphics driver will not take: the windows stay still.
        this._painterFailed = true;
        this._painter = null;
        // eslint-disable-next-line no-console
        console.info("norman: the view is shown still", error);
      }
    }
    this._run();
  }

  /**
   * Draw frames while the panel is on the page and in sight; hold the last one while it is not.
   * Once the windows have had to go still there is nothing left to draw.
   */
  _run() {
    const wanted = this._connected && Boolean(this._painter) && this._wantsMotion() && this._panesLive;
    const run = wanted && !document.hidden && typeof requestAnimationFrame === "function";
    if (run && !this._frame) {
      this._lastFrame = 0;
      this._frame = requestAnimationFrame(this._tick);
    } else if (!run && this._frame) {
      cancelAnimationFrame(this._frame);
      this._frame = 0;
    }
    if (!wanted) this._setDrawing(false);
  }

  _tick(now) {
    this._frame = requestAnimationFrame(this._tick);
    const painter = this._painter;
    const elapsed = this._lastFrame ? now - this._lastFrame : 0;
    this._lastFrame = now;
    // The darkening eases to where it should be, as the still picture's does.
    painter.dim += (this._dim - painter.dim) * Math.min(1, elapsed / 500 || 1);
    this._setDrawing(painter.render((now - this._started) / 1000));
    if (!this._drawing || !elapsed || elapsed > 200) return;
    // Too slow on this device: draw fewer pixels, and then leave the windows still.
    this._slow.total += elapsed;
    this._slow.frames += 1;
    if (this._slow.frames < 90) return;
    const average = this._slow.total / this._slow.frames;
    this._slow = { total: 0, frames: 0 };
    if (average <= SLOW_FRAME_MS) return;
    if (this._scale > 0.5) this._scale = Math.max(0.5, this._scale * 0.8);
    else if (this._panesLive && this._panes.length) this._panesLive = false;
    else return;
    this.resize();
    this._run();
  }

  /** Swap the windows between the moving picture and the still one. */
  _setDrawing(drawing) {
    if (drawing === this._drawing) return;
    this._drawing = drawing;
    for (const pane of this._panes) pane.painted = null;
    this._paintStillPanes();
  }

  /** Show the chosen photograph: in the windows, moving or still, and in the page's colours. */
  _show(instant) {
    const key = this._key;
    if (!key) return;
    const scene = this.scenes[key];
    if (this._painter) {
      this._painter.show(key, instant).catch(() => {});
      // The birds are a module of their own, fetched the first time a sky has any.
      if (scene.motion.birds?.length && !this._birdsAsked) {
        this._birdsAsked = true;
        import(new URL(`./norman-birds.js?v=${encodeURIComponent(VIEW_VERSION)}`, import.meta.url).href).then(
          (kit) => this._painter?.setBirds(kit),
          () => {},
        );
      }
    }
    this._paintGround(instant);
    this._loadPaneStill(key);
  }

  /** The page's ground: the layer that is not showing takes the new one and fades in over it. */
  _paintGround(instant) {
    const scene = this.scene;
    if (!scene?.colours) return;
    const ground = groundOf(scene.colours, this._dim, this._light);
    if (ground === this._ground) return;
    this._ground = ground;
    const next = this._grounds[1 - this._groundTop];
    const previous = this._grounds[this._groundTop];
    const still = instant || prefersReducedMotion();
    for (const layer of this._grounds) layer.style.transitionDuration = still ? "0s" : `${FADE_S}s`;
    next.style.background = ground;
    next.style.zIndex = "1";
    previous.style.zIndex = "0";
    next.style.opacity = "1";
    previous.style.opacity = "0";
    this._groundTop = 1 - this._groundTop;
  }

  _syncNight() {
    this._paintGround(false);
    if (!this._drawing) this._paintStillPanes();
  }

  /** The strip as an image, for when the windows are drawn still. */
  _loadPaneStill(key) {
    const scene = this.scenes[key];
    if (typeof Image !== "function") return;
    loadImage(fileUrl(`${key}.webp`, scene.rev)).then(
      (image) => {
        if (this._key !== key) return;
        this._paneStill = { key, image };
        for (const pane of this._panes) pane.painted = null;
        this._paintStillPanes();
      },
      () => {},
    );
  }

  /** Draw the windows still: whenever the painter is not drawing them. */
  _paintStillPanes() {
    if (this._drawing && this._panesLive) return;
    const still = this._paneStill;
    if (!still || still.key !== this._key) return;
    const { image } = still;
    const scene = this.scenes[still.key];
    for (const pane of this._panes) {
      if (!pane.context || !pane.w || !pane.slot) continue;
      // What it was last drawn with: the photograph, its darkening, and the window's place.
      const stamp = `${still.key}/${this._dim}/${pane.slot.join()}`;
      if (pane.painted === stamp) continue;
      const [x, y, w, h] = lookOf(scene, pane.slot);
      const [width, height] = [image.naturalWidth, image.naturalHeight];
      pane.context.drawImage(image, x * width, y * height, w * width, h * height, 0, 0, pane.w, pane.h);
      if (this._dim > 0) {
        pane.context.globalAlpha = this._dim;
        pane.context.fillStyle = NIGHT_CSS;
        pane.context.fillRect(0, 0, pane.w, pane.h);
        pane.context.globalAlpha = 1;
      }
      pane.painted = stamp;
    }
  }
}
