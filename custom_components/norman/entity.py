"""Base entity and shared helpers for Norman platforms."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import NormanApiError, NormanConnectionError
from .const import COVER_TYPE_SINGLE_RAIL, COVER_TYPE_TWO_RAIL, DOMAIN, MANUFACTURER
from .coordinator import NormanConfigEntry, NormanCoordinator, hub_identifier
from .models import NormanPeripheralData

# Model names follow the Norman app's product catalogue (its General_Display_* strings).
# ModuleType 33 matches the app's dual-rail Cellular Shade (Japanese: "honeycomb screen,
# twin, up/down"), which is what every type-33 blind on the reference hub is. ModuleType 32
# has not been matched to a catalogue entry yet (Roller Shade, single Cellular Shade,
# PerfectSheer, and Shutter are the candidates), so it keeps a descriptive name.
COVER_TYPE_MODELS = {
    COVER_TYPE_TWO_RAIL: "Cellular Shade (dual rail)",
    COVER_TYPE_SINGLE_RAIL: "Single-rail window covering",
}


def _via_hub(coordinator: NormanCoordinator, entry: NormanConfigEntry) -> dict:
    """Link a blind's device to the hub device.

    Home Assistant 2026.9 replaced DeviceInfo's ``via_device`` (an identifier tuple) with
    ``via_device_id`` (a registry id) and warns on the old key; earlier releases only know
    the old one. Pick whichever this release supports.
    """
    if "via_device_id" in DeviceInfo.__annotations__:
        return {"via_device_id": coordinator.hub_device_id}
    return {"via_device": (DOMAIN, hub_identifier(entry))}


class NormanEntity(CoordinatorEntity[NormanCoordinator]):
    """An entity belonging to one Norman peripheral."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NormanCoordinator,
        device_id: int,
        entry: NormanConfigEntry,
    ) -> None:
        """Initialize the entity and its device."""
        super().__init__(coordinator)
        self._device_id = device_id

        device_data = coordinator.data[device_id]
        self._device_name = device_data.name or f"Norman Cover {device_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device_id))},
            name=self._device_name,
            manufacturer=MANUFACTURER,
            model=COVER_TYPE_MODELS.get(device_data.type, "Window covering"),
            model_id=(
                f"{device_data.module_type}/{device_data.module_detail}"
                if device_data.module_type is not None
                else None
            ),
            suggested_area=device_data.room_name or None,
            sw_version=device_data.display_firmware_version,
            # The app's "Serial Number" is believed to be the PeripheralUID: no other
            # per-blind identifier appears in any hub payload.
            serial_number=str(device_id),
            **_via_hub(coordinator, entry),
        )

    @property
    def _data(self) -> NormanPeripheralData | None:
        """Return this peripheral's latest data, if the hub still reports it."""
        return self.coordinator.data.get(self._device_id)

    @property
    def available(self) -> bool:
        """Unavailable when the hub is unreachable or no longer reports this peripheral.

        A blind that is out of radio range or has a flat battery is not distinguishable
        from a healthy one here: the hub keeps listing it in ``status`` with its last known
        position, and the fields that might reveal the difference do not. ``RssiMean`` reads
        0 on healthy two-rail blinds, and ``Timestamp`` is the last state *change*, so a
        blind nobody has moved for a week looks identical to one that has dropped off.
        Marking a blind unavailable on either would blank working entities, which is worse
        than a stale position. So availability tracks only what the hub actually tells us:
        the peripheral is gone from the payload entirely, or the hub itself is unreachable.
        """
        return super().available and self._device_id in self.coordinator.data


def clamp_position(value: int) -> int:
    """Clamp a rail position to the 0-100 range Home Assistant uses."""
    return max(0, min(100, value))


class NormanRailMixin(NormanEntity):
    """Shared rail arithmetic for entities that move a blind.

    The hub's control call always takes **both** rails, so any entity that moves one rail
    has to send the other back unchanged. That rule, and the "target, then current, then
    fully open" fallback it needs, lives here so the cover and number platforms cannot
    drift apart.
    """

    def _target_or_current_bottom(self) -> int:
        """Bottom rail value to send when a command leaves the bottom rail alone."""
        data = self._data
        if data is None:
            return 100
        for value in (data.target_bottom_rail_position, data.bottom_rail_position):
            if value is not None:
                return value
        return 100

    def _target_or_current_middle(self) -> int:
        """Middle rail value to send when a command leaves the middle rail alone."""
        data = self._data
        if data is None:
            return 100
        for value in (data.target_middle_rail_position, data.middle_rail_position):
            if value is not None:
                return value
        return 100

    async def _async_set_position(
        self,
        bottom: int | None,
        middle: int | None,
        action: str,
        value: int | None = None,
    ) -> None:
        """Send both rail positions to the hub; ``None`` keeps a rail where it is heading."""
        bottom_val = self._target_or_current_bottom() if bottom is None else clamp_position(bottom)
        middle_val = self._target_or_current_middle() if middle is None else clamp_position(middle)

        try:
            await self.coordinator.api.async_set_position(self._device_id, bottom_val, middle_val)
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
        await self.coordinator.async_request_refresh()

    async def _async_stop_motor(self) -> None:
        """Stop the motor where it is (the hub has one stop per blind, not per rail)."""
        try:
            await self.coordinator.api.async_stop(self._device_id)
        except (NormanApiError, NormanConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="stop_failed",
                translation_placeholders={"name": self._device_name, "error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class NormanHubEntity(CoordinatorEntity[NormanCoordinator]):
    """An entity belonging to the hub itself."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NormanCoordinator, entry: NormanConfigEntry) -> None:
        """Attach the entity to the hub device created at setup."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub_identifier(entry))})


@callback
def async_add_entities_for_new_devices(
    entry: NormanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[int], Iterable[Entity]],
) -> None:
    """Create entities for every peripheral now, and for new ones as the hub reports them.

    ``factory`` receives a peripheral id and returns the entities for it. The listener is
    detached when the entry unloads.
    """
    coordinator = entry.runtime_data
    known_ids: set[int] = set()

    @callback
    def _async_add_new() -> None:
        new_ids = set(coordinator.data) - known_ids
        if not new_ids:
            return
        known_ids.update(new_ids)
        async_add_entities(entity for device_id in sorted(new_ids) for entity in factory(device_id))

    _async_add_new()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))
