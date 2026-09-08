"""Support for Norman window coverings."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    async_get_current_platform,
)
import voluptuous as vol

from .const import (
    ATTR_STEP,
    ATTR_TARGET_POSITION,
    ATTR_TARGET_TILT,
    COVER_TYPE_SINGLE_RAIL,
    COVER_TYPE_TWO_RAIL,
    SERVICE_NUDGE_POSITION,
    SERVICE_NUDGE_TILT,
)
from .coordinator import NormanConfigEntry, NormanCoordinator
from .entity import NormanRailMixin, async_add_entities_for_new_devices, clamp_position

_LOGGER = logging.getLogger(__name__)

# Entities are push-updated by the coordinator; commands are not throttled.
PARALLEL_UPDATES = 0

NUDGE_SCHEMA = {vol.Required(ATTR_STEP): vol.All(vol.Coerce(int), vol.Range(min=-100, max=100))}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NormanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Norman cover devices."""
    coordinator = entry.runtime_data

    def _covers_for(device_id: int) -> list[NormanCoverBase]:
        cover_type = coordinator.data[device_id].type
        covers: list[NormanCoverBase] = [
            COVER_CLASSES.get(cover_type, NormanBlind)(coordinator, device_id, entry)
        ]
        if cover_type != COVER_TYPE_SINGLE_RAIL:
            # Day/night and top-down/bottom-up shades have a second fabric on the middle
            # rail; the app shows two sliders, so it gets its own cover here as well.
            covers.append(NormanMiddleRailCover(coordinator, device_id, entry))
        return covers

    async_add_entities_for_new_devices(entry, async_add_entities, _covers_for)

    platform = async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_NUDGE_POSITION, NUDGE_SCHEMA, "async_nudge_position"
    )
    platform.async_register_entity_service(
        SERVICE_NUDGE_TILT,
        NUDGE_SCHEMA,
        "async_nudge_tilt",
        required_features=[CoverEntityFeature.SET_TILT_POSITION],
    )


class NormanCoverBase(NormanRailMixin, CoverEntity):
    """Base class for Norman covers: a single bottom rail with position control.

    Used directly for single-rail products (ModuleType 32): the hub still wants a middle
    rail value in every command, and reports it as 0, so it is echoed back unchanged.
    """

    # Every cover is named for the rail it drives ("Bottom rail", "Middle rail") rather than
    # taking the device's own name. On a two-rail blind that keeps the pair legible: "Living
    # Drape Bottom rail" and "Living Drape Middle rail" instead of one entity called after
    # the device and a second called Middle rail.
    _attr_translation_key = "bottom_rail"
    _attr_device_class = CoverDeviceClass.BLIND
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.STOP
    )

    def __init__(
        self,
        coordinator: NormanCoordinator,
        device_id: int,
        entry: NormanConfigEntry,
    ) -> None:
        """Initialize the cover."""
        super().__init__(coordinator, device_id, entry)
        # The bare peripheral id, kept from the first release so entity ids survive upgrades
        self._attr_unique_id = str(device_id)

    @property
    def is_closed(self) -> bool | None:
        """Return True if the cover is closed, None if the position is unknown."""
        position = self.current_cover_position
        if position is None:
            return None
        return position == 0

    @property
    def current_cover_position(self) -> int | None:
        """Return the bottom rail position, 0 (closed) to 100 (open), as the hub reports it."""
        data = self._data
        return data.bottom_rail_position if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the hub's target position, which leads the current position while moving."""
        data = self._data
        return {ATTR_TARGET_POSITION: data.target_bottom_rail_position if data else None}

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover (bottom rail to 0), leaving the middle rail where it is."""
        await self._async_set_position(bottom=0, middle=None, action="close cover")

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover (bottom rail to 100), leaving the middle rail where it is."""
        await self._async_set_position(bottom=100, middle=None, action="open cover")

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        position = kwargs[ATTR_POSITION]
        await self._async_set_position(
            bottom=position, middle=None, action="set position", value=position
        )

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the motor where it is (the hub has one stop for both rails)."""
        await self._async_stop_motor()

    async def async_nudge_position(self, step: int) -> None:
        """Move the cover by ``step`` relative to where it is heading (or is)."""
        new_pos = clamp_position(self._target_or_current_bottom() + step)
        await self.async_set_cover_position(position=new_pos)


class NormanShade(NormanCoverBase):
    """A single-rail covering: position only."""

    _attr_translation_key = "bottom_rail"
    _attr_device_class = CoverDeviceClass.SHADE


class NormanBlind(NormanCoverBase):
    """A two-rail covering (ModuleType 33, SmartDrape, top-down/bottom-up): position + tilt."""

    _attr_translation_key = "bottom_rail"
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.STOP
        | CoverEntityFeature.OPEN_TILT
        | CoverEntityFeature.CLOSE_TILT
        | CoverEntityFeature.SET_TILT_POSITION
        | CoverEntityFeature.STOP_TILT
    )

    @property
    def current_cover_tilt_position(self) -> int | None:
        """Return the middle rail position (0-100), which the hub uses for tilt."""
        data = self._data
        return data.middle_rail_position if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose both rail targets."""
        data = self._data
        return {
            **super().extra_state_attributes,
            ATTR_TARGET_TILT: data.target_middle_rail_position if data else None,
        }

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Open the cover tilt."""
        await self._async_set_position(bottom=None, middle=100, action="open tilt")

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Close the cover tilt."""
        await self._async_set_position(bottom=None, middle=0, action="close tilt")

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Move the cover tilt to a specific position."""
        tilt_position = kwargs[ATTR_TILT_POSITION]
        await self._async_set_position(
            bottom=None,
            middle=tilt_position,
            action="set tilt position",
            value=tilt_position,
        )

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
        """Stop the tilt: the same motor stop, since the hub has no per-rail stop."""
        await self._async_stop_motor()

    async def async_nudge_tilt(self, step: int) -> None:
        """Move the tilt by ``step`` relative to where it is heading (or is)."""
        new_tilt = clamp_position(self._target_or_current_middle() + step)
        await self.async_set_cover_tilt_position(tilt_position=new_tilt)


class NormanMiddleRailCover(NormanCoverBase):
    """The middle rail of a two-rail covering as a cover of its own.

    On a day/night shade this is the second fabric; on a top-down/bottom-up shade it is the
    top rail; on a SmartDrape it is the vane tilt, which the primary cover also exposes as
    tilt. Position semantics match the primary: 0 closed, 100 open, as the hub reports.
    """

    _attr_translation_key = "middle_rail"
    _attr_device_class = CoverDeviceClass.SHADE

    def __init__(
        self,
        coordinator: NormanCoordinator,
        device_id: int,
        entry: NormanConfigEntry,
    ) -> None:
        """Initialize the middle-rail cover."""
        super().__init__(coordinator, device_id, entry)
        self._attr_unique_id = f"{device_id}_middle"

    @property
    def current_cover_position(self) -> int | None:
        """Return the middle rail position."""
        data = self._data
        return data.middle_rail_position if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the middle rail's target."""
        data = self._data
        return {ATTR_TARGET_POSITION: data.target_middle_rail_position if data else None}

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the middle rail, leaving the bottom rail where it is heading."""
        await self._async_set_position(bottom=None, middle=0, action="close middle rail")

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the middle rail, leaving the bottom rail where it is heading."""
        await self._async_set_position(bottom=None, middle=100, action="open middle rail")

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the middle rail to a specific position."""
        position = kwargs[ATTR_POSITION]
        await self._async_set_position(
            bottom=None, middle=position, action="set middle rail position", value=position
        )

    async def async_nudge_position(self, step: int) -> None:
        """Move the middle rail by ``step`` relative to where it is heading (or is)."""
        await self.async_set_cover_position(
            position=clamp_position(self._target_or_current_middle() + step)
        )


# Cover type -> entity class. Types come from MODULE_TYPE_COVER_TYPES in const.py; extend
# both when another Norman product is mapped. Unknown types fall back to the two-rail blind.
COVER_CLASSES: dict[str, type[NormanCoverBase]] = {
    COVER_TYPE_TWO_RAIL: NormanBlind,
    COVER_TYPE_SINGLE_RAIL: NormanShade,
}
