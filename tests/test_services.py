"""Tests for the integration-level actions: get_hub_data, send_hub_command and room_command."""

from __future__ import annotations

import re

import aiohttp
from homeassistant.config_entries import SOURCE_IGNORE, ConfigEntryDisabler, ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

try:
    import probatio as vol
except ImportError:  # pragma: no cover - Home Assistant < 2026.9
    import voluptuous as vol  # type: ignore[no-redef]

from custom_components.norman.const import DOMAIN

from .conftest import FakeHub, cover_entity_id
from .const import (
    HUB_THING_NAME,
    HUB_URL,
    UID_BEDROOM,
    UID_LIVING,
    UID_ROMAN,
    UID_SHUTTER,
    UID_STATUS_ONLY,
)


async def _get_hub_data(hass: HomeAssistant, **data) -> dict:
    return await hass.services.async_call(
        DOMAIN, "get_hub_data", data, blocking=True, return_response=True
    )


def _peripheral_uids(node: object) -> list[object]:
    """Every PeripheralUID in a response, at any depth."""
    if isinstance(node, dict):
        own = [node["PeripheralUID"]] if "PeripheralUID" in node else []
        return own + [uid for value in node.values() for uid in _peripheral_uids(value)]
    if isinstance(node, list):
        return [uid for item in node for uid in _peripheral_uids(item)]
    return []


async def test_get_hub_data_returns_raw_payloads(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The response is the hub's own JSON, fetched live, unknown fields included."""
    fake_hub.peripheral_status(UID_LIVING)["SomethingNew"] = 42

    response = await _get_hub_data(hass)

    assert response["devices"]["results"]["RoomList"][0]["RoomName"] == "Living Room"
    # Home/network identifiers are blanked even in the live response
    assert response["devices"]["results"]["GeoLoc"] == "**REDACTED**"
    assert response["devices"]["results"]["ThingName"] == "**REDACTED**"
    assert HUB_THING_NAME not in str(response)
    assert any(p.get("SomethingNew") == 42 for p in response["status"]["Peripherals"])


async def test_get_hub_data_calls_blinds_what_diagnostics_calls_them(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
) -> None:
    """A blind's id is its serial number, so each is the alias a diagnostics download uses.

    The device list and the status give a blind the same alias, so they still line up.
    """
    fake_hub.peripheral_status(UID_LIVING)["SomethingNew"] = 42

    response = await _get_hub_data(hass)

    uids = _peripheral_uids(response)
    assert any(re.fullmatch(r"blind_\d+", str(uid)) for uid in uids), uids
    # The hub sends an id as a number or a string of digits; anything else is not a serial.
    serials = [uid for uid in uids if isinstance(uid, int) or str(uid).isdigit()]
    assert not serials, f"serial numbers left in the response: {serials}"
    living = next(
        blind["PeripheralUID"]
        for room in response["devices"]["results"]["RoomList"]
        for group in room["GroupList"]
        for blind in group["PeripheralList"]
        if blind["PeripheralName"] == "Living Drape"
    )
    status = next(p for p in response["status"]["Peripherals"] if p.get("SomethingNew") == 42)
    assert status["PeripheralUID"] == living
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)
    assert diagnostics["devices"][living]["name"] == "Living Drape"


async def test_get_hub_data_shows_serial_numbers_when_asked(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A script matching blinds up with their devices can have the real ids."""
    response = await _get_hub_data(hass, show_serial_numbers=True)

    uids = {str(uid) for uid in _peripheral_uids(response)}
    assert {str(UID_LIVING), str(UID_BEDROOM)} <= uids
    assert not any(uid.startswith("blind_") for uid in uids)
    assert HUB_THING_NAME not in str(response), "the hub's identity is blanked all the same"


async def test_get_hub_data_accepts_an_explicit_entry(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The entry id selector targets a specific hub."""
    response = await _get_hub_data(hass, config_entry_id=init_integration.entry_id)
    assert "Peripherals" in response["status"]


async def test_get_hub_data_rejects_unknown_entry(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A wrong id is a validation error, not a crash."""
    with pytest.raises(ServiceValidationError, match="No Norman hub") as excinfo:
        await _get_hub_data(hass, config_entry_id="nope")
    assert excinfo.value.translation_key == "unknown_entry"


async def test_get_hub_data_requires_entry_id_with_several_hubs(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """With more than one hub the id must be given."""
    other = MockConfigEntry(domain=DOMAIN, data={"host": "192.168.1.99"}, unique_id="Other")
    other.add_to_hass(hass)
    other.mock_state(hass, ConfigEntryState.LOADED)
    with pytest.raises(ServiceValidationError, match="2 Norman hubs"):
        await _get_hub_data(hass)


@pytest.mark.parametrize(
    "other",
    [
        {"source": SOURCE_IGNORE},
        {"disabled_by": ConfigEntryDisabler.USER},
        {},
    ],
    ids=["ignored", "disabled", "not-set-up"],
)
async def test_get_hub_data_needs_no_id_with_one_hub_set_up(
    hass: HomeAssistant, init_integration: MockConfigEntry, other: dict
) -> None:
    """A discovered hub ignored, one disabled, or one not set up leaves one hub to address.

    The sidebar panel and the card send no hub then either.
    """
    MockConfigEntry(
        domain=DOMAIN, data={"host": "192.168.1.99"}, unique_id="Other", **other
    ).add_to_hass(hass)

    response = await _get_hub_data(hass)

    assert response["devices"]


async def test_get_hub_data_requires_a_loaded_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The action exists as soon as the integration loads, but needs a loaded hub."""
    aioclient_mock.post(f"{HUB_URL}/NM/v1/registration", exc=aiohttp.ClientConnectionError())
    mock_config_entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY

    assert hass.services.has_service(DOMAIN, "get_hub_data")
    with pytest.raises(ServiceValidationError, match="not loaded"):
        await _get_hub_data(hass)


async def test_get_hub_data_reports_hub_failures(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A hub that cannot be read fails the call with a clear message."""
    fake_hub.status_exc = aiohttp.ClientConnectionError("gone")
    with pytest.raises(HomeAssistantError, match="Could not read from Norman hub"):
        await _get_hub_data(hass)


async def test_get_hub_data_returns_a_failed_device_list_as_sent(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A device list the hub could not read is returned as it came, not raised.

    The hub's configuration reader can fail while status still answers, which is when a
    report needs the raw reply.
    """
    fake_hub.devices = {"status": {"code": 1, "error": "Request process fail."}}

    response = await _get_hub_data(hass)

    assert response["devices"] == {"status": {"code": 1, "error": "Request process fail."}}
    assert response["status"]["Peripherals"]


async def test_send_hub_command_posts_fields_and_returns_reply(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Arbitrary fields reach the control endpoint with the ids filled in; the reply comes back."""
    fake_hub.control_response = {"Error": 0, "PeripheralUID": UID_LIVING, "MotorStop": 1}
    status_calls = len(fake_hub.calls_to("/status"))

    response = await hass.services.async_call(
        DOMAIN,
        "send_hub_command",
        {"peripheral_uid": str(UID_LIVING), "fields": {"MotorStop": 1}},
        blocking=True,
        return_response=True,
    )

    call = fake_hub.control_calls[-1]
    assert call["PeripheralUID"] == UID_LIVING
    assert call["MotorStop"] == 1
    assert {"Timestamp", "TaskID"} <= set(call)
    assert response["reply"]["MotorStop"] == 1
    # A refresh follows so any resulting movement shows up
    assert len(fake_hub.calls_to("/status")) == status_calls + 1


@pytest.mark.parametrize(
    ("fields", "watched"),
    [({"Favorite": 0}, False), ({"StatusRequest": 0}, True)],
    ids=["verb", "status-request"],
)
async def test_send_hub_command_takes_the_blind_over(
    hass: HomeAssistant, init_integration: MockConfigEntry, fields: dict, watched: bool
) -> None:
    """A verb sent by hand ends the move watch; a status request leaves it running.

    Left running, the watch would read the blind heading elsewhere as its move never
    arriving, and send that move again on top of the verb.
    """
    coordinator = init_integration.runtime_data
    await coordinator.async_move_blind(UID_LIVING, 10, None)
    assert UID_LIVING in coordinator._move_watchers

    await hass.services.async_call(
        DOMAIN,
        "send_hub_command",
        {"peripheral_uid": str(UID_LIVING), "fields": fields},
        blocking=True,
        return_response=True,
    )

    assert (UID_LIVING in coordinator._move_watchers) is watched
    coordinator.async_supersede()


async def test_send_hub_command_reports_rejection(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A non-zero Error from the hub fails the call with the hub's code."""
    fake_hub.control_response = {"Error": 7}
    with pytest.raises(HomeAssistantError, match="rejected the command.*error code: 7"):
        await hass.services.async_call(
            DOMAIN,
            "send_hub_command",
            {"peripheral_uid": UID_LIVING, "fields": {"MotorStop": 1}},
            blocking=True,
            return_response=True,
        )


async def test_send_hub_command_validates_input(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Missing or malformed fields never reach the hub."""
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "send_hub_command", {"fields": {"MotorStop": 1}}, blocking=True
        )
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "send_hub_command",
            {"peripheral_uid": UID_LIVING, "fields": {"Nested": {"a": 1}}},
            blocking=True,
        )
    assert fake_hub.control_calls == []


async def test_send_hub_command_is_admin_only(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    hass_read_only_user: MockUser,
) -> None:
    """A non-admin user cannot send raw verbs, which can wipe a blind's limits or pairing."""
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            "send_hub_command",
            {"peripheral_uid": UID_LIVING, "fields": {"CleanTopLimit": 0}},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    assert fake_hub.control_calls == []


async def test_room_command_sends_the_room_wide_verb(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A room command addresses the room by RoomID, not one request per blind.

    This is the app's own Best Privacy: the hub accepts RoomID in place of PeripheralUID.
    """
    status_calls = len(fake_hub.calls_to("/status"))

    await hass.services.async_call(
        DOMAIN,
        "room_command",
        {"room": "Living Room", "command": "best_privacy"},
        blocking=True,
    )

    call = fake_hub.control_calls[-1]
    assert call["RoomID"] == 1
    assert call["Switch"] == 0
    # Addressing the room replaces the per-blind id; sending both would be ambiguous.
    assert "PeripheralUID" not in call
    assert {"Timestamp", "TaskID"} <= set(call)
    # One read, for the targets the room's watches aim at; it serves as the refresh too.
    await hass.async_block_till_done()
    assert len(fake_hub.calls_to("/status")) == status_calls + 1


async def test_room_command_maps_each_button_to_its_verb(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """best_view opens the bottom rail, favorite runs to the stored position."""
    await hass.services.async_call(
        DOMAIN, "room_command", {"room": "Bedroom", "command": "best_view"}, blocking=True
    )
    assert fake_hub.control_calls[-1]["Switch"] == 1
    assert fake_hub.control_calls[-1]["RoomID"] == 2

    await hass.services.async_call(
        DOMAIN, "room_command", {"room": "Bedroom", "command": "favorite"}, blocking=True
    )
    assert fake_hub.control_calls[-1]["Favorite"] == 0
    assert "Switch" not in fake_hub.control_calls[-1]


async def test_room_command_matches_the_name_case_insensitively(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Room names come from the hub, so a user typing them should not have to match case."""
    await hass.services.async_call(
        DOMAIN, "room_command", {"room": "living room", "command": "best_view"}, blocking=True
    )
    assert fake_hub.control_calls[-1]["RoomID"] == 1


async def test_room_command_rejects_an_unknown_room(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A typo names the rooms that do exist rather than silently doing nothing."""
    before = len(fake_hub.control_calls)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "room_command", {"room": "Kitchen", "command": "best_view"}, blocking=True
        )

    assert "Kitchen" in str(err.value)
    assert len(fake_hub.control_calls) == before  # nothing was sent


async def test_room_command_validates_the_command(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Only the app's three buttons are accepted; anything else is a schema error."""
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "room_command", {"room": "Bedroom", "command": "explode"}, blocking=True
        )


async def test_room_command_reports_hub_rejection(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A hub error surfaces with the room and command in the message."""
    fake_hub.control_response = {"Error": 7}

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN, "room_command", {"room": "Bedroom", "command": "best_privacy"}, blocking=True
        )

    assert "Bedroom" in str(err.value)


async def test_room_command_without_a_room_addresses_the_whole_hub(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Omitting the room sends the verb with no RoomID, which the hub reads as everything."""
    await hass.services.async_call(DOMAIN, "room_command", {"command": "best_view"}, blocking=True)

    call = fake_hub.control_calls[-1]
    assert call["Switch"] == 1
    # No scope field at all: an omitted RoomID is what makes it hub-wide.
    assert "RoomID" not in call
    assert "PeripheralUID" not in call


async def test_hub_wide_favorite_sends_the_bare_verb(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Favorite works hub-wide too, as the bare verb with no scope field.

    Captured from the app's "All Rooms" screen. Every command the app offers per room it
    also offers for the whole house, so all three are allowed without a room.
    """
    await hass.services.async_call(DOMAIN, "room_command", {"command": "favorite"}, blocking=True)

    call = fake_hub.control_calls[-1]
    assert call["Favorite"] == 0
    assert "RoomID" not in call
    assert "PeripheralUID" not in call


async def test_room_command_refresh_asks_the_room_to_report_in(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Room refresh addresses its blinds, while hub refresh is one unscoped status request."""
    before = len(fake_hub.control_calls)
    await hass.services.async_call(
        DOMAIN, "room_command", {"room": "Living Room", "command": "refresh"}, blocking=True
    )
    calls = fake_hub.control_calls[before:]
    assert calls[0]["StatusRequest"] == 0
    assert calls[0]["PeripheralUID"] == UID_LIVING
    assert len(calls) == 1

    before = len(fake_hub.control_calls)
    await hass.services.async_call(
        DOMAIN, "room_command", {"room": "Bedroom", "command": "refresh"}, blocking=True
    )
    calls = fake_hub.control_calls[before:]
    assert len(calls) == 1
    assert calls[0]["PeripheralUID"] == UID_BEDROOM
    assert calls[0]["StatusRequest"] == 0

    before = len(fake_hub.control_calls)
    await hass.services.async_call(DOMAIN, "room_command", {"command": "refresh"}, blocking=True)
    calls = fake_hub.control_calls[before:]
    assert len(calls) == 1
    assert set(calls[0]) == {"Timestamp", "TaskID", "StatusRequest"}


# ---- room_command on chosen blinds ------------------------------------------------------


async def test_room_command_on_every_blind_of_a_room_sends_the_room_request(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Blinds that make up a whole room get the room's preset: one request, by RoomID."""
    await hass.services.async_call(
        DOMAIN,
        "room_command",
        {"blinds": [cover_entity_id(hass, UID_LIVING)], "command": "best_privacy"},
        blocking=True,
    )

    call = fake_hub.control_calls[-1]
    assert call["RoomID"] == 1
    assert call["Switch"] == 0
    assert "PeripheralUID" not in call


async def test_room_command_on_part_of_a_room_sends_each_blind_its_own(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Part of a room gets a preset each, so the room's other blinds stay where they are.

    The dashboard card sends the blinds it shows under one heading, which need not be all of
    a room's: a blind moved to another area in Home Assistant is shown under that one.
    """
    before = len(fake_hub.control_calls)
    await hass.services.async_call(
        DOMAIN,
        "room_command",
        {
            "blinds": [cover_entity_id(hass, UID_LIVING), cover_entity_id(hass, UID_ROMAN)],
            "command": "favorite",
        },
        blocking=True,
    )

    presets = [call for call in fake_hub.control_calls[before:] if "Favorite" in call]
    assert sorted(call["PeripheralUID"] for call in presets) == sorted([UID_LIVING, UID_ROMAN])
    # Addressed as each blind's own Favorite button sends it: its room and its group.
    assert all(call["RoomID"] == 1 and "GroupID" in call for call in presets)


async def test_room_command_spans_rooms_one_request_per_whole_room(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Blinds from two rooms, each room whole, get each room's request."""
    before = len(fake_hub.control_calls)
    await hass.services.async_call(
        DOMAIN,
        "room_command",
        {
            "blinds": [cover_entity_id(hass, UID_LIVING), cover_entity_id(hass, UID_BEDROOM)],
            "command": "best_view",
        },
        blocking=True,
    )

    presets = [call for call in fake_hub.control_calls[before:] if "Switch" in call]
    assert sorted(call["RoomID"] for call in presets) == [1, 2]
    assert not any("PeripheralUID" in call for call in presets)


async def test_room_command_stop_on_a_whole_room_is_one_room_stop(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Stopping a whole room is the room's own MotorStop, not one paced stop per blind."""
    await hass.services.async_call(
        DOMAIN,
        "room_command",
        {"blinds": [cover_entity_id(hass, UID_LIVING)], "command": "stop"},
        blocking=True,
    )

    stops = [call for call in fake_hub.control_calls if "MotorStop" in call]
    assert len(stops) == 1
    assert stops[0]["MotorStop"] == 170
    assert stops[0]["RoomID"] == 1
    assert "PeripheralUID" not in stops[0]


async def test_room_command_stop_on_part_of_a_room_stops_each_blind_but_a_shutter(
    hass: HomeAssistant, init_with_every_product: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Part of a room is stopped blind by blind; a Shutter's louvers take no stop."""
    before = len(fake_hub.control_calls)
    await hass.services.async_call(
        DOMAIN,
        "room_command",
        {
            "blinds": [cover_entity_id(hass, UID_LIVING), cover_entity_id(hass, UID_SHUTTER)],
            "command": "stop",
        },
        blocking=True,
    )

    stops = [call for call in fake_hub.control_calls[before:] if "MotorStop" in call]
    assert [call["PeripheralUID"] for call in stops] == [UID_LIVING]
    assert "RoomID" not in stops[0]


async def test_room_command_stop_for_a_named_room_and_for_the_whole_hub(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Stop works as the other commands do: by the hub's room name, or for every blind."""
    await hass.services.async_call(
        DOMAIN, "room_command", {"room": "Bedroom", "command": "stop"}, blocking=True
    )
    assert fake_hub.control_calls[-1]["MotorStop"] == 170
    assert fake_hub.control_calls[-1]["RoomID"] == 2

    await hass.services.async_call(DOMAIN, "room_command", {"command": "stop"}, blocking=True)
    call = fake_hub.control_calls[-1]
    assert call["MotorStop"] == 170
    assert "RoomID" not in call and "PeripheralUID" not in call


async def test_room_command_refresh_on_blinds_asks_each_to_report_in(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """Refresh on chosen blinds is one status request each, as a room's refresh sends."""
    before = len(fake_hub.control_calls)
    await hass.services.async_call(
        DOMAIN,
        "room_command",
        {
            "blinds": [cover_entity_id(hass, UID_BEDROOM), cover_entity_id(hass, UID_LIVING)],
            "command": "refresh",
        },
        blocking=True,
    )

    requests = [call for call in fake_hub.control_calls[before:] if "StatusRequest" in call]
    assert [call["PeripheralUID"] for call in requests] == [UID_LIVING, UID_BEDROOM]
    assert not any("ReportBatteryLevel" in call for call in fake_hub.control_calls)


async def test_room_command_takes_any_of_a_blinds_entities(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A blind's slider or battery names the blind as well as its cover does."""
    registry = er.async_get(hass)
    battery = registry.async_get_entity_id("sensor", DOMAIN, f"{UID_BEDROOM}_battery_level")
    assert battery

    await hass.services.async_call(
        DOMAIN, "room_command", {"blinds": [battery], "command": "best_view"}, blocking=True
    )

    assert fake_hub.control_calls[-1]["RoomID"] == 2


@pytest.mark.parametrize(
    ("blinds", "key"),
    [
        (["light.kitchen"], "not_a_norman_blind"),
        ([], "no_blinds_picked"),
    ],
)
async def test_room_command_refuses_what_is_not_a_blind(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_hub: FakeHub,
    blinds: list[str],
    key: str,
) -> None:
    """Something that is not a Norman blind, or no blind at all, sends nothing."""
    before = len(fake_hub.control_calls)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "room_command", {"blinds": blinds, "command": "stop"}, blocking=True
        )

    assert err.value.translation_key == key
    assert len(fake_hub.control_calls) == before


async def test_room_command_refuses_a_hubs_own_entity_as_a_blind(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """The hub's and the rooms' entities belong to no blind."""
    hub_button = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, f"{init_integration.entry_id}_refresh_blinds"
    )
    assert hub_button

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "room_command", {"blinds": [hub_button], "command": "stop"}, blocking=True
        )

    assert err.value.translation_key == "not_a_norman_blind"


async def test_room_command_refuses_a_blind_on_another_hub(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """With a hub named, every blind has to be on it."""
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "room_command",
            {
                "blinds": [cover_entity_id(hass, UID_LIVING)],
                "command": "stop",
                "config_entry_id": "another-hub",
            },
            blocking=True,
        )

    assert err.value.translation_key == "blind_on_other_hub"


async def test_room_command_takes_a_room_or_blinds_not_both(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A room and blinds together would leave which one counts to a guess."""
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "room_command",
            {
                "room": "Bedroom",
                "blinds": [cover_entity_id(hass, UID_LIVING)],
                "command": "best_view",
            },
            blocking=True,
        )


async def test_a_preset_needs_a_blind_the_hub_can_address(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A blind the device list does not place in a room and group cannot take a preset."""
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "room_command",
            {"blinds": [cover_entity_id(hass, UID_STATUS_ONLY)], "command": "best_view"},
            blocking=True,
        )

    assert err.value.translation_key == "button_needs_room"


async def test_room_command_on_blinds_reports_hub_rejection(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_hub: FakeHub
) -> None:
    """A hub error names the command, as a room's does."""
    fake_hub.control_response = {"Error": 7}

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN,
            "room_command",
            {"blinds": [cover_entity_id(hass, UID_LIVING)], "command": "stop"},
            blocking=True,
        )

    assert err.value.translation_key == "blinds_command_failed"
