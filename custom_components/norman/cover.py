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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    async_get_current_platform,
)
import voluptuous as vol

from .api import NormanApiError, NormanConnectionError
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
from .entity import NormanEntity, async_add_entities_for_new_devices

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
        cover_class = COVER_CLASSES.get(coordinator.data[device_id].type, NormanBlind)
        return [cover_class(coordinator, device_id, entry)]

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


def _clamp(value: int) -> int:
    """Clamp a position to the 0-100 range Home Assistant uses."""
    return max(0, min(100, value))


class NormanCoverBase(NormanEntity, CoverEntity):
    """Base class for Norman covers: a single bottom rail with position control.

    Used directly for single-rail products (ModuleType 32): the hub still wants a middle
    rail value in every command, and reports it as 0, so it is echoed back unchanged.
    """

    # The cover is the device's primary entity, so it takes the device's name
    _attr_name = None
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

    def _target_or_current_bottom(self) -> int:
        """Bottom rail value to send when a command leaves the bottom rail alone."""
        data = self._data
        if data is None:
            return 100
        if data.target_bottom_rail_position is not None:
            return data.target_bottom_rail_position
        if data.bottom_rail_position is not None:
            return data.bottom_rail_position
        return 100

    def _target_or_current_middle(self) -> int:
        """Middle rail value to send when a command leaves the middle rail alone."""
        data = self._data
        if data is None:
            return 100
        if data.target_middle_rail_position is not None:
            return data.target_middle_rail_position
        if data.middle_rail_position is not None:
            return data.middle_rail_position
        return 100

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
        await self._async_stop()

    async def _async_stop(self) -> None:
        try:
            await self.coordinator.api.async_stop(self._device_id)
        except (NormanApiError, NormanConnectionError) as err:
            raise HomeAssistantError(f"Failed to stop {self._device_name}: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_nudge_position(self, step: int) -> None:
        """Move the cover by ``step`` relative to where it is heading (or is)."""
        new_pos = _clamp(self._target_or_current_bottom() + step)
        await self.async_set_cover_position(position=new_pos)

    async def _async_set_position(
        self,
        bottom: int | None,
        middle: int | None,
        action: str,
        value: int | None = None,
    ) -> None:
        """Send both rail positions to the hub; ``None`` keeps a rail where it is heading.

        The hub's control call always takes both rails, so the untouched rail is sent its
        current target (or current position when no target is known).
        """
        bottom_val = self._target_or_current_bottom() if bottom is None else _clamp(bottom)
        middle_val = self._target_or_current_middle() if middle is None else _clamp(middle)

        try:
            await self.coordinator.api.async_set_position(self._device_id, bottom_val, middle_val)
        except (NormanApiError, NormanConnectionError) as err:
            detail = f" (value: {value})" if value is not None else ""
            raise HomeAssistantError(
                f"Failed to {action}{detail} for {self._device_name}: {err}"
            ) from err
        await self.coordinator.async_request_refresh()


class NormanShade(NormanCoverBase):
    """A single-rail covering: position only."""

    _attr_device_class = CoverDeviceClass.SHADE


class NormanBlind(NormanCoverBase):
    """A two-rail covering (ModuleType 33, SmartDrape, top-down/bottom-up): position + tilt."""

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
        await self._async_stop()

    async def async_nudge_tilt(self, step: int) -> None:
        """Move the tilt by ``step`` relative to where it is heading (or is)."""
        new_tilt = _clamp(self._target_or_current_middle() + step)
        await self.async_set_cover_tilt_position(tilt_position=new_tilt)


# Cover type -> entity class. Types come from MODULE_TYPE_COVER_TYPES in const.py; extend
# both when another Norman product is mapped. Unknown types fall back to the two-rail blind.
COVER_CLASSES: dict[str, type[NormanCoverBase]] = {
    COVER_TYPE_TWO_RAIL: NormanBlind,
    COVER_TYPE_SINGLE_RAIL: NormanShade,
}
