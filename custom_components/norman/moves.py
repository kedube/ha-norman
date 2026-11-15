"""Where each blind is heading, and making sure the commands sent to it arrive.

The hub acks a command it never transmits (const.py, ``MOVE_TIMEOUT``), and commands for the
same blind can wait their turn in the control queue together. This module holds what keeps
them straight, mixed into ``NormanCoordinator`` (``MoveTracker``):

- the rails each move in flight was sent to (``async_note_move``), so a second move right
  behind it fills its other rail in from the first rather than from a stale hub target;
- which command last took each blind over (``holds``, ``async_supersede``), so one that
  waited its turn is dropped rather than sent after a stop or a newer command;
- the move watchdog (``async_watch_move`` and ``_async_supervise``), which asks a silent
  blind to report in and sends the command again only if it never moved;
- when each blind set off for a target it has not reached (``travelling``), for the
  covers' opening and closing states.

The rail arithmetic every move shares (``rails_to_send``, ``has_middle_rail``, ...) is here
too, so the covers, the sliders and the room commands cannot drift apart.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any, NamedTuple

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .api import NormanApiClient, NormanApiError, NormanConnectionError
from .const import (
    ARRIVAL_TOLERANCE,
    COVER_TYPE_SHEER,
    COVER_TYPE_SHUTTER,
    COVER_TYPE_SINGLE_RAIL,
    COVER_TYPE_TWO_RAIL,
    DOMAIN,
    EVENT_COMMAND_FAILED,
    MOVE_ATTEMPTS,
    MOVE_REPORT_WAIT,
    MOVE_TIMEOUT,
    MOVE_WINDOW,
)
from .models import NormanDevices, NormanPeripheralData

if TYPE_CHECKING:
    from .coordinator import NormanConfigEntry

_LOGGER = logging.getLogger(__name__)


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

    A PerfectSheer's vanes open only with the shade fully down. The hub accepts a tilt sent
    with the shade raised, then sets the vane target back to 0 by itself, and the vanes never
    move (issue #6). So opening the vanes lowers the shade first, as the hub does when sent
    both, and raising the shade closes them, which the hub would do anyway. Sending what the
    hub will report also lets the move watchdog see the move arrive. Where both are asked,
    as a scene does, the shade's position wins, as it does at the hub.
    """
    bottom_val = heading[0] if bottom is None else clamp_position(bottom)
    middle_val = heading[1] if middle is None else clamp_position(middle)
    if cover_type == COVER_TYPE_TWO_RAIL:
        if middle is None:
            middle_val = max(middle_val, bottom_val)
        elif bottom is None:
            bottom_val = min(bottom_val, middle_val)
    elif cover_type == COVER_TYPE_SHEER and bottom_val and middle_val:
        if bottom is None:
            bottom_val = 0
        else:
            middle_val = 0
    return bottom_val, middle_val


def _first_known(*values: int | None) -> int:
    """The first of ``values`` that is known, or 100 (fully open) if none is."""
    return next((value for value in values if value is not None), 100)


class MoveTracker:
    """The move records and the watchdog, for ``NormanCoordinator`` to mix in.

    It reads the coordinator's data and client, and waits on its updates, so it declares
    what it uses from it here; ``_init_move_tracking`` sets up its own state.
    """

    # Provided by the coordinator this is mixed into.
    hass: HomeAssistant
    api: NormanApiClient
    config_entry: NormanConfigEntry
    data: NormanDevices

    if TYPE_CHECKING:

        async def async_refresh(self) -> None:
            """Re-read the hub (DataUpdateCoordinator)."""

        def async_add_listener(
            self, update_callback: CALLBACK_TYPE, context: Any = None
        ) -> Callable[[], None]:
            """Call ``update_callback`` after every update (DataUpdateCoordinator)."""

        def async_update_listeners(self) -> None:
            """Tell every listener the data changed (DataUpdateCoordinator)."""

    def _init_move_tracking(self, entry: NormanConfigEntry) -> None:
        """Set up the move records; called once from the coordinator's ``__init__``."""
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
        # Each blind heading for a target it has not reached, with the target and when it set
        # off, for the covers' opening and closing states (travelling). One timer redraws
        # them when the next of these runs out of MOVE_WINDOW.
        self._headings: dict[int, tuple[_Rails, datetime]] = {}
        self._heading_timer: CALLBACK_TYPE | None = None
        entry.async_on_unload(self._async_cancel_heading_timer)

    def _still_holds(self, device_ids: Iterable[int], serial: int) -> Callable[[], bool]:
        """The check a command for these blinds, taken over as ``serial``, is sent under."""
        claims: dict[int, int | None] = dict.fromkeys(device_ids, serial)
        return lambda: self._holds_all(claims)

    def travelling(self, device_id: int) -> bool:
        """Whether a blind is on its way to a target it has not reached yet.

        From when the hub first shows the target until the blind reports it is there, or
        ``MOVE_WINDOW`` passes: a blind that missed the command leaves the hub showing the
        target, unreached, until it next reports in, which can be hours.
        """
        heading = self._headings.get(device_id)
        if heading is None:
            return False
        return (dt_util.utcnow() - heading[1]).total_seconds() < MOVE_WINDOW

    @callback
    def _track_headings(self, devices: NormanDevices) -> None:
        """Note when each blind set off for a target it has not reached (``travelling``)."""
        now = dt_util.utcnow()
        for device_id, data in devices.items():
            targets = _targets(data)
            heading = any(
                target is not None and target != rail
                for rail, target in zip(_rails(data), targets, strict=True)
            )
            if not heading:
                self._headings.pop(device_id, None)
            elif (known := self._headings.get(device_id)) is None or known[0] != targets:
                self._headings[device_id] = (targets, now)
        for device_id in set(self._headings) - set(devices):
            del self._headings[device_id]
        self._async_schedule_heading_expiry(now)

    @callback
    def _async_schedule_heading_expiry(self, now: datetime) -> None:
        """Redraw the covers when the next blind's ``MOVE_WINDOW`` runs out."""
        self._async_cancel_heading_timer()
        ends = [
            seconds
            for _, since in self._headings.values()
            if (seconds := MOVE_WINDOW - (now - since).total_seconds()) > 0
        ]
        if not ends:
            return

        @callback
        def _expired(_now: datetime) -> None:
            self._heading_timer = None
            self.async_update_listeners()
            self._async_schedule_heading_expiry(dt_util.utcnow())

        self._heading_timer = async_call_later(self.hass, min(ends), _expired)

    @callback
    def _async_cancel_heading_timer(self) -> None:
        if self._heading_timer is not None:
            self._heading_timer()
            self._heading_timer = None

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
