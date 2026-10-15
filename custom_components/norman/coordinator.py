"""Data update coordinator for Norman devices."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime, timedelta
import functools
import logging
import time
from typing import Any, NamedTuple

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import NormanApiClient, NormanApiError, NormanConnectionError
from .const import (
    ARRIVAL_TOLERANCE,
    CONF_CONTROL_INTERVAL,
    CONF_POLL_INTERVAL,
    CONF_WAKE_INTERVAL,
    COVER_TYPE_SHUTTER,
    COVER_TYPE_SINGLE_RAIL,
    COVER_TYPE_TWO_RAIL,
    DEFAULT_CONTROL_INTERVAL,
    DEFAULT_COVER_TYPE,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_WAKE_INTERVAL,
    DOMAIN,
    EVENT_COMMAND_FAILED,
    HUB_CMD_REQUEST_STATUS,
    HUB_CMD_STOP,
    HUB_COMMAND_SETTING,
    KNOWN_HUB_FIELDS,
    KNOWN_PERIPHERAL_FIELDS,
    KNOWN_SCENE_FIELDS,
    KNOWN_SCENE_GROUP_FIELDS,
    KNOWN_SCENE_GROUP_ITEM_FIELDS,
    KNOWN_SCENE_TARGET_FIELDS,
    MAX_CONTROL_INTERVAL,
    MAX_POLL_INTERVAL,
    MAX_WAKE_INTERVAL,
    MIN_CONTROL_INTERVAL,
    MIN_POLL_INTERVAL,
    MIN_WAKE_INTERVAL,
    MODULE_DETAIL_COVER_TYPES,
    MODULE_TYPE_COVER_TYPES,
    MOVE_ATTEMPTS,
    MOVE_REPORT_WAIT,
    MOVE_TIMEOUT,
    MSD_STACK_SIDES,
    POLL_DISABLED,
    RECONNECT_INTERVAL,
    ROOM_MIDDLE_WITHOUT_TWO_RAIL,
    ROOM_POSITION_TYPES,
    SHUTTER_CLOSED,
    WAKE_DISABLED,
    is_default_title,
)
from .models import (
    NormanDevices,
    NormanHubData,
    NormanPeripheralData,
    NormanScene,
    NormanSceneGroup,
    NormanSceneTarget,
    scene_key,
)

_LOGGER = logging.getLogger(__name__)
DEVICE_LIST_RETRY_INTERVAL = 60  # seconds after a failed configuration read

type NormanConfigEntry = ConfigEntry[NormanCoordinator]

# A blind's two rails, (bottom, middle); the middle is None on a single-rail blind.
type _Rails = tuple[int | None, int | None]


class _Sighting(NamedTuple):
    """Where the hub last saw a blind, and when it last heard from it (its ``Timestamp``)."""

    rails: _Rails
    heard: Any


def _rails(data: NormanPeripheralData) -> _Rails:
    """What a blind reports it is at. A Shutter's louvers stand in for the bottom rail."""
    if data.type == COVER_TYPE_SHUTTER:
        return (data.position, None)
    middle = None if data.type == COVER_TYPE_SINGLE_RAIL else data.middle_rail_position
    return (data.bottom_rail_position, middle)


def _targets(data: NormanPeripheralData) -> _Rails:
    """What the hub has recorded as a blind's target, in the same shape as ``_rails``."""
    if data.type == COVER_TYPE_SHUTTER:
        return (data.target_position, None)
    middle = None if data.type == COVER_TYPE_SINGLE_RAIL else data.target_middle_rail_position
    return (data.target_bottom_rail_position, middle)


def _distance(rails: _Rails, goal: _Rails) -> int:
    """How far the rails are from the goal, over the rails both sides have a value for."""
    return sum(
        abs(rail - target)
        for rail, target in zip(rails, goal, strict=True)
        if rail is not None and target is not None
    )


def _arrived(rails: _Rails, goal: _Rails, tolerance: int) -> bool:
    """Whether every rail with a value on both sides is within ``tolerance`` of the goal."""
    return all(
        abs(rail - target) <= tolerance
        for rail, target in zip(rails, goal, strict=True)
        if rail is not None and target is not None
    )


def hub_identifier(entry: ConfigEntry) -> str:
    """Device-registry identifier of the hub device for ``entry``."""
    return f"hub_{entry.entry_id}"


def room_identifier(entry: ConfigEntry, room_id: int) -> str:
    """Device-registry identifier of one of the hub's rooms.

    Scoped to the entry: room ids are the hub's own, and a second hub numbers its rooms
    independently.
    """
    return f"room_{entry.entry_id}_{room_id}"


def clamp_position(value: int) -> int:
    """Clamp a rail position to the 0-100 range Home Assistant uses."""
    return max(0, min(100, value))


def has_bottom_rail(cover_type: str) -> bool:
    """Whether a blind of this type has a bottom rail to move. A Shutter has only louvers."""
    return cover_type != COVER_TYPE_SHUTTER


def has_middle_rail(cover_type: str) -> bool:
    """Whether a blind of this type has a middle rail of its own.

    Only a two-rail shade does. A single-rail blind reports the field as a constant 0, and on
    a drape or a PerfectSheer it is the vane tilt, which belongs to the cover.
    """
    return cover_type == COVER_TYPE_TWO_RAIL


def rails_to_send(
    cover_type: str | None,
    heading: tuple[int, int],
    bottom: int | None,
    middle: int | None,
) -> tuple[int, int]:
    """The pair a move sends to one blind; ``None`` keeps a rail where it is ``heading``.

    The hub's control call takes both rails, so a move of one rail has to send the other.
    On a two-rail blind the middle rail always hangs above the bottom rail, so a rail kept
    where it is heading is carried along when the other would pass it: lowering the middle
    rail below the bottom rail takes the bottom rail down with it, and raising the bottom
    rail above the middle rail takes the middle rail up. The hub is never asked for a shape
    the blind cannot make. A drape's two values are how far it is drawn and how its vanes are
    tilted, which do not constrain each other, so they are sent as asked.
    """
    bottom_val = heading[0] if bottom is None else clamp_position(bottom)
    middle_val = heading[1] if middle is None else clamp_position(middle)
    if cover_type == COVER_TYPE_TWO_RAIL:
        if middle is None:
            middle_val = max(middle_val, bottom_val)
        elif bottom is None:
            bottom_val = min(bottom_val, middle_val)
    return bottom_val, middle_val


def _reaches(cover_type: str, bottom: int | None, middle: int | None) -> bool:
    """Whether a move of these rails has anything to move on a blind of this type."""
    return (bottom is not None and has_bottom_rail(cover_type)) or (
        middle is not None and has_middle_rail(cover_type)
    )


def _first_known(*values: int | None) -> int:
    """The first of ``values`` that is known, or 100 (fully open) if none is."""
    return next((value for value in values if value is not None), 100)


def rooms_of(devices: NormanDevices) -> dict[int, str]:
    """The hub's rooms that hold a blind, by id, each with the name the hub gives it."""
    rooms: dict[int, str] = {}
    for device in devices.values():
        if device.room_id is not None and device.room_id not in rooms:
            rooms[device.room_id] = device.room_name or f"Room {device.room_id}"
    return rooms


def _poll_interval(entry: NormanConfigEntry) -> timedelta | None:
    """The configured poll interval, or None when polling is switched off.

    ``POLL_DISABLED`` (0) means "push only": returning None leaves the coordinator without
    an ``update_interval``, so it refreshes solely on notifications and commands.

    A value that is missing, non-numeric, or out of range falls back to the default rather
    than raising: options are user input, and a bad one should not stop the integration from
    loading. 0 is the one value outside the supported range that is honoured rather than
    corrected, and it is also the default -- so an unconfigured entry polls not at all.
    """
    raw = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        seconds = DEFAULT_POLL_INTERVAL
    if seconds != POLL_DISABLED and not MIN_POLL_INTERVAL <= seconds <= MAX_POLL_INTERVAL:
        seconds = DEFAULT_POLL_INTERVAL
    return None if seconds == POLL_DISABLED else timedelta(seconds=seconds)


def _control_interval(entry: NormanConfigEntry) -> float:
    """Seconds to leave between control sends.

    The hub drops commands sent faster than its radio can transmit them (const.py,
    ``DEFAULT_CONTROL_INTERVAL``). An unusable or out-of-range value falls back to the
    default rather than stopping the entry from loading.
    """
    raw = entry.options.get(CONF_CONTROL_INTERVAL, DEFAULT_CONTROL_INTERVAL)
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_CONTROL_INTERVAL
    if not MIN_CONTROL_INTERVAL <= seconds <= MAX_CONTROL_INTERVAL:
        return DEFAULT_CONTROL_INTERVAL
    return seconds


def _wake_interval(entry: NormanConfigEntry) -> timedelta | None:
    """The configured wake sweep interval, or None when the sweep is off.

    Same rules as ``_poll_interval``: 0 (the default) means off, an unusable value falls
    back to the default rather than stopping the entry from loading.
    """
    raw = entry.options.get(CONF_WAKE_INTERVAL, DEFAULT_WAKE_INTERVAL)
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        seconds = DEFAULT_WAKE_INTERVAL
    if seconds != WAKE_DISABLED and not MIN_WAKE_INTERVAL <= seconds <= MAX_WAKE_INTERVAL:
        seconds = DEFAULT_WAKE_INTERVAL
    return None if seconds == WAKE_DISABLED else timedelta(seconds=seconds)


class NormanCoordinator(DataUpdateCoordinator[NormanDevices]):
    """Norman data update coordinator.

    The hub pushes state changes over a long-poll (see ``listen_notifications``): every
    notification, reconnect, and command triggers a refresh, and the stream is cycled every
    NOTIF_MAX_DURATION, so a missed notification is caught within five minutes. An optional
    poll (off by default) shortens that; it re-reads the same cache, so it cannot correct a
    sleeping blind's position (const.py). The interval is configurable in the integration's
    options; the entry is reloaded when it changes.
    """

    config_entry: NormanConfigEntry

    def __init__(self, hass: HomeAssistant, entry: NormanConfigEntry, api: NormanApiClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data.get('host', '')}".strip(),
            update_interval=_poll_interval(entry),
        )
        self.api = api
        # The hub drops control commands sent faster than its radio can transmit them, so
        # the client spaces them; the gap is configurable per hub (see _control_interval).
        api.control_interval = _control_interval(entry)
        # Registry id of the hub device, set by async_setup_entry once it is created
        self.hub_device_id: str | None = None
        # What the hub says about itself; refreshed alongside the peripherals
        self.hub = NormanHubData(model=api.hub_model, firmware_version=api.hub_firmware_version)
        self._device_info: dict[str, Any] = {}
        # The entry's data and options as this setup read them; a later change to either
        # reloads the entry, a new title does not (__init__._async_entry_updated).
        self.config_at_setup: tuple[dict[str, Any], dict[str, Any]] = (
            dict(entry.data),
            dict(entry.options),
        )
        self._device_info_stale = True
        self._device_info_error_logged = False
        # Area ids for rooms named after their blinds' area while the hub cannot name them
        self._room_areas: dict[int, str] = {}
        self._next_device_info_retry = 0.0
        self._unknown_fields: set[tuple[str, str]] = set()
        self._unknown_module_types: set[int | None] = set()
        # True while the notification stream is known to be down, so that the outage is
        # logged once at error level rather than on every reconnect attempt.
        self._listener_offline = False
        # One move watchdog per blind (see async_watch_move); a new move replaces it.
        self._move_watchers: dict[int, asyncio.Task[None]] = {}
        # The rails each blind's move in flight was sent to, keyed by blind, with the serial
        # of the move that recorded them (see async_note_move).
        self._moves: dict[int, tuple[int, tuple[int, int]]] = {}
        self._move_serial = 0
        # The serial of the last command to take each blind over: a move (async_note_move)
        # or a stop, jog, preset or scene (async_supersede). A command that waited its turn
        # in the control queue is sent and watched only while it still holds its blind, so
        # a stop or a newer command issued meanwhile is not undone.
        self._claims: dict[int, int] = {}
        # Blinds taken over by something other than a move, whose next move reads the hub
        # first (async_settle): where each was when it was taken over, and whether the
        # command aimed it at a target the hub records (a preset) or halted it (a stop).
        self._unsettled: dict[int, tuple[_Sighting, bool]] = {}
        # The scenes and scene groups saved on the hub, from its device list (_parse_scenes).
        # Kept from the last good read while the hub cannot read its configuration.
        self.scenes: dict[str, NormanScene] = {}
        self.scene_groups: dict[str, NormanSceneGroup] = {}

    @callback
    def async_start_wake_sweep(self) -> None:
        """Schedule the wake sweep at the configured interval, if any.

        Called once from setup; the timer is removed when the entry unloads. A changed
        interval is applied by reloading the entry, like the poll interval.
        """
        interval = _wake_interval(self.config_entry)
        if interval is None:
            return

        async def _async_sweep() -> None:
            try:
                await self.async_wake_disconnected_blinds()
            except (NormanApiError, NormanConnectionError) as err:
                _LOGGER.warning("Wake sweep failed: %s", err)

        @callback
        def _sweep(_now: datetime) -> None:
            # A task of the entry's, so unloading it stops a sweep part-way through: one left
            # running would send through the old client, unpaced against the new one.
            self.config_entry.async_create_background_task(
                self.hass, _async_sweep(), name="norman-wake-sweep"
            )

        self.config_entry.async_on_unload(
            async_track_time_interval(self.hass, _sweep, interval, name="norman-wake-sweep")
        )

    async def async_wake_disconnected_blinds(self) -> None:
        """Ask each blind the hub has not heard from for ``UNRESPONSIVE_AFTER`` to report in.

        This is the wake sweep. The app offers a refresh only for a blind it lists as
        disconnected, never for a connected one, so the sweep does the same: one
        ``StatusRequest`` per disconnected blind, and nothing at all while every blind is
        connected. It used to send every blind
        the hub-wide ``ReportBatteryLevel`` and a ``StatusRequest`` each, and on a hub of
        type 48 roller shades that closed them every time it ran (issue #5).
        """
        now = dt_util.utcnow()
        for device_id, device in (self.data or {}).items():
            if device.disconnected(now):
                await self.api.async_request_status(device_id)

    async def async_refresh_blinds(self, room_id: int | None = None) -> None:
        """Ask every blind on the hub, or each blind in a room, for fresh status.

        An unscoped ``StatusRequest`` reached all thirteen blinds on a hub in a live test,
        with the last answer arriving within two minutes. A ``RoomID`` did not constrain
        that verb, so room refresh uses one addressed request per blind. Their answers
        arrive later as hub notifications.
        """
        if room_id is None:
            await self.api.async_send_room_control(
                None, {HUB_CMD_REQUEST_STATUS: HUB_COMMAND_SETTING}
            )
            return

        for device_id, device in (self.data or {}).items():
            if device.room_id == room_id:
                await self.api.async_request_status(device_id)

    async def async_report_battery_levels(self, room_id: int | None = None) -> None:
        """Send the Norman app's report command to a room or the hub.

        This is deliberately separate from status refresh: ``ReportBatteryLevel`` has
        closed roller and two-rail cellular shades on real hardware. So it takes the blinds
        over as a stop does, and is dropped at its turn if a command takes one of them over
        while it waits (``_still_holds``).
        """
        serial = self.async_supersede_room(room_id)
        await self.api.async_request_battery_report(
            room_id, still_wanted=self._still_holds(self.blinds_in(room_id), serial)
        )

    async def async_send_room_verb(self, room_id: int | None, fields: dict[str, Any]) -> None:
        """Send a stop or a jog to every blind in a room (every blind on the hub, for None).

        One request; the hub carries it to each blind. It takes the blinds over first: a move
        in flight is no longer watched, and one still queued is not sent. A jog that waits
        its turn is itself dropped if a command takes one of its blinds over meanwhile, as a
        move would be; a stop never is -- it is served first instead (api._ControlQueue).
        """
        serial = self.async_supersede_room(room_id)
        still_wanted = (
            None if HUB_CMD_STOP in fields else self._still_holds(self.blinds_in(room_id), serial)
        )
        await self.api.async_send_room_control(room_id, fields, still_wanted=still_wanted)

    def _still_holds(self, device_ids: Iterable[int], serial: int) -> Callable[[], bool]:
        """The check a command for these blinds, taken over as ``serial``, is sent under."""
        claims: dict[int, int | None] = dict.fromkeys(device_ids, serial)
        return lambda: self._holds_all(claims)

    @property
    def has_device_list(self) -> bool:
        """Whether the hub's device list has been read, so its rooms and scenes are known."""
        return bool(self._device_info)

    @property
    def listening(self) -> bool:
        """Whether the notification stream is up, so the blinds' reports arrive as they come."""
        return not self._listener_offline

    def commanded_rails(self, device_id: int) -> tuple[int, int] | None:
        """The rails this blind's move in flight was sent to, or None when there is none."""
        move = self._moves.get(device_id)
        return None if move is None else move[1]

    @callback
    def async_note_move(self, device_id: int, bottom: int, middle: int) -> int:
        """Record a move the moment it is worked out, before it waits its turn to be sent.

        A command that moves one rail sends the other where it is heading, and until the hub
        has been re-read its target still shows where the blind was heading before. Moves
        issued together -- a scene applies its entities at once -- or inside the refresh
        debouncer's ten-second cooldown would each fill the other rail in from that stale
        target, and the second would undo the first. Reading this record first lets each
        see the one before it. It lasts until the move's watch ends, the move fails to send,
        or another command supersedes it (``async_supersede``). Returns the move's serial,
        which ends the record only while it is still this move's, and which holds the blind
        until another command takes it over (``holds``).

        The move in flight before it loses its watch now, not once this one is sent: left
        running, that watch would read the blind heading here as its own move never arriving
        and send it again -- and this move may never be sent, or never be watched.
        """
        self.async_cancel_move_watch(device_id)
        self._move_serial += 1
        self._moves[device_id] = (self._move_serial, (bottom, middle))
        self._claims[device_id] = self._move_serial
        self._unsettled.pop(device_id, None)
        return self._move_serial

    def holds(self, device_id: int, serial: int) -> bool:
        """Whether command ``serial`` is still the last to have taken this blind over."""
        return self._claims.get(device_id) == serial

    def _holds_all(self, claims: dict[int, int | None]) -> bool:
        """Whether no command has taken any of these blinds over since ``claims`` was read.

        One request reaches all of them, so a busy hub's retry is dropped once any has been
        taken over: it would undo that blind's newer command. The rest are still watched,
        and sent their move on their own if they never went.
        """
        return all(self._claims.get(device_id) == claim for device_id, claim in claims.items())

    @callback
    def async_forget_move(self, device_id: int, serial: int | None = None) -> None:
        """Drop a blind's move record: only while it is still move ``serial``, if given."""
        move = self._moves.get(device_id)
        if move is not None and (serial is None or move[0] == serial):
            del self._moves[device_id]

    @callback
    def async_supersede(
        self, device_ids: Iterable[int] | None = None, *, aimed: bool = False
    ) -> int:
        """Another command has taken these blinds over (every blind, for None).

        A stop, a jog or a preset replaces whatever move was in flight, so its watch has to
        go too: left running, it would read the blind heading somewhere else as a move that
        never arrived and send the old one again, undoing the new command. The move record
        goes with it, and the next move reads the hub before it fills its other rail in
        (``async_settle``). ``aimed`` says the command sends the blinds to targets the hub
        records on accepting it -- a preset, a scene -- rather than halting them somewhere
        only their report will tell. A command still waiting its turn loses the blinds too:
        it is not sent, or watched, once it has lost them (``holds``). Returns the new
        command's serial, which holds the blinds until something else takes them over.
        """
        self._move_serial += 1
        if device_ids is None:
            device_ids = set(self.data or {}) | set(self._moves) | set(self._move_watchers)
        for device_id in list(device_ids):
            self.async_cancel_move_watch(device_id)
            self.async_forget_move(device_id)
            self._claims[device_id] = self._move_serial
            self._unsettled[device_id] = (self._sighting(device_id), aimed)
        return self._move_serial

    @callback
    def async_supersede_room(self, room_id: int | None, *, aimed: bool = False) -> int:
        """``async_supersede`` for every blind in a room, or on the hub for None."""
        if room_id is None:
            return self.async_supersede(aimed=aimed)
        return self.async_supersede(self.blinds_in(room_id), aimed=aimed)

    async def async_settle(self, device_ids: Iterable[int]) -> None:
        """Before a move works out where these blinds' other rails are heading: read the hub.

        A blind taken over by a stop, a jog or a preset (``async_supersede``) has no move
        record to fill its other rail in from, and the hub's target in hand is still the one
        from before: the read the command asked for waits out the refresh debouncer's
        cooldown, which the move before it started. A one-rail move made then would send the
        stopped rail on to the target the stop abandoned. So the hub is read straight away.

        A halted blind may still be on its way to report where it stopped: one not heard
        from since, while the hub holds a target it has not reached, is given up to
        ``MOVE_REPORT_WAIT`` to report. The hub replaces the target with the blind's
        position when it does. A preset's target is the hub's from the moment it accepts
        it, so an aimed blind is only read. Each takeover is settled once.
        """
        marks = {
            device_id: self._unsettled[device_id]
            for device_id in device_ids
            if device_id in self._unsettled
        }
        if not marks:
            return
        await self._async_watch_read()
        waiting = {
            device_id: before
            for device_id, (before, aimed) in marks.items()
            if not aimed and self._halted_on_the_way(device_id, before)
        }
        if waiting and not await self._async_wait_until(
            lambda: all(
                self._heard_since(device_id, before) for device_id, before in waiting.items()
            ),
            MOVE_REPORT_WAIT,
        ):
            # The report normally arrives as a notification that refreshes the data;
            # re-read in case it did not.
            await self._async_watch_read()
        for device_id, mark in marks.items():
            if self._unsettled.get(device_id) is mark:
                del self._unsettled[device_id]

    def _halted_on_the_way(self, device_id: int, before: _Sighting) -> bool:
        """Whether a halted blind has not reported since, with the hub's target not reached."""
        data = (self.data or {}).get(device_id)
        if data is None or self._heard_since(device_id, before):
            return False
        return any(
            target is not None and target != rail
            for rail, target in zip(_rails(data), _targets(data), strict=True)
        )

    def room_name(self, room_id: int) -> str | None:
        """The hub's name for one of its rooms: from a blind in it, else from a scene saved in it.

        None while the hub's device list is unreadable and its blinds have no room names.
        """
        for data in (self.data or {}).values():
            if data.room_id == room_id and data.room_name:
                return data.room_name
        for scene in self.scenes.values():
            if scene.room_id == room_id and scene.room_name:
                return scene.room_name
        return None

    def blinds_in(self, room_id: int | None) -> dict[int, NormanPeripheralData]:
        """The blinds in one of the hub's rooms, or every blind on the hub for None."""
        return {
            device_id: device
            for device_id, device in (self.data or {}).items()
            if room_id is None or device.room_id == room_id
        }

    def heading_rails(self, device_id: int) -> tuple[int, int]:
        """Where a blind's rails are heading, for a move that leaves one of them alone.

        The last move sent from here while it is in flight (``async_note_move``), otherwise
        the hub's target, falling back to where the rail is and then to fully open.
        """
        if (commanded := self.commanded_rails(device_id)) is not None:
            return commanded
        data = (self.data or {}).get(device_id)
        if data is None:
            return (100, 100)
        return (
            _first_known(data.target_bottom_rail_position, data.bottom_rail_position),
            _first_known(data.target_middle_rail_position, data.middle_rail_position),
        )

    async def async_move_blind(
        self, device_id: int, bottom: int | None, middle: int | None
    ) -> None:
        """Move one blind's rails, ``None`` keeping a rail where it is heading.

        The move is recorded before it waits its turn to be sent, so a second command right
        behind it -- or issued at the same moment, as a scene does -- keeps it rather than
        undoing it (``async_note_move``). Once sent it is watched until the blind reports it
        moved (``async_watch_move``). Raises the client's errors; a move that could not be
        sent leaves no record behind.
        """
        await self.async_settle([device_id])
        data = (self.data or {}).get(device_id)
        rails = rails_to_send(
            data.type if data else None, self.heading_rails(device_id), bottom, middle
        )
        serial = self.async_note_move(device_id, *rails)
        try:
            sent = await self.api.async_set_position(
                device_id, *rails, still_wanted=functools.partial(self.holds, device_id, serial)
            )
        except BaseException:
            self.async_forget_move(device_id, serial)
            raise
        if sent:
            self.async_watch_move(device_id, *rails, serial)

    async def async_turn_louvers(self, device_id: int, position: int) -> None:
        """Turn a Shutter's louvers to ``position`` (0-7), then watch them as a move is.

        Recorded like a move (``async_note_move``, the louvers in the bottom rail's place), so
        a nudge right behind it -- inside the refresh debouncer's cooldown, when the hub's
        target in hand is still the old one -- starts from where this one sends them.
        """
        serial = self.async_note_move(device_id, position, 0)
        try:
            sent = await self.api.async_set_louvers(
                device_id, position, still_wanted=functools.partial(self.holds, device_id, serial)
            )
        except BaseException:
            self.async_forget_move(device_id, serial)
            raise
        if sent:
            self.async_watch_louvers(device_id, position, serial)

    async def async_move_room(
        self, room_id: int | None, bottom: int | None, middle: int | None
    ) -> None:
        """Move a rail of every blind in a room (every blind on the hub, for None).

        Each blind that has the rail is moved exactly as its own slider would move it: its
        other rail stays where it is heading, and is carried along where the move would pass
        it (``rails_to_send``). Blinds without the rail are left alone.

        That usually takes one request. A room-wide position reaches every blind in scope
        with the same pair (``async_set_room_position``), so when every blind would be sent
        the same pair anyway -- a room moved together, by a preset or an earlier room move --
        that is what goes. When they would not, one request would drag a blind's other rail
        to its neighbour's, so each blind is sent its own instead, paced like any batch. So
        is a room holding a product the room request has not been tried on
        (``ROOM_POSITION_TYPES``).

        Either way, every blind moved is watched afterwards and sent its move on its own if
        it does not go: on 2026-10-10 the hub acked a room restore that one of two shades
        only carried out when its own command was resent. A room request dropped because a
        command took one of its blinds over while it waited is sent to the rest blind by
        blind instead, at once.
        """
        await self.async_settle(self.blinds_in(room_id))
        blinds = self.blinds_in(room_id)
        moves = {
            device_id: rails_to_send(device.type, self.heading_rails(device_id), bottom, middle)
            for device_id, device in blinds.items()
            if _reaches(device.type, bottom, middle)
        }
        if not moves:
            return
        rails = self._shared_rails(blinds, moves)
        if rails is None:
            await self._async_move_each(moves)
            return
        serials = {device_id: self.async_note_move(device_id, *rails) for device_id in moves}
        # The request reaches every blind in scope, not only the ones it moves, so a busy
        # hub's retry is dropped once any of them is taken over.
        claims = {device_id: self._claims.get(device_id) for device_id in blinds}
        try:
            sent = await self.api.async_set_room_position(
                room_id, *rails, still_wanted=lambda: self._holds_all(claims)
            )
        except BaseException:
            for device_id, serial in serials.items():
                self.async_forget_move(device_id, serial)
            raise
        if not sent:
            await self._async_move_each(dict.fromkeys(serials, rails), serials)
            return
        for device_id, serial in serials.items():
            self.async_watch_move(device_id, *rails, serial)

    def _shared_rails(
        self, blinds: dict[int, NormanPeripheralData], moves: dict[int, tuple[int, int]]
    ) -> tuple[int, int] | None:
        """The one pair a room request can send in place of ``moves``, if there is one.

        The request reaches every blind in the room, including any the move is not for (a
        single-rail blind, when the middle rails move), so those must be heading to the same
        bottom rail already. A single-rail blind's middle value is moot -- it has no middle
        rail to move -- so only the two-rail blinds have to agree on it.
        """
        if any(device.type not in ROOM_POSITION_TYPES for device in blinds.values()):
            return None
        bottoms = {
            moves[device_id][0] if device_id in moves else self.heading_rails(device_id)[0]
            for device_id in blinds
        }
        middles = {
            rails[1]
            for device_id, rails in moves.items()
            if has_middle_rail(blinds[device_id].type)
        }
        if len(bottoms) != 1 or len(middles) > 1:
            return None
        return bottoms.pop(), middles.pop() if middles else ROOM_MIDDLE_WITHOUT_TWO_RAIL

    async def _async_move_each(
        self,
        moves: dict[int, tuple[int, int]],
        serials: dict[int, int] | None = None,
        louvers: frozenset[int] = frozenset(),
    ) -> None:
        """Send each blind its own move, one after another.

        Every move is recorded before the first is sent, as ``async_move_blind`` does for one,
        so a command issued while these queue sees where each blind is going -- unless they
        were recorded already (``serials``: a room request or a scene that was dropped, sent
        blind by blind instead). A blind that another command takes over before its turn -- a
        stop, or a newer move -- is skipped. A Shutter in ``louvers`` is sent its louvers,
        the first value of its pair. A failure stops the rest, and the moves left unsent are
        forgotten.
        """
        pending = (
            {d: self.async_note_move(d, *rails) for d, rails in moves.items()}
            if serials is None
            else dict(serials)
        )
        try:
            for device_id, rails in moves.items():
                serial = pending[device_id]
                if not self.holds(device_id, serial):
                    del pending[device_id]
                    continue
                still_wanted = functools.partial(self.holds, device_id, serial)
                if device_id in louvers:
                    sent = await self.api.async_set_louvers(
                        device_id, rails[0], still_wanted=still_wanted
                    )
                    if sent:
                        self.async_watch_louvers(device_id, rails[0], serial)
                else:
                    sent = await self.api.async_set_position(
                        device_id, *rails, still_wanted=still_wanted
                    )
                    if sent:
                        self.async_watch_move(device_id, *rails, serial)
                del pending[device_id]
        finally:
            for device_id, serial in pending.items():
                self.async_forget_move(device_id, serial)

    @callback
    def async_watch_move(
        self, device_id: int, bottom: int, middle: int, serial: int | None = None
    ) -> None:
        """After a move, make sure the blind actually went -- without holding anything up.

        The hub acks a move it never transmits, so the only proof a blind acted is it
        reporting a new position (const.py, ``MOVE_TIMEOUT``). The watch runs in the
        background and costs nothing while it waits: it listens to the updates the hub pushes
        anyway and ends as soon as the blind reports it moved. Only a blind that stays silent
        is asked to report in, and only one that then shows it never moved is sent the move
        again (``_async_supervise``). A new move for the same blind replaces the watch; a
        stop cancels it. ``serial`` is the move's record (``async_note_move``), which ends
        with the watch; a move that lost its blind while it waited to be sent is not watched.
        """

        async def resend() -> None:
            await self.api.async_set_position(device_id, bottom, middle)

        self._async_start_watch(device_id, (bottom, middle), resend, "move", serial)

    @callback
    def async_watch_louvers(self, device_id: int, position: int, serial: int | None = None) -> None:
        """``async_watch_move`` for a Shutter: its louvers take the bottom rail's place."""

        async def resend() -> None:
            await self.api.async_set_louvers(device_id, position)

        self._async_start_watch(device_id, (position, None), resend, "louver", serial)

    @callback
    def async_watch_preset(
        self, device_id: int, resend: Callable[[], Awaitable[Any]], serial: int | None = None
    ) -> None:
        """After a preset verb (Best Privacy, Best View, Favorite), make sure it arrived.

        A preset has no position for the caller to aim at: the blind resolves it to its own
        stored one. The hub records that in its target fields as soon as it accepts the
        command -- for a command it then drops, too -- so the watch reads its goal from there
        first and then supervises it exactly like a move. ``serial`` is the one that took the
        blind over for the preset (``async_supersede``), if any.
        """
        self._async_start_watch(device_id, None, resend, "preset", serial)

    async def async_send_room_preset(self, room_id: int | None, fields: dict[str, Any]) -> None:
        """Send a preset to every blind in a room (every blind on the hub, for None).

        One request: the hub carries the command to each blind itself. It acks it whether or
        not each blind hears it, so every blind it reached is then watched as its own preset
        would be (``async_watch_preset``), and one that never moves is sent the preset on its
        own. Those watches are what catch a blind the command reached but whose report did
        not: on 2026-10-12 a blind closed for Best Privacy without the hub hearing it, and
        the hub showed it open, heading for closed, for two hours until it was asked to report
        in. A blind without a room and group to address it by is not watched.

        A command that takes one of the blinds over while the preset waits its turn drops it
        (``_still_holds``); the rest are then sent the preset blind by blind, at once.
        """
        serial = self.async_supersede_room(room_id, aimed=True)
        blinds = self.blinds_in(room_id)
        reply = await self.api.async_send_room_control(
            room_id, fields, still_wanted=self._still_holds(blinds, serial)
        )
        if reply is None:
            await self._async_preset_each(blinds, fields, serial)
            return
        # Every watch needs the targets the hub recorded on accepting the command, and one
        # read serves them all. The watches are registered now rather than after it, so a
        # stop or a move for one of these blinds meanwhile still replaces its watch.
        # A background task, so unloading the entry cancels it rather than waiting on it.
        targets_read = self.config_entry.async_create_background_task(
            self.hass, self.async_refresh(), name="norman-room-preset-read"
        )
        for device_id, device in self.blinds_in(room_id).items():
            if device.room_id is None or device.group_id is None:
                continue
            resend = functools.partial(
                self.api.async_send_blind_control,
                device.room_id,
                device.group_id,
                fields,
                device_id,
            )
            self._async_start_watch(device_id, None, resend, "preset", serial, targets_read)

    async def _async_preset_each(
        self, blinds: dict[int, NormanPeripheralData], fields: dict[str, Any], serial: int
    ) -> None:
        """Send a preset to each of these blinds still held as ``serial``, and watch it."""
        for device_id, device in blinds.items():
            if device.room_id is None or device.group_id is None:
                continue
            send = functools.partial(
                self.api.async_send_blind_control,
                device.room_id,
                device.group_id,
                fields,
                device_id,
                still_wanted=functools.partial(self.holds, device_id, serial),
            )
            if await send() is not None:
                self.async_watch_preset(device_id, send, serial)

    async def async_run_scene(self, scene: NormanScene) -> None:
        """Run a scene saved in one of the hub's rooms, then watch each of its blinds.

        One request runs the whole scene (``SetToScene``), and the hub sends each blind to
        the position the scene stored for it. The hub acks it whether or not every blind
        hears it, so each blind is then watched like a move of its own, aimed at that stored
        position: one that never moves is sent the position on its own, not the scene again.
        """
        await self._async_run_saved(
            self._scene_targets([scene]),
            lambda still_wanted: self.api.async_run_scene(
                scene.room_id, scene.scene_id, still_wanted=still_wanted
            ),
        )

    async def async_run_scene_group(self, group: NormanSceneGroup) -> None:
        """Run a group of room scenes, watching every blind its scenes send.

        A group needs this more than a room scene: in its one test, a member blind's target
        changed and the blind never moved (docs/NORMAN_API.md, "Run a saved scene"). A member
        scene the hub no longer lists is run by the hub as it sees fit and not watched.
        """
        members = [self.scenes[key] for key in group.scene_keys if key in self.scenes]
        await self._async_run_saved(
            self._scene_targets(members),
            lambda still_wanted: self.api.async_run_scene_group(
                group.group_id, still_wanted=still_wanted
            ),
        )

    def _scene_targets(self, scenes: Iterable[NormanScene]) -> dict[int, NormanSceneTarget]:
        """Where these scenes send each blind that the hub still reports."""
        devices = self.data or {}
        return {
            device_id: target
            for scene in scenes
            for device_id, target in scene.targets.items()
            if device_id in devices
        }

    async def _async_run_saved(
        self,
        targets: dict[int, NormanSceneTarget],
        send: Callable[[Callable[[], bool]], Awaitable[bool]],
    ) -> None:
        """Send a saved scene, then watch every blind in it.

        The scene replaces any move in flight for its blinds. Each blind's move is recorded
        before the request goes, as a room move's are (``async_note_move``), so a command for
        one of them right behind it keeps the scene's other rail. A Shutter is aimed at its
        stored louvers, every other blind at its stored rails. ``send`` is handed the check
        asked at the request's turn and before a busy hub's retry: whether the scene still
        holds every one of its blinds. Dropped, the scene is sent blind by blind to the rest.
        """
        await self.async_settle(targets)
        devices = self.data or {}
        targets = {
            device_id: target for device_id, target in targets.items() if device_id in devices
        }
        serial = self.async_supersede(targets, aimed=True)
        moves: dict[int, tuple[int, int]] = {}
        louvers: set[int] = set()
        for device_id, target in targets.items():
            device_type = devices[device_id].type
            if device_type == COVER_TYPE_SHUTTER:
                if target.position is not None:
                    moves[device_id] = (target.position, 0)
                    louvers.add(device_id)
            elif target.bottom is not None:
                middle = None if device_type == COVER_TYPE_SINGLE_RAIL else target.middle
                moves[device_id] = rails_to_send(
                    device_type, self.heading_rails(device_id), target.bottom, middle
                )
        serials = {
            device_id: self.async_note_move(device_id, *rails) for device_id, rails in moves.items()
        }
        claims: dict[int, int | None] = {
            device_id: serials.get(device_id, serial) for device_id in targets
        }
        try:
            sent = await send(lambda: self._holds_all(claims))
        except BaseException:
            for device_id, move_serial in serials.items():
                self.async_forget_move(device_id, move_serial)
            raise
        if not sent:
            await self._async_move_each(moves, serials, frozenset(louvers))
            return
        for device_id, rails in moves.items():
            if device_id in louvers:
                self.async_watch_louvers(device_id, rails[0], serials[device_id])
            else:
                self.async_watch_move(device_id, *rails, serials[device_id])

    @callback
    def _async_start_watch(
        self,
        device_id: int,
        goal: _Rails | None,
        resend: Callable[[], Awaitable[Any]],
        kind: str,
        serial: int | None = None,
        targets_read: Awaitable[None] | None = None,
    ) -> None:
        if serial is not None and not self.holds(device_id, serial):
            # A stop or a newer command took the blind over while this one waited to be
            # sent. Its watch would read the new heading as a command that never arrived.
            return
        self.async_cancel_move_watch(device_id)
        start = self._sighting(device_id)
        self._move_watchers[device_id] = self.config_entry.async_create_background_task(
            self.hass,
            self._async_supervise(device_id, start, goal, resend, serial, targets_read),
            name=f"norman-{kind}-watch-{device_id}",
        )

    @callback
    def async_cancel_move_watch(self, device_id: int) -> None:
        """Drop the watchdog for a blind (a stop means there is no target to reach)."""
        if task := self._move_watchers.pop(device_id, None):
            task.cancel()

    def _forget_move_watch(self, device_id: int) -> None:
        """Drop this blind's watcher entry, but only if it is still *this* task's.

        A replacement watcher (a second move while the first is pending) cancels its
        predecessor and takes the slot. The cancelled task's ``finally`` runs afterwards, so
        an unconditional ``pop`` would delete the replacement's entry and leave the live
        watcher untracked -- ``async_cancel_move_watch`` would then no longer be able to
        stop it. Comparing against the running task makes the cleanup order-independent.
        """
        try:
            current = asyncio.current_task()
        except RuntimeError:  # pragma: no cover - only outside a running loop
            current = None
        if self._move_watchers.get(device_id) in (current, None):
            self._move_watchers.pop(device_id, None)

    async def _async_supervise(
        self,
        device_id: int,
        start: _Sighting,
        goal: _Rails | None,
        resend: Callable[[], Awaitable[Any]],
        serial: int | None = None,
        targets_read: Awaitable[None] | None = None,
    ) -> None:
        """Confirm a command reached the blind, resending it only while the blind is silent.

        Each attempt waits up to ``MOVE_TIMEOUT`` for the blind to report that it moved. A
        blind that stays quiet is asked to report in (one ``StatusRequest``); if its answer
        shows it never moved, the command goes again. After ``MOVE_ATTEMPTS`` sends the blind
        is reported as not responding, with a warning in the log and a ``norman_command_failed``
        event. Nothing here holds up other commands: the requests it does send queue with
        everything else, paced like any other.
        """
        name = self._blind_name(device_id)
        try:
            if goal is None:
                # A preset: read the position the hub resolved it to, now. The hub replaces
                # its target with the blind's actual position whenever the blind reports in,
                # so a target read after asking the blind to report in always matches -- which
                # is how a dropped preset used to go unnoticed (2026-09-21). A
                # room- or hub-wide preset shares one read among its blinds; shielded, so a
                # watch replaced meanwhile does not cancel it for the rest.
                if targets_read is None:
                    await self._async_watch_read()
                else:
                    await asyncio.shield(targets_read)
                goal = self._hub_target(device_id)
                if goal is None:
                    return
            for attempt in range(1, MOVE_ATTEMPTS + 1):
                if await self._async_wait_for_progress(device_id, start, goal):
                    return
                # Silent for the whole travel time: ask the blind where it is.
                asked = self._sighting(device_id)
                await self.api.async_request_status(device_id)
                await self._async_wait_for_report(device_id, asked)
                if self._made_progress(device_id, start, goal):
                    return
                if attempt == MOVE_ATTEMPTS:
                    break
                _LOGGER.warning(
                    "%s reports it has not moved %.0f s after the command; sending it again "
                    "(attempt %s of %s)",
                    name,
                    MOVE_TIMEOUT + MOVE_REPORT_WAIT,
                    attempt + 1,
                    MOVE_ATTEMPTS,
                )
                # Measure the next attempt from where the blind has just said it is.
                start = self._sighting(device_id)
                await resend()
            self._async_command_failed(device_id, name, goal)
        except (NormanApiError, NormanConnectionError) as err:
            _LOGGER.warning("Could not confirm the command to %s: %s", name, err)
        finally:
            self._forget_move_watch(device_id)
            if serial is not None:
                self.async_forget_move(device_id, serial)

    async def _async_wait_for_progress(
        self, device_id: int, start: _Sighting, goal: _Rails
    ) -> bool:
        """Wait up to ``MOVE_TIMEOUT`` for the blind to report it moved towards ``goal``.

        Only a report made since the command counts early on: a blind still finishing an
        earlier move can be sitting on the new goal in the hub's cache without having heard
        the new command. Once the time is up, being at the goal is enough -- a blind that was
        already there has nothing to report.
        """
        if await self._async_wait_until(
            lambda: (
                self._heard_since(device_id, start) and self._made_progress(device_id, start, goal)
            ),
            MOVE_TIMEOUT,
        ):
            return True
        return self._made_progress(device_id, start, goal)

    async def _async_wait_for_report(self, device_id: int, asked: _Sighting) -> None:
        """Wait up to ``MOVE_REPORT_WAIT`` for the blind to answer a status request."""
        if not await self._async_wait_until(
            lambda: self._heard_since(device_id, asked), MOVE_REPORT_WAIT
        ):
            # The answer normally arrives as a notification that refreshes the data;
            # re-read in case it did not.
            await self._async_watch_read()

    async def _async_watch_read(self) -> None:
        """Re-read the hub for a watch, in a task of its own that the watch only waits on.

        A watch is cancelled whenever a stop or a newer command takes its blind over, and
        cancelling a task inside ``async_refresh`` marks the update failed: every entity of
        the hub would read unavailable, and Home Assistant would drop commands to them, until
        the next good read. Shielded, the read finishes whatever happens to the watch; a
        background task, it is cancelled when the entry unloads rather than waited for.
        """
        await asyncio.shield(
            self.config_entry.async_create_background_task(
                self.hass, self.async_refresh(), name="norman-watch-read"
            )
        )

    async def async_request_refresh(self) -> None:
        """Ask for a refresh, debounced, that its caller being cancelled cannot fail.

        The debouncer runs the first request at once, in the caller's task: every command
        asks for one, so an automation restarted mid-command (``mode: restart``) would
        cancel the read and mark the update failed, as a watch would (``_async_watch_read``).
        """
        await asyncio.shield(
            self.config_entry.async_create_background_task(
                self.hass, super().async_request_refresh(), name="norman-request-refresh"
            )
        )

    async def _async_wait_until(self, condition: Callable[[], bool], timeout: float) -> bool:
        """Wait until an update makes ``condition`` true, or ``timeout`` passes.

        Nothing is polled: the check runs on the refreshes the hub's notifications trigger
        anyway.
        """
        if condition():
            return True
        met = asyncio.Event()

        @callback
        def _check() -> None:
            if condition():
                met.set()

        remove = self.async_add_listener(_check)
        try:
            async with asyncio.timeout(timeout):
                await met.wait()
        except TimeoutError:
            return False
        finally:
            remove()
        return True

    def _sighting(self, device_id: int) -> _Sighting:
        """Where the hub last saw this blind, and when it last heard from it."""
        data = (self.data or {}).get(device_id)
        if data is None:
            return _Sighting((None, None), None)
        return _Sighting(_rails(data), data.last_update)

    def _heard_since(self, device_id: int, before: _Sighting) -> bool:
        """Whether the blind has reported in since ``before`` was taken.

        The hub's ``Timestamp`` moves on every report, moved or not. A hub that leaves it
        out falls back to the position changing.
        """
        now = self._sighting(device_id)
        if now.heard is not None and before.heard is not None:
            return now.heard != before.heard
        return now.rails != before.rails

    def _made_progress(self, device_id: int, start: _Sighting, goal: _Rails) -> bool:
        """At the goal, or nearer to it than when the command went out.

        Any movement towards the goal proves the blind received the command. One that stopped
        short -- an obstruction, a stall -- is not helped by being sent it again.
        """
        data = (self.data or {}).get(device_id)
        if data is None or _rails(data)[0] is None:
            return True  # gone from the hub, or no position to judge by; nothing to chase
        rails = _rails(data)
        # A rail that lands a point short is there: a blind sent to 25 has reported 24, and
        # one sent there again has nothing to move. A Shutter's louvers have eight steps, so
        # theirs must match.
        tolerance = 0 if data.type == COVER_TYPE_SHUTTER else ARRIVAL_TOLERANCE
        if _arrived(rails, goal, tolerance):
            return True
        return _distance(rails, goal) < _distance(start.rails, goal)

    def _hub_target(self, device_id: int) -> _Rails | None:
        """The position the hub has recorded as this blind's target, if any."""
        data = (self.data or {}).get(device_id)
        if data is None:
            return None
        targets = _targets(data)
        return None if targets[0] is None else targets

    def _blind_name(self, device_id: int) -> str:
        data = (self.data or {}).get(device_id)
        return data.name if data is not None else str(device_id)

    @callback
    def _async_command_failed(self, device_id: int, name: str, goal: _Rails) -> None:
        """Log, and tell any automation listening, that a blind ignored every send.

        A log line rather than a repair issue: one command going unanswered is not a
        condition the user has to fix, and a flat battery already shows on the blind's
        battery sensor.
        """
        _LOGGER.warning(
            "%s did not move after %s attempts; giving up. Check its battery and that it is "
            "in range of the hub",
            name,
            MOVE_ATTEMPTS,
        )
        data = (self.data or {}).get(device_id)
        # A Shutter's goal is its louvers, not a rail (see _rails).
        louvers = data is not None and data.type == COVER_TYPE_SHUTTER
        self.hass.bus.async_fire(
            EVENT_COMMAND_FAILED,
            {
                "device_id": self._registry_device_id(device_id),
                "peripheral_uid": device_id,
                "name": name,
                "attempts": MOVE_ATTEMPTS,
                "bottom_rail_position": None if louvers else goal[0],
                "middle_rail_position": goal[1],
                "louver_position": goal[0] if louvers else None,
            },
        )

    def _registry_device_id(self, device_id: int) -> str | None:
        """The Home Assistant device id for a blind, for automations to match on."""
        registry = dr.async_get(self.hass)
        # Looked up through the entry: identifiers are no longer unique across config
        # entries in Home Assistant 2026.9 (see _sync_device_names).
        for device in dr.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            if (DOMAIN, str(device_id)) in device.identifiers:
                return device.id
        return None

    async def listen_notifications(self) -> None:
        """Continuously listen for hub notifications and refresh data on change.

        Runs as a config-entry background task; cancellation ends the loop.
        """
        while True:
            # Whether the device list is read again before the next connection: after a
            # stream cycle or the first failure, but not on every retry of an outage. The
            # list is large, and the hub's reader for it is the part that fails.
            reread = True
            try:
                async for notification in self.api.async_listen_notifications():
                    _LOGGER.debug("Received notification: %s", notification)
                    if self._listener_offline:
                        self._listener_offline = False
                        _LOGGER.info("Norman hub notification stream restored")
                        # Anything renamed or paired while the stream was down.
                        self._device_info_stale = True
                    if self._structure_changed(notification):
                        # A rename, room edit, or hub rename in the Norman app: re-read
                        # the device list so names and rooms follow. Keep the last good
                        # tree if that read fails; status can still update the blinds.
                        self._device_info_stale = True
                    # Debounced rather than immediate: the hub answers a sweep with one
                    # notification *per blind* over ~30 s (docs/NORMAN_API.md, "Waking a
                    # blind"), so a thirteen-blind hub would otherwise fire thirteen full
                    # status reads in a burst -- contending with the very radio the control
                    # pacing exists to protect. The debouncer is immediate=True, so the
                    # first notification still refreshes at once and the rest coalesce.
                    await self.async_request_refresh()
            except NormanConnectionError as err:
                if not self._listener_offline:
                    self._listener_offline = True
                    _LOGGER.error(
                        "Notification listener disconnected: %s; retrying every %s seconds",
                        err,
                        RECONNECT_INTERVAL,
                    )
                else:
                    _LOGGER.debug("Notification listener still down: %s", err)
                    reread = False
                await asyncio.sleep(RECONNECT_INTERVAL)
            except Exception:  # noqa: BLE001 - the listener must outlive any single failure
                # A poll, if one is set, would keep state moving, but at a fraction of the
                # push path's responsiveness, and none is set by default. Letting an
                # unexpected error escape the loop would leave the integration loaded and
                # apparently healthy while every change made at a remote or in the app went
                # unnoticed -- a far worse failure than a logged exception and a retry. The
                # refresh inside the try above reaches the device registry, so this is not
                # merely theoretical.
                _LOGGER.exception(
                    "Unexpected error in the Norman notification listener; retrying in %s seconds",
                    RECONNECT_INTERVAL,
                )
                await asyncio.sleep(RECONNECT_INTERVAL)
            else:
                # The stream was cycled on purpose after NOTIF_MAX_DURATION; reconnect
                # right away. A full cycle is a working stream, whether or not anything
                # moved during it, so an outage before it is over.
                if self._listener_offline:
                    self._listener_offline = False
                    _LOGGER.info("Norman hub notification stream restored")
                    self._device_info_stale = True
                _LOGGER.debug("Reconnecting notification listener")

            # Re-read the hub before the next connection so anything that changed while the
            # stream was down (or a newly paired blind) is picked up.
            if reread:
                self._device_info_stale = True
            await self.async_refresh()

    @staticmethod
    def _structure_changed(notification: dict[str, Any]) -> bool:
        """Whether a notification says the room / blind / hub metadata changed.

        ``UpdateTime`` carries one key per changed thing: ``room``, ``peripheral``,
        ``device`` (the hub itself), or ``schedule``. Schedules are not modelled, so they
        do not invalidate anything.
        """
        update = notification.get("UpdateTime")
        if not isinstance(update, dict):
            return False
        return any(key != "schedule" for key in update)

    async def _async_update_data(self) -> NormanDevices:
        """Fetch data from API.

        Returns:
            Dictionary with peripheral data keyed by device ID

        Raises:
            UpdateFailed: If the update operation fails

        """
        try:
            # A hub can keep answering status while its configuration reader returns
            # "Request process fail." Keep the last good tree, or use status-only
            # placeholders on first setup, and retry the structure read next refresh.
            if self._device_info_stale and time.monotonic() >= self._next_device_info_retry:
                try:
                    self._device_info = await self.api.async_get_devices()
                except (NormanConnectionError, NormanApiError) as err:
                    self._next_device_info_retry = time.monotonic() + DEVICE_LIST_RETRY_INTERVAL
                    if not self._device_info_error_logged:
                        _LOGGER.warning(
                            "Norman hub device list unavailable: %s; using status and cached names",
                            err,
                        )
                        self._device_info_error_logged = True
                    else:
                        _LOGGER.debug("Norman hub device list still unavailable: %s", err)
                else:
                    self._device_info_stale = False
                    self._next_device_info_retry = 0.0
                    if self._device_info_error_logged:
                        _LOGGER.info("Norman hub device list restored")
                        self._device_info_error_logged = False
                    # The scenes live in the device list, so they change only when it does.
                    if self._device_info:
                        self.scenes, self.scene_groups = _parse_scenes(self._device_info)

            # Status is the lightweight call that carries positions
            status_data = await self.api.async_get_status()
        except NormanConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="connect_failed",
                translation_placeholders={"hub": self.config_entry.title, "error": str(err)},
            ) from err
        except NormanApiError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="hub_read_failed",
                translation_placeholders={"hub": self.config_entry.title, "error": str(err)},
            ) from err

        self._log_unknown_fields(self._device_info, status_data)
        self._update_hub_data(self._device_info, status_data)
        devices = self._process_data(self._device_info, status_data)
        if not self._device_info:
            self._keep_registry_names(devices)
        self._warn_about_unknown_module_types(devices)
        self._sync_device_names(devices)
        return devices

    def _keep_registry_names(self, devices: NormanDevices) -> None:
        """Name status-only placeholders as the device registry already has them.

        Without the device list every blind is ``Norman <uid>``, every room ``Room <id>``,
        and the hub has no custom name (setup would fall back to the entry title). A restart
        while the hub cannot read its configuration would otherwise push those placeholders
        over the names the registry kept from the last good read.
        """
        registry = dr.async_get(self.hass)
        known: dict[str, str] = {}
        areas: dict[str, str | None] = {}
        for device in dr.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            for domain, identifier in device.identifiers:
                if domain != DOMAIN:
                    continue
                areas[identifier] = device.area_id
                if device.name:
                    known[identifier] = device.name
        if not self.hub.custom_name:
            self.hub.custom_name = known.get(hub_identifier(self.config_entry))
        for device_id, data in devices.items():
            data.name = known.get(str(device_id), data.name)
            if data.room_id is not None and not data.room_name:
                room_name = known.get(room_identifier(self.config_entry, data.room_id))
                # A placeholder kept from an earlier unreadable start is not the hub's name
                if room_name != f"Room {data.room_id}":
                    data.room_name = room_name
        self._name_rooms_after_areas(devices, areas)

    def _name_rooms_after_areas(self, devices: NormanDevices, areas: dict[str, str | None]) -> None:
        """Name a room the hub cannot name after the one area all of its blinds are in.

        Home Assistant keeps a blind's area across a restart and restores it when the
        integration is re-added, so the blinds still say where a room is. A room whose
        blinds are spread over several areas, or not placed yet, keeps its placeholder.
        """
        unnamed: dict[int, set[str | None]] = {}
        for device_id, data in devices.items():
            if data.room_id is not None and not data.room_name:
                unnamed.setdefault(data.room_id, set()).add(areas.get(str(device_id)))
        area_registry = ar.async_get(self.hass)
        self._room_areas = {}
        for room_id, room_areas in unnamed.items():
            area_id = room_areas.pop() if len(room_areas) == 1 else None
            area = area_registry.async_get_area(area_id) if area_id else None
            if area is None:
                continue
            self._room_areas[room_id] = area.id
            for data in devices.values():
                if data.room_id == room_id:
                    data.room_name = area.name

    @callback
    def async_apply_registry_names(self) -> None:
        """Re-run the registry fallbacks once the platforms have created their devices.

        The first refresh runs before the blinds' devices exist, and on a re-add before
        Home Assistant has restored their areas, so the rooms can only be named after that.
        """
        if self._device_info or self.data is None:
            return
        self._keep_registry_names(self.data)
        self._sync_device_names(self.data)
        self.async_update_listeners()

    def _sync_device_names(self, devices: NormanDevices) -> None:
        """Carry renames made in the Norman app into the device registry.

        Devices are named when they are created and Home Assistant does not re-read
        ``DeviceInfo`` afterwards, so the hub's names are pushed here. A name the user set
        in Home Assistant (``name_by_user``) is untouched: it always takes precedence. A room
        named after its blinds' area is also put in that area, unless it already has one.
        """
        registry = dr.async_get(self.hass)
        wanted = {str(device_id): data.name for device_id, data in devices.items()}
        for room_id, room_name in rooms_of(devices).items():
            wanted[room_identifier(self.config_entry, room_id)] = room_name
        # A room holding only scenes is named after them.
        for scene in self.scenes.values():
            if scene.room_name:
                wanted.setdefault(
                    room_identifier(self.config_entry, scene.room_id), scene.room_name
                )
        if self.hub_device_id and self.hub.custom_name:
            wanted[hub_identifier(self.config_entry)] = self.hub.custom_name
        # Devices are looked up through the entry rather than by identifier: identifiers
        # are no longer unique across config entries in Home Assistant 2026.9.
        room_areas = {
            room_identifier(self.config_entry, room_id): area_id
            for room_id, area_id in self._room_areas.items()
        }
        for device in dr.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            for domain, identifier in device.identifiers:
                if domain != DOMAIN:
                    continue
                name = wanted.get(identifier)
                if name and device.name != name:
                    if identifier == hub_identifier(self.config_entry):
                        self._async_retitle(device.name, name)
                    registry.async_update_device(device.id, name=name)
                area_id = room_areas.get(identifier)
                if area_id and device.area_id is None:
                    registry.async_update_device(device.id, area_id=area_id)
        # Placed once: a room taken out of its area afterwards is not put back
        self._room_areas = {}

    @callback
    def _async_retitle(self, previous: str | None, name: str) -> None:
        """Follow a hub renamed in the Norman app with the entry's title, as setup does.

        Only a title the integration gave moves: the default ``Norman Hub (<host>)`` or the
        hub's previous name. One chosen in Home Assistant stays.
        """
        title = self.config_entry.title
        if title != name and (is_default_title(title) or title == previous):
            self.hass.config_entries.async_update_entry(self.config_entry, title=name)

    def _update_hub_data(self, device_info: dict[str, Any], status_data: dict[str, Any]) -> None:
        """Refresh the hub's own attributes from the two payloads."""
        results = device_info.get("results")
        if isinstance(results, dict):
            self.hub.custom_name = results.get("CustomDeviceName") or self.hub.custom_name
            # As reported, not kept from an earlier read: a hub has been seen to lose its time
            # zone and regain it for a while, and the sensor should show which
            self.hub.time_zone = results.get("TimeZone") or None
        self.hub.model = self.api.hub_model or self.hub.model
        self.hub.firmware_version = self.api.hub_firmware_version or self.hub.firmware_version
        self.hub.wifi_ssid = self.api.hub_wifi_ssid or self.hub.wifi_ssid
        rssi = status_data.get("WiFiRSSI")
        self.hub.wifi_rssi = int(rssi) if isinstance(rssi, int | float) else None
        ota = status_data.get("OTA")
        self.hub.ota_in_progress = bool(ota) if ota is not None else None
        pairing = status_data.get("PairingMode")
        self.hub.pairing_mode = int(pairing) if isinstance(pairing, int) else None

    def _log_unknown_fields(self, *payloads: dict[str, Any]) -> None:
        """Note any field the hub sends that this integration has never seen.

        The hub's protocol is reverse-engineered, so a firmware update or an unmapped
        product can start sending fields nobody has documented. Each new name is logged once
        per Home Assistant run at debug level (not warning: an unknown field is interesting,
        not a problem) so that turning on debug logging for a while is enough to find them.
        """
        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        for payload in payloads:
            results = payload.get("results")
            top: dict[str, Any] = results if isinstance(results, dict) else payload
            self._note_unknown("hub", KNOWN_HUB_FIELDS, top)
            for peripheral in top.get("Peripherals") or []:
                if isinstance(peripheral, dict):
                    self._note_unknown("peripheral", KNOWN_PERIPHERAL_FIELDS, peripheral)
            for scene_group in top.get("SceneGroupList") or []:
                if not isinstance(scene_group, dict):
                    continue
                self._note_unknown("scene group", KNOWN_SCENE_GROUP_FIELDS, scene_group)
                for item in scene_group.get("SceneList") or []:
                    if isinstance(item, dict):
                        self._note_unknown("scene group item", KNOWN_SCENE_GROUP_ITEM_FIELDS, item)
            for room in top.get("RoomList") or []:
                if not isinstance(room, dict):
                    continue
                for scene in room.get("SceneList") or []:
                    if not isinstance(scene, dict):
                        continue
                    self._note_unknown("scene", KNOWN_SCENE_FIELDS, scene)
                    for target in scene.get("PeripheralList") or []:
                        if isinstance(target, dict):
                            self._note_unknown("scene target", KNOWN_SCENE_TARGET_FIELDS, target)
                for group in room.get("GroupList") or []:
                    if not isinstance(group, dict):
                        continue
                    for peripheral in group.get("PeripheralList") or []:
                        if isinstance(peripheral, dict):
                            self._note_unknown("peripheral", KNOWN_PERIPHERAL_FIELDS, peripheral)

    def _note_unknown(self, scope: str, known: frozenset[str], payload: dict[str, Any]) -> None:
        """Log each field in ``payload`` that is not in ``known``, once per name."""
        for field in payload:
            if field in known or (scope, field) in self._unknown_fields:
                continue
            self._unknown_fields.add((scope, field))
            _LOGGER.debug(
                "Norman hub sent an undocumented %s field %r (value %r). Please open an issue "
                "at https://github.com/kedube/ha-norman/issues so it can be documented",
                scope,
                field,
                payload[field],
            )

    def _warn_about_unknown_module_types(self, devices: NormanDevices) -> None:
        """Log once per unknown ModuleType so owners can report it."""
        for device in devices.values():
            if (
                device.module_type in MODULE_TYPE_COVER_TYPES
                or device.module_type in self._unknown_module_types
            ):
                continue
            self._unknown_module_types.add(device.module_type)
            _LOGGER.warning(
                "Norman peripheral %s (%s) reports unknown ModuleType %s/%s; treating it as a "
                "two-rail blind. Please run the norman.get_hub_data action and open an issue "
                "with the result so the type can be mapped",
                device.id,
                device.name,
                device.module_type,
                device.module_detail,
            )

    @staticmethod
    def _process_data(device_info: dict[str, Any], status_data: dict[str, Any]) -> NormanDevices:
        """Process and combine data from GetAllPeripheral and status endpoints.

        Args:
            device_info: Data from GetAllPeripheral endpoint
            status_data: Data from status endpoint

        Returns:
            Combined data keyed by device ID

        """
        devices: NormanDevices = {}

        # Process device information (names, room, group)
        results = device_info.get("results")
        room_list = results.get("RoomList") if isinstance(results, dict) else None
        for room in _dicts(room_list):
            room_id = room.get("RoomID")
            room_name = room.get("RoomName", "")

            for group in _dicts(room.get("GroupList")):
                group_id = group.get("GroupID")
                group_name = group.get("GroupName", "")

                for peripheral in _dicts(group.get("PeripheralList")):
                    peripheral_uid = _parse_uid(peripheral.get("PeripheralUID"))
                    if peripheral_uid is None:
                        continue

                    module_type = _parse_int(peripheral.get("ModuleType"))
                    module_detail = _parse_int(peripheral.get("ModuleDetail"))
                    devices[peripheral_uid] = NormanPeripheralData(
                        id=peripheral_uid,
                        name=peripheral.get("PeripheralName") or f"Norman {peripheral_uid}",
                        type=cover_type(module_type, module_detail),
                        room_id=_parse_int(room_id),
                        room_name=room_name,
                        group_id=_parse_int(group_id),
                        group_name=group_name,
                        module_type=module_type,
                        module_detail=module_detail,
                        stack=_parse_stack(peripheral.get("MSDStackType")),
                    )

        # Add status information
        for peripheral in _dicts(status_data.get("Peripherals")):
            peripheral_uid = _parse_uid(peripheral.get("PeripheralUID"))
            if peripheral_uid is None:
                continue

            if peripheral_uid not in devices:
                # Create minimal device if not found in device_info
                module_type = _parse_int(peripheral.get("ModuleType"))
                module_detail = _parse_int(peripheral.get("ModuleDetail"))
                devices[peripheral_uid] = NormanPeripheralData(
                    id=peripheral_uid,
                    name=f"Norman {peripheral_uid}",
                    type=cover_type(module_type, module_detail),
                    room_id=_parse_int(peripheral.get("RoomID")),
                    group_id=_parse_int(peripheral.get("GroupID")),
                    module_type=module_type,
                    module_detail=module_detail,
                )

            device = devices[peripheral_uid]
            device.bottom_rail_position = _parse_position(peripheral.get("BottomRailPosition"))
            device.middle_rail_position = _parse_position(peripheral.get("MiddleRailPosition"))
            device.target_bottom_rail_position = _parse_position(
                peripheral.get("TargetBottomRailPosition")
            )
            device.target_middle_rail_position = _parse_position(
                peripheral.get("TargetMiddleRailPosition")
            )
            device.position = _parse_louvers(peripheral.get("Position"))
            device.target_position = _parse_louvers(peripheral.get("TargetPosition"))
            # Despite its name the field is a 0-100 level on every hub seen so far
            device.battery_level = _parse_position(peripheral.get("BatteryVoltage"))
            device.signal_strength = _parse_int(peripheral.get("RssiMean"))
            device.firmware_version = peripheral.get("FirmwareVersion") or None
            device.rf_firmware_version = peripheral.get("RfFirmwareVersion") or None
            device.last_update = peripheral.get("Timestamp")

        return devices


def cover_type(module_type: int | None, module_detail: int | None = None) -> str:
    """The cover type for a ModuleType/ModuleDetail, defaulting when the type is unknown."""
    if module_type is None:
        return DEFAULT_COVER_TYPE
    if module_detail is not None and (module_type, module_detail) in MODULE_DETAIL_COVER_TYPES:
        return MODULE_DETAIL_COVER_TYPES[(module_type, module_detail)]
    return MODULE_TYPE_COVER_TYPES.get(module_type, DEFAULT_COVER_TYPE)


def _dicts(raw: Any) -> list[dict[str, Any]]:
    """The dict entries of ``raw``, or an empty list if it is not a list of dicts.

    The hub's payloads are reverse-engineered and unvalidated, so a firmware change (or a
    partial write) can put a string, a null, or a scalar where a list of objects belongs.
    Reaching ``.get()`` on one of those raises AttributeError out of ``_async_update_data``,
    which Home Assistant catches -- but only by logging a stack trace and marking EVERY
    entity on the hub unavailable, for what may be one malformed record among twenty.
    Skipping what cannot be read keeps the rest of the house working, and matches the
    isinstance guards ``_log_unknown_fields`` already applies to the same structures.
    """
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _parse_scenes(
    device_info: dict[str, Any],
) -> tuple[dict[str, NormanScene], dict[str, NormanSceneGroup]]:
    """The scenes and scene groups saved on the hub, from ``GetAllPeripheral``.

    Each room's ``SceneList`` holds its scenes, each sending some of the room's blinds to
    stored positions, and ``SceneGroupList`` holds groups of room scenes. The hub stores
    every value in them as a string, ids and positions included (docs/NORMAN_API.md). A
    scene whose id is not a number is left out, since ``SetToScene`` takes the id as one,
    and so is a group without an id. A missing name is left empty: the scene entity is then
    called what its kind is called, translated.
    """
    results = device_info.get("results")
    if not isinstance(results, dict):
        return {}, {}
    scenes: dict[str, NormanScene] = {}
    for room in _dicts(results.get("RoomList")):
        room_id = _parse_int(room.get("RoomID"))
        if room_id is None:
            continue
        for raw in _dicts(room.get("SceneList")):
            scene_id = _parse_int(raw.get("SceneID"))
            if scene_id is None:
                continue
            targets: dict[int, NormanSceneTarget] = {}
            for target in _dicts(raw.get("PeripheralList")):
                device_id = _parse_uid(target.get("PeripheralUID"))
                if device_id is None:
                    continue
                targets[device_id] = NormanSceneTarget(
                    bottom=_parse_position(target.get("BottomRailPosition")),
                    middle=_parse_position(target.get("MiddleRailPosition")),
                    position=_parse_louvers(target.get("Position")),
                )
            scene = NormanScene(
                room_id=room_id,
                scene_id=scene_id,
                name=str(raw.get("SceneName") or ""),
                targets=targets,
                room_name=str(room.get("RoomName") or ""),
            )
            scenes[scene.key] = scene
    groups: dict[str, NormanSceneGroup] = {}
    for raw in _dicts(results.get("SceneGroupList")):
        group_id = raw.get("SceneGroupID")
        if not isinstance(group_id, str) or not group_id:
            continue
        members = []
        for item in _dicts(raw.get("SceneList")):
            room_id = _parse_int(item.get("RoomID"))
            scene_id = _parse_int(item.get("SceneID"))
            if room_id is not None and scene_id is not None:
                members.append(scene_key(room_id, scene_id))
        groups[group_id] = NormanSceneGroup(
            group_id=group_id,
            name=str(raw.get("SceneGroupName") or ""),
            scene_keys=members,
        )
    return scenes, groups


def _parse_int(raw: Any) -> int | None:
    """Coerce a value the hub sends as int in one payload and str in another.

    ``bool`` is rejected explicitly: it is an ``int`` subclass, so a stray ``true`` would
    otherwise become 1 and read as a real id or position.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# A PeripheralUID parses exactly like any other hub int; the alias keeps the call sites
# reading as what they are without a second identical implementation to keep in step.
_parse_uid = _parse_int


def _parse_position(raw: Any) -> int | None:
    """Coerce a rail position to an int clamped to 0-100, or None if unusable."""
    value = _parse_int(raw)
    return None if value is None else max(0, min(100, value))


def _parse_stack(raw: Any) -> str | None:
    """A SmartDrape's stack side from ``MSDStackType``, by name or the app's number."""
    if raw is None:
        return None
    return MSD_STACK_SIDES.get(str(raw).strip().lower())


def _parse_louvers(raw: Any) -> int | None:
    """Coerce a Shutter's louver position to an int clamped to 0-7, or None if unusable."""
    value = _parse_int(raw)
    return None if value is None else max(0, min(SHUTTER_CLOSED, value))
