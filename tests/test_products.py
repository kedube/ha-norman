"""Every product in the Norman app's module table, and how each one is driven.

The table comes from the ShadeAuto app (0.8.33): six ModuleTypes, with the ModuleDetail
deciding the product where one type covers several. Only the two cellular shades are
verified on real hardware, issue #2 added a roller shade and a SmartDrape, and issue #6 a
PerfectSheer's vanes; the rest are pinned to what the app does with them. See const.py,
"Cover types".
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_CURRENT_TILT_POSITION,
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntityFeature,
    CoverState,
)
from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_CLOSE_COVER,
    SERVICE_CLOSE_COVER_TILT,
    SERVICE_OPEN_COVER,
    SERVICE_OPEN_COVER_TILT,
    SERVICE_SET_COVER_POSITION,
    SERVICE_SET_COVER_TILT_POSITION,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceNotSupported
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.norman.const import (
    COVER_TYPE_SHEER,
    DOMAIN,
    EVENT_COMMAND_FAILED,
    MOVE_ATTEMPTS,
)
from custom_components.norman.coordinator import NormanCoordinator, rails_to_send

from .conftest import FakeHub, cover_entity_id
from .const import (
    EVERY_NEW_PRODUCT,
    UID_BEDROOM,
    UID_LIVING,
    UID_ROLLER,
    UID_ROLLER_MRS2,
    UID_ROMAN,
    UID_SHEER,
    UID_SHUTTER,
    UID_SMARTDRAPE,
    UID_TDBU,
)

POSITION = (
    CoverEntityFeature.OPEN
    | CoverEntityFeature.CLOSE
    | CoverEntityFeature.SET_POSITION
    | CoverEntityFeature.STOP
)
POSITION_AND_TILT = (
    POSITION
    | CoverEntityFeature.OPEN_TILT
    | CoverEntityFeature.CLOSE_TILT
    | CoverEntityFeature.SET_TILT_POSITION
    | CoverEntityFeature.STOP_TILT
)
LOUVERS = (
    CoverEntityFeature.OPEN
    | CoverEntityFeature.CLOSE
    | CoverEntityFeature.OPEN_TILT
    | CoverEntityFeature.CLOSE_TILT
    | CoverEntityFeature.SET_TILT_POSITION
)
BOTTOM = "bottom_rail_position"
MIDDLE = "middle_rail_position"


def _entity_id(hass: HomeAssistant, domain: str, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)


def _model(hass: HomeAssistant, entry: MockConfigEntry, uid: int) -> str | None:
    for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id):
        if (DOMAIN, str(uid)) in device.identifiers:
            return device.model
    raise KeyError(uid)


async def _call(hass: HomeAssistant, uid: int, service: str, **data: Any) -> None:
    await hass.services.async_call(
        COVER_DOMAIN, service, {ATTR_ENTITY_ID: cover_entity_id(hass, uid), **data}, blocking=True
    )


async def _nudge(hass: HomeAssistant, uid: int, service: str, step: int) -> None:
    await hass.services.async_call(
        DOMAIN, service, {ATTR_ENTITY_ID: cover_entity_id(hass, uid), "step": step}, blocking=True
    )


def _rails_sent(fake_hub: FakeHub, uid: int) -> tuple[int, int]:
    call = [c for c in fake_hub.control_calls if c.get("PeripheralUID") == uid][-1]
    return call["BottomRailPosition"], call["MiddleRailPosition"]


def _louvers_sent(fake_hub: FakeHub, uid: int) -> list[dict[str, Any]]:
    return [c for c in fake_hub.control_calls if c.get("PeripheralUID") == uid and "Position" in c]


async def _show(hass: HomeAssistant, entry: MockConfigEntry, fake_hub: FakeHub, **fields: Any):
    """Have the hub report ``fields`` for a peripheral, and return its cover's new state."""
    uid = fields.pop("uid")
    fake_hub.peripheral_status(uid).update(fields)
    await entry.runtime_data.async_refresh()
    return hass.states.get(cover_entity_id(hass, uid))


# ---- what each product gets ------------------------------------------------------------


@pytest.mark.parametrize(
    ("uid", "device_class", "features", "sliders", "middle_cover", "model"),
    [
        (
            UID_LIVING,
            "blind",
            POSITION_AND_TILT,
            {BOTTOM, MIDDLE},
            True,
            "Cellular Shade (dual rail)",
        ),
        (UID_BEDROOM, "shade", POSITION, {BOTTOM}, False, "Cellular Shade"),
        (UID_TDBU, "blind", POSITION_AND_TILT, {BOTTOM, MIDDLE}, True, "Cellular Shade"),
        (UID_ROLLER, "shade", POSITION, {BOTTOM}, False, "Roller Shade"),
        (UID_ROMAN, "shade", POSITION, {BOTTOM}, False, "Roman Shade"),
        (UID_ROLLER_MRS2, "shade", POSITION, {BOTTOM}, False, "Roller Shade"),
        (UID_SHEER, "shade", POSITION_AND_TILT, {BOTTOM}, False, "PerfectSheer"),
        (UID_SMARTDRAPE, "curtain", POSITION_AND_TILT, {BOTTOM}, False, "SmartDrape"),
        (UID_SHUTTER, "shutter", LOUVERS, set(), False, "Shutter"),
    ],
    ids=["dual", "cellular", "tdbu", "roller", "roman", "mrs2", "perfectsheer", "drape", "shutter"],
)
async def test_every_product_gets_the_entities_the_app_gives_it(
    hass: HomeAssistant,
    init_with_every_product: MockConfigEntry,
    uid: int,
    device_class: str,
    features: int,
    sliders: set[str],
    middle_cover: bool,
    model: str,
) -> None:
    """A slider per control the app shows, a device class per product, and its app name.

    Only a two-rail shade has a Middle rail cover and slider: a PerfectSheer's and a
    SmartDrape's second value is its vanes, the cover's tilt, and a Shutter has no rails.
    """
    state = hass.states.get(cover_entity_id(hass, uid))
    assert state.attributes[ATTR_DEVICE_CLASS] == device_class
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == features
    assert {k for k in (BOTTOM, MIDDLE) if _entity_id(hass, "number", f"{uid}_{k}")} == sliders
    assert bool(_entity_id(hass, "cover", f"{uid}_middle")) is middle_cover
    assert _model(hass, init_with_every_product, uid) == model


async def test_upgrading_drops_the_entities_a_type_no_longer_has(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub, notifications
) -> None:
    """The two-rail fallback's extra entities go once a product is mapped.

    Unmapped, every one of these was driven as two-rail and given a Middle rail cover and
    two sliders. Left in the registry they would sit on the device page as "no longer
    provided", and the dashboard card, which reads the registry, would go on drawing a
    second fabric -- or, for a Shutter, rails it does not have.
    """
    registry = er.async_get(hass)
    mock_config_entry.add_to_hass(hass)
    stale = [
        registry.async_get_or_create(
            domain, DOMAIN, unique_id, config_entry=mock_config_entry
        ).entity_id
        for domain, unique_id in (
            ("cover", f"{UID_ROLLER}_middle"),
            ("number", f"{UID_ROLLER}_{MIDDLE}"),
            ("cover", f"{UID_SMARTDRAPE}_middle"),
            ("number", f"{UID_SMARTDRAPE}_{MIDDLE}"),
            ("cover", f"{UID_SHUTTER}_middle"),
            ("number", f"{UID_SHUTTER}_{BOTTOM}"),
            ("number", f"{UID_SHUTTER}_{MIDDLE}"),
        )
    ]
    for device, status in EVERY_NEW_PRODUCT:
        fake_hub.add_blind(device, status)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert [entity_id for entity_id in stale if registry.async_get(entity_id)] == []
    assert _entity_id(hass, "cover", f"{UID_LIVING}_middle"), "a two-rail shade keeps its own"
    assert _entity_id(hass, "number", f"{UID_TDBU}_{MIDDLE}")


async def test_another_hubs_entity_is_left_alone(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_hub: FakeHub, notifications
) -> None:
    """The clean-up only touches this entry's own registry entries."""
    registry = er.async_get(hass)
    other = MockConfigEntry(domain=DOMAIN, entry_id="another-hub")
    other.add_to_hass(hass)
    theirs = registry.async_get_or_create(
        "cover", DOMAIN, f"{UID_ROLLER}_middle", config_entry=other
    ).entity_id
    mock_config_entry.add_to_hass(hass)
    for device, status in EVERY_NEW_PRODUCT:
        fake_hub.add_blind(device, status)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(theirs) is not None


# ---- SmartDrape: seven vane stops ------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "tilt"),
    [(0, 0), (17, 33), (33, 67), (50, 100), (66, 67), (83, 33), (100, 0), (40, 67)],
)
async def test_smartdrape_vanes_read_as_how_open_they_are(
    hass: HomeAssistant,
    init_with_every_product: MockConfigEntry,
    fake_hub: FakeHub,
    raw: int,
    tilt: int,
) -> None:
    """50 is fully open and both ends closed, so either end reads 0.

    A value between stops (40) reads as the nearest one. The app reads such a value as its
    last stop; the nearest is kinder to a blind still turning its vanes.
    """
    state = await _show(
        hass,
        init_with_every_product,
        fake_hub,
        uid=UID_SMARTDRAPE,
        MiddleRailPosition=raw,
        TargetMiddleRailPosition=raw,
    )
    assert state.attributes[ATTR_CURRENT_TILT_POSITION] == tilt
    assert state.attributes["target_tilt"] == tilt


async def test_smartdrape_reports_the_side_it_stacks_to(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry
) -> None:
    """The device list's MSDStackType, for the dashboard card to draw the drape gathering there."""
    state = hass.states.get(cover_entity_id(hass, UID_SMARTDRAPE))
    assert state.attributes["stack"] == "left"


@pytest.mark.parametrize(
    ("service", "data", "vanes"),
    [
        (SERVICE_OPEN_COVER_TILT, {}, 50),
        (SERVICE_CLOSE_COVER_TILT, {}, 100),
        (SERVICE_SET_COVER_TILT_POSITION, {ATTR_TILT_POSITION: 100}, 50),
        (SERVICE_SET_COVER_TILT_POSITION, {ATTR_TILT_POSITION: 60}, 66),
        (SERVICE_SET_COVER_TILT_POSITION, {ATTR_TILT_POSITION: 40}, 83),
        (SERVICE_SET_COVER_TILT_POSITION, {ATTR_TILT_POSITION: 0}, 100),
    ],
)
async def test_smartdrape_vanes_are_sent_as_the_apps_stops(
    hass: HomeAssistant,
    init_with_every_product: MockConfigEntry,
    fake_hub: FakeHub,
    service: str,
    data: dict[str, Any],
    vanes: int,
) -> None:
    """Only the seven values the app sends go out; opening means 50, not 100.

    Sent as a plain 0-100 tilt, "open tilt" went to 100 -- which on a SmartDrape closes the
    vanes the other way.
    """
    fake_hub.set_position(UID_SMARTDRAPE, bottom=60, middle=0)
    await init_with_every_product.runtime_data.async_refresh()

    await _call(hass, UID_SMARTDRAPE, service, **data)

    assert _rails_sent(fake_hub, UID_SMARTDRAPE) == (60, vanes)


@pytest.mark.parametrize(
    ("service", "data", "expected"),
    [
        # Driven as a two-rail shade these were (100, 100), (20, 20) and (0, 0).
        (SERVICE_OPEN_COVER, {}, (100, 33)),
        (SERVICE_SET_COVER_TILT_POSITION, {ATTR_TILT_POSITION: 20}, (60, 83)),
        (SERVICE_CLOSE_COVER_TILT, {}, (60, 100)),
    ],
)
async def test_smartdrape_draw_and_vanes_do_not_carry_each_other(
    hass: HomeAssistant,
    init_with_every_product: MockConfigEntry,
    fake_hub: FakeHub,
    service: str,
    data: dict[str, Any],
    expected: tuple[int, int],
) -> None:
    """A shade's rails cannot cross, so one pushed past the other carries it; a drape's can."""
    fake_hub.set_position(UID_SMARTDRAPE, bottom=60, middle=33)
    await init_with_every_product.runtime_data.async_refresh()

    await _call(hass, UID_SMARTDRAPE, service, **data)

    assert _rails_sent(fake_hub, UID_SMARTDRAPE) == expected


@pytest.mark.parametrize(("vanes", "step", "sent"), [(50, -10, 66), (100, 10, 83), (50, 10, 50)])
async def test_smartdrape_vane_nudges_move_at_least_one_stop(
    hass: HomeAssistant,
    init_with_every_product: MockConfigEntry,
    fake_hub: FakeHub,
    vanes: int,
    step: int,
    sent: int,
) -> None:
    """A small nudge still moves a stop; the stops are a third apart, not a tenth."""
    fake_hub.set_position(UID_SMARTDRAPE, bottom=0, middle=vanes)
    await init_with_every_product.runtime_data.async_refresh()

    await _nudge(hass, UID_SMARTDRAPE, "nudge_tilt", step)

    assert _rails_sent(fake_hub, UID_SMARTDRAPE) == (0, sent)


# ---- PerfectSheer: the shade and its vanes -----------------------------------------------


async def test_perfectsheer_vanes_are_the_tilt(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry
) -> None:
    """The middle rail is how open the vanes are, 0 closed to 100 open."""
    state = hass.states.get(cover_entity_id(hass, UID_SHEER))
    assert state.attributes[ATTR_CURRENT_POSITION] == 0
    assert state.attributes[ATTR_CURRENT_TILT_POSITION] == 40


@pytest.mark.parametrize(
    ("rails", "service", "data", "sent"),
    [
        # Down, the vanes tilt on their own and keep their tilt as the shade closes.
        ((0, 40), SERVICE_SET_COVER_TILT_POSITION, {ATTR_TILT_POSITION: 70}, (0, 70)),
        ((0, 40), SERVICE_CLOSE_COVER, {}, (0, 40)),
        # Raising the shade closes them, as the hub would.
        ((0, 40), SERVICE_OPEN_COVER, {}, (100, 0)),
        ((0, 40), SERVICE_SET_COVER_POSITION, {ATTR_POSITION: 50}, (50, 0)),
        # Raised, opening them lowers the shade first; sent as (60, 20), the hub drops the tilt.
        ((60, 0), SERVICE_SET_COVER_TILT_POSITION, {ATTR_TILT_POSITION: 20}, (0, 20)),
        ((60, 0), SERVICE_OPEN_COVER_TILT, {}, (0, 100)),
        # Closing them, as they already are, leaves the shade where it is.
        ((60, 0), SERVICE_CLOSE_COVER_TILT, {}, (60, 0)),
    ],
)
async def test_perfectsheer_vanes_open_only_with_the_shade_down(
    hass: HomeAssistant,
    init_with_every_product: MockConfigEntry,
    fake_hub: FakeHub,
    rails: tuple[int, int],
    service: str,
    data: dict[str, Any],
    sent: tuple[int, int],
) -> None:
    """The hub keeps a vane target only while the shade's is 0 (issue #6)."""
    fake_hub.set_position(UID_SHEER, bottom=rails[0], middle=rails[1])
    await init_with_every_product.runtime_data.async_refresh()

    await _call(hass, UID_SHEER, service, **data)

    assert _rails_sent(fake_hub, UID_SHEER) == sent


async def test_perfectsheer_tilt_nudge_on_a_raised_shade_lowers_it(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A nudge that opens the vanes is a tilt like any other."""
    fake_hub.set_position(UID_SHEER, bottom=60, middle=0)
    await init_with_every_product.runtime_data.async_refresh()

    await _nudge(hass, UID_SHEER, "nudge_tilt", 10)

    assert _rails_sent(fake_hub, UID_SHEER) == (0, 10)


async def test_perfectsheer_closed_right_after_a_raise_keeps_its_vanes_closed(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The raise closed the vanes, so the shade comes back down with them closed, not at 40.

    Inside the refresh debouncer's cooldown the hub's target in hand is still the one from
    before the raise, so the close fills the vanes in from the raise's own record
    (``async_note_move``). The raise has to record them closed for that to match the hub.
    """
    await _call(hass, UID_SHEER, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 50})
    await _call(hass, UID_SHEER, SERVICE_CLOSE_COVER)

    assert _rails_sent(fake_hub, UID_SHEER) == (0, 0)


@pytest.mark.parametrize(
    ("heading", "bottom", "middle", "sent"),
    [
        ((60, 0), None, 40, (0, 40)),
        ((0, 40), 100, None, (100, 0)),
        ((0, 40), 0, None, (0, 40)),
        ((60, 0), None, 0, (60, 0)),
        # Both asked, as a scene does: the shade's position wins, as it does at the hub.
        ((0, 0), 50, 100, (50, 0)),
        ((50, 0), 0, 100, (0, 100)),
    ],
)
def test_perfectsheer_is_never_sent_open_vanes_on_a_raised_shade(
    heading: tuple[int, int], bottom: int | None, middle: int | None, sent: tuple[int, int]
) -> None:
    """Every move works out its pair here: the cover, its slider, a room's, and a scene."""
    assert rails_to_send(COVER_TYPE_SHEER, heading, bottom, middle) == sent


# ---- Shutter: louvers ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("position", "tilt", "state"),
    [
        (7, 0, CoverState.CLOSED),
        (6, 25, CoverState.OPEN),
        (4, 75, CoverState.OPEN),
        (3, 100, CoverState.OPEN),
        (2, 75, CoverState.OPEN),
        (0, 25, CoverState.OPEN),
    ],
)
async def test_shutter_louvers_read_as_how_open_they_are(
    hass: HomeAssistant,
    init_with_every_product: MockConfigEntry,
    fake_hub: FakeHub,
    position: int,
    tilt: int,
    state: str,
) -> None:
    """7 is shut, 3 horizontal; below 3 the louvers turn the other way and close again.

    Position 0, as far as they turn that way, still lets light in, so it is not "closed".
    """
    shown = await _show(
        hass,
        init_with_every_product,
        fake_hub,
        uid=UID_SHUTTER,
        Position=position,
        TargetPosition=position,
    )
    assert shown.state == state
    assert shown.attributes[ATTR_CURRENT_TILT_POSITION] == tilt
    assert shown.attributes["target_tilt"] == tilt
    assert shown.attributes["louver_position"] == position
    assert ATTR_CURRENT_POSITION not in shown.attributes


async def test_shutter_is_named_for_its_louvers(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry
) -> None:
    """Not "Bottom rail": a Shutter has none."""
    state = hass.states.get(cover_entity_id(hass, UID_SHUTTER))
    assert state.attributes["friendly_name"] == "Study Shutter Louvers"
    assert state.attributes[ATTR_DEVICE_CLASS] == CoverDeviceClass.SHUTTER


@pytest.mark.parametrize(
    ("service", "data", "position"),
    [
        (SERVICE_OPEN_COVER, {}, 3),
        (SERVICE_CLOSE_COVER, {}, 7),
        (SERVICE_OPEN_COVER_TILT, {}, 3),
        (SERVICE_CLOSE_COVER_TILT, {}, 7),
        (SERVICE_SET_COVER_TILT_POSITION, {ATTR_TILT_POSITION: 50}, 5),
        (SERVICE_SET_COVER_TILT_POSITION, {ATTR_TILT_POSITION: 60}, 5),
        (SERVICE_SET_COVER_TILT_POSITION, {ATTR_TILT_POSITION: 100}, 3),
        (SERVICE_SET_COVER_TILT_POSITION, {ATTR_TILT_POSITION: 0}, 7),
    ],
)
async def test_shutter_commands_send_the_louver_position(
    hass: HomeAssistant,
    init_with_every_product: MockConfigEntry,
    fake_hub: FakeHub,
    service: str,
    data: dict[str, Any],
    position: int,
) -> None:
    """A Shutter is sent ``Position`` alone, as the app does -- never rail fields."""
    await _call(hass, UID_SHUTTER, service, **data)

    sent = _louvers_sent(fake_hub, UID_SHUTTER)
    assert sent[-1]["Position"] == position
    assert "BottomRailPosition" not in sent[-1]
    assert "MiddleRailPosition" not in sent[-1]


async def test_a_shutter_has_no_position_to_set(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry
) -> None:
    """Set position is not offered: the louvers' opening is the tilt."""
    with pytest.raises(ServiceNotSupported):
        await _call(hass, UID_SHUTTER, SERVICE_SET_COVER_POSITION, **{ATTR_POSITION: 50})


@pytest.mark.parametrize(
    ("service", "step", "position"),
    [("nudge_tilt", 10, 6), ("nudge_tilt", -10, 7), ("nudge_position", 50, 5)],
)
async def test_shutter_nudges_turn_the_louvers(
    hass: HomeAssistant,
    init_with_every_product: MockConfigEntry,
    fake_hub: FakeHub,
    service: str,
    step: int,
    position: int,
) -> None:
    """A nudge moves at least one step, and nudge_position turns the louvers too."""
    await _nudge(hass, UID_SHUTTER, service, step)

    assert _louvers_sent(fake_hub, UID_SHUTTER)[-1]["Position"] == position


async def test_louvers_turning_open_read_as_opening(
    hass: HomeAssistant,
    init_with_every_product: MockConfigEntry,
    fake_hub: FakeHub,
) -> None:
    """Shut (7) and heading for horizontal (3): the Shutter is opening."""
    fake_hub.peripheral_status(UID_SHUTTER)["TargetPosition"] = 3
    await init_with_every_product.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(cover_entity_id(hass, UID_SHUTTER)).state == CoverState.OPENING


async def test_quick_louver_nudges_add_up(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Three quick nudges from shut turn the louvers three steps, as three rail nudges move three.

    Each starts where the one before sends them. Read from the hub's target, the second and
    third saw the same stale value inside the refresh cooldown, and sent 6, 5, 5.
    """
    orig = fake_hub._control

    async def _hub(method, url, data):  # noqa: ANN001
        body = json.loads(data) if isinstance(data, str | bytes) else data
        if body.get("PeripheralUID") == UID_SHUTTER and "Position" in body:
            # Stored as the target on accept, as the hub stores a rail's.
            fake_hub.peripheral_status(UID_SHUTTER)["TargetPosition"] = body["Position"]
        return await orig(method, url, data)

    with patch.object(fake_hub, "_control", _hub):
        fake_hub.mock.clear_requests()
        fake_hub._register()
        for _ in range(3):
            await _nudge(hass, UID_SHUTTER, "nudge_tilt", 25)

    assert [c["Position"] for c in _louvers_sent(fake_hub, UID_SHUTTER)] == [6, 5, 4]
    init_with_every_product.runtime_data.async_supersede()


async def test_a_busy_hub_is_retried_for_louvers_too(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Error 2 is retried for a Shutter the way it is for a rail move."""
    fake_hub.control_responses = [{"Error": 2}, {"Error": 0}]
    with patch("custom_components.norman.api.HUB_BUSY_RETRY_DELAY", 0):
        await _call(hass, UID_SHUTTER, SERVICE_OPEN_COVER)

    assert [c["Position"] for c in _louvers_sent(fake_hub, UID_SHUTTER)] == [3, 3]


async def _watch_done(coordinator: NormanCoordinator, uid: int) -> None:
    if task := coordinator._move_watchers.get(uid):
        await task
    await coordinator.hass.async_block_till_done()


async def test_shutter_watchdog_resends_louvers_that_never_turned(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The move watchdog judges a Shutter by its Position, and resends Position."""
    coordinator: NormanCoordinator = init_with_every_product.runtime_data
    events = async_capture_events(hass, EVENT_COMMAND_FAILED)
    with (
        patch("custom_components.norman.coordinator.MOVE_TIMEOUT", 0),
        patch("custom_components.norman.coordinator.MOVE_REPORT_WAIT", 0),
    ):
        await _call(hass, UID_SHUTTER, SERVICE_OPEN_COVER)
        await _watch_done(coordinator, UID_SHUTTER)

    assert [c["Position"] for c in _louvers_sent(fake_hub, UID_SHUTTER)] == [3] * MOVE_ATTEMPTS
    # The event says where the louvers were sent, not a rail a Shutter does not have.
    (event,) = events
    assert event.data["louver_position"] == 3
    assert event.data["bottom_rail_position"] is None


async def test_shutter_watchdog_is_quiet_when_the_louvers_turn(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Louvers that reach the Position get no status request and no resend."""
    orig = fake_hub._control

    async def _turn(method, url, data):  # noqa: ANN001
        body = json.loads(data) if isinstance(data, str | bytes) else data
        if "Position" in body:
            fake_hub.peripheral_status(UID_SHUTTER).update(
                Position=body["Position"], TargetPosition=body["Position"]
            )
        return await orig(method, url, data)

    with (
        patch.object(fake_hub, "_control", _turn),
        patch("custom_components.norman.coordinator.MOVE_TIMEOUT", 0),
        patch("custom_components.norman.coordinator.MOVE_REPORT_WAIT", 0),
    ):
        fake_hub.mock.clear_requests()
        fake_hub._register()
        await _call(hass, UID_SHUTTER, SERVICE_OPEN_COVER)
        await _watch_done(init_with_every_product.runtime_data, UID_SHUTTER)

    assert len(_louvers_sent(fake_hub, UID_SHUTTER)) == 1
    assert not [c for c in fake_hub.control_calls if "StatusRequest" in c]


async def test_a_louver_turn_refused_as_busy_is_not_retried_after_a_newer_command(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A newer command for the Shutter while the hub is waited out drops the retry and its
    watch: the hub never turned the louvers for the refused one."""
    coordinator = init_with_every_product.runtime_data
    orig = fake_hub._control
    fake_hub.control_responses = [{"Error": 2}]

    async def _taken_over(method, url, data):  # noqa: ANN001
        body = json.loads(data) if isinstance(data, str | bytes) else data
        if "Position" in body:
            coordinator.async_supersede([UID_SHUTTER])
        return await orig(method, url, data)

    with (
        patch.object(fake_hub, "_control", _taken_over),
        patch("custom_components.norman.api.HUB_BUSY_RETRY_DELAY", 0),
    ):
        fake_hub.mock.clear_requests()
        fake_hub._register()
        await _call(hass, UID_SHUTTER, SERVICE_OPEN_COVER_TILT)

    assert len(_louvers_sent(fake_hub, UID_SHUTTER)) == 1
    assert UID_SHUTTER not in coordinator._move_watchers
