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
from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    async_get_current_platform,
)
from homeassistant.helpers.typing import VolDictType
import voluptuous as vol

from .api import NormanApiError, NormanConnectionError
from .const import (
    ATTR_LOUVER_POSITION,
    ATTR_STACK,
    ATTR_STEP,
    ATTR_TARGET_POSITION,
    ATTR_TARGET_TILT,
    COVER_TYPE_DRAPE,
    COVER_TYPE_SHEER,
    COVER_TYPE_SHUTTER,
    COVER_TYPE_SINGLE_RAIL,
    COVER_TYPE_TWO_RAIL,
    DOMAIN,
    MSD_VANE_OPEN_STOP,
    MSD_VANE_STOPS,
    SERVICE_NUDGE_POSITION,
    SERVICE_NUDGE_TILT,
    SHUTTER_CLOSED,
    SHUTTER_OPEN,
)
from .coordinator import NormanConfigEntry, NormanCoordinator
from .entity import (
    NormanRailMixin,
    async_add_entities_for_new_devices,
    async_remove_entity,
    clamp_position,
)

_LOGGER = logging.getLogger(__name__)

# The Middle rail cover's unique id is the peripheral id plus this.
MIDDLE_RAIL_SUFFIX = "_middle"

# Entities are push-updated by the coordinator; commands are not throttled.
PARALLEL_UPDATES = 0

NUDGE_SCHEMA: VolDictType = {
    vol.Required(ATTR_STEP): vol.All(vol.Coerce(int), vol.Range(min=-100, max=100))
}

# How open a SmartDrape's vanes or a Shutter's louvers can be, in steps from closed: the
# drape's seven vane stops fold to four (closed, a third, two thirds, open) and the Shutter's
# eight louver positions to five (closed, a quarter ... open). The cover's tilt is the step
# as a percentage.
VANE_LEVELS = MSD_VANE_OPEN_STOP
LOUVER_LEVELS = SHUTTER_CLOSED - SHUTTER_OPEN


def _percent(level: int, levels: int) -> int:
    return round(level * 100 / levels)


def _level(percent: int, levels: int) -> int:
    return round(clamp_position(percent) * levels / 100)


def _nudged(level: int, step: int, levels: int) -> int:
    """The level ``step`` percent from ``level``, moving at least one level for any step."""
    target = round(level + step * levels / 100)
    if target == level and step:
        target += 1 if step > 0 else -1
    return max(0, min(levels, target))


def _vane_level(raw: int) -> int:
    """How open a SmartDrape's vanes are, 0-3, from the middle rail's raw stop."""
    stop = min(range(len(MSD_VANE_STOPS)), key=lambda i: abs(MSD_VANE_STOPS[i] - raw))
    return VANE_LEVELS - abs(stop - MSD_VANE_OPEN_STOP)


def _vane_raw(level: int) -> int:
    """The middle-rail stop for a vane level, closing towards 100 (the Best Privacy side)."""
    return MSD_VANE_STOPS[len(MSD_VANE_STOPS) - 1 - level]


def _louver_level(position: int) -> int:
    """How open a Shutter's louvers are, 0-4: 7 closed, 3 horizontal, 0 tilted the other way."""
    if position >= SHUTTER_OPEN:
        return SHUTTER_CLOSED - position
    return LOUVER_LEVELS - (SHUTTER_OPEN - position)


def _louver_position(level: int) -> int:
    """The Position for a louver level, on the side "Fully Close" and calibration use."""
    return SHUTTER_CLOSED - level


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
        if cover_type == COVER_TYPE_TWO_RAIL:
            # Day/night and top-down/bottom-up shades have a second fabric on the middle
            # rail; the app shows two sliders, so it gets its own cover here as well. A
            # drape's or a PerfectSheer's middle rail is its vane tilt, which its one cover
            # already has, and a Shutter has no rails.
            covers.append(NormanMiddleRailCover(coordinator, device_id, entry))
        else:
            async_remove_entity(hass, entry, COVER_DOMAIN, f"{device_id}{MIDDLE_RAIL_SUFFIX}")
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
    """A two-rail covering (ModuleType 33, day/night, top-down/bottom-up): position + tilt."""

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


class NormanDrape(NormanBlind):
    """A SmartDrape (ModuleType 80): how far it is drawn as position, its vanes as tilt.

    The hub carries the two in the same fields as a shade's rails -- the bottom rail is the
    draw, the middle rail the vanes -- but they are independent motions, so neither is
    carried along by the other (see ``_async_set_position``). There is no Middle rail cover:
    the tilt already is one.

    The vanes take seven stops (``MSD_VANE_STOPS``), closed at both ends and open at 50, so
    the tilt is how open they are: 0, 33, 67 or 100. Either closed end reads 0; a tilt sent
    from here closes them towards 100, which is where Best Privacy puts them.
    """

    _attr_device_class = CoverDeviceClass.CURTAIN

    @property
    def current_cover_tilt_position(self) -> int | None:
        """How open the vanes are, 0-100, from the middle rail's stop."""
        data = self._data
        if data is None or data.middle_rail_position is None:
            return None
        return _percent(_vane_level(data.middle_rail_position), VANE_LEVELS)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The draw's target, how open the vanes are heading to be, and the stack side."""
        data = self._data
        target = data.target_middle_rail_position if data else None
        return {
            ATTR_TARGET_POSITION: data.target_bottom_rail_position if data else None,
            ATTR_TARGET_TILT: None
            if target is None
            else _percent(_vane_level(target), VANE_LEVELS),
            # Which side the drape gathers to when open; the dashboard card draws it there.
            ATTR_STACK: data.stack if data else None,
        }

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Open the vanes fully (the middle stop, 50)."""
        await self._async_set_vanes(VANE_LEVELS, "open tilt")

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Close the vanes (towards 100, the Best Privacy side)."""
        await self._async_set_vanes(0, "close tilt")

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Open the vanes to the stop nearest ``tilt_position``."""
        tilt = kwargs[ATTR_TILT_POSITION]
        await self._async_set_vanes(_level(tilt, VANE_LEVELS), "set tilt position", tilt)

    async def async_nudge_tilt(self, step: int) -> None:
        """Open or close the vanes by ``step``, at least one stop for any step."""
        level = _vane_level(self._target_or_current_middle())
        await self._async_set_vanes(_nudged(level, step, VANE_LEVELS), "nudge tilt", step)

    async def _async_set_vanes(self, level: int, action: str, value: int | None = None) -> None:
        await self._async_set_position(
            bottom=None, middle=_vane_raw(level), action=action, value=value
        )


class NormanSheer(NormanBlind):
    """A PerfectSheer (ModuleType 48/49, ModuleDetail 3): the shade as position, vanes as tilt.

    The shade is the bottom rail, the vanes between its two sheers the middle rail, 0
    closed to 100 open -- the app draws the vanes more see-through as the value rises. As on
    a drape the two are independent, so neither carries the other. The app only draws the
    vanes while the shade is fully lowered, which is presumably the only place they open.
    """

    _attr_device_class = CoverDeviceClass.SHADE


class NormanShutter(NormanCoverBase):
    """A Shutter (ModuleType 1): its louvers as tilt, open/close turning them.

    A Shutter has no rails. The hub reports its louvers as ``Position`` 0-7: 7 fully closed,
    3 horizontal, 0 as far as they turn the other way, which still lets light in. The tilt is
    how open they are -- 0, 25, 50, 75 or 100 -- so both sides of horizontal read the same;
    a tilt sent from here turns them on the 7-3 side, the one the app's "Fully Close" and
    calibration start from. Open and close turn the louvers too, so "open the shutters" does
    what it says.
    """

    _attr_translation_key = "louvers"
    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.OPEN_TILT
        | CoverEntityFeature.CLOSE_TILT
        | CoverEntityFeature.SET_TILT_POSITION
    )

    @property
    def is_closed(self) -> bool | None:
        """Closed only when the louvers are fully shut (Position 7)."""
        data = self._data
        if data is None or data.position is None:
            return None
        return data.position == SHUTTER_CLOSED

    @property
    def current_cover_position(self) -> int | None:
        """A Shutter has no rail to report."""
        return None

    @property
    def current_cover_tilt_position(self) -> int | None:
        """How open the louvers are, 0-100."""
        data = self._data
        if data is None or data.position is None:
            return None
        return _percent(_louver_level(data.position), LOUVER_LEVELS)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Where the louvers are heading, and the hub's own 0-7 Position."""
        data = self._data
        target = data.target_position if data else None
        return {
            ATTR_TARGET_TILT: None
            if target is None
            else _percent(_louver_level(target), LOUVER_LEVELS),
            ATTR_LOUVER_POSITION: data.position if data else None,
        }

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Turn the louvers horizontal."""
        await self._async_set_louvers(SHUTTER_OPEN, "open cover")

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the louvers fully."""
        await self._async_set_louvers(SHUTTER_CLOSED, "close cover")

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Turn the louvers horizontal."""
        await self._async_set_louvers(SHUTTER_OPEN, "open tilt")

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Close the louvers fully."""
        await self._async_set_louvers(SHUTTER_CLOSED, "close tilt")

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Open the louvers to the step nearest ``tilt_position``."""
        tilt = kwargs[ATTR_TILT_POSITION]
        position = _louver_position(_level(tilt, LOUVER_LEVELS))
        await self._async_set_louvers(position, "set tilt position", tilt)

    async def async_nudge_tilt(self, step: int) -> None:
        """Open or close the louvers by ``step``, at least one step for any step."""
        level = _louver_level(self._target_or_current_louvers())
        position = _louver_position(_nudged(level, step, LOUVER_LEVELS))
        await self._async_set_louvers(position, "nudge tilt", step)

    async def async_nudge_position(self, step: int) -> None:
        """A Shutter's only motion is its louvers, so a position nudge turns them."""
        await self.async_nudge_tilt(step)

    def _target_or_current_louvers(self) -> int:
        data = self._data
        for value in (
            data.target_position if data else None,
            data.position if data else None,
        ):
            if value is not None:
                return value
        return SHUTTER_CLOSED

    async def _async_set_louvers(
        self, position: int, action: str, value: int | None = None
    ) -> None:
        try:
            await self.coordinator.api.async_set_louvers(self._device_id, position)
        except (NormanApiError, NormanConnectionError) as err:
            detail = f" (value: {value})" if value is not None else ""
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={
                    "action": f"{action}{detail}",
                    "name": self._device_name,
                    "error": str(err),
                },
            ) from err
        self.coordinator.async_watch_louvers(self._device_id, position)
        await self.coordinator.async_request_refresh()


class NormanMiddleRailCover(NormanCoverBase):
    """The middle rail of a two-rail covering as a cover of its own.

    On a day/night shade this is the second fabric; on a top-down/bottom-up shade it is the
    top rail. Position semantics match the primary: 0 closed, 100 open, as the hub reports.
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
        self._attr_unique_id = f"{device_id}{MIDDLE_RAIL_SUFFIX}"

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
    COVER_TYPE_DRAPE: NormanDrape,
    COVER_TYPE_SHEER: NormanSheer,
    COVER_TYPE_SHUTTER: NormanShutter,
}
