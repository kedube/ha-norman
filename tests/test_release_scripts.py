"""Tests for the release automation scripts under .github/scripts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

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
    for name in ("manifest.json", "frontend.py", "const.py"):
        (component / name).write_text((source / name).read_text(encoding="utf-8"), encoding="utf-8")

    def resource_url() -> str:
        """Evaluate the copy's frontend.py and read the URL it would register.

        The constant is computed at import time from the manifest sitting next to it, so
        it has to be re-evaluated (not just re-read) to see the effect of a bump. The copy
        is not a package, so the one relative import is substituted out.
        """
        source_text = (component / "frontend.py").read_text(encoding="utf-8")
        namespace: dict[str, object] = {"__file__": str(component / "frontend.py")}
        exec(  # noqa: S102 - our own source, executed to observe its import-time constants
            source_text.replace("from .const import DOMAIN", 'DOMAIN = "norman"'),
            namespace,
        )
        return str(namespace["CARD_RESOURCE_URL"])

    before = resource_url()
    assert before.endswith(f"?v={json.loads((component / 'manifest.json').read_text())['version']}")

    monkeypatch.setattr("sys.argv", ["bump_manifest_version.py", str(component / "manifest.json")])
    assert bump_manifest_version.main() == 0
    new_version = json.loads((component / "manifest.json").read_text())["version"]

    after = resource_url()
    assert after != before, "the card URL did not follow the manifest bump"
    assert after.endswith(f"?v={new_version}")
