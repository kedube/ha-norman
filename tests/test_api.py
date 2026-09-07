"""Tests for the hub API client and the notification stream parser."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.norman.api import (
    JsonStreamParser,
    NormanApiClient,
    NormanApiError,
    NormanConnectionError,
)

from .const import HUB_HOST, HUB_THING_NAME, HUB_URL

REGISTRATION = f"{HUB_URL}/NM/v1/registration"
GET_ALL = f"{HUB_URL}/NM/v1/GetAllPeripheral"
STATUS = f"{HUB_URL}/NM/v1/status"
CONTROL = f"{HUB_URL}/NM/v1/control"
NOTIFICATION = f"{HUB_URL}/NM/v1/notification"


@pytest.fixture
async def client(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> NormanApiClient:
    """A client bound to Home Assistant's shared session, which aioclient_mock intercepts."""
    return NormanApiClient(HUB_HOST, async_get_clientsession(hass))


# ---- URL building ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("192.168.1.50", "http://192.168.1.50:10123"),
        ("norman-hub.local", "http://norman-hub.local:10123"),
        ("fe80::1", "http://[fe80::1]:10123"),
    ],
)
def test_base_url(host: str, expected: str) -> None:
    """The hub port is fixed and IPv6 literals are bracketed."""
    assert str(NormanApiClient(host, MagicMock()).base_url) == expected


# ---- registration ----------------------------------------------------------------------


async def test_validate_connection_returns_thing_name(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A successful registration stores and returns the ThingName."""
    aioclient_mock.post(REGISTRATION, json={"Error": 0, "ThingName": HUB_THING_NAME})

    assert await client.async_validate_connection() == HUB_THING_NAME
    assert client.thing_name == HUB_THING_NAME
    assert "Timestamp" in aioclient_mock.mock_calls[0][2]


async def test_registration_error_code(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A non-zero Error field is an API error."""
    aioclient_mock.post(REGISTRATION, json={"Error": 3, "ThingName": HUB_THING_NAME})

    with pytest.raises(NormanApiError, match="error code: 3"):
        await client.async_validate_connection()
    assert client.thing_name is None


@pytest.mark.parametrize(
    "mock_kwargs",
    [
        {"status": 500, "text": "oops"},
        {"text": "<html>not json</html>"},
        {"json": [1, 2, 3]},
    ],
    ids=["http-error", "not-json", "not-an-object"],
)
async def test_bad_responses_are_api_errors(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker, mock_kwargs: dict
) -> None:
    """Anything the hub answers that is not a JSON object is an API error, not a crash."""
    aioclient_mock.post(REGISTRATION, **mock_kwargs)

    with pytest.raises(NormanApiError):
        await client.async_validate_connection()


@pytest.mark.parametrize(
    "exc",
    [aiohttp.ClientConnectionError("refused"), aiohttp.ClientOSError(), TimeoutError()],
    ids=["connection", "os", "timeout"],
)
async def test_unreachable_hub_is_connection_error(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker, exc: Exception
) -> None:
    """Transport failures, including the bare TimeoutError aiohttp raises, are connection errors."""
    aioclient_mock.post(REGISTRATION, exc=exc)

    with pytest.raises(NormanConnectionError):
        await client.async_validate_connection()


# ---- devices / status / control --------------------------------------------------------


async def test_get_devices_registers_first(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """GetAllPeripheral needs the ThingName, so an unregistered client registers first."""
    aioclient_mock.post(REGISTRATION, json={"Error": 0, "ThingName": HUB_THING_NAME})
    aioclient_mock.post(GET_ALL, json={"status": {"code": 0}, "results": {"RoomList": []}})

    data = await client.async_get_devices()

    assert data["results"] == {"RoomList": []}
    assert [str(call[1]) for call in aioclient_mock.mock_calls] == [REGISTRATION, GET_ALL]
    payload = aioclient_mock.mock_calls[1][2]
    assert payload["ThingName"] == HUB_THING_NAME
    assert isinstance(payload["TaskID"], int)

    # Already registered: no second registration
    await client.async_get_devices()
    assert aioclient_mock.call_count == 3


async def test_get_devices_status_error(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """GetAllPeripheral reports errors under status.code rather than Error."""
    aioclient_mock.post(REGISTRATION, json={"Error": 0, "ThingName": HUB_THING_NAME})
    aioclient_mock.post(GET_ALL, json={"status": {"code": 2, "error": "busy"}})

    with pytest.raises(NormanApiError, match="busy"):
        await client.async_get_devices()


async def test_get_status(client: NormanApiClient, aioclient_mock: AiohttpClientMocker) -> None:
    """Status does not need registration and surfaces its Error field."""
    aioclient_mock.post(STATUS, json={"Error": 0, "Peripherals": []})
    assert (await client.async_get_status())["Peripherals"] == []

    aioclient_mock.clear_requests()
    aioclient_mock.post(STATUS, json={"Error": 9})
    with pytest.raises(NormanApiError, match="error code: 9"):
        await client.async_get_status()


async def test_set_position_payload(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Control sends both rails and a fresh TaskID each time."""
    aioclient_mock.post(CONTROL, json={"Error": 0})

    await client.async_set_position(1001, 25, 75)
    await client.async_set_position(1001, 0, 0)

    first, second = (call[2] for call in aioclient_mock.mock_calls)
    assert first["PeripheralUID"] == 1001
    assert first["BottomRailPosition"] == 25
    assert first["MiddleRailPosition"] == 75
    assert first["TaskID"] != second["TaskID"]


async def test_set_position_error(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A control error code is raised to the caller."""
    aioclient_mock.post(CONTROL, json={"Error": 1})
    with pytest.raises(NormanApiError, match="Control request failed"):
        await client.async_set_position(1001, 25, 75)


# ---- notification stream parser --------------------------------------------------------


def _feed_all(parser: JsonStreamParser, *chunks: bytes) -> list[dict]:
    out: list[dict] = []
    for chunk in chunks:
        out.extend(parser.feed(chunk))
    return out


def test_parser_handles_back_to_back_objects() -> None:
    """The hub writes objects with no separator; each one is returned once."""
    assert _feed_all(JsonStreamParser(), b'{"a":1}{"b":2} {"c":3}') == [
        {"a": 1},
        {"b": 2},
        {"c": 3},
    ]


def test_parser_reassembles_objects_split_across_chunks() -> None:
    """A read boundary in the middle of an object does not lose it."""
    parser = JsonStreamParser()
    assert parser.feed(b'{"PeripheralList":[{"Peri') == []
    assert parser.feed(b'pheralUID":1}]}{"x"') == [{"PeripheralList": [{"PeripheralUID": 1}]}]
    assert parser.feed(b":2}") == [{"x": 2}]


def test_parser_reassembles_split_multibyte_characters() -> None:
    """A UTF-8 sequence cut in two by the chunk size must decode to the original text."""
    text = '{"PeripheralName":"Salón"}'.encode()
    cut = text.index("ó".encode()) + 1  # split inside the two-byte character
    parser = JsonStreamParser()
    assert parser.feed(text[:cut]) == []
    assert parser.feed(text[cut:]) == [{"PeripheralName": "Salón"}]


def test_parser_ignores_braces_inside_strings() -> None:
    """Braces and escaped quotes inside strings are not object boundaries."""
    assert _feed_all(JsonStreamParser(), b'{"name":"Kid\'s {room}"}{"n":1}') == [
        {"name": "Kid's {room}"},
        {"n": 1},
    ]
    assert _feed_all(JsonStreamParser(), b'{"name":"say \\"}\\" ok"}{"n":2}') == [
        {"name": 'say "}" ok'},
        {"n": 2},
    ]


def test_parser_skips_garbage_and_corrupt_objects() -> None:
    """Filler before an object and a corrupt object are dropped once the next one begins."""
    assert _feed_all(JsonStreamParser(), b'\r\n junk {"bad": nope}{"ok":1}') == [{"ok": 1}]
    assert _feed_all(JsonStreamParser(), b"[1,2,3]") == []


def test_parser_caps_unterminated_buffer() -> None:
    """A hub that never closes an object cannot grow the buffer without bound."""
    parser = JsonStreamParser(max_buffer=32)
    assert parser.feed(b'{"never":"' + b"x" * 64) == []
    # Buffer was discarded, so a fresh object parses on its own
    assert parser.feed(b'{"fresh":1}') == [{"fresh": 1}]


# ---- notification stream ---------------------------------------------------------------


async def test_listen_yields_only_state_changes_then_reports_eof(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """The ack without PeripheralList is skipped; hub EOF is a connection error."""
    body = '{"Error":0}{"PeripheralList":[{"PeripheralUID":1}]}{"PeripheralList":[]}'
    aioclient_mock.post(NOTIFICATION, text=body)

    received = []
    with pytest.raises(NormanConnectionError, match="closed by hub"):
        async for notification in client.async_listen_notifications():
            received.append(notification)

    assert received == [{"PeripheralList": [{"PeripheralUID": 1}]}, {"PeripheralList": []}]


async def test_listen_returns_when_max_duration_elapses(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Hitting NOTIF_MAX_DURATION ends the generator normally so the caller reconnects."""
    aioclient_mock.post(NOTIFICATION, text='{"PeripheralList":[]}')

    with patch("custom_components.norman.api.NOTIF_MAX_DURATION", 0):
        received = [n async for n in client.async_listen_notifications()]

    assert received == []


@pytest.mark.parametrize(
    "mock_kwargs",
    [{"status": 503, "text": ""}, {"exc": aiohttp.ClientConnectionError("down")}],
    ids=["http-error", "transport-error"],
)
async def test_listen_connection_failures(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker, mock_kwargs: dict
) -> None:
    """Refused or failed stream connections surface as connection errors."""
    aioclient_mock.post(NOTIFICATION, **mock_kwargs)

    with pytest.raises(NormanConnectionError):
        async for _ in client.async_listen_notifications():
            pass


# ---- traffic recorder ------------------------------------------------------------------


async def test_recorder_keeps_requests_and_errors(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Successful and failed exchanges are both recorded, with status, body, and error."""
    aioclient_mock.post(REGISTRATION, json={"Error": 0, "ThingName": HUB_THING_NAME})
    aioclient_mock.post(STATUS, exc=TimeoutError())

    await client.async_validate_connection()
    with pytest.raises(NormanConnectionError):
        await client.async_get_status()

    ok, failed = client.traffic.as_dict()["exchanges"]
    assert ok["kind"] == "request"
    assert ok["endpoint"] == REGISTRATION.removeprefix(HUB_URL)
    assert ok["status"] == 200
    assert "Timestamp" in ok["request"]
    assert HUB_THING_NAME in ok["response"]
    assert ok["error"] is None
    assert ok["duration_ms"] is not None
    assert ok["when"].endswith("Z")

    assert failed["endpoint"] == STATUS.removeprefix(HUB_URL)
    assert failed["status"] is None
    assert "Timed out" in failed["error"]


async def test_recorder_is_bounded_and_keeps_latest_raw_per_endpoint(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """The ring buffer drops old entries, but the last full body per endpoint survives."""
    aioclient_mock.post(REGISTRATION, json={"Error": 0, "ThingName": HUB_THING_NAME})
    aioclient_mock.post(GET_ALL, json={"status": {"code": 0}, "results": {"RoomList": []}})
    aioclient_mock.post(STATUS, json={"Error": 0, "Peripherals": []})

    await client.async_get_devices()
    for _ in range(client.traffic.max_exchanges + 5):
        await client.async_get_status()

    traffic = client.traffic.as_dict()
    assert len(traffic["exchanges"]) == client.traffic.max_exchanges
    assert all(e["endpoint"] == "/NM/v1/status" for e in traffic["exchanges"])
    assert set(traffic["latest_raw"]) == {
        "/NM/v1/registration",
        "/NM/v1/GetAllPeripheral",
        "/NM/v1/status",
    }
    assert '"RoomList"' in traffic["latest_raw"]["/NM/v1/GetAllPeripheral"]


async def test_recorder_truncates_large_bodies_but_not_latest_raw(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Ring-buffer bodies are clipped; the per-endpoint copy is kept whole."""
    big = {"Error": 0, "Peripherals": [{"PeripheralUID": i, "pad": "x" * 100} for i in range(400)]}
    aioclient_mock.post(STATUS, json=big)

    await client.async_get_status()

    traffic = client.traffic.as_dict()
    clipped = traffic["exchanges"][0]["response"]
    assert len(clipped) < client.traffic.body_limit + 64
    assert "more bytes]" in clipped
    assert len(traffic["latest_raw"]["/NM/v1/status"]) > client.traffic.body_limit


async def test_recorder_captures_stream_chunks(
    client: NormanApiClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Notification chunks are recorded raw, before parsing, along with open/close events."""
    aioclient_mock.post(NOTIFICATION, text='{"Error":0}{"PeripheralList":[]}')

    with pytest.raises(NormanConnectionError):
        async for _ in client.async_listen_notifications():
            pass

    kinds = [(e["kind"], e["status"], e["error"]) for e in client.traffic.as_dict()["exchanges"]]
    assert kinds[0] == ("stream", 200, None)
    assert kinds[-1] == ("stream", None, "closed by hub")
    chunks = [e["response"] for e in client.traffic.as_dict()["exchanges"] if e["response"]]
    assert chunks == ['{"Error":0}{"PeripheralList":[]}']
    assert "/NM/v1/notification" not in client.traffic.as_dict()["latest_raw"]
