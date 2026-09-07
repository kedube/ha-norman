"""Base entity and shared helpers for Norman platforms."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import NormanConfigEntry, NormanCoordinator
from .models import NormanPeripheralData


def hub_identifier(entry: NormanConfigEntry) -> str:
    """Return the device-registry identifier used for the hub device."""
    return f"hub_{entry.entry_id}"


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
            model=f"Window Covering {device_data.module_type}",
            suggested_area=device_data.room_name or None,
            sw_version=device_data.firmware_version,
            **_via_hub(coordinator, entry),
        )

    @property
    def _data(self) -> NormanPeripheralData | None:
        """Return this peripheral's latest data, if the hub still reports it."""
        return self.coordinator.data.get(self._device_id)

    @property
    def available(self) -> bool:
        """Unavailable when the hub is unreachable or no longer reports this peripheral."""
        # TODO: handle case where individual devices can go offline
        return super().available and self._device_id in self.coordinator.data


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
