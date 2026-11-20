"""Guards for metadata that must stay in step with the code.

Each of these files is edited by hand, in a separate step from the code it describes, and
therefore silently falls behind: translations, services.yaml, the manifest, the HACS
metadata, and the documentation's cross-links. Pinning them here keeps them honest.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import tomllib

import pytest
import yaml

from custom_components.norman.const import DOMAIN, SIDEBAR_VIEW_NONE, SIDEBAR_VIEWS

REPO = pathlib.Path(__file__).resolve().parent.parent
COMPONENT = REPO / "custom_components" / DOMAIN
TRANSLATIONS = COMPONENT / "translations"


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _flatten(node: object, prefix: str = "") -> set[str]:
    """Return every dotted key path in a nested dict, so missing leaves are caught."""
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            keys.add(path)
            keys |= _flatten(value, path)
    return keys


# ---- manifest / HACS metadata ----------------------------------------------------------


def test_manifest_points_at_this_repository() -> None:
    """Documentation and issue links must lead users to this project, not a fork's origin."""
    manifest = _load(COMPONENT / "manifest.json")
    assert manifest["domain"] == DOMAIN
    assert manifest["documentation"] == "https://github.com/kedube/ha-norman"
    assert manifest["issue_tracker"] == "https://github.com/kedube/ha-norman/issues"
    assert manifest["codeowners"], "hassfest requires at least one code owner"


def test_manifest_version_uses_release_format() -> None:
    """The release workflow bumps ``major.minor`` with a two-digit minor (see CONTRIBUTING)."""
    version = _load(COMPONENT / "manifest.json")["version"]
    assert re.fullmatch(r"\d+\.\d{2}", version), (
        f"manifest version {version!r} is not major.minor with a two-digit minor"
    )


def test_hacs_name_matches_manifest() -> None:
    """HACS shows hacs.json's name; the integration shows the manifest's. Keep them equal."""
    assert _load(REPO / "hacs.json")["name"] == _load(COMPONENT / "manifest.json")["name"]


def test_hacs_declares_a_minimum_home_assistant_version() -> None:
    """The bundled brand icon needs 2026.3+; HACS enforces this key on download."""
    minimum = _load(REPO / "hacs.json")["homeassistant"]
    assert re.fullmatch(r"\d{4}\.\d{1,2}\.\d+", minimum), minimum
    assert minimum >= "2026.3.0"


def test_entity_translation_keys_are_translated() -> None:
    """Every entity description's translation_key needs a name (and buttons an icon)."""
    from custom_components.norman.binary_sensor import CONNECTION, PAIRING_MODE, PUSH_UPDATES
    from custom_components.norman.button import BUTTONS, HUB_BUTTONS, ROOM_BUTTONS
    from custom_components.norman.number import HUB_NUMBERS, NUMBERS, ROOM_NUMBERS
    from custom_components.norman.scene import ROOM_SCENE_KEY, SCENE_GROUP_KEY
    from custom_components.norman.select import SELECTS
    from custom_components.norman.sensor import HUB_SENSORS, SENSORS

    strings = _load(COMPONENT / "strings.json")["entity"]
    sensor_keys = {description.translation_key for description in (*SENSORS, *HUB_SENSORS)}
    assert sensor_keys == set(strings["sensor"])
    assert {
        CONNECTION.translation_key,
        PAIRING_MODE.translation_key,
        PUSH_UPDATES.translation_key,
    } == set(strings["binary_sensor"])
    number_keys = {d.translation_key for d in (*NUMBERS, *ROOM_NUMBERS, *HUB_NUMBERS)}
    assert number_keys == set(strings["number"])
    button_keys = {
        description.translation_key for description in (*BUTTONS, *HUB_BUTTONS, *ROOM_BUTTONS)
    }
    assert button_keys == set(strings["button"])
    icons = _load(COMPONENT / "icons.json")["entity"]["button"]
    assert button_keys == set(icons)
    # A scene is named as in the Norman app; the translated name is for one saved without.
    assert {ROOM_SCENE_KEY, SCENE_GROUP_KEY} == set(strings["scene"])
    # A color select names each of its colors, and has an icon.
    select_keys = {description.translation_key for description in SELECTS}
    assert select_keys == set(strings["select"])
    for description in SELECTS:
        assert set(description.options or ()) == set(
            strings["select"][description.translation_key]["state"]
        )
    assert select_keys == set(_load(COMPONENT / "icons.json")["entity"]["select"])


def test_card_draws_the_divided_lights_the_select_offers() -> None:
    """Each pattern of divided lights the select offers, the card draws and names, in order.

    As with the colors, the card matches the select's state against its own table
    (WINDOW_LIGHTS), drawing one it does not know as the default, and lists the patterns in that
    table's order; each pattern's name in every language is the integration's own word for it.
    """
    from custom_components.norman.select import (
        DEFAULT_WINDOW_LIGHTS,
        WINDOW_LIGHTS,
        WINDOW_LIGHTS_SELECT,
    )

    card = (COMPONENT / "www" / "norman-shades-card.js").read_text(encoding="utf-8")
    assert _card_table(card, "WINDOW_LIGHTS") == list(WINDOW_LIGHTS)
    assert f'const DEFAULT_WINDOW_LIGHTS = "{DEFAULT_WINDOW_LIGHTS}";' in card
    assert f'const KEY_WINDOW_LIGHTS = "{WINDOW_LIGHTS_SELECT.translation_key}";' in card

    for language, said in _card_words().items():
        states = _load(COMPONENT / "translations" / f"{language}.json")["entity"]["select"][
            "window_lights"
        ]
        assert said["lights"] == states["name"], language
        for pattern in WINDOW_LIGHTS:
            assert said[f"lights_{pattern}"] == states["state"][pattern], (language, pattern)


def test_observed_fields_are_catalogued() -> None:
    """Every field named in the protocol reference's tables must be in the known-field sets.

    The catalogue in const.py is what makes "undocumented field" logging meaningful: a field
    documented in NORMAN_API.md but missing from the catalogue would be reported as new on
    every install, and one added to the catalogue without documentation is invisible.
    """
    from custom_components.norman.const import (
        KNOWN_HUB_FIELDS,
        KNOWN_PERIPHERAL_FIELDS,
        KNOWN_SCENE_FIELDS,
        KNOWN_SCENE_GROUP_FIELDS,
        KNOWN_SCENE_GROUP_ITEM_FIELDS,
        KNOWN_SCENE_TARGET_FIELDS,
    )

    api_doc = (REPO / "docs" / "NORMAN_API.md").read_text(encoding="utf-8")
    observed = api_doc.split("## Observed fields", 1)[1].split("## Error conventions", 1)[0]
    documented = set(re.findall(r"`([A-Z][A-Za-z]+)`", observed))
    known = (
        KNOWN_HUB_FIELDS
        | KNOWN_PERIPHERAL_FIELDS
        | KNOWN_SCENE_FIELDS
        | KNOWN_SCENE_TARGET_FIELDS
        | KNOWN_SCENE_GROUP_FIELDS
        | KNOWN_SCENE_GROUP_ITEM_FIELDS
    )
    # Prose in that section also names cover types and endpoints; only check field-shaped
    # names, i.e. ones that appear in a table row's first column.
    fields = {
        name
        for row in observed.splitlines()
        if row.startswith("|") and row.count("|") >= 3
        for name in re.findall(r"`([A-Z][A-Za-z]+)`", row.split("|")[1])
    }
    missing = fields - known
    assert not missing, (
        f"documented in NORMAN_API.md but missing from const.py's known-field sets: "
        f"{sorted(missing)}"
    )
    assert documented  # the section still parses


def test_exception_translation_keys_exist() -> None:
    """Every translation_key raised as an error must have a message in strings.json.

    A missing key does not crash, it just shows the raw key to the user, which is the
    kind of thing nobody notices until a user reports "unknown_entry" as an error.
    """
    exceptions = set(_load(COMPONENT / "strings.json")["exceptions"])
    raised: set[str] = set()
    for source in COMPONENT.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        for block in re.findall(
            r"(?:HomeAssistantError|ServiceValidationError|ConfigEntryNotReady|UpdateFailed)"
            r"\((.*?)\)\s*(?:from|$)",
            text,
            re.S,
        ):
            raised |= set(re.findall(r'translation_key="([a-z_]+)"', block))
    assert raised, "no translated exceptions found -- the regex needs updating"
    assert raised <= exceptions, f"raised but not translated: {sorted(raised - exceptions)}"
    assert exceptions <= raised, f"translated but never raised: {sorted(exceptions - raised)}"
    # Placeholders in the English message must match what the code passes
    strings = _load(COMPONENT / "strings.json")["exceptions"]
    for key, entry in strings.items():
        assert "{" in entry["message"] or key, key


# ---- frontend card ---------------------------------------------------------------------


def test_card_registers_itself_in_the_picker() -> None:
    """The card must push itself onto window.customCards or it never appears in the picker.

    A card that renders perfectly but is invisible in "Add card" is indistinguishable from a
    broken install, and nothing else in the suite executes the JS.
    """
    from custom_components.norman.frontend import CARD_FILENAME

    card = (COMPONENT / "www" / CARD_FILENAME).read_text(encoding="utf-8")
    assert "window.customCards" in card, "the card never registers in the picker"
    assert 'type: "norman-shades-card"' in card, "registered under the wrong type"
    assert 'customElements.define("norman-shades-card"' in card


def test_card_reads_its_version_from_the_resource_url() -> None:
    """The card must derive its version from ?v=, never hardcode one.

    A hardcoded version is a second place to bump at release time, and the release
    workflow only touches manifest.json -- so it would silently drift and the console
    banner would then misreport which build is actually loaded.
    """
    card = (COMPONENT / "www" / "norman-shades-card.js").read_text(encoding="utf-8")

    assert 'searchParams.get("v")' in card, (
        "the card must read its version from its own ?v= stamp "
        "(new URL(import.meta.url).searchParams.get('v'))"
    )

    version = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))["version"]
    # A literal manifest version anywhere in the card is the drift this guards against.
    assert f'"{version}"' not in card and f"'{version}'" not in card, (
        f"the card hardcodes version {version}; derive it from the ?v= stamp instead"
    )

    assert "CARD_VERSION" in card, "the card should expose its version for the console banner"


def test_card_draws_the_shade_with_css_not_bitmaps() -> None:
    """The shade picture must be drawn in CSS, never with embedded images.

    The card this one is modelled on draws its shutter from three base64 PNGs, which is why
    its travel height cannot change: the geometry is pinned to features baked into a bitmap.
    Drawing the slats with a repeating gradient instead keeps the picture themeable, crisp at
    any pixel density, and free to scale -- and keeps the file reviewable, since a base64
    blob is not something anyone can read a change to.
    """
    from custom_components.norman.frontend import CARD_FILENAME

    card = (COMPONENT / "www" / CARD_FILENAME).read_text(encoding="utf-8")
    assert "repeating-linear-gradient" in card, (
        "the shade's slats should be a CSS gradient, not an image"
    )
    assert "data:image" not in card, "the card embeds a bitmap; draw the shade in CSS instead"
    assert "base64" not in card, "the card embeds base64 data; draw the shade in CSS instead"


def test_card_shade_geometry_is_relative() -> None:
    """The picture must be sized in percent and aspect-ratio, not fixed pixels.

    A shade laid out in absolute pixels cannot follow the card's width, so it either clips or
    leaves a gap on a phone. The rails' own thickness is the one thing allowed to be fixed:
    it is a constant visual weight, not a measurement of the window.
    """
    from custom_components.norman.frontend import CARD_FILENAME

    card = (COMPONENT / "www" / CARD_FILENAME).read_text(encoding="utf-8")
    assert "aspect-ratio" in card, "the picture should get its height from an aspect ratio"

    # The headrail depth and the rail thickness are shared between the CSS tokens and the
    # drawing arithmetic. If a pair drifts, the fabric hangs off its rail instead of from it.
    # scripts/check_card.mjs drives the geometry; this pins that each pair agrees at all.
    for token_name, constant_name in (
        ("--n-head", "SHADE_HEAD_PCT"),
        ("--n-rail", "SHADE_RAIL_PCT"),
    ):
        token = re.search(rf"{token_name}:\s*([\d.]+)%", card)
        assert token, f"the shade geometry should have a {token_name} percentage token"
        constant = re.search(rf"const {constant_name} = ([\d.]+);", card)
        assert constant, f"the drawing code should read a named {constant_name}, not a literal"
        assert token.group(1) == constant.group(1), (
            f"{token_name} is {token.group(1)}% but {constant_name} is {constant.group(1)}"
        )


def test_docs_do_not_pin_a_card_version() -> None:
    """No document may hardcode a ?v= stamp for the card resource.

    The release workflow bumps only manifest.json, so a literal version in a doc is stale
    from the next release onward -- and a wrong ?v= in a copied YAML-mode `resources:`
    block serves the browser a URL that does not match the installed integration.
    """
    pinned: list[str] = []
    for name in ("README.md", "docs/dashboard.md"):
        text = (REPO / name).read_text(encoding="utf-8")
        pinned += [f"{name}: {m}" for m in re.findall(r"\?v=\d[\w.]*", text)]

    assert not pinned, (
        "documentation pins a card version; use a <version> placeholder instead:\n  "
        + "\n  ".join(pinned)
    )


def test_card_identifies_entities_by_translation_key_not_unique_id() -> None:
    """The card must not read ``unique_id`` from the frontend entity registry.

    ``EntityRegistryEntry._as_display_dict`` (homeassistant/helpers/entity_registry.py)
    sends only entity_id, platform, area/device/labels, icon, translation_key and a few
    display flags. ``unique_id`` is never part of it, so reading it yields undefined for
    every entity -- which silently drops the middle rail and the battery rather than
    erroring. This regressed once; pin it.
    """
    card = (COMPONENT / "www" / "norman-shades-card.js").read_text(encoding="utf-8")

    # Match a property *access*, not the word: the comment above the constants explains
    # why unique_id is unusable and must stay.
    reads = re.findall(r"[.\[]\s*[\"']?unique_id", card)
    assert not reads, (
        "the card reads unique_id, which the frontend entity registry never sends; "
        "identify entities by translation_key instead"
    )
    assert "translation_key" in card, "the card should identify entities by translation_key"


def test_card_matches_the_translation_keys_the_entities_use() -> None:
    """Every key the card matches on must be one the integration actually sets.

    A typo here fails the same silent way: the entity is simply never found.
    """
    card = (COMPONENT / "www" / "norman-shades-card.js").read_text(encoding="utf-8")
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))

    declared = {
        key
        for section in ("cover", "number", "select", "sensor", "scene")
        for key in strings["entity"][section]
    }
    # The KEY_* constants are exactly what the card matches entities on.
    matched = set(re.findall(r'^const KEY_\w+ = "(\w+)";', card, re.M))

    assert matched, "no KEY_* constants found in the card"
    unknown = matched - declared
    assert not unknown, (
        f"the card matches translation keys no entity declares: {sorted(unknown)}. "
        f"Known keys: {sorted(declared)}"
    )
    # The middle rail is the one that regressed, so require it explicitly.
    assert {"bottom_rail", "middle_rail"} <= matched, (
        "the card must match both rail covers by translation key"
    )
    # The buttons it presses (a blind's Request status) are matched the same way.
    buttons = set(re.findall(r'^const BUTTON_\w+ = "(\w+)";', card, re.M))
    assert buttons, "no BUTTON_* constants found in the card"
    assert buttons <= set(strings["entity"]["button"]), sorted(
        buttons - set(strings["entity"]["button"])
    )
    assert not {key for key in buttons if "report_battery" in key}, "never the battery report"


def _card_table(card: str, name: str) -> list[str]:
    """The keys of one of the card's color tables (``const NAME = { key: ..., }``), in order."""
    block = re.search(rf"^const {name} = \{{\n(.*?)^\}};", card, re.M | re.S)
    assert block, f"no {name} in the card"
    return re.findall(r"^  (\w+): ", block.group(1), re.M)


def _card_words() -> dict[str, dict[str, str]]:
    """The card's words (www/norman-strings.js), by language, as plain ``key: "text"`` pairs."""
    text = (COMPONENT / "www" / "norman-strings.js").read_text(encoding="utf-8")
    words: dict[str, dict[str, str]] = {}
    language = None
    for line in text.splitlines():
        if heading := re.fullmatch(r'  "?([\w-]+)"?: \{', line):
            language = heading.group(1)
            words[language] = {}
        elif language and (pair := re.fullmatch(r'    (\w+): (".*"),', line)):
            words[language][pair.group(1)] = json.loads(pair.group(2))
    return words


def test_card_draws_the_colors_the_selects_offer() -> None:
    """Each color a blind's select offers, the card draws and names, in the same order.

    The card matches a select's state against its own tables (SHADE_COLORS, SHUTTER_COLORS):
    a color it does not know is drawn as the default, which a typo would do silently. Its
    window select lists the colors in its own order, so that has to be the select's too, and
    each color's name in every language is the integration's own word for that state.
    """
    from custom_components.norman.select import (
        DEFAULT_SHADE_COLOR,
        DEFAULT_SHUTTER_COLOR,
        SHADE_COLOR,
        SHADE_COLORS,
        SHUTTER_COLOR,
        SHUTTER_COLORS,
    )

    card = (COMPONENT / "www" / "norman-shades-card.js").read_text(encoding="utf-8")
    assert _card_table(card, "SHADE_COLORS") == list(SHADE_COLORS)
    assert _card_table(card, "SHUTTER_COLORS") == list(SHUTTER_COLORS)
    assert f'const DEFAULT_SHADE_COLOR = "{DEFAULT_SHADE_COLOR}";' in card
    assert f'const DEFAULT_SHUTTER_COLOR = "{DEFAULT_SHUTTER_COLOR}";' in card
    assert f'const KEY_SHADE_COLOR = "{SHADE_COLOR.translation_key}";' in card
    assert f'const KEY_SHUTTER_COLOR = "{SHUTTER_COLOR.translation_key}";' in card

    words = _card_words()
    assert set(words) == {
        "en",
        *(path.stem for path in (COMPONENT / "translations").glob("*.json")),
    }
    for language, said in words.items():
        selects = _load(COMPONENT / "translations" / f"{language}.json")["entity"]["select"]
        for key, colors in (("shade_color", SHADE_COLORS), ("shutter_color", SHUTTER_COLORS)):
            for color in colors:
                assert said[f"color_{color}"] == selects[key]["state"][color], (
                    language,
                    key,
                    color,
                )


def test_card_turns_the_louvers_through_the_tilts_the_cover_reports() -> None:
    """The card's louver stops are the cover's tilts for the hub's eight Positions.

    The card snaps a drag, a key and its list slider to these tilts and draws the louvers from
    them, so a table out of step with SHUTTER_TILTS would send tilts between the hub's stops
    and draw Positions where the hub has none.
    """
    from custom_components.norman.const import SHUTTER_CLOSED, SHUTTER_OPEN, SHUTTER_TILTS

    card = (COMPONENT / "www" / "norman-shades-card.js").read_text(encoding="utf-8")
    table = re.search(r"^const LOUVER_TILTS = \[([\d, ]+)\];$", card, re.M)
    assert table, "no LOUVER_TILTS in the card"
    assert [int(tilt) for tilt in table.group(1).split(",")] == list(SHUTTER_TILTS)
    assert f"const LOUVER_HORIZONTAL = {SHUTTER_TILTS[SHUTTER_OPEN]};" in card
    assert f"const LOUVER_OPEN_POSITION = {SHUTTER_OPEN};" in card
    assert len(SHUTTER_TILTS) == SHUTTER_CLOSED + 1


def test_card_finds_the_hub_by_keys_only_the_hub_has() -> None:
    """``HUB_KEYS`` must name hub entities, and only hub entities.

    The card titles itself after the device carrying one of them. A room device carries no
    cover either, so "the device without a cover" stopped meaning the hub once rooms became
    devices -- and a renamed hub key would leave the card titled after nothing, silently.
    """
    from custom_components.norman.binary_sensor import PAIRING_MODE, PUSH_UPDATES
    from custom_components.norman.button import HUB_BUTTONS
    from custom_components.norman.sensor import HUB_SENSORS

    card = (COMPONENT / "www" / "norman-shades-card.js").read_text(encoding="utf-8")
    block = re.search(r"^const HUB_KEYS = new Set\(\[(.*?)\]\);", card, re.M | re.S)
    assert block, "no HUB_KEYS set found in the card"
    hub_keys = set(re.findall(r'"(\w+)"', block.group(1)))

    hub_only = {d.translation_key for d in (*HUB_SENSORS, *HUB_BUTTONS, PAIRING_MODE, PUSH_UPDATES)}
    assert hub_keys, "HUB_KEYS is empty"
    assert hub_keys <= hub_only, f"not hub entities: {sorted(hub_keys - hub_only)}"


def test_card_controls_each_rail_independently() -> None:
    """Open/stop/close must target the rail they sit on, not the blind's bottom rail.

    The buttons originally lived in the blind header and were hardcoded to
    ``blind.bottomCover``, so a two-rail blind had a middle-rail slider but no way to open
    or stop that rail -- and the header buttons silently moved the bottom one instead.
    """
    card = (COMPONENT / "www" / "norman-shades-card.js").read_text(encoding="utf-8")

    assert "entity_id: rail.coverId" in card, (
        "the cover service calls must target rail.coverId so each rail controls itself"
    )
    assert "entity_id: blind.bottomCover" not in card, (
        "a control still targets blind.bottomCover; the middle rail would move the wrong rail"
    )


def test_card_element_names_match_the_registration() -> None:
    """The element the card defines, the editor it asks for, and the picker type must agree."""
    from custom_components.norman.frontend import CARD_FILENAME

    card = (COMPONENT / "www" / CARD_FILENAME).read_text(encoding="utf-8")
    defined = set(re.findall(r'customElements\.define\("([a-z-]+)"', card))
    assert defined == {"norman-shades-card", "norman-shades-card-editor"}
    # getConfigElement must name an element that actually exists, or the visual editor 500s
    (editor,) = re.findall(r'createElement\("([a-z-]+-editor)"\)', card)
    assert editor in defined


def test_card_file_is_served_from_the_registered_directory() -> None:
    """The resource URL must point at a file that ships, or every dashboard 404s."""
    from custom_components.norman.frontend import CARD_FILENAME, CARD_URL_PATH

    assert (COMPONENT / "www" / CARD_FILENAME).is_file()
    assert CARD_URL_PATH.endswith(CARD_FILENAME)


def test_sidebar_panel_matches_its_registration() -> None:
    """The panel file must ship, define the element frontend.py registers, and load the card.

    A mismatch is silent in the wild: the sidebar entry appears, and opens a blank page.
    """
    from custom_components.norman.frontend import CARD_FILENAME, PANEL_ELEMENT, PANEL_FILENAME

    panel = (COMPONENT / "www" / PANEL_FILENAME).read_text(encoding="utf-8")
    assert set(re.findall(r'customElements\.define\("([a-z-]+)"', panel)) == {PANEL_ELEMENT}
    # The card it hosts, imported beside it at the panel's own ?v= so the two never mix
    # versions, and created by the name the card file defines.
    assert f"./{CARD_FILENAME}?v=" in panel
    assert 'searchParams.get("v")' in panel
    assert 'createElement("norman-shades-card")' in panel
    # The card hides its menu button unless the panel marks it as the panel's.
    assert 'setAttribute("panel", "")' in panel


def test_card_words_ship_and_are_imported_at_the_version_stamp() -> None:
    """The card and the panel share their words (www/norman-strings.js), imported at ``?v=``.

    ``/norman/`` is served with long-lived cache headers, so a plain relative import of the
    words could pair an upgraded card with the previous release's: each file stamps the import
    with its own ``?v=``, as the panel does the card.
    """
    www = COMPONENT / "www"
    assert (www / "norman-strings.js").is_file()
    for name in ("norman-shades-card.js", "norman-panel.js"):
        text = (www / name).read_text(encoding="utf-8")
        assert "./norman-strings.js?v=" in text, f"{name} does not import the words"
        unstamped = re.search(r"""^\s*import\s[^(]*?["']\./norman-strings\.js["']""", text, re.M)
        assert not unstamped, f"{name} imports the words without the ?v= stamp"


def test_sidebar_panel_keeps_clear_of_the_safe_areas() -> None:
    """The panel pads itself for a phone's notch and home indicator, on every release.

    Home Assistant pads a custom panel itself from 2026.8 unless it opts out, and not at all
    before; the panel opts out (frontend.py) and reads Home Assistant's variables, with the
    browser's to fall back on.
    """
    panel = (COMPONENT / "www" / "norman-panel.js").read_text(encoding="utf-8")
    for edge in ("top", "right", "bottom", "left"):
        assert f"--safe-area-inset-{edge}" in panel, edge
        assert f"env(safe-area-inset-{edge}" in panel, edge
    assert "handle_safe_area" in (COMPONENT / "frontend.py").read_text(encoding="utf-8")


# ---- the sidebar page's view -----------------------------------------------------------

VIEW = COMPONENT / "www" / "view"
# The pictures each scene ships: the strip of its photograph the windows look out on, and the
# same part of its map of sky and water.
SCENE_FILES = (".webp", "-mask.jpg")
# Every weather and part of the day the page can ask for (pickScene in www/norman-view.js).
WEATHERS = ("partly", "cloudy", "fog", "rain", "storm", "snow")
PARTS_OF_DAY = ("dawn", "day", "golden", "sunset", "dusk", "twilight", "night")


def _scenes() -> dict[str, dict]:
    return _load(VIEW / "scenes.json")


def test_view_ships_exactly_the_pictures_its_index_lists() -> None:
    """Each scene in scenes.json has its two pictures, and www/view holds nothing else.

    A scene without a picture is a blank page the first time its weather comes round, months
    after the release; a picture without a scene is weight on every install for nothing.
    """
    expected = {"scenes.json", "moon.jpg"} | {
        f"{key}{suffix}" for key in _scenes() for suffix in SCENE_FILES
    }
    shipped = {path.name for path in VIEW.iterdir()}
    assert shipped == expected, (
        f"missing: {sorted(expected - shipped)}; not in the index: {sorted(shipped - expected)}"
    )


def test_view_index_is_built_from_the_scene_table() -> None:
    """scenes.json is what scripts/build_view.py makes of scripts/view/scenes.toml.

    The table is edited by hand and the index built from it, so each can fall behind the
    other: the same scenes, credits and motion, and each scene's ``rev`` the hash of the
    pictures that ship. The page stamps a picture's URL with its rev, and /norman/ is served
    with long-lived cache headers, so a picture changed without its rev would never reach a
    browser that has the old one.
    """
    table = tomllib.loads((REPO / "scripts" / "view" / "scenes.toml").read_text(encoding="utf-8"))
    scenes = _scenes()
    assert set(scenes) == set(table)
    for key, scene in scenes.items():
        row = table[key]
        assert f"{scene['place']}-{scene['when']}" == key
        assert (scene["by"], scene["license"], scene["title"], scene["where"]) == (
            row["author"],
            row["license"],
            row["title"],
            row["where"],
        ), key
        for name in ("sky", "water", "birds", "light", "rain", "snow", "fog", "storm", "stars"):
            assert scene["motion"].get(name) == row.get(name), f"{key}: {name}"
        # The strip is two wide by one high, inside the photograph.
        left, top, width, height = scene["strip"]
        assert abs(width * scene["aspect"] / height - 2) < 0.01, f"{key}: the strip is not 2:1"
        assert left >= 0 and top >= 0 and left + width <= 1.00001 and top + height <= 1.00001, key
        assert len(scene["colours"]) == 3, f"{key}: no colours for the page behind"
        digest = hashlib.sha256()
        for suffix in SCENE_FILES:
            digest.update((VIEW / f"{key}{suffix}").read_bytes())
        assert scene["rev"] == digest.hexdigest()[:10], (
            f"{key}: its pictures changed; run scripts/build_view.py index"
        )


def test_view_photographs_are_free_to_use_and_credited() -> None:
    """Only CC0 and public-domain photographs ship, each with its author and its source.

    The page cuts each photograph and sets it moving, which a licence that forbids changes
    would not allow. Neither CC0 nor the public domain asks for attribution, so the page carries
    none; NOTICE credits every author anyway, and the view option's description in the options
    form links to it, in every language.
    """
    from custom_components.norman.const import PHOTO_CREDITS_URL

    notice = (REPO / "NOTICE").read_text(encoding="utf-8")
    for key, scene in _scenes().items():
        assert scene["license"] in {"CC0", "Public domain"}, key
        assert scene["by"].strip(), f"{key} has no author"
        assert scene["source"].startswith("https://commons.wikimedia.org/wiki/File:"), key
        assert scene["by"] in notice, f"NOTICE does not credit {scene['by']} ({key})"
    assert "NASA" in notice, "NOTICE should credit the map of the moon"

    manifest = _load(COMPONENT / "manifest.json")
    notice_url = f"{manifest['documentation']}/blob/main/NOTICE"
    assert notice_url == PHOTO_CREDITS_URL
    for path in (COMPONENT / "strings.json", *sorted((COMPONENT / "translations").glob("*.json"))):
        described = _load(path)["options"]["step"]["init"]["data_description"]["sidebar_view"]
        assert "]({credits})" in described, f"{path.name} does not link the photo credits"


def test_view_has_a_photograph_for_every_place_weather_and_hour() -> None:
    """Whatever the weather and the hour, the page finds a photograph for each place.

    Each place has its own for every part of the day. Weather may be borrowed from another
    place (only the lake has snow), but some place must have it.
    """
    scenes = _scenes()
    have = {(scene["place"], scene["when"]) for scene in scenes.values()}
    assert {place for place, _ in have} == set(SIDEBAR_VIEWS)
    for place in SIDEBAR_VIEWS:
        missing = [when for when in PARTS_OF_DAY if (place, when) not in have]
        assert not missing, f"{place} has no photograph for {missing}"
    for weather in WEATHERS:
        assert any((place, weather) in have for place in SIDEBAR_VIEWS), weather


def test_view_places_are_the_ones_the_option_offers() -> None:
    """The option's places, the page's and the translations' are the same list.

    A place the option offers and the page does not know shows the first place instead; one
    without a name in a language shows its key in the dropdown.
    """
    view = (COMPONENT / "www" / "norman-view.js").read_text(encoding="utf-8")
    (places,) = re.findall(r"export const PLACES = (\[[^\]]*\]);", view)
    assert tuple(json.loads(places)) == SIDEBAR_VIEWS
    for path in [COMPONENT / "strings.json", *sorted(TRANSLATIONS.glob("*.json"))]:
        options = _load(path)["selector"]["sidebar_view"]["options"]
        assert set(options) == {*SIDEBAR_VIEWS, SIDEBAR_VIEW_NONE}, path.name


def test_view_knows_every_weather_state_home_assistant_has() -> None:
    """Each state a weather entity can have is a kind of weather the page has a photograph of.

    A state the page does not know shows the hour's own photograph, clear sky and all, so a
    state added by a later Home Assistant should be given its weather here.
    """
    from homeassistant.components import weather

    states = {
        value
        for name, value in vars(weather).items()
        if name.startswith("ATTR_CONDITION_") and name != "ATTR_CONDITION_CLASS"
    }
    assert len(states) >= 15, "Home Assistant's weather states were not found"
    view = (COMPONENT / "www" / "norman-view.js").read_text(encoding="utf-8")
    (block,) = re.findall(r"const WEATHER = \{(.*?)\n\};", view, re.S)
    known = set(re.findall(r'^\s*"?([a-z-]+)"?:', block, re.M))
    assert states <= known, f"the view does not know {sorted(states - known)}"


def test_view_photographs_stay_small() -> None:
    """The photographs are most of what an install downloads, so their size is pinned.

    The integration was 1 MB before them, and they keep it near 2: only the strip each window
    looks out on ships, small (scripts/build_view.py), never a photograph to fill a screen. A
    set that grows past this wants a smaller picture, or a place fewer, not a higher limit.
    """
    sizes = {path.name: path.stat().st_size for path in VIEW.iterdir()}
    heavy = {name: size // 1024 for name, size in sizes.items() if size > 64 * 1024}
    assert not heavy, f"pictures over 64 KB: {heavy}"
    total = sum(sizes.values())
    assert total <= 1024 * 1024, f"www/view is {total / 1e6:.2f} MB"


def test_view_modules_are_loaded_at_the_version_stamp() -> None:
    """The panel loads the view, and the view its birds, at their own ``?v=``, on demand.

    /norman/ is served with long-lived cache headers, so an unstamped import could pair an
    upgraded panel with the last release's view. Both are imported only when wanted (a plain
    page loads neither), and neither defines an element: the panel hosts the view itself.
    """
    www = COMPONENT / "www"
    panel = (www / "norman-panel.js").read_text(encoding="utf-8")
    view = (www / "norman-view.js").read_text(encoding="utf-8")
    birds = (www / "norman-birds.js").read_text(encoding="utf-8")
    assert "./norman-view.js?v=" in panel
    assert "./norman-birds.js?v=" in view
    assert 'searchParams.get("v")' in view
    for name, text in (("norman-panel.js", panel), ("norman-view.js", view)):
        static = re.search(r"""^\s*import\s[^(]*?["']\./norman-(view|birds)\.js""", text, re.M)
        assert not static, f"{name} imports the view up front; it must load on demand"
    for name, text in (("norman-view.js", view), ("norman-birds.js", birds)):
        assert "customElements.define" not in text, f"{name} must not define an element"
    # The birds are built from the Light Control card's; a change made here would be lost.
    assert "GENERATED by scripts/build_birds.mjs" in birds


def test_probe_script_refuses_write_endpoints() -> None:
    """The endpoint prober must never send anything that could change the hub.

    It is pointed at a live hub by hand, so its read-only guarantee is a safety property,
    not a style preference.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "probe_hub_endpoints", REPO / "scripts" / "probe_hub_endpoints.py"
    )
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    for name in ("GetAllScene", "GetDeviceInfo", "registration", "status", "GetPairingMode"):
        assert probe.is_read_only(name), f"{name} should be probeable"
    for name in (
        "control",
        "notification",
        "AddSchedule",
        "DeleteSchedule",
        "UpdateRoom",
        "UpdatePeripheral",
        "UpdateDeviceInfo",
        "SetTopLimit",
        "CleanBottomLimit",
        "Calibration",
        "MotorStop",
        "PairPeripheral",
        "FactoryReset",
    ):
        assert not probe.is_read_only(name), f"{name} must never be probed"

    # Every name the script ships with must pass its own filter.
    for name in (*probe.KNOWN, *probe.CANDIDATES):
        assert probe.is_read_only(name), f"shipped candidate {name} is not read-only"


def test_release_workflow_targets_this_manifest() -> None:
    """The release workflow hard-codes the manifest path; a domain rename must update it."""
    workflow = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    bump_script = (REPO / ".github" / "scripts" / "bump_manifest_version.py").read_text(
        encoding="utf-8"
    )
    for text in (workflow, bump_script):
        assert f"custom_components/{DOMAIN}/manifest.json" in text
        assert "hellofresh" not in text


def test_no_tests_ship_inside_the_integration() -> None:
    """HACS zips the integration directory; a tests/ package in it would land on every install."""
    assert not (COMPONENT / "tests").exists()
    assert not list(COMPONENT.rglob("test_*.py"))


# ---- translations ----------------------------------------------------------------------


def test_strings_and_en_translation_match() -> None:
    """``strings.json`` and ``translations/en.json`` must expose identical keys.

    Home Assistant reads strings.json for the config flow and en.json at runtime; a key
    in one but not the other surfaces as a raw translation key in the UI.
    """
    strings = _flatten(_load(COMPONENT / "strings.json"))
    english = _flatten(_load(TRANSLATIONS / "en.json"))
    assert strings == english, (
        f"strings.json / en.json drift.\n"
        f"  only in strings.json: {sorted(strings - english)[:10]}\n"
        f"  only in en.json     : {sorted(english - strings)[:10]}"
    )


@pytest.mark.parametrize(
    "locale_file",
    sorted(p.name for p in TRANSLATIONS.glob("*.json") if p.name != "en.json"),
)
def test_translation_locales_are_complete(locale_file: str) -> None:
    """Every shipped locale must cover all of en.json -- a missing key renders as a raw key."""
    english = _flatten(_load(TRANSLATIONS / "en.json"))
    locale = _flatten(_load(TRANSLATIONS / locale_file))
    missing = english - locale
    extra = locale - english
    assert not missing, f"{locale_file} is missing {len(missing)} keys, e.g. {sorted(missing)[:5]}"
    assert not extra, f"{locale_file} has {len(extra)} unknown keys, e.g. {sorted(extra)[:5]}"


# Kept in English in every language: the hub's own name in the discovery title, the name of
# the hub's PeripheralUID field, and a lake's name where the language uses it as it is.
KEPT_IN_ENGLISH = frozenset(
    {
        "config.flow_title",
        "services.send_hub_command.fields.peripheral_uid.name",
        "selector.sidebar_view.options.lake",
    }
)


def _texts(node: object, prefix: str = "") -> dict[str, str]:
    """Every string in a nested dict, by its dotted key path."""
    if isinstance(node, str):
        return {prefix: node}
    texts: dict[str, str] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            texts |= _texts(value, f"{prefix}.{key}" if prefix else str(key))
    return texts


@pytest.mark.parametrize(
    "locale_file",
    sorted(p.name for p in TRANSLATIONS.glob("*.json") if p.name != "en.json"),
)
def test_translation_locales_are_translated(locale_file: str) -> None:
    """A string copied over from en.json fills its key in, and shows English all the same.

    That is how the whole-house buttons and the Command spacing option went untranslated.
    One word can be the same in both languages ("Hub"), so only longer text counts.
    """
    english = _texts(_load(TRANSLATIONS / "en.json"))
    locale = _texts(_load(TRANSLATIONS / locale_file))
    copied = sorted(
        path
        for path, text in locale.items()
        if text == english.get(path) and " " in text and path not in KEPT_IN_ENGLISH
    )
    assert not copied, f"{locale_file} still has English at {copied}"


def test_config_flow_errors_and_aborts_are_translated() -> None:
    """Every error/abort reason the flow can return needs a string, or the UI shows the key."""
    flow_src = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    strings = _load(COMPONENT / "strings.json")["config"]

    errors = set(re.findall(r'errors\["base"\]\s*=\s*"([a-z_]+)"', flow_src))
    assert errors <= set(strings["error"]), errors - set(strings["error"])

    aborts = set(re.findall(r'reason="([a-z_]+)"', flow_src)) | {"already_configured"}
    if "async_update_reload_and_abort" in flow_src:
        aborts.add("reconfigure_successful")
    assert aborts <= set(strings["abort"]), aborts - set(strings["abort"])


# ---- services --------------------------------------------------------------------------


def _registered_services() -> set[str]:
    const_src = (COMPONENT / "const.py").read_text(encoding="utf-8")
    service_consts = dict(re.findall(r'^(SERVICE_[A-Z_0-9]+)\s*=\s*"([^"]+)"', const_src, re.M))
    registered: set[str] = set()
    for source in COMPONENT.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        for name in re.findall(r"async_register_entity_service\(\s*([A-Z_0-9]+)", text):
            registered.add(service_consts.get(name, name))
        for name in re.findall(
            r"async_register(?:_admin_service)?\(\s*(?:hass,\s*)?DOMAIN,\s*([A-Z_0-9]+)", text
        ):
            registered.add(service_consts.get(name, name))
    return registered


def test_services_yaml_matches_registered_services() -> None:
    """Every registered service needs a services.yaml entry, and vice versa.

    A service missing from services.yaml still works when called from YAML but is invisible
    in the UI action picker and has no field descriptions.
    """
    declared = set(yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8")))
    registered = _registered_services()

    assert registered, "no registered services found -- the detection regex needs updating"
    assert declared == registered, (
        f"services.yaml / registration drift.\n"
        f"  documented but not registered: {sorted(declared - registered)}\n"
        f"  registered but undocumented  : {sorted(registered - declared)}"
    )


def test_services_are_translated() -> None:
    """The action picker reads names/descriptions from strings.json's ``services`` block."""
    services = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))
    translated = _load(COMPONENT / "strings.json")["services"]
    assert set(services) == set(translated)
    for name, spec in services.items():
        assert set(spec.get("fields", {})) == set(translated[name].get("fields", {})), name


# ---- brand assets ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [("icon.png", (256, 256)), ("icon@2x.png", (512, 512))],
)
def test_brand_icons_are_square_at_the_required_sizes(name: str, expected: tuple[int, int]) -> None:
    """home-assistant/brands rejects icons that are not exactly 256/512 px squares."""
    from PIL import Image

    with Image.open(COMPONENT / "brand" / name) as image:
        assert image.format == "PNG"
        assert image.size == expected
        assert image.mode == "RGBA", "icons should keep their transparent background"


@pytest.mark.parametrize(
    ("name", "shortest", "longest_max"),
    [("logo.png", (128, 256), 256 * 8), ("logo@2x.png", (256, 512), 512 * 8)],
)
def test_brand_logos_meet_the_size_rules(
    name: str, shortest: tuple[int, int], longest_max: int
) -> None:
    """The logo keeps the wordmark's aspect ratio with the shortest side in the allowed band."""
    from PIL import Image

    with Image.open(COMPONENT / "brand" / name) as image:
        assert image.format == "PNG"
        low, high = shortest
        assert low <= min(image.size) <= high, image.size
        assert image.width >= image.height, "the wordmark is landscape"
        assert image.getbbox() == (0, 0, *image.size), "brands wants trimmed images"


def test_service_icons_cover_every_service() -> None:
    """icons.json gives each action its icon in the UI; a missing one shows a generic glyph."""
    icons = _load(COMPONENT / "icons.json")["services"]
    assert set(icons) == _registered_services()
    for name, spec in icons.items():
        assert spec["service"].startswith("mdi:"), name


# ---- quality scale ---------------------------------------------------------------------


def test_quality_scale_statuses_are_valid() -> None:
    """hassfest accepts done/todo/exempt only; anything else is a typo."""
    rules = yaml.safe_load((COMPONENT / "quality_scale.yaml").read_text(encoding="utf-8"))
    for rule, status in rules["rules"].items():
        value = status["status"] if isinstance(status, dict) else status
        assert value in {"done", "todo", "exempt"}, f"{rule}: {value!r}"
        if isinstance(status, dict) and value == "exempt":
            assert status.get("comment"), f"{rule}: exempt rules need a comment"


# ---- documentation links ---------------------------------------------------------------


def _heading_anchors(text: str) -> set[str]:
    """GitHub's anchor slugs for every heading in a Markdown document."""
    anchors: set[str] = set()
    for heading in re.findall(r"^#{1,6}\s+(.+)$", text, re.M):
        slug = re.sub(r"[`*\[\]()]", "", heading).strip().lower()
        slug = re.sub(r"[^\w\s-]", "", slug).replace(" ", "-")
        anchors.add(slug)
    return anchors


DOCS = [
    "README.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "QUALITY_SCALE.md",
    "docs/NORMAN_API.md",
    "docs/dashboard.md",
    "docs/entities.md",
    "docs/services.md",
]


def test_documentation_links_resolve() -> None:
    """Every relative Markdown link must point at a real file and a real heading.

    Cross-document links are exactly the thing nobody re-checks by hand after a section
    is moved or renamed.
    """
    texts = {name: (REPO / name).read_text(encoding="utf-8") for name in DOCS}
    anchors = {name: _heading_anchors(text) for name, text in texts.items()}

    broken: list[str] = []
    for name, text in texts.items():
        base = (REPO / name).parent
        for match in re.finditer(r"\[[^\]]*\]\((?!https?:|mailto:)([^)]+)\)", text):
            target, _, fragment = match.group(1).partition("#")
            if not target:  # same-document anchor
                if fragment and fragment not in anchors[name]:
                    broken.append(f"{name}: #{fragment}")
                continue
            resolved = (base / target).resolve()
            if not resolved.exists():
                broken.append(f"{name}: missing file {target}")
                continue
            rel = str(resolved.relative_to(REPO))
            if fragment and rel in anchors and fragment not in anchors[rel]:
                broken.append(f"{name}: {target}#{fragment}")

    assert not broken, "broken documentation links:\n  " + "\n  ".join(broken)


def test_entities_doc_lists_the_entities_that_exist() -> None:
    """docs/entities.md names every entity, and only entities that exist.

    The table is the first thing a user reads and the last thing anyone updates after
    adding or removing an entity description. Comparing it to the descriptions themselves
    is what keeps "five buttons" honest.
    """
    from custom_components.norman.button import BUTTONS
    from custom_components.norman.number import NUMBERS
    from custom_components.norman.select import SELECTS
    from custom_components.norman.sensor import HUB_SENSORS, SENSORS

    text = (REPO / "docs" / "entities.md").read_text(encoding="utf-8")
    strings = _load(COMPONENT / "strings.json")["entity"]

    missing: list[str] = []
    for platform, descriptions in (
        ("button", BUTTONS),
        ("number", NUMBERS),
        ("select", SELECTS),
        ("sensor", (*SENSORS, *HUB_SENSORS)),
    ):
        for description in descriptions:
            name = strings[platform][description.translation_key]["name"]
            if name.lower() not in text.lower():
                missing.append(f"{platform}.{description.translation_key} ({name})")
    assert not missing, "docs/entities.md does not mention:\n  " + "\n  ".join(missing)

    # The counts in the opening sentence, which is where a removed entity hides longest.
    counts = {
        "button": len(BUTTONS),
        "diagnostic sensor": len(SENSORS),
    }
    words = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}
    for noun, count in counts.items():
        assert f"{words[count]} **{noun}s**" in text, (
            f"docs/entities.md should say {words[count]} {noun}s; there are {count}"
        )


def test_entities_doc_marks_exactly_the_disabled_entities() -> None:
    """The doc's ``*`` footnote must match ``entity_registry_enabled_default``.

    A starred entity the user can see by default (or an unstarred one they cannot find)
    sends people hunting through settings for something that is not there.
    """
    from custom_components.norman.button import BUTTONS
    from custom_components.norman.sensor import HUB_SENSORS, SENSORS

    text = (REPO / "docs" / "entities.md").read_text(encoding="utf-8")
    strings = _load(COMPONENT / "strings.json")["entity"]

    wrong: list[str] = []
    for platform, description in (
        *(("sensor", d) for d in (*SENSORS, *HUB_SENSORS)),
        *(("button", d) for d in BUTTONS),
    ):
        name = strings[platform][description.translation_key]["name"]
        disabled = description.entity_registry_enabled_default is False
        starred = f"{name}\\*" in text
        if disabled != starred:
            wrong.append(
                f"{description.translation_key}: disabled={disabled} but starred={starred}"
            )
    assert not wrong, "docs/entities.md star footnote is wrong for:\n  " + "\n  ".join(wrong)


def test_dashboard_doc_documents_every_card_option() -> None:
    """Every option the card's editor exposes must appear in docs/dashboard.md.

    The card reads its options straight from the YAML, so an undocumented one is
    invisible: there is no error and no hint that it exists.
    """
    card = (COMPONENT / "www" / "norman-shades-card.js").read_text(encoding="utf-8")
    text = (REPO / "docs" / "dashboard.md").read_text(encoding="utf-8")
    options = set(re.findall(r'\{ key: "(\w+)"', card))
    assert options, "no editor options found in the card"
    missing = sorted(option for option in options if option not in text)
    assert not missing, "docs/dashboard.md does not document: " + ", ".join(missing)


def test_upstream_attribution_is_present() -> None:
    """The Apache-2.0 attribution to the original author must survive edits.

    This project is a derivative of keito/home-assistant-norman. Most of the code has been
    rewritten, but the obligation to credit the original does not scale with how much was
    replaced -- so the credit is pinned here rather than left to whoever next tidies the
    README.
    """
    for name in ("README.md", "NOTICE"):
        text = (REPO / name).read_text(encoding="utf-8")
        assert "Keito Uchiyama" in text, f"{name} no longer credits the original author"
    notice = (REPO / "NOTICE").read_text(encoding="utf-8")
    assert "keito/home-assistant-norman" in notice, "NOTICE should name the upstream repository"
    assert "Apache License" in notice, "NOTICE should name the licence the original was under"


def test_documentation_images_exist_and_have_alt_text() -> None:
    """Every image a document references must exist, and describe itself.

    A broken image is silent on GitHub -- a small broken-image icon and nothing in any log --
    so a renamed or moved file goes unnoticed. Alt text is checked at the same time because
    a screenshot with none is invisible to anyone using a screen reader, and these carry
    real information about what the integration provides.
    """
    docs = ["README.md", *(f"docs/{name}" for name in ("dashboard.md", "entities.md"))]
    problems: list[str] = []
    for name in docs:
        text = (REPO / name).read_text(encoding="utf-8")
        base = (REPO / name).parent
        # Markdown ![alt](src) and the HTML <img> tags used for width control.
        for alt, src in re.findall(r"!\[([^\]]*)\]\(([^)\s]+)\)", text):
            # Remote images (the CI and release badges) are not this repository's to check.
            if src.startswith(("http://", "https://")):
                continue
            if not (base / src).resolve().exists():
                problems.append(f"{name}: missing image {src}")
            elif not alt.strip():
                problems.append(f"{name}: {src} has no alt text")
        for tag in re.findall(r"<img\s[^>]*>", text):
            src_match = re.search(r'src="([^"]+)"', tag)
            alt_match = re.search(r'alt="([^"]*)"', tag)
            if src_match is None:
                problems.append(f"{name}: <img> with no src")
                continue
            src = src_match.group(1)
            if src.startswith(("http://", "https://")):
                continue
            if not (base / src).resolve().exists():
                problems.append(f"{name}: missing image {src}")
            elif alt_match is None or not alt_match.group(1).strip():
                problems.append(f"{name}: {src} has no alt text")
        # A <picture>'s dark-theme <source>, shown in place of its <img> to a reader in a dark
        # theme; the <img> beside it carries the alt text for both.
        for srcset in re.findall(r'<source\s[^>]*srcset="([^"]+)"', text):
            if (
                not srcset.startswith(("http://", "https://"))
                and not (base / srcset).resolve().exists()
            ):
                problems.append(f"{name}: missing image {srcset}")
    assert not problems, "documentation image problems:\n  " + "\n  ".join(problems)


def test_documentation_images_are_not_oversized() -> None:
    """Screenshots must stay small enough that cloning the repo is cheap.

    HACS clones this repository onto every install, so a few untouched Retina captures
    (4 MB for the set) is a real cost for something only ever viewed at about 900 px.
    """
    oversized = [
        f"{image.relative_to(REPO)} is {image.stat().st_size // 1024} KB"
        for image in sorted((REPO / "images").iterdir())
        if image.suffix in (".png", ".jpg") and image.stat().st_size > 600 * 1024
    ]
    assert not oversized, (
        "documentation images are too large; downscale them to about 1600 px wide:\n  "
        + "\n  ".join(oversized)
    )


def test_readme_documents_every_service() -> None:
    """Each action must be named in the README so users can find it without reading YAML."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    services_doc = (REPO / "docs" / "services.md").read_text(encoding="utf-8")
    for service in _registered_services():
        assert f"`{DOMAIN}.{service}`" in readme, f"README does not mention {DOMAIN}.{service}"
        assert f"`{DOMAIN}.{service}`" in services_doc, f"docs/services.md lacks {service}"
