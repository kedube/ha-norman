"""Shared fixtures for the Norman test suite.

The integration talks to the hub through Home Assistant's shared aiohttp session, so the
suite drives it at the HTTP level with ``aioclient_mock`` (from
pytest-homeassistant-custom-component) rather than patching client methods. That way the
request payloads, error handling, and the notification stream parser are all exercised
for real. The one exception is the notification long-poll: the mock can only return a
finite body, so integration tests replace the listener with a queue-fed fake
(``notifications``) and the real listener is covered in ``test_api.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
import json
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.norman.api import NormanApiClient
from custom_components.norman.const import DOMAIN

from .const import (
    HUB_HOST,
    HUB_THING_NAME,
    HUB_URL,
    MOCK_CONFIG,
    REGISTRATION_RESPONSE,
    devices_payload,
    status_payload,
)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ for every test."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A config entry for the test hub."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Norman Hub ({HUB_HOST})",
        data=MOCK_CONFIG,
        unique_id=HUB_THING_NAME,
        entry_id="norman-test-entry",
    )


class FakeHub:
    """Register the hub's endpoints on ``aioclient_mock`` and record control calls.

    Mutate ``devices`` / ``status`` to change what later requests return; the endpoints
    read them on every call.
    """

    def __init__(self, aioclient_mock: AiohttpClientMocker) -> None:
        """Wire up every endpoint with default (healthy) responses."""
        self.mock = aioclient_mock
        self.devices: dict[str, Any] = devices_payload()
        self.status: dict[str, Any] = status_payload()
        self.control_response: dict[str, Any] = {"Error": 0}
        self.control_exc: Exception | None = None
        self.status_exc: Exception | None = None
        self.notification_body: str = json.dumps({"Error": 0})
        self._register()

    def _register(self) -> None:
        self.mock.post(f"{HUB_URL}/NM/v1/registration", json=REGISTRATION_RESPONSE)
        self.mock.post(f"{HUB_URL}/NM/v1/GetAllPeripheral", side_effect=self._devices)
        self.mock.post(f"{HUB_URL}/NM/v1/status", side_effect=self._status)
        self.mock.post(f"{HUB_URL}/NM/v1/control", side_effect=self._control)
        self.mock.post(f"{HUB_URL}/NM/v1/notification", side_effect=self._notification)

    async def _devices(self, method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(method, url, json=self.devices)

    async def _status(self, method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        if self.status_exc is not None:
            raise self.status_exc
        return AiohttpClientMockResponse(method, url, json=self.status)

    async def _control(self, method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        if self.control_exc is not None:
            raise self.control_exc
        return AiohttpClientMockResponse(method, url, json=self.control_response)

    async def _notification(self, method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(method, url, text=self.notification_body)

    def calls_to(self, endpoint: str) -> list[dict[str, Any]]:
        """Payloads of every request to ``endpoint`` so far, oldest first."""
        return [call[2] for call in self.mock.mock_calls if str(call[1]).endswith(endpoint)]

    @property
    def control_calls(self) -> list[dict[str, Any]]:
        """Payloads of every /control request so far, oldest first."""
        return self.calls_to("/NM/v1/control")

    def peripheral_status(self, uid: int) -> dict[str, Any]:
        """The status record the hub reports for ``uid``."""
        for peripheral in self.status["Peripherals"]:
            if peripheral.get("PeripheralUID") == uid:
                return peripheral
        raise KeyError(uid)

    def set_position(
        self,
        uid: int,
        bottom: int | None = None,
        middle: int | None = None,
        *,
        target_bottom: int | None = None,
        target_middle: int | None = None,
    ) -> None:
        """Update what the hub reports for a peripheral (targets follow current)."""
        peripheral = self.peripheral_status(uid)
        if bottom is not None:
            peripheral["BottomRailPosition"] = bottom
            peripheral["TargetBottomRailPosition"] = bottom
        if middle is not None:
            peripheral["MiddleRailPosition"] = middle
            peripheral["TargetMiddleRailPosition"] = middle
        if target_bottom is not None:
            peripheral["TargetBottomRailPosition"] = target_bottom
        if target_middle is not None:
            peripheral["TargetMiddleRailPosition"] = target_middle


@pytest.fixture
def fake_hub(aioclient_mock: AiohttpClientMocker) -> FakeHub:
    """A healthy fake hub answering on every endpoint."""
    return FakeHub(aioclient_mock)


@pytest.fixture
def notifications() -> AsyncGenerator[asyncio.Queue]:
    """Replace the hub's notification long-poll with a queue.

    Put a dict to deliver a notification, an exception to simulate the stream dropping,
    or ``None`` to simulate the periodic reconnect (the listener returning normally).
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def fake_listen(self: NormanApiClient) -> AsyncIterator[dict[str, Any]]:
        while True:
            item = await queue.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    with patch.object(NormanApiClient, "async_listen_notifications", fake_listen):
        yield queue


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_hub: FakeHub,
    notifications: asyncio.Queue,
) -> AsyncGenerator[MockConfigEntry]:
    """Set up the integration against the fake hub and tear it down afterwards."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    yield mock_config_entry
    if mock_config_entry.state.recoverable:
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()


def cover_entity_id(hass: HomeAssistant, uid: int) -> str:
    """Resolve a blind's entity id from its hub id.

    Entity ids are not hard-coded because Home Assistant's generated ids changed in 2026.9
    (they gained an area prefix); only the unique id is stable.
    """
    entity_id = er.async_get(hass).async_get_entity_id("cover", DOMAIN, str(uid))
    assert entity_id, f"no cover registered for peripheral {uid}"
    return entity_id


async def settle(hass: HomeAssistant) -> None:
    """Give the background notification listener a chance to run, then block till done."""
    for _ in range(25):
        await asyncio.sleep(0)
    await hass.async_block_till_done()
