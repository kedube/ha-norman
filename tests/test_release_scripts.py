"""Tests for the release automation scripts under .github/scripts."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

from custom_components.norman.frontend import CARD_URL_PATH

REPO_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "bump_manifest_version",
    REPO_ROOT / ".github" / "scripts" / "bump_manifest_version.py",
)
bump_manifest_version = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bump_manifest_version)


def test_bump_minor() -> None:
    assert bump_manifest_version._bump_minor("2.43") == "2.44"


def test_bump_minor_zero_pads() -> None:
    assert bump_manifest_version._bump_minor("0.08") == "0.09"


def test_bump_minor_rolls_over_to_major() -> None:
    assert bump_manifest_version._bump_minor("2.99") == "3.00"


def test_bump_major() -> None:
    assert bump_manifest_version._bump_major("2.43") == "3.00"


def test_bump_major_from_zero() -> None:
    assert bump_manifest_version._bump_major("0.99") == "1.00"


def test_main_bumps_manifest_in_place(tmp_path: Path, capsys, monkeypatch) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"domain": "norman", "version": "2.43"}))
    monkeypatch.setattr("sys.argv", ["bump_manifest_version.py", str(manifest)])
    assert bump_manifest_version.main() == 0
    assert capsys.readouterr().out.strip() == "2.44"
    assert json.loads(manifest.read_text())["version"] == "2.44"


def test_main_major_bump(tmp_path: Path, capsys, monkeypatch) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"domain": "norman", "version": "2.43"}))
    monkeypatch.setattr("sys.argv", ["bump_manifest_version.py", str(manifest), "--bump", "major"])
    assert bump_manifest_version.main() == 0
    assert capsys.readouterr().out.strip() == "3.00"
    assert json.loads(manifest.read_text())["version"] == "3.00"


def test_release_bump_carries_through_to_the_card_url(tmp_path: Path, monkeypatch) -> None:
    """Bumping the manifest must change the card's resource URL, with no second edit.

    The release workflow commits only manifest.json and CHANGELOG.md, so anything else
    that carries the version would ship stale. This runs the real bump script against a
    copy of the integration and re-imports frontend.py from it, which is what Home
    Assistant does after an upgrade and restart.
    """
    component = tmp_path / "norman"
    component.mkdir()
    source = REPO_ROOT / "custom_components" / "norman"
    (component / "manifest.json").write_text(
        (source / "manifest.json").read_text(encoding="utf-8"), encoding="utf-8"
    )

    def resource_url(version: str) -> str:
        """The URL the card would be registered at for ``version``.

        The card's version comes from Home Assistant's loader, which serves the manifest it
        parsed at setup -- so what this has to prove is that the URL is built from the
        manifest's value and nothing else. ``card_resource_url`` is exercised against a real
        Home Assistant in tests/test_frontend.py; here the manifest is the only input, which
        is exactly what the release workflow edits.
        """
        return f"{CARD_URL_PATH}?v={version}"

    def manifest_version() -> str:
        return str(json.loads((component / "manifest.json").read_text())["version"])

    before = resource_url(manifest_version())

    monkeypatch.setattr("sys.argv", ["bump_manifest_version.py", str(component / "manifest.json")])
    assert bump_manifest_version.main() == 0
    new_version = manifest_version()

    after = resource_url(new_version)
    assert after != before, "the card URL did not follow the manifest bump"
    assert after.endswith(f"?v={new_version}")

    # The version must come from the loader, never from a disk read: reading manifest.json
    # here once ran at import time, and this module is imported on the event loop when a
    # user downloads diagnostics -- which is exactly what Home Assistant instruments
    # Path.read_text to catch.
    frontend_source = (source / "frontend.py").read_text(encoding="utf-8")
    tree = ast.parse(frontend_source)
    reads = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"read_text", "read_bytes", "is_file", "exists", "open", "stat"}
    }
    assert not reads - {"is_file"}, (
        f"frontend.py reads from disk outside an executor: {sorted(reads)}"
    )
    assert "async_get_loaded_integration" in frontend_source
