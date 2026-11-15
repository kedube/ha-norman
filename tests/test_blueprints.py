"""The automation blueprints in blueprints/automation/norman, used as Home Assistant uses them.

Each is installed where an import puts it, set up through ``use_blueprint`` as an automation,
and driven by what it listens for: the integration's ``norman_command_failed`` event, and a
blind's battery falling on the hub.
"""

from __future__ import annotations

import asyncio
import pathlib
import shutil
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.norman.const import DOMAIN, EVENT_COMMAND_FAILED

from .conftest import FakeHub, settle
from .const import UID_LIVING

BLUEPRINTS = pathlib.Path(__file__).resolve().parent.parent / "blueprints" / "automation" / "norman"

# Actions that report what the blueprint handed them, in place of a notification.
REPORT = "norman_test_report"


@pytest.fixture
def installed(hass: HomeAssistant, tmp_path: pathlib.Path) -> pathlib.Path:
    """A configuration directory with the blueprints where importing them puts them."""
    hass.config.config_dir = str(tmp_path)
    folder = tmp_path / "blueprints" / "automation" / "norman"
    folder.mkdir(parents=True)
    for blueprint in BLUEPRINTS.glob("*.yaml"):
        shutil.copy(blueprint, folder / blueprint.name)
    return folder


async def _automate(hass: HomeAssistant, blueprint: str, inputs: dict[str, Any]) -> None:
    assert await async_setup_component(
        hass,
        "automation",
        {"automation": [{"use_blueprint": {"path": f"norman/{blueprint}", "input": inputs}}]},
    )
    await hass.async_block_till_done()
    automations = hass.states.async_entity_ids("automation")
    assert len(automations) == 1, automations
    assert hass.states.get(automations[0]).state == "on", "the blueprint did not set up"


def _reports(hass: HomeAssistant) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    hass.bus.async_listen(REPORT, lambda event: reports.append(dict(event.data)))
    return reports


def _command_failed(device_id: str = "device-1") -> dict[str, Any]:
    """The event the move watchdog fires (coordinator._async_command_failed)."""
    return {
        "device_id": device_id,
        "peripheral_uid": UID_LIVING,
        "name": "Living Drape",
        "attempts": 3,
        "bottom_rail_position": 0,
        "middle_rail_position": 100,
        "louver_position": None,
    }


def test_every_blueprint_is_documented() -> None:
    """Each blueprint is offered in the README, with a link that imports it."""
    readme = (BLUEPRINTS.parent.parent.parent / "README.md").read_text(encoding="utf-8")
    shipped = sorted(path.name for path in BLUEPRINTS.glob("*.yaml"))
    assert shipped == ["battery_low.yaml", "blind_did_not_move.yaml"]
    for name in shipped:
        raw = f"https://github.com/kedube/ha-norman/blob/main/blueprints/automation/norman/{name}"
        assert raw in readme, f"README does not offer {name}"
        assert raw in (BLUEPRINTS / name).read_text(encoding="utf-8"), f"{name}: wrong source_url"


async def test_a_blind_that_did_not_move_runs_the_actions(
    hass: HomeAssistant, installed: pathlib.Path
) -> None:
    """The actions get the blind's name, its device and the number of sends."""
    reports = _reports(hass)
    await _automate(
        hass,
        "blind_did_not_move.yaml",
        {
            "actions": [
                {
                    "event": REPORT,
                    "event_data": {
                        "blind": "{{ blind }}",
                        "device": "{{ device_id }}",
                        "attempts": "{{ attempts }}",
                    },
                }
            ]
        },
    )

    hass.bus.async_fire(EVENT_COMMAND_FAILED, _command_failed())
    await hass.async_block_till_done()

    assert len(reports) == 1
    assert reports[0]["blind"] == "Living Drape"
    assert reports[0]["device"] == "device-1"
    assert int(reports[0]["attempts"]) == 3


async def test_a_blind_left_out_of_the_list_is_let_be(
    hass: HomeAssistant, installed: pathlib.Path
) -> None:
    """With blinds chosen, another blind's failure runs nothing."""
    reports = _reports(hass)
    await _automate(
        hass,
        "blind_did_not_move.yaml",
        {"blinds": ["device-2"], "actions": [{"event": REPORT}]},
    )

    hass.bus.async_fire(EVENT_COMMAND_FAILED, _command_failed("device-1"))
    hass.bus.async_fire(EVENT_COMMAND_FAILED, _command_failed("device-2"))
    await hass.async_block_till_done()

    assert len(reports) == 1


async def test_by_default_a_blind_that_did_not_move_leaves_a_notification(
    hass: HomeAssistant, installed: pathlib.Path
) -> None:
    """Left as it comes, the blueprint shows a notification in Home Assistant, one per blind."""
    assert await async_setup_component(hass, "persistent_notification", {})
    await _automate(hass, "blind_did_not_move.yaml", {})

    hass.bus.async_fire(EVENT_COMMAND_FAILED, _command_failed())
    await hass.async_block_till_done()

    shown = persistent_notification._async_get_or_create_notifications(hass)
    notification = shown["norman_command_failed_device-1"]
    assert notification["title"] == "Living Drape did not move"
    assert "3" in notification["message"] and "battery" in notification["message"]


async def test_a_battery_falling_below_the_level_runs_the_actions(
    hass: HomeAssistant,
    installed: pathlib.Path,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """A blind's battery read off the hub below the level runs the actions, once."""
    battery = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{UID_LIVING}_battery_level"
    )
    assert battery
    reports = _reports(hass)
    await _automate(
        hass,
        "battery_low.yaml",
        {
            "batteries": [battery],
            "level": 20,
            "actions": [
                {
                    "event": REPORT,
                    "event_data": {
                        "blind": "{{ blind }}",
                        "battery": "{{ battery }}",
                        "sensor": "{{ sensor }}",
                    },
                }
            ],
        },
    )

    fake_hub.peripheral_status(UID_LIVING)["BatteryVoltage"] = 30
    await notifications.put({"PeripheralList": [UID_LIVING]})
    await settle(hass)
    assert reports == [], "30% is above the level"

    fake_hub.peripheral_status(UID_LIVING)["BatteryVoltage"] = 12
    await notifications.put({"PeripheralList": [UID_LIVING]})
    await settle(hass)
    fake_hub.peripheral_status(UID_LIVING)["BatteryVoltage"] = 11
    await notifications.put({"PeripheralList": [UID_LIVING]})
    await settle(hass)

    assert len(reports) == 1, "a battery already below the level does not alert again"
    assert reports[0]["blind"] == "Living Drape"
    assert int(reports[0]["battery"]) == 12
    assert reports[0]["sensor"] == battery


async def test_by_default_a_low_battery_leaves_a_notification(
    hass: HomeAssistant,
    installed: pathlib.Path,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Left as it comes, the blueprint shows a notification naming the blind and its level."""
    assert await async_setup_component(hass, "persistent_notification", {})
    battery = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{UID_LIVING}_battery_level"
    )
    await _automate(hass, "battery_low.yaml", {"batteries": [battery]})

    fake_hub.peripheral_status(UID_LIVING)["BatteryVoltage"] = 9
    await notifications.put({"PeripheralList": [UID_LIVING]})
    await settle(hass)

    shown = persistent_notification._async_get_or_create_notifications(hass)
    notification = shown[f"norman_battery_low_{battery}"]
    assert notification["title"] == "Living Drape's battery is low"
    assert "9%" in notification["message"]
