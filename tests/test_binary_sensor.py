"""Tests for the per-blind connection sensor."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    STATE_OFF,
    STATE_ON,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.norman.binary_sensor import RECHECK_INTERVAL
from custom_components.norman.const import DOMAIN, UNRESPONSIVE_AFTER

from .conftest import FakeHub, settle
from .const import UID_BEDROOM, UID_LIVING


def connection_entity_id(hass: HomeAssistant, uid: int) -> str:
    """Resolve a blind's connection sensor from its unique id."""
    entity_id = er.async_get(hass).async_get_entity_id("binary_sensor", DOMAIN, f"{uid}_connection")
    assert entity_id, f"no connection sensor for peripheral {uid}"
    return entity_id


async def test_connection_follows_the_apps_24h_rule(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A blind last heard from in 2023 is disconnected; one without a timestamp is unknown.

    The Norman app lists a blind under "Disconnect" once the hub has not heard from it
    for 86400 s (the constant in its isDisconnectPeripheral:withHub: check), and this
    sensor applies the same threshold so the two never disagree.
    """
    assert timedelta(hours=24) == UNRESPONSIVE_AFTER

    living = hass.states.get(connection_entity_id(hass, UID_LIVING))
    assert living.state == STATE_OFF
    assert living.attributes[ATTR_DEVICE_CLASS] == "connectivity"
    assert living.attributes["friendly_name"] == "Living Drape Connection"

    # The bedroom shade's status record carries no Timestamp at all.
    assert hass.states.get(connection_entity_id(hass, UID_BEDROOM)).state == STATE_UNKNOWN

    entry = er.async_get(hass).async_get(connection_entity_id(hass, UID_LIVING))
    assert entry.entity_category is EntityCategory.DIAGNOSTIC
    assert entry.disabled_by is None


async def test_reporting_in_turns_the_sensor_on_and_silence_turns_it_off(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A fresh Timestamp (pushed by the hub) flips it on; a day of quiet flips it off again.

    The second half needs no hub event: the blind simply stops being heard from, so the
    sensor re-evaluates on its own timer.
    """
    entity_id = connection_entity_id(hass, UID_LIVING)
    now = dt_util.utcnow()

    fake_hub.peripheral_status(UID_LIVING)["Timestamp"] = int(now.timestamp())
    await notifications.put({"PeripheralList": [UID_LIVING]})
    await settle(hass)
    assert hass.states.get(entity_id).state == STATE_ON

    freezer.tick(UNRESPONSIVE_AFTER + RECHECK_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_OFF


async def test_pairing_mode_sensor_follows_the_hub(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> None:
    """Off while status says PairingMode 0; on while it says 5 (the ten-minute window)."""
    entity_id = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{init_integration.entry_id}_pairing_mode"
    )
    assert entity_id
    state = hass.states.get(entity_id)
    assert state.state == STATE_OFF
    assert state.attributes["friendly_name"] == "ShadeAuto Hub Pairing mode"
    assert er.async_get(hass).async_get(entity_id).entity_category is EntityCategory.DIAGNOSTIC

    fake_hub.status["PairingMode"] = 5
    await notifications.put({"UpdateTime": {"device": 1}})
    await settle(hass)
    assert hass.states.get(entity_id).state == STATE_ON
