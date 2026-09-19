"""Whether the hub has heard from each blind recently."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import UNRESPONSIVE_AFTER
from .coordinator import NormanConfigEntry, NormanCoordinator
from .entity import NormanEntity, NormanHubEntity, async_add_entities_for_new_devices
from .sensor import parse_last_update

_LOGGER = logging.getLogger(__name__)

# Push-updated by the coordinator; nothing to throttle.
PARALLEL_UPDATES = 0

# The state also depends on the clock: a blind that goes quiet crosses the threshold with
# no hub event to mark it. Re-evaluating this often bounds how late the sensor can be.
RECHECK_INTERVAL = timedelta(minutes=15)

CONNECTION = BinarySensorEntityDescription(
    key="connection",
    translation_key="connection",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)

# On the hub: whether its pairing window is open. `status` reports `PairingMode: 5` for ten
# minutes after the Start pairing button (or the app) opens it, and 0 otherwise.
PAIRING_MODE = BinarySensorEntityDescription(
    key="pairing_mode",
    translation_key="pairing_mode",
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NormanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a connection sensor for every blind, including ones paired later."""
    coordinator = entry.runtime_data

    async_add_entities([NormanPairingModeSensor(coordinator, entry)])

    def _sensors_for(device_id: int) -> list[NormanConnectionSensor]:
        return [NormanConnectionSensor(coordinator, device_id, entry)]

    async_add_entities_for_new_devices(entry, async_add_entities, _sensors_for)


class NormanPairingModeSensor(NormanHubEntity, BinarySensorEntity):
    """On while the hub's pairing window is open."""

    entity_description = PAIRING_MODE

    def __init__(self, coordinator: NormanCoordinator, entry: NormanConfigEntry) -> None:
        """Attach the sensor to the hub device."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{PAIRING_MODE.key}"

    @property
    def is_on(self) -> bool | None:
        """True when status reports a non-zero PairingMode; None if the hub never said."""
        mode = self.coordinator.hub.pairing_mode
        return None if mode is None else mode != 0


class NormanConnectionSensor(NormanEntity, BinarySensorEntity):
    """On while the hub has heard from the blind within the app's "Disconnect" window.

    The hub's per-blind ``Timestamp`` is when it last heard from the blind -- it moves
    when the blind reports in with nothing changed, not only on a state change. The Norman
    app lists a blind as "Disconnect" once that is more than 24 h old
    (``UNRESPONSIVE_AFTER``); this sensor applies the same rule, so the two agree. A blind
    that has never reported a timestamp is *unknown* rather than off.

    A quiet blind is not necessarily unreachable -- a battery blind's radio sleeps and a
    command still wakes it -- so this is deliberately a sensor and not the availability of
    the blind's other entities. The Request status button (or the hub's Refresh blinds)
    asks it to report in, which is the fastest way to turn this back on.
    """

    entity_description = CONNECTION

    def __init__(
        self, coordinator: NormanCoordinator, device_id: int, entry: NormanConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, entry)
        self._attr_unique_id = f"{device_id}_{CONNECTION.key}"

    async def async_added_to_hass(self) -> None:
        """Re-evaluate on a timer as well as on hub updates; the threshold is time-based."""
        await super().async_added_to_hass()

        @callback
        def _recheck(_now: object) -> None:
            self.async_write_ha_state()

        self.async_on_remove(async_track_time_interval(self.hass, _recheck, RECHECK_INTERVAL))

    @property
    def is_on(self) -> bool | None:
        """True when the blind was heard from within the window; None when never dated."""
        data = self._data
        last_seen = parse_last_update(data.last_update) if data else None
        if last_seen is None:
            return None
        return dt_util.utcnow() - last_seen <= UNRESPONSIVE_AFTER
