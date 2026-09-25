"""Data update coordinator for Norman devices."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
import logging
from typing import Any, NamedTuple

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NormanApiClient, NormanApiError, NormanConnectionError
from .const import (
    CONF_CONTROL_INTERVAL,
    CONF_POLL_INTERVAL,
    CONF_WAKE_INTERVAL,
    COVER_TYPE_SINGLE_RAIL,
    DEFAULT_CONTROL_INTERVAL,
    DEFAULT_COVER_TYPE,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_WAKE_INTERVAL,
    DOMAIN,
    EVENT_COMMAND_FAILED,
    ISSUE_BLIND_NOT_RESPONDING,
    KNOWN_HUB_FIELDS,
    KNOWN_PERIPHERAL_FIELDS,
    MAX_CONTROL_INTERVAL,
    MAX_POLL_INTERVAL,
    MAX_WAKE_INTERVAL,
    MIN_CONTROL_INTERVAL,
    MIN_POLL_INTERVAL,
    MIN_WAKE_INTERVAL,
    MODULE_TYPE_COVER_TYPES,
    MOVE_ATTEMPTS,
    MOVE_REPORT_WAIT,
    MOVE_TIMEOUT,
    POLL_DISABLED,
    RECONNECT_INTERVAL,
    WAKE_DISABLED,
)
from .models import NormanDevices, NormanHubData, NormanPeripheralData

_LOGGER = logging.getLogger(__name__)

type NormanConfigEntry = ConfigEntry[NormanCoordinator]

# A blind's two rails, (bottom, middle); the middle is None on a single-rail blind.
type _Rails = tuple[int | None, int | None]


class _Sighting(NamedTuple):
    """Where the hub last saw a blind, and when it last heard from it (its ``Timestamp``)."""

    rails: _Rails
    heard: Any


def _rails(data: NormanPeripheralData) -> _Rails:
    middle = None if data.type == COVER_TYPE_SINGLE_RAIL else data.middle_rail_position
    return (data.bottom_rail_position, middle)


def _distance(rails: _Rails, goal: _Rails) -> int:
    """How far the rails are from the goal, over the rails both sides have a value for."""
    return sum(
        abs(rail - target)
        for rail, target in zip(rails, goal, strict=True)
        if rail is not None and target is not None
    )


def _not_responding_issue_id(device_id: int) -> str:
    return f"{ISSUE_BLIND_NOT_RESPONDING}_{device_id}"


def hub_identifier(entry: ConfigEntry) -> str:
    """Device-registry identifier of the hub device for ``entry``."""
    return f"hub_{entry.entry_id}"


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
    notification, reconnect, and command triggers a refresh. A slow poll backs that up,
    because a sleeping blind generates no notifications and its cached position would
    otherwise go stale without ever being corrected. The interval is configurable in the
    integration's options; the entry is reloaded when it changes.
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
        self._unknown_fields: set[tuple[str, str]] = set()
        self._unknown_module_types: set[int | None] = set()
        # True while the notification stream is known to be down, so that the outage is
        # logged once at error level rather than on every reconnect attempt.
        self._listener_offline = False
        # One move watchdog per blind (see async_watch_move); a new move replaces it.
        self._move_watchers: dict[int, asyncio.Task[None]] = {}

    @callback
    def async_start_wake_sweep(self) -> None:
        """Schedule the wake sweep at the configured interval, if any.

        Called once from setup; the timer is removed when the entry unloads. A changed
        interval is applied by reloading the entry, like the poll interval.
        """
        interval = _wake_interval(self.config_entry)
        if interval is None:
            return

        async def _sweep(_now: datetime) -> None:
            try:
                await self.async_refresh_blinds()
            except (NormanApiError, NormanConnectionError) as err:
                _LOGGER.warning("Wake sweep failed: %s", err)

        self.config_entry.async_on_unload(
            async_track_time_interval(self.hass, _sweep, interval, name="norman-wake-sweep")
        )

    async def async_refresh_blinds(self, room_id: int | None = None) -> None:
        """Have every blind (in a room, or on the hub) report in.

        The hub-wide ``ReportBatteryLevel`` sweep reaches only the battery (two-rail) blinds:
        on the reference hub the four single-rail blinds ignored it every time, while a
        per-blind ``StatusRequest`` had one answering in four seconds. So the sweep is
        followed by a status request to each single-rail blind in scope. Nothing moves; the
        answers arrive as notifications over the next half minute, each refreshing the data.
        """
        await self.api.async_request_battery_report(room_id)
        # ``data`` is None until the first refresh completes. Setup refreshes before the wake
        # sweep is scheduled, so this is unreachable today -- but the guard costs nothing and
        # keeps a future reordering (or a caller added before the first refresh) from turning
        # into an AttributeError out of a timer callback.
        for device_id, device in (self.data or {}).items():
            if device.type != COVER_TYPE_SINGLE_RAIL:
                continue
            if room_id is not None and device.room_id != room_id:
                continue
            await self.api.async_request_status(device_id)

    @callback
    def async_watch_move(self, device_id: int, bottom: int, middle: int) -> None:
        """After a move, make sure the blind actually went -- without holding anything up.

        The hub acks a move it never transmits, so the only proof a blind acted is it
        reporting a new position (const.py, ``MOVE_TIMEOUT``). The watch runs in the
        background and costs nothing while it waits: it listens to the updates the hub pushes
        anyway and ends as soon as the blind reports it moved. Only a blind that stays silent
        is asked to report in, and only one that then shows it never moved is sent the move
        again (``_async_supervise``). A new move for the same blind replaces the watch; a
        stop cancels it.
        """

        async def resend() -> None:
            await self.api.async_set_position(device_id, bottom, middle)

        self._async_start_watch(device_id, (bottom, middle), resend, "move")

    @callback
    def async_watch_preset(self, device_id: int, resend: Callable[[], Awaitable[Any]]) -> None:
        """After a preset verb (Best Privacy, Best View, Favorite), make sure it arrived.

        A preset has no position for the caller to aim at: the blind resolves it to its own
        stored one. The hub records that in its target fields as soon as it accepts the
        command -- for a command it then drops, too -- so the watch reads its goal from there
        first and then supervises it exactly like a move.
        """
        self._async_start_watch(device_id, None, resend, "preset")

    @callback
    def _async_start_watch(
        self,
        device_id: int,
        goal: _Rails | None,
        resend: Callable[[], Awaitable[Any]],
        kind: str,
    ) -> None:
        self.async_cancel_move_watch(device_id)
        start = self._sighting(device_id)
        self._move_watchers[device_id] = self.config_entry.async_create_background_task(
            self.hass,
            self._async_supervise(device_id, start, goal, resend),
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
    ) -> None:
        """Confirm a command reached the blind, resending it only while the blind is silent.

        Each attempt waits up to ``MOVE_TIMEOUT`` for the blind to report that it moved. A
        blind that stays quiet is asked to report in (one ``StatusRequest``); if its answer
        shows it never moved, the command goes again. After ``MOVE_ATTEMPTS`` sends the blind
        is reported as not responding, with a repair issue and a ``norman_command_failed``
        event. Nothing here holds up other commands: the requests it does send queue with
        everything else, paced like any other.
        """
        name = self._blind_name(device_id)
        try:
            if goal is None:
                # A preset: read the position the hub resolved it to, now. The hub replaces
                # its target with the blind's actual position whenever the blind reports in,
                # so a target read after asking the blind to report in always matches -- which
                # is how a dropped preset used to go unnoticed (blind 9943, 2026-09-21).
                await self.async_refresh()
                goal = self._hub_target(device_id)
                if goal is None:
                    return
            for attempt in range(1, MOVE_ATTEMPTS + 1):
                if await self._async_wait_for_progress(device_id, start, goal):
                    self._async_command_confirmed(device_id)
                    return
                # Silent for the whole travel time: ask the blind where it is.
                asked = self._sighting(device_id)
                await self.api.async_request_status(device_id)
                await self._async_wait_for_report(device_id, asked)
                if self._made_progress(device_id, start, goal):
                    self._async_command_confirmed(device_id)
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
            await self.async_refresh()

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
        if data is None or data.bottom_rail_position is None:
            return True  # gone from the hub, or no position to judge by; nothing to chase
        remaining = _distance(_rails(data), goal)
        return remaining == 0 or remaining < _distance(start.rails, goal)

    def _hub_target(self, device_id: int) -> _Rails | None:
        """The position the hub has recorded as this blind's target, if any."""
        data = (self.data or {}).get(device_id)
        if data is None or data.target_bottom_rail_position is None:
            return None
        middle = None if data.type == COVER_TYPE_SINGLE_RAIL else data.target_middle_rail_position
        return (data.target_bottom_rail_position, middle)

    def _blind_name(self, device_id: int) -> str:
        data = (self.data or {}).get(device_id)
        return data.name if data is not None else str(device_id)

    @callback
    def _async_command_confirmed(self, device_id: int) -> None:
        """The blind acted on a command: withdraw any "not responding" issue it had."""
        ir.async_delete_issue(self.hass, DOMAIN, _not_responding_issue_id(device_id))

    @callback
    def _async_command_failed(self, device_id: int, name: str, goal: _Rails) -> None:
        """Tell the user, and any automation listening, that a blind ignored every send."""
        _LOGGER.warning(
            "%s did not move after %s attempts; giving up. Check its battery and that it is "
            "in range of the hub",
            name,
            MOVE_ATTEMPTS,
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            _not_responding_issue_id(device_id),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_BLIND_NOT_RESPONDING,
            translation_placeholders={"name": name, "attempts": str(MOVE_ATTEMPTS)},
        )
        self.hass.bus.async_fire(
            EVENT_COMMAND_FAILED,
            {
                "device_id": self._registry_device_id(device_id),
                "peripheral_uid": device_id,
                "name": name,
                "attempts": MOVE_ATTEMPTS,
                "bottom_rail_position": goal[0],
                "middle_rail_position": goal[1],
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
            try:
                async for notification in self.api.async_listen_notifications():
                    _LOGGER.debug("Received notification: %s", notification)
                    if self._listener_offline:
                        self._listener_offline = False
                        _LOGGER.info("Norman hub notification stream restored")
                    if self._structure_changed(notification):
                        # A rename, room edit, or hub rename in the Norman app: re-read
                        # the device list so names and rooms follow.
                        self._device_info = {}
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
                await asyncio.sleep(RECONNECT_INTERVAL)
            except Exception:  # noqa: BLE001 - the listener must outlive any single failure
                # POLL_INTERVAL would keep state moving, but at a fraction of the push
                # path's responsiveness. Letting an unexpected error escape the loop would
                # leave the integration loaded and apparently healthy while every change made
                # at a remote or in the app went unnoticed until the next poll -- a far worse
                # failure than a logged exception and a retry. The refresh inside the try
                # above reaches the device registry, so this is not merely theoretical.
                _LOGGER.exception(
                    "Unexpected error in the Norman notification listener; retrying in %s seconds",
                    RECONNECT_INTERVAL,
                )
                await asyncio.sleep(RECONNECT_INTERVAL)
            else:
                # The stream was cycled on purpose after NOTIF_MAX_DURATION; reconnect
                # right away.
                _LOGGER.debug("Reconnecting notification listener")

            # Re-fetch the device list and states before the next connection so anything
            # that changed while the stream was down (or a newly paired blind) is picked up.
            self._device_info = {}
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
            # The device list rarely changes, so it is only re-read when it has been
            # invalidated (first refresh, or a listener reconnect).
            if not self._device_info:
                self._device_info = await self.api.async_get_devices()

            # Status is the lightweight call that carries positions
            status_data = await self.api.async_get_status()
        except NormanConnectionError as err:
            raise UpdateFailed(f"Error communicating with Norman hub: {err}") from err
        except NormanApiError as err:
            raise UpdateFailed(f"Invalid response from Norman hub: {err}") from err

        self._log_unknown_fields(self._device_info, status_data)
        self._update_hub_data(self._device_info, status_data)
        devices = self._process_data(self._device_info, status_data)
        self._warn_about_unknown_module_types(devices)
        self._sync_device_names(devices)
        return devices

    def _sync_device_names(self, devices: NormanDevices) -> None:
        """Carry renames made in the Norman app into the device registry.

        Devices are named when they are created and Home Assistant does not re-read
        ``DeviceInfo`` afterwards, so the hub's names are pushed here. A name the user set
        in Home Assistant (``name_by_user``) is untouched: it always takes precedence.
        """
        registry = dr.async_get(self.hass)
        wanted = {str(device_id): data.name for device_id, data in devices.items()}
        if self.hub_device_id and self.hub.custom_name:
            wanted[hub_identifier(self.config_entry)] = self.hub.custom_name
        # Devices are looked up through the entry rather than by identifier: identifiers
        # are no longer unique across config entries in Home Assistant 2026.9.
        for device in dr.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            for domain, identifier in device.identifiers:
                name = wanted.get(identifier) if domain == DOMAIN else None
                if name and device.name != name:
                    registry.async_update_device(device.id, name=name)

    def _update_hub_data(self, device_info: dict[str, Any], status_data: dict[str, Any]) -> None:
        """Refresh the hub's own attributes from the two payloads."""
        results = device_info.get("results")
        if isinstance(results, dict):
            self.hub.custom_name = results.get("CustomDeviceName") or self.hub.custom_name
            self.hub.time_zone = results.get("TimeZone") or self.hub.time_zone
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
            for room in top.get("RoomList") or []:
                if not isinstance(room, dict):
                    continue
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
                    devices[peripheral_uid] = NormanPeripheralData(
                        id=peripheral_uid,
                        name=peripheral.get("PeripheralName") or f"Norman {peripheral_uid}",
                        type=_cover_type(module_type),
                        room_id=_parse_int(room_id),
                        room_name=room_name,
                        group_id=_parse_int(group_id),
                        group_name=group_name,
                        module_type=module_type,
                        module_detail=_parse_int(peripheral.get("ModuleDetail")),
                    )

        # Add status information
        for peripheral in _dicts(status_data.get("Peripherals")):
            peripheral_uid = _parse_uid(peripheral.get("PeripheralUID"))
            if peripheral_uid is None:
                continue

            if peripheral_uid not in devices:
                # Create minimal device if not found in device_info
                module_type = _parse_int(peripheral.get("ModuleType"))
                devices[peripheral_uid] = NormanPeripheralData(
                    id=peripheral_uid,
                    name=f"Norman {peripheral_uid}",
                    type=_cover_type(module_type),
                    module_type=module_type,
                    module_detail=_parse_int(peripheral.get("ModuleDetail")),
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
            # Despite its name the field is a 0-100 level on every hub seen so far
            device.battery_level = _parse_position(peripheral.get("BatteryVoltage"))
            device.signal_strength = _parse_int(peripheral.get("RssiMean"))
            device.firmware_version = peripheral.get("FirmwareVersion") or None
            device.rf_firmware_version = peripheral.get("RfFirmwareVersion") or None
            device.last_update = peripheral.get("Timestamp")

        return devices


def _cover_type(module_type: int | None) -> str:
    """The cover type for a ModuleType, defaulting when it is unknown or missing."""
    if module_type is None:
        return DEFAULT_COVER_TYPE
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
