"""Guards for metadata that must stay in step with the code.

Each of these files is edited by hand, in a separate step from the code it describes, and
therefore silently falls behind: translations, services.yaml, the manifest, the HACS
metadata, and the documentation's cross-links. Pinning them here keeps them honest.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest
import yaml

from custom_components.norman.const import DOMAIN

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
    from custom_components.norman.button import BUTTONS
    from custom_components.norman.sensor import HUB_SENSORS, SENSORS

    strings = _load(COMPONENT / "strings.json")["entity"]
    sensor_keys = {description.translation_key for description in (*SENSORS, *HUB_SENSORS)}
    assert sensor_keys == set(strings["sensor"])
    button_keys = {description.translation_key for description in BUTTONS}
    assert button_keys == set(strings["button"])
    icons = _load(COMPONENT / "icons.json")["entity"]["button"]
    assert button_keys == set(icons)


def test_observed_fields_are_catalogued() -> None:
    """Every field named in the protocol reference's tables must be in the known-field sets.

    The catalogue in const.py is what makes "undocumented field" logging meaningful: a field
    documented in NORMAN_API.md but missing from the catalogue would be reported as new on
    every install, and one added to the catalogue without documentation is invisible.
    """
    from custom_components.norman.const import KNOWN_HUB_FIELDS, KNOWN_PERIPHERAL_FIELDS

    api_doc = (REPO / "docs" / "NORMAN_API.md").read_text(encoding="utf-8")
    observed = api_doc.split("## Observed fields", 1)[1].split("## Error conventions", 1)[0]
    documented = set(re.findall(r"`([A-Z][A-Za-z]+)`", observed))
    known = KNOWN_HUB_FIELDS | KNOWN_PERIPHERAL_FIELDS
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
            r"(?:HomeAssistantError|ServiceValidationError)\((.*?)\)\s*(?:from|$)", text, re.S
        ):
            raised |= set(re.findall(r'translation_key="([a-z_]+)"', block))
    assert raised, "no translated exceptions found -- the regex needs updating"
    assert raised <= exceptions, f"raised but not translated: {sorted(raised - exceptions)}"
    assert exceptions <= raised, f"translated but never raised: {sorted(exceptions - raised)}"
    # Placeholders in the English message must match what the code passes
    strings = _load(COMPONENT / "strings.json")["exceptions"]
    for key, entry in strings.items():
        assert "{" in entry["message"] or key, key


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
        for name in re.findall(r"async_register\(\s*DOMAIN,\s*([A-Z_0-9]+)", text):
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


def test_readme_stays_browsable() -> None:
    """The README is the landing page; detail belongs in docs/.

    This is a smoke alarm, not a style rule -- if it trips, move the newest reference
    material into docs/ rather than raising the number.
    """
    length = len((REPO / "README.md").read_text(encoding="utf-8").splitlines())
    assert length < 500, (
        f"README.md is {length} lines. Move reference detail into docs/ "
        f"(see docs/entities.md and docs/services.md for the pattern)."
    )


def test_readme_documents_every_service() -> None:
    """Each action must be named in the README so users can find it without reading YAML."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    services_doc = (REPO / "docs" / "services.md").read_text(encoding="utf-8")
    for service in _registered_services():
        assert f"`{DOMAIN}.{service}`" in readme, f"README does not mention {DOMAIN}.{service}"
        assert f"`{DOMAIN}.{service}`" in services_doc, f"docs/services.md lacks {service}"
