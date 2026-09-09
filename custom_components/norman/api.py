"""API client for the Norman hub.

The hub exposes a small unauthenticated JSON-over-HTTP API on the local network; the
endpoints and payload shapes are documented in docs/NORMAN_API.md.
"""

from __future__ import annotations

import asyncio
import codecs
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
import itertools
import json
import logging
import time
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant.exceptions import HomeAssistantError
from yarl import URL

from .const import (
    HUB_CMD_STOP,
    HUB_COMMAND_TRIGGER,
    HUB_PORT,
    NOTIF_MAX_BUFFER,
    NOTIF_MAX_DURATION,
    READ_CHUNK_SIZE,
    REQUEST_TIMEOUT,
    TRAFFIC_BODY_LIMIT,
    TRAFFIC_MAX_EXCHANGES,
)

_LOGGER = logging.getLogger(__name__)

# API endpoints
ENDPOINT_REGISTRATION = "/NM/v1/registration"
ENDPOINT_GET_ALL_PERIPHERAL = "/NM/v1/GetAllPeripheral"
ENDPOINT_STATUS = "/NM/v1/status"
ENDPOINT_CONTROL = "/NM/v1/control"
ENDPOINT_NOTIFICATION = "/NM/v1/notification"


class NormanApiError(HomeAssistantError):
    """The hub answered, but with an error or an unparseable body."""


class NormanConnectionError(HomeAssistantError):
    """The hub could not be reached, or the request timed out."""


@dataclass(slots=True)
class HubExchange:
    """One recorded exchange with the hub: a request/response pair or a stream event."""

    when: str  # ISO 8601, UTC
    kind: str  # "request" or "stream"
    endpoint: str
    duration_ms: float | None = None
    request: dict[str, Any] | None = None
    status: int | None = None
    response: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the exchange as plain data for diagnostics."""
        return asdict(self)


@dataclass
class TrafficRecorder:
    """Keep the most recent raw exchanges with the hub, below the parsing layer.

    The coordinator's model drops every field it does not understand, so this is the only
    place an unknown blind type's payload or an unexpected status field can be seen. It is
    always on: the buffer is bounded and bodies are truncated, so the cost is a few hundred
    kilobytes at most. Everything here is exported by diagnostics.
    """

    max_exchanges: int = TRAFFIC_MAX_EXCHANGES
    body_limit: int = TRAFFIC_BODY_LIMIT
    exchanges: deque[HubExchange] = field(init=False)
    # Last complete raw response per endpoint, kept outside the ring buffer so a burst of
    # notifications cannot push the device list out of the export.
    latest_raw: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Size the ring buffer."""
        self.exchanges = deque(maxlen=self.max_exchanges)

    def _clip(self, body: str | None) -> str | None:
        if body is None or len(body) <= self.body_limit:
            return body
        return f"{body[: self.body_limit]}… [{len(body) - self.body_limit} more bytes]"

    def record(
        self,
        kind: str,
        endpoint: str,
        *,
        request: dict[str, Any] | None = None,
        status: int | None = None,
        response: str | None = None,
        error: str | None = None,
        started: float | None = None,
    ) -> None:
        """Append an exchange; ``started`` is a ``time.monotonic()`` reading."""
        if kind == "request" and response is not None and error is None:
            self.latest_raw[endpoint] = response
        self.exchanges.append(
            HubExchange(
                when=_utc_now_iso(),
                kind=kind,
                endpoint=endpoint,
                duration_ms=(
                    round((time.monotonic() - started) * 1000, 1) if started is not None else None
                ),
                request=request,
                status=status,
                response=self._clip(response),
                error=error,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        """Return everything recorded, oldest exchange first."""
        return {
            "latest_raw": dict(self.latest_raw),
            "exchanges": [exchange.as_dict() for exchange in self.exchanges],
        }


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class JsonStreamParser:
    """Incrementally split a byte stream into the top-level JSON objects it contains.

    The notification endpoint is a long-poll that writes bare JSON objects back to back
    (no framing, no newlines). Bytes are decoded incrementally so a multi-byte UTF-8
    character split across two reads survives, and object boundaries are found with a
    scanner that tracks string state, so braces inside names and nested objects do not
    confuse the framing. Text outside any object is discarded.
    """

    def __init__(self, max_buffer: int = NOTIF_MAX_BUFFER) -> None:
        """Initialize the parser."""
        self._utf8 = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._max_buffer = max_buffer
        self._buffer = ""
        # Scanner state, carried across feeds so each character is examined once
        self._pos = 0
        self._depth = 0
        self._in_string = False
        self._escaped = False

    def _reset(self) -> None:
        self._buffer = ""
        self._pos = 0
        self._depth = 0
        self._in_string = False
        self._escaped = False

    def feed(self, chunk: bytes) -> list[dict[str, Any]]:
        """Consume a chunk of bytes and return every object it completed."""
        self._buffer += self._utf8.decode(chunk)
        objects: list[dict[str, Any]] = []

        while self._pos < len(self._buffer):
            char = self._buffer[self._pos]
            self._pos += 1

            if self._depth == 0:
                if char == "{":
                    # Drop whatever preceded this object; it cannot be part of one
                    self._buffer = self._buffer[self._pos - 1 :]
                    self._pos = 1
                    self._depth = 1
                continue

            if self._in_string:
                if self._escaped:
                    self._escaped = False
                elif char == "\\":
                    self._escaped = True
                elif char == '"':
                    self._in_string = False
            elif char == '"':
                self._in_string = True
            elif char == "{":
                self._depth += 1
            elif char == "}":
                self._depth -= 1
                if self._depth == 0:
                    segment = self._buffer[: self._pos]
                    self._buffer = self._buffer[self._pos :]
                    self._pos = 0
                    try:
                        obj = json.loads(segment)
                    except json.JSONDecodeError:
                        _LOGGER.debug("Skipping unparseable notification data: %s", segment)
                    else:
                        if isinstance(obj, dict):
                            objects.append(obj)

        if self._depth == 0:
            # Nothing pending; forget any trailing filler
            self._reset()
        elif len(self._buffer) > self._max_buffer:
            _LOGGER.debug(
                "Discarding %d bytes of unterminated notification data", len(self._buffer)
            )
            self._reset()

        return objects


class NormanApiClient:
    """API client for the Norman hub."""

    def __init__(self, host: str, session: ClientSession) -> None:
        """Initialize the API client.

        Args:
            host: IP address or hostname of the Norman hub.
            session: Shared aiohttp session (owned by Home Assistant, never closed here).

        """
        self.host = host
        self.base_url = URL.build(scheme="http", host=host, port=HUB_PORT)
        self._session = session
        self._thing_name: str | None = None
        self._task_ids = itertools.count(1)
        self.traffic = TrafficRecorder()
        # Hub identity from the registration reply, for the hub device
        self.hub_model: str | None = None
        self.hub_firmware_version: str | None = None
        self.hub_wifi_ssid: str | None = None

    @property
    def thing_name(self) -> str | None:
        """Return the hub's ThingName, once registration has succeeded."""
        return self._thing_name

    def _next_task_id(self) -> int:
        """Return a request-scoped task id; the hub echoes it, so it only needs to vary."""
        return next(self._task_ids) % 10000

    async def _async_request(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST a JSON payload and return the decoded JSON object.

        Every exchange, successful or not, is recorded in ``self.traffic`` and logged at
        debug level (bodies truncated) for troubleshooting.

        Raises:
            NormanConnectionError: the hub could not be reached or timed out.
            NormanApiError: the hub replied with an HTTP error, a non-JSON body, or a body
                that is not a JSON object.

        """
        started = time.monotonic()
        status: int | None = None
        text: str | None = None
        try:
            async with self._session.post(
                self.base_url.with_path(endpoint),
                json=payload,
                timeout=ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                status = response.status
                text = await response.text()
        except TimeoutError as err:
            # aiohttp's total timeout raises a bare TimeoutError, which is *not* a
            # ClientError, so it needs its own clause or it escapes as an unexpected error.
            error = f"Timed out talking to Norman hub at {self.host}"
            self._record(endpoint, payload, status, text, error, started)
            raise NormanConnectionError(error) from err
        except ClientError as err:
            error = f"Failed to connect to Norman hub at {self.host}: {err}"
            self._record(endpoint, payload, status, text, error, started)
            raise NormanConnectionError(error) from err

        if status >= 400:
            error = f"Hub returned HTTP {status} for {endpoint}"
            self._record(endpoint, payload, status, text, error, started)
            raise NormanApiError(error)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as err:
            error = f"Invalid JSON from Norman hub for {endpoint}"
            self._record(endpoint, payload, status, text, error, started)
            raise NormanApiError(error) from err
        if not isinstance(data, dict):
            error = f"Unexpected response shape from Norman hub for {endpoint}"
            self._record(endpoint, payload, status, text, error, started)
            raise NormanApiError(error)

        self._record(endpoint, payload, status, text, None, started)
        return data

    def _record(
        self,
        endpoint: str,
        payload: dict[str, Any],
        status: int | None,
        text: str | None,
        error: str | None,
        started: float,
    ) -> None:
        """Record an exchange and mirror it to the debug log."""
        self.traffic.record(
            "request",
            endpoint,
            request=payload,
            status=status,
            response=text,
            error=error,
            started=started,
        )
        _LOGGER.debug(
            "POST %s %s -> %s %s%s",
            endpoint,
            payload,
            status,
            text[:500] if text else text,
            f" ({error})" if error else "",
        )

    @staticmethod
    def _raise_on_error_code(data: dict[str, Any], what: str) -> None:
        """Raise NormanApiError when the hub's ``Error`` field signals a failure.

        The hub answers ``0`` on most endpoints but the string ``"Success."`` on the
        notification acknowledgement, so both spellings of success are accepted.
        """
        error = data.get("Error", 0)
        if error in (0, "0", None) or (isinstance(error, str) and error.lower().startswith("succ")):
            return
        raise NormanApiError(f"{what} failed with error code: {error}")

    async def async_validate_connection(self) -> str | None:
        """Register with the hub and return its ThingName.

        Raises:
            NormanConnectionError: If the hub cannot be reached.
            NormanApiError: If the hub answers with an error.

        """
        data = await self._async_registration()
        return data.get("ThingName")

    async def _async_registration(self) -> dict[str, Any]:
        """Send registration request to get ThingName."""
        data = await self._async_request(ENDPOINT_REGISTRATION, {"Timestamp": int(time.time())})
        self._raise_on_error_code(data, "Registration")
        self._thing_name = data.get("ThingName")
        self.hub_model = data.get("Model") or self.hub_model
        self.hub_firmware_version = data.get("FirmwareVersion") or self.hub_firmware_version
        self.hub_wifi_ssid = data.get("WiFiSSID") or self.hub_wifi_ssid
        return data

    async def async_get_devices(self) -> dict[str, Any]:
        """Get the list of all devices (rooms, groups, peripherals) from the hub."""
        # GetAllPeripheral needs the ThingName obtained during registration
        if not self._thing_name:
            await self._async_registration()

        data = await self._async_request(
            ENDPOINT_GET_ALL_PERIPHERAL,
            {
                "ThingName": self._thing_name,
                "TaskID": self._next_task_id(),
                "Timestamp": int(time.time()),
            },
        )
        status = data.get("status")
        if isinstance(status, dict) and status.get("code", 0) != 0:
            raise NormanApiError(f"GetAllPeripheral failed: {status.get('error', 'Unknown error')}")
        return data

    async def async_get_status(self) -> dict[str, Any]:
        """Get the current status (positions, battery, firmware) of all devices."""
        data = await self._async_request(ENDPOINT_STATUS, {"Timestamp": int(time.time())})
        self._raise_on_error_code(data, "Status request")
        return data

    async def async_set_position(
        self, device_id: int, bottom_rail_position: int, middle_rail_position: int
    ) -> None:
        """Move a cover.

        Args:
            device_id: PeripheralUID of the Norman device
            bottom_rail_position: Bottom rail position (0=closed, 100=open)
            middle_rail_position: Middle rail position (0=closed, 100=open)

        """
        await self.async_send_control(
            device_id,
            {
                "BottomRailPosition": bottom_rail_position,
                "MiddleRailPosition": middle_rail_position,
            },
        )

    async def async_stop(self, device_id: int) -> None:
        """Stop a cover's motor where it is.

        Sends ``MotorStop: 170`` exactly as the Norman app does; the hub echoes the field
        back and the blind's target positions catch up on the next status read.
        """
        await self.async_send_control(device_id, {HUB_CMD_STOP: HUB_COMMAND_TRIGGER})

    async def async_send_control(self, device_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        """POST arbitrary fields to the control endpoint for one peripheral.

        ``PeripheralUID``, ``Timestamp`` and ``TaskID`` are filled in; ``fields`` is merged
        on top. This is what ``async_set_position`` and ``async_stop`` use, and what the
        ``send_hub_command`` action exposes for the other verbs the hub advertises (see
        docs/NORMAN_API.md, "Control verbs"). Returns the hub's reply.
        """
        data = await self._async_request(
            ENDPOINT_CONTROL,
            {
                "PeripheralUID": device_id,
                "Timestamp": int(time.time()),
                "TaskID": self._next_task_id(),
                **fields,
            },
        )
        self._raise_on_error_code(data, "Control request")
        return data

    async def async_send_blind_control(
        self, room_id: int, group_id: int, fields: dict[str, Any], device_id: int | None = None
    ) -> dict[str, Any]:
        """POST a verb addressed at one blind by its room and group.

        The ``Switch`` and ``Favorite`` verbs are **not** addressed by ``PeripheralUID``: the
        app targets a single blind with ``RoomID`` + ``GroupID``, which is unique per blind
        (``GroupID`` is the blind's remote-control button within its room). A
        ``PeripheralUID`` is sent alongside when known, as the app does, but the pair is what
        selects the blind -- captured from the app's per-blind Best Privacy / Best View /
        Favorite buttons.
        """
        payload: dict[str, Any] = {
            "RoomID": room_id,
            "GroupID": group_id,
            "Timestamp": int(time.time()),
            "TaskID": self._next_task_id(),
            **fields,
        }
        if device_id is not None:
            payload["PeripheralUID"] = device_id
        data = await self._async_request(ENDPOINT_CONTROL, payload)
        self._raise_on_error_code(data, "Blind control request")
        return data

    async def async_send_room_control(
        self, room_id: int | None, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """POST a room-wide command: every blind in one room, in a single request.

        The hub accepts ``RoomID`` in place of ``PeripheralUID`` for the ``Switch`` and
        ``Favorite`` verbs (docs/NORMAN_API.md, "Room-wide and hub-wide control"). This is
        what the Norman app's Best Privacy / Best View / Remote Favorite buttons send.

        ``room_id`` of ``None`` omits the field entirely, which addresses **every blind on
        the hub** -- an empty scope means "everything", not "nothing", so never pass None
        expecting a no-op.
        """
        payload: dict[str, Any] = {
            "Timestamp": int(time.time()),
            "TaskID": self._next_task_id(),
            **fields,
        }
        if room_id is not None:
            payload["RoomID"] = room_id
        data = await self._async_request(ENDPOINT_CONTROL, payload)
        self._raise_on_error_code(data, "Room control request")
        return data

    async def async_listen_notifications(self) -> AsyncIterator[dict[str, Any]]:
        """Yield peripheral state-change notifications from the hub's long-poll.

        Returns normally when NOTIF_MAX_DURATION elapses (the caller should simply
        reconnect) and raises NormanConnectionError if the hub closes the stream or the
        connection fails.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + NOTIF_MAX_DURATION
        parser = JsonStreamParser()

        try:
            async with self._session.post(
                self.base_url.with_path(ENDPOINT_NOTIFICATION),
                timeout=ClientTimeout(total=None),
            ) as response:
                if response.status >= 400:
                    self.traffic.record(
                        "stream",
                        ENDPOINT_NOTIFICATION,
                        status=response.status,
                        error="refused",
                    )
                    raise NormanConnectionError(
                        f"Notification stream refused with HTTP {response.status}"
                    )
                self.traffic.record("stream", ENDPOINT_NOTIFICATION, status=response.status)
                content = response.content
                while True:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        break
                    try:
                        chunk = await asyncio.wait_for(
                            content.read(READ_CHUNK_SIZE), timeout=remaining
                        )
                    except TimeoutError:
                        break
                    if not chunk:
                        self.traffic.record("stream", ENDPOINT_NOTIFICATION, error="closed by hub")
                        raise NormanConnectionError("Notification stream closed by hub")
                    self.traffic.record(
                        "stream",
                        ENDPOINT_NOTIFICATION,
                        response=chunk.decode(errors="replace"),
                    )
                    for obj in parser.feed(chunk):
                        # The hub first acknowledges the subscription with a bare Error
                        # object. State changes carry PeripheralList (ids of the blinds
                        # that moved); edits made in the Norman app carry UpdateTime
                        # (which of room / peripheral / device / schedule changed).
                        if "PeripheralList" in obj or "UpdateTime" in obj:
                            yield obj
        except ClientError as err:
            raise NormanConnectionError(f"Notification listener connection error: {err}") from err

        _LOGGER.debug(
            "Max notification connection time reached (%s seconds); reconnecting",
            NOTIF_MAX_DURATION,
        )
