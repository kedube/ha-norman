"""Position sliders, one per rail.

The cover entities already accept a position, but Home Assistant renders a cover as
up/stop/down buttons in most places and hides its slider in the more-info dialog. These
number entities put a plain 0-100 slider on the dashboard, in 10% steps, which is closer to
how the Norman app drives a shade and is easier to use from an automation or a voice assistant
("set the bedroom shade to 30").

They read and write the same hub values as the covers, so the two never disagree.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
import logging

from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import NormanApiError, NormanConnectionError
from .const import DOMAIN
from .coordinator import (
    NormanConfigEntry,
    NormanCoordinator,
    has_bottom_rail,
    has_middle_rail,
    rooms_of,
)
from .entity import (
    NormanRailMixin,
    NormanScopeEntity,
    async_add_entities_for_new_devices,
    async_add_scope_entities,
    async_remove_entity,
)
from .models import NormanDevices, NormanPeripheralData

_LOGGER = logging.getLogger(__name__)

# Push-updated by the coordinator; commands are not throttled.
PARALLEL_UPDATES = 0

# The hub takes any whole percentage, but a 10% step is what makes the slider usable with a
# mouse or a keyboard: 11 stops instead of 101. Anything finer is what the Jog buttons and
# the nudge actions are for.
POSITION_STEP = 10

BOTTOM_RAIL_POSITION = "bottom_rail_position"
MIDDLE_RAIL_POSITION = "middle_rail_position"


def _rails_for(cover_type: str) -> frozenset[str]:
    """The rail sliders a cover type gets.

    Only a two-rail shade gets a middle-rail slider. A single-rail blind reports that rail as
    a constant 0; on a drape or a PerfectSheer it is the vane tilt, which the cover already
    offers -- and a slider for it would have the dashboard card draw a second fabric. A
    Shutter has no rails at all: its louvers are the cover's tilt.
    """
    rails: set[str] = set()
    if has_bottom_rail(cover_type):
        rails.add(BOTTOM_RAIL_POSITION)
    if has_middle_rail(cover_type):
        rails.add(MIDDLE_RAIL_POSITION)
    return frozenset(rails)


@dataclass(frozen=True, kw_only=True)
class NormanNumberDescription(NumberEntityDescription):
    """Describes a rail slider: how to read the rail, and how to move it."""

    value_fn: Callable[[NormanPeripheralData], int | None]
    # Returns the (bottom, middle) pair to send, with None meaning "leave this rail alone".
    position_fn: Callable[[int], tuple[int | None, int | None]]


NUMBERS: tuple[NormanNumberDescription, ...] = (
    NormanNumberDescription(
        key=BOTTOM_RAIL_POSITION,
        translation_key=BOTTOM_RAIL_POSITION,
        value_fn=lambda data: data.bottom_rail_position,
        position_fn=lambda value: (value, None),
    ),
    NormanNumberDescription(
        key=MIDDLE_RAIL_POSITION,
        translation_key=MIDDLE_RAIL_POSITION,
        value_fn=lambda data: data.middle_rail_position,
        position_fn=lambda value: (None, value),
    ),
)
_BLIND_NUMBERS = {description.key: description for description in NUMBERS}


@dataclass(frozen=True, kw_only=True)
class NormanScopeNumberDescription(NumberEntityDescription):
    """A rail slider for every blind in a room, or on the hub."""

    # The per-blind slider this one stands for: it reads and moves that rail on every blind
    # in scope that has one, and leaves the rest alone.
    rail: str


# One room's rails, on the room's device. Present when some blind in the room has the rail.
ROOM_NUMBERS: tuple[NormanScopeNumberDescription, ...] = (
    NormanScopeNumberDescription(
        key="room_bottom_rail_position",
        translation_key="room_bottom_rail_position",
        rail=BOTTOM_RAIL_POSITION,
    ),
    NormanScopeNumberDescription(
        key="room_middle_rail_position",
        translation_key="room_middle_rail_position",
        rail=MIDDLE_RAIL_POSITION,
    ),
)
# Every blind's rails, on the hub device: the same request with no RoomID at all.
HUB_NUMBERS: tuple[NormanScopeNumberDescription, ...] = (
    NormanScopeNumberDescription(
        key="all_bottom_rail_position",
        translation_key="all_bottom_rail_position",
        rail=BOTTOM_RAIL_POSITION,
    ),
    NormanScopeNumberDescription(
        key="all_middle_rail_position",
        translation_key="all_middle_rail_position",
        rail=MIDDLE_RAIL_POSITION,
    ),
)


def _scope_numbers(
    devices: NormanDevices,
) -> Iterator[tuple[int | None, NormanScopeNumberDescription]]:
    """The room and hub-wide sliders the hub's blinds call for: a rail some blind has."""
    rails_by_room: dict[int, set[str]] = {room_id: set() for room_id in rooms_of(devices)}
    every_rail: set[str] = set()
    for device in devices.values():
        rails = _rails_for(device.type)
        every_rail |= rails
        if device.room_id is not None:
            rails_by_room[device.room_id] |= rails
    for description in HUB_NUMBERS:
        if description.rail in every_rail:
            yield None, description
    for room_id, room_rails in rails_by_room.items():
        for description in ROOM_NUMBERS:
            if description.rail in room_rails:
                yield room_id, description


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NormanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a slider per rail, including for blinds paired later, and per room."""
    coordinator = entry.runtime_data

    def _numbers_for(device_id: int) -> list[NormanNumber]:
        numbers: list[NormanNumber] = []
        rails = _rails_for(coordinator.data[device_id].type)
        for description in NUMBERS:
            if description.key in rails:
                numbers.append(NormanNumber(coordinator, device_id, entry, description))
            else:
                async_remove_entity(hass, entry, NUMBER_DOMAIN, f"{device_id}_{description.key}")
        return numbers

    async_add_entities_for_new_devices(entry, async_add_entities, _numbers_for)

    def _scope_number(
        room_id: int | None, description: NormanScopeNumberDescription
    ) -> NormanScopeNumber:
        return NormanScopeNumber(coordinator, entry, room_id, description)

    async_add_scope_entities(entry, async_add_entities, _scope_numbers, _scope_number)


class NormanNumber(NormanRailMixin, NumberEntity):
    """A 0-100 slider for one rail of one blind."""

    entity_description: NormanNumberDescription

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = POSITION_STEP
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: NormanCoordinator,
        device_id: int,
        entry: NormanConfigEntry,
        description: NormanNumberDescription,
    ) -> None:
        """Initialize the slider."""
        super().__init__(coordinator, device_id, entry)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> float | None:
        """Return the rail's current position as the hub reports it."""
        data = self._data
        return self.entity_description.value_fn(data) if data else None

    async def async_set_native_value(self, value: float) -> None:
        """Move this rail, leaving the other one where it is heading."""
        bottom, middle = self.entity_description.position_fn(int(value))
        await self._async_set_position(
            bottom=bottom, middle=middle, action="set position", value=int(value)
        )


class NormanScopeNumber(NormanScopeEntity, NumberEntity):
    """One rail of every blind in a room, or on the hub, as a single 0-100 slider.

    Setting it moves that rail on each blind that has one, as each blind's own slider would,
    in one hub request whenever the blinds allow it (``NormanCoordinator.async_move_room``).
    """

    entity_description: NormanScopeNumberDescription

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = POSITION_STEP
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    @property
    def _rail_blinds(self) -> list[NormanPeripheralData]:
        """The blinds in scope that have this rail."""
        rail = self.entity_description.rail
        return [device for device in self._blinds.values() if rail in _rails_for(device.type)]

    @property
    def available(self) -> bool:
        """Unavailable, too, once no blind in scope has the rail."""
        return super().available and bool(self._rail_blinds)

    @property
    def native_value(self) -> float | None:
        """The rail's average position across the blinds that have it.

        As a Home Assistant cover group reports its members, so the slider settles on the
        value it was set to once every blind has arrived, and reads between while they
        travel or when they were left apart.
        """
        read = _BLIND_NUMBERS[self.entity_description.rail].value_fn
        values = [value for device in self._rail_blinds if (value := read(device)) is not None]
        return round(sum(values) / len(values)) if values else None

    async def async_set_native_value(self, value: float) -> None:
        """Move this rail on every blind in scope that has one."""
        position = int(value)
        bottom, middle = _BLIND_NUMBERS[self.entity_description.rail].position_fn(position)
        try:
            await self.coordinator.async_move_room(self._room_id, bottom, middle)
        except (NormanApiError, NormanConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={
                    "action": f"set position (value: {position})",
                    "name": self._scope_name,
                    "error": str(err),
                },
            ) from err
        await self.coordinator.async_request_refresh()
