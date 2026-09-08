"""Position sliders, one per rail.

The cover entities already accept a position, but Home Assistant renders a cover as
up/stop/down buttons in most places and hides its slider in the more-info dialog. These
number entities put a plain 0-100 slider on the dashboard, in 10% steps, which is closer to
how the Norman app drives a shade and is easier to use from an automation or a voice assistant
("set the bedroom shade to 30").

They read and write the same hub values as the covers, so the two never disagree.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import COVER_TYPE_SINGLE_RAIL
from .coordinator import NormanConfigEntry, NormanCoordinator
from .entity import NormanRailMixin, async_add_entities_for_new_devices
from .models import NormanPeripheralData

_LOGGER = logging.getLogger(__name__)

# Push-updated by the coordinator; commands are not throttled.
PARALLEL_UPDATES = 0

# The hub takes any whole percentage, but a 10% step is what makes the slider usable with a
# mouse or a keyboard: 11 stops instead of 101. Anything finer is what the Jog buttons and
# the nudge actions are for.
POSITION_STEP = 10


@dataclass(frozen=True, kw_only=True)
class NormanNumberDescription(NumberEntityDescription):
    """Describes a rail slider: how to read the rail, and how to move it."""

    value_fn: Callable[[NormanPeripheralData], int | None]
    # Returns the (bottom, middle) pair to send, with None meaning "leave this rail alone".
    position_fn: Callable[[int], tuple[int | None, int | None]]


NUMBERS: tuple[NormanNumberDescription, ...] = (
    NormanNumberDescription(
        key="bottom_rail_position",
        translation_key="bottom_rail_position",
        value_fn=lambda data: data.bottom_rail_position,
        position_fn=lambda value: (value, None),
    ),
    NormanNumberDescription(
        key="middle_rail_position",
        translation_key="middle_rail_position",
        value_fn=lambda data: data.middle_rail_position,
        position_fn=lambda value: (None, value),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NormanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a slider per rail, including for blinds paired later."""
    coordinator = entry.runtime_data

    def _numbers_for(device_id: int) -> list[NormanNumber]:
        single_rail = coordinator.data[device_id].type == COVER_TYPE_SINGLE_RAIL
        return [
            NormanNumber(coordinator, device_id, entry, description)
            for description in NUMBERS
            # A single-rail blind has no middle rail: the hub reports it as a constant 0.
            if not (single_rail and description.key == "middle_rail_position")
        ]

    async_add_entities_for_new_devices(entry, async_add_entities, _numbers_for)


class NormanNumber(NormanRailMixin, NumberEntity):
    """A 0-100 slider for one rail of one blind."""

    entity_description: NormanNumberDescription

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = POSITION_STEP
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    # Configuration rather than a plain control: the cover entities are the primary way to
    # drive a blind, and this keeps the device page's Controls group to the covers alone.
    _attr_entity_category = EntityCategory.CONFIG

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
