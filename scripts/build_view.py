#!/usr/bin/env python3
"""Build the photographs the sidebar page's windows look out on.

    python scripts/build_view.py fetch          # originals, from Wikimedia Commons
    python scripts/build_view.py masks --model segformer-b5-ade.onnx
    python scripts/build_view.py cut index      # the pictures that ship, and their index

The view (custom_components/norman/www/norman-view.js) shows one real photograph for each
hour and weather in the windows the card draws, and sets its sky and water moving. This script
makes everything it loads, from the table in scripts/view/scenes.toml:

  fetch   downloads each photograph, 3840 px wide, into .cache/view (not committed), and the
          map of the moon.
  masks   finds the sky and the water in each whole photograph, so only those move: a map of
          each (red: sky that may drift, green: water that may drift, blue: open sky) kept in
          .cache/view, and scripts/view/masks.json (the photograph's size, the horizon, the top
          of the water, the sky's colour). Needs numpy, onnxruntime and a SegFormer ADE20K
          model exported to ONNX (this set was made with segformer-b5-finetuned-ade-640-640);
          the other steps need only Pillow.
  cut     crops each photograph to its strip, two wide by one high, and writes it small into
          www/view as <scene>.webp, with the same part of its map as <scene>-mask.jpg, and the
          moon. Nothing is retouched.
  index   writes www/view/scenes.json, which the page reads: each scene's credit, strip,
          colours and motion, and a short hash of its files that stamps their URLs, so a
          browser keeps a picture it has across releases that did not change it.

Run the steps a change needs: a new strip is `cut index`; a new photograph, or a new trim, is
all four. `cut` needs the maps `masks` keeps in .cache/view.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import tomllib
from typing import Any
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "scripts" / "view" / "scenes.toml"
MASK_NOTES = ROOT / "scripts" / "view" / "masks.json"
CACHE = ROOT / ".cache" / "view"
OUT = ROOT / "custom_components" / "norman" / "www" / "view"

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_PAGE = "https://commons.wikimedia.org/wiki/File:"
# The colour map from NASA's CGI Moon Kit (Scientific Visualization Studio, public domain).
MOON_URL = "https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/lroc_color_poles_1k.jpg"
USER_AGENT = "norman-view-builder/1.0 (image build script)"

FETCH_WIDTH = 3840
# The strip the windows look out on, and its map of sky and water: a row of three windows on a
# tablet shows the strip about 800 device pixels wide, a phone's or a desktop's less.
STRIP_SIZE = (720, 360)
STRIP_MASK_SIZE = (360, 180)
WEBP_QUALITY = 76
# The width the sky and the water are mapped at, across the whole photograph.
MASK_WIDTH = 768
MOON_SIZE = (256, 128)

# ADE20K classes: sky; then water, sea, river, lake, waterfall and swimming pool.
SKY_CLASSES = [2]
WATER_CLASSES = [21, 26, 60, 128, 109, 113]

# What scenes.json carries for the page, beyond the credit and the crops.
MOTION_KEYS = (
    "sky",
    "water",
    "fall",
    "rain",
    "snow",
    "fog",
    "storm",
    "stars",
    "ambient",
    "moon",
    "glare",
    "birds",
    "light",
)


def scenes() -> dict[str, dict[str, Any]]:
    """The table, checked: every scene named <place>-<when> and freely licensed."""
    with TABLE.open("rb") as handle:
        table = tomllib.load(handle)
    for key, scene in table.items():
        place, _, when = key.partition("-")
        if not place or not when:
            raise SystemExit(f"{key}: a scene is named <place>-<when>")
        if scene["license"] not in ("CC0", "Public domain"):
            raise SystemExit(f"{key}: only CC0 and public-domain photographs can ship")
    return table


def _get(url: str, tries: int = 6) -> bytes:
    """One download, patiently: Wikimedia rate-limits a burst of large files."""
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=180) as response:
                return response.read()
        except OSError as err:
            if attempt == tries - 1:
                raise
            print(f"  retrying after {err}", flush=True)
            time.sleep(12 + 14 * attempt)
    raise AssertionError("unreachable")


def _original(key: str) -> Path:
    return CACHE / f"{key}.jpg"


def fetch(table: dict[str, dict[str, Any]]) -> None:
    """Download each photograph the cache lacks, and the moon."""
    CACHE.mkdir(parents=True, exist_ok=True)
    for key, scene in table.items():
        target = _original(key)
        if target.exists() and target.stat().st_size > 200_000:
            continue
        query = urllib.parse.urlencode(
            {
                "action": "query",
                "format": "json",
                "titles": f"File:{scene['source']}",
                "prop": "imageinfo",
                "iiprop": "url|size",
                "iiurlwidth": str(FETCH_WIDTH),
            }
        )
        pages = json.loads(_get(f"{COMMONS_API}?{query}"))["query"]["pages"]
        info = next(iter(pages.values()))["imageinfo"][0]
        data = _get(info.get("thumburl") or info["url"])
        target.write_bytes(data)
        print(f"{key}: {len(data) / 1e6:.1f} MB", flush=True)
        time.sleep(2.5)
    moon = CACHE / "moon.jpg"
    if not moon.exists():
        moon.write_bytes(_get(MOON_URL))
        print("moon: fetched", flush=True)


def _open(key: str, scene: dict[str, Any]) -> Any:
    """A scene's photograph, trimmed as the table says."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    source = _original(key)
    if not source.exists():
        raise SystemExit(f"{key}: no original in {CACHE}; run `fetch` first")
    image = Image.open(source).convert("RGB")
    if "trim" in scene:
        left, top, right, bottom = scene["trim"]
        width, height = image.size
        image = image.crop(
            (round(left * width), round(top * height), round(right * width), round(bottom * height))
        )
    return image


def _strip(scene: dict[str, Any], width: float, height: float) -> list[float]:
    """Where the windows' strip sits in a photograph of this size: left, top, width, height.

    Two wide by one high, as wide as the table's share of the picture (all of it unless the
    table says), placed as CSS object-position places a picture, and kept inside it.
    """
    x, y, *rest = scene["strip"]
    strip_width = width * (rest[0] if rest else 1.0)
    strip_height = strip_width / 2
    if strip_height > height:
        strip_height, strip_width = height, height * 2
    return [
        (width - strip_width) * x / 100,
        (height - strip_height) * y / 100,
        strip_width,
        strip_height,
    ]


def _mask_map(key: str) -> Path:
    """Where `masks` keeps a photograph's whole map of sky and water."""
    return CACHE / f"{key}-mask.png"


def cut(table: dict[str, dict[str, Any]]) -> None:
    """Write each scene's strip and the same part of its map, and the moon."""
    from PIL import Image

    OUT.mkdir(parents=True, exist_ok=True)
    for key, scene in table.items():
        image = _open(key, scene)
        left, top, width, height = _strip(scene, *image.size)
        box = (left, top, left + width, top + height)
        image.resize(STRIP_SIZE, Image.LANCZOS, box=box).save(
            OUT / f"{key}.webp", quality=WEBP_QUALITY, method=6
        )

        if not _mask_map(key).exists():
            raise SystemExit(f"{key}: no map of its sky and water in {CACHE}; run `masks` first")
        with Image.open(_mask_map(key)) as whole:
            scale = whole.width / image.width
            part = tuple(edge * scale for edge in box)
            mask = whole.convert("RGB").resize(STRIP_MASK_SIZE, Image.BILINEAR, box=part)
        mask.save(OUT / f"{key}-mask.jpg", quality=88, subsampling=0)
        sizes = [(OUT / name).stat().st_size // 1024 for name in (f"{key}.webp", f"{key}-mask.jpg")]
        print(f"{key}: {sizes} KB", flush=True)

    moon = CACHE / "moon.jpg"
    if moon.exists():
        Image.open(moon).convert("RGB").resize(MOON_SIZE, Image.LANCZOS).save(
            OUT / "moon.jpg", quality=88
        )
    elif not (OUT / "moon.jpg").exists():
        raise SystemExit(f"no moon map in {CACHE}; run `fetch` first")


def masks(table: dict[str, dict[str, Any]], model: Path) -> None:
    """Map the sky and the water of each photograph, and note where they meet."""
    import numpy as np
    import onnxruntime
    from PIL import Image, ImageFilter

    session = onnxruntime.InferenceSession(str(model), providers=["CPUExecutionProvider"])

    def box(values: Any, radius: int) -> Any:
        """The mean over a (2 * radius + 1) square, edges repeated."""
        padded = np.pad(values, radius, mode="edge").astype(np.float64)
        total = np.pad(padded.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        side = 2 * radius + 1
        rows, columns = values.shape
        area = (
            total[side : side + rows, side : side + columns]
            - total[0:rows, side : side + columns]
            - total[side : side + rows, 0:columns]
            + total[0:rows, 0:columns]
        )
        return (area / (side * side)).astype(np.float32)

    def guided(guide: Any, values: Any, radius: int, eps: float) -> Any:
        """A guided filter: the map takes the photograph's own edges."""
        mean_guide, mean_values = box(guide, radius), box(values, radius)
        slope = (box(guide * values, radius) - mean_guide * mean_values) / (
            box(guide * guide, radius) - mean_guide * mean_guide + eps
        )
        offset = mean_values - slope * mean_guide
        return np.clip(box(slope, radius) * guide + box(offset, radius), 0, 1)

    def resized(values: Any, size: tuple[int, int]) -> Any:
        return np.asarray(
            Image.fromarray(values.astype(np.float32), "F").resize(size, Image.BILINEAR)
        )

    def classes(image: Any) -> Any:
        """Each pixel's chance of being each ADE20K class, averaged with the mirror image."""
        width = 1024
        height = round(image.height * width / image.width / 32) * 32
        pixels = np.asarray(image.resize((width, height), Image.BILINEAR), np.float32) / 255
        pixels = (pixels - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
        batch = pixels.transpose(2, 0, 1)[None].astype(np.float32)
        logits = session.run(None, {"pixel_values": batch})[0][0]
        mirrored = session.run(None, {"pixel_values": batch[:, :, :, ::-1].copy()})[0][0]
        logits = (logits + mirrored[:, :, ::-1]) / 2
        chance = np.exp(logits - logits.max(0))
        return chance / chance.sum(0)

    def softened(values: Any, erode: int, blur: float) -> Any:
        image = Image.fromarray((np.clip(values, 0, 1) * 255).astype(np.uint8))
        if erode:
            image = image.filter(ImageFilter.MinFilter(2 * erode + 1))
        return np.asarray(image.filter(ImageFilter.GaussianBlur(blur)), np.float32) / 255

    CACHE.mkdir(parents=True, exist_ok=True)
    notes: dict[str, dict[str, Any]] = {}
    for key, scene in table.items():
        image = _open(key, scene)
        height = round(MASK_WIDTH * image.height / image.width)
        size = (MASK_WIDTH, height)
        chance = classes(image)
        sky = resized(chance[SKY_CLASSES].sum(0), size)
        water = resized(chance[WATER_CLASSES].sum(0), size)
        grey = np.asarray(image.resize(size, Image.LANCZOS).convert("L"), np.float32) / 255
        sky_soft, water_soft = guided(grey, sky, 10, 2e-3), guided(grey, water, 10, 2e-3)
        sky_hard = (sky_soft > 0.5).astype(np.float32)
        water_hard = (water_soft > 0.5).astype(np.float32)

        # Thin dark things in front of the sky or the water (twigs, treetops, posts, rocks)
        # must not be carried along with it.
        dark = box(grey, 5) - grey

        def keep(threshold: float, dark: Any = dark) -> Any:
            thin = Image.fromarray(((dark > threshold) * 255).astype(np.uint8))
            thin = thin.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(2.5))
            return 1 - np.asarray(thin, np.float32) / 255

        mask = np.stack(
            [
                softened(sky_hard, 7, 6) * keep(0.06),
                softened(water_hard, 5, 5) * keep(0.15),
                softened(sky_soft, 0, 1.2),
            ],
            -1,
        )
        Image.fromarray((mask * 255).astype(np.uint8)).save(_mask_map(key))

        # The horizon: where the sky ends above the water, as a share of the height.
        sky_columns = sky_hard.sum(0) > 3
        sky_bottom = np.where(sky_columns, height - np.argmax(sky_hard[::-1], axis=0), 0) / height
        water_columns = water_hard.sum(0) > 3
        both = sky_columns & water_columns
        if both.sum() > MASK_WIDTH * 0.05:
            horizon = float(np.median(sky_bottom[both]))
        elif sky_columns.any():
            horizon = float(np.percentile(sky_bottom[sky_columns], 80))
        else:
            horizon = 0.5
        water_top = 1.0
        if water_columns.sum() > MASK_WIDTH * 0.05:
            tops = np.argmax(water_hard, axis=0)[water_columns] / height
            water_top = float(np.percentile(tops, 15))
        colour = np.asarray(image.resize(size, Image.LANCZOS), np.float32) / 255
        sky_colour = (
            colour[sky_hard > 0.5].mean(0) if (sky_hard > 0.5).any() else colour.mean((0, 1))
        )
        notes[key] = {
            "size": list(image.size),
            "horizon": round(horizon, 3),
            "water_top": round(water_top, 3),
            "sky_color": [round(float(value), 3) for value in sky_colour],
        }
        print(f"{key}: {notes[key]}", flush=True)
    MASK_NOTES.write_text(json.dumps(notes, indent=1) + "\n", encoding="utf-8")


def _revision(key: str) -> str:
    """A short hash of a scene's files, which stamps their URLs."""
    digest = hashlib.sha256()
    for name in (f"{key}.webp", f"{key}-mask.jpg"):
        digest.update((OUT / name).read_bytes())
    return digest.hexdigest()[:10]


def _colours(key: str) -> list[str]:
    """The strip's colours from top to bottom, for the page behind the windows.

    One each for its top quarter, the band across its middle and its bottom quarter: the mean of
    the most colourful third of each, so that a golden sky over a dark rock is golden, not the
    grey the whole band averages to.
    """
    from PIL import Image

    with Image.open(OUT / f"{key}.webp") as strip:
        small = strip.convert("RGB").resize((96, 48), Image.BOX)
    colours = []
    for top, bottom in ((0, 12), (18, 30), (36, 48)):
        pixels = [small.getpixel((x, y)) for y in range(top, bottom) for x in range(small.width)]
        pixels.sort(key=lambda pixel: max(pixel) - min(pixel), reverse=True)
        vivid = pixels[: len(pixels) // 3]
        mean = [round(sum(pixel[i] for pixel in vivid) / len(vivid)) for i in range(3)]
        colours.append("#" + "".join(f"{value:02x}" for value in mean))
    return colours


def index(table: dict[str, dict[str, Any]]) -> None:
    """Write scenes.json from the table, the mask notes and the pictures themselves."""
    notes = json.loads(MASK_NOTES.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for key, scene in table.items():
        place, _, when = key.partition("-")
        # The strip is a share of the photograph as trimmed, whose size the mask notes keep, so
        # the index can be written without the originals.
        note = dict(notes[key])
        width, height = note.pop("size")
        left, top, strip_width, strip_height = _strip(scene, width, height)
        motion = {**note, **{name: scene[name] for name in MOTION_KEYS if name in scene}}
        if "horizon" in scene:
            motion["horizon"] = scene["horizon"]
        out[key] = {
            "place": place,
            "when": when,
            "title": scene["title"],
            "where": scene["where"],
            "by": scene["author"],
            "license": scene["license"],
            "source": COMMONS_PAGE + urllib.parse.quote(scene["source"].replace(" ", "_")),
            "tone": scene.get("tone", ""),
            "aspect": round(width / height, 4),
            "strip": [
                round(left / width, 5),
                round(top / height, 5),
                round(strip_width / width, 5),
                round(strip_height / height, 5),
            ],
            "colours": _colours(key),
            "rev": _revision(key),
            "motion": motion,
        }
    (OUT / "scenes.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    total = sum(path.stat().st_size for path in OUT.iterdir())
    print(f"{len(out)} scenes, {total / 1e6:.1f} MB in {OUT.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("steps", nargs="+", choices=["fetch", "masks", "cut", "index"])
    parser.add_argument("--model", type=Path, help="the SegFormer ADE20K ONNX model, for masks")
    parser.add_argument("--only", nargs="*", help="scene names, to work on a few")
    args = parser.parse_args()
    table = scenes()
    chosen = {key: scene for key, scene in table.items() if not args.only or key in args.only}
    # In this order whatever order they are given in: `cut` needs the maps `masks` makes.
    if "fetch" in args.steps:
        fetch(chosen)
    if "masks" in args.steps:
        if args.model is None:
            parser.error("masks needs --model")
        if args.only:
            parser.error("masks writes its notes for every scene; run it without --only")
        masks(table, args.model)
    if "cut" in args.steps:
        cut(chosen)
    if "index" in args.steps:
        index(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
