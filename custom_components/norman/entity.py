"""Base entity and shared helpers for Norman platforms."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import NormanApiError, NormanConnectionError
from .const import DOMAIN, MANUFACTURER
from .coordinator import (
    NormanConfigEntry,
    NormanCoordinator,
    hub_identifier,
    room_identifier,
    rooms_of,
)
from .models import NormanDevices, NormanPeripheralData

# Model names are the Norman app's (its General_Display_* strings, English and Japanese), as
# the app picks them from ModuleType and ModuleDetail. 32 and 33 are both "Cellular Shade" in
# the app; the Japanese tells them apart as single and "twin, up/down", kept here as "dual
# rail". The roller family (48, 49) is named by ModuleDetail, 1-3, the way the app's pairing
# list names a newly found blind; another detail keeps the family's name.
MODULE_TYPE_MODELS: dict[int, str] = {
    1: "Shutter",
    32: "Cellular Shade",
    33: "Cellular Shade (dual rail)",
    48: "Roller Shade",
    49: "Roller Shade",
    80: "SmartDrape",
}
MODULE_DETAIL_MODELS: dict[tuple[int, int], str] = {
    (48, 2): "Roman Shade",
    (48, 3): "PerfectSheer",
    (49, 2): "Roman Shade",
    (49, 3): "PerfectSheer",
}


def _model(data: NormanPeripheralData) -> str:
    """The product name for a blind, or "Window covering" for a type the app does not know."""
    if data.module_type is None:
        return "Window covering"
    if data.module_detail is not None:
        model = MODULE_DETAIL_MODELS.get((data.module_type, data.module_detail))
        if model is not None:
            return model
    return MODULE_TYPE_MODELS.get(data.module_type, "Window covering")


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
            model=_model(device_data),
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
        0 on healthy two-rail blinds, and ``Timestamp`` is when the hub last *heard* from the
        blind -- a battery blind's radio sleeps between commands, so a healthy blind nobody
        has touched goes quiet too, and a command still wakes it. Marking a blind
        unavailable on either would blank working entities, which is worse than a stale
        position. So availability tracks only what the hub actually tells us: the
        peripheral is gone from the payload entirely, or the hub itself is unreachable. The
        connection binary sensor reports the quiet-for-a-day case separately, with the
        app's own 24 h rule, and the Request status button ends it.
        """
        return super().available and self._device_id in self.coordinator.data


class NormanRailMixin(NormanEntity):
    """Shared rail handling for entities that move a blind.

    The hub's control call always takes **both** rails, so any entity that moves one rail
    has to send the other back unchanged. That rule, and the "move in flight, then target,
    then current, then fully open" fallback it needs, lives in the coordinator
    (``heading_rails``, ``rails_to_send``) so the cover and number platforms -- and the room
    sliders, which apply it to every blind in a room -- cannot drift apart.
    """

    def _target_or_current_bottom(self) -> int:
        """Bottom rail value to send when a command leaves the bottom rail alone."""
        return self.coordinator.heading_rails(self._device_id)[0]

    def _target_or_current_middle(self) -> int:
        """Middle rail value to send when a command leaves the middle rail alone."""
        return self.coordinator.heading_rails(self._device_id)[1]

    async def _async_set_position(
        self,
        bottom: int | None,
        middle: int | None,
        action: str,
        value: int | None = None,
    ) -> None:
        """Send both rail positions to the hub; ``None`` keeps a rail where it is heading.

        A two-rail blind's rail kept where it is heading is carried along when the other
        would pass it, so the dashboard card can move either rail from anywhere -- fully open
        included (``rails_to_send`` in the coordinator, which ``async_move_blind`` applies).
        """
        try:
            await self.coordinator.async_move_blind(self._device_id, bottom, middle)
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
        self.coordinator.async_supersede([self._device_id])
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


class NormanScopeEntity(CoordinatorEntity[NormanCoordinator]):
    """An entity that acts on every blind in one of the hub's rooms, or on the whole hub.

    ``room_id`` None is the whole hub, and the entity goes on the hub device. A room gets a
    device of its own, named as the hub names the room and suggested into the area of the
    same name, so its controls sit beside its blinds. The hub's room is what counts, not the
    Home Assistant area: the hub addresses a room by its ``RoomID``, whatever area a blind
    has since been moved to.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NormanCoordinator,
        entry: NormanConfigEntry,
        room_id: int | None,
        description: EntityDescription,
    ) -> None:
        """Attach the entity to its room's device, or to the hub's."""
        super().__init__(coordinator)
        self.entity_description = description
        self._room_id = room_id
        if room_id is None:
            # Alongside the hub's other entities, which are keyed the same way.
            self._attr_unique_id = f"{entry.entry_id}_{description.key}"
            self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub_identifier(entry))})
            return
        self._attr_unique_id = f"{entry.entry_id}_{room_id}_{description.key}"
        name = rooms_of(coordinator.data).get(room_id, f"Room {room_id}")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room_identifier(entry, room_id))},
            name=name,
            manufacturer=MANUFACTURER,
            model="Room",
            suggested_area=name,
            **_via_hub(coordinator, entry),
        )

    @property
    def _blinds(self) -> NormanDevices:
        """The blinds this entity acts on, as the hub reports them now."""
        return self.coordinator.blinds_in(self._room_id)

    @property
    def _scope_name(self) -> str:
        """The room's name, or the hub's, for error messages."""
        if self._room_id is None:
            return self.coordinator.hub.custom_name or self.coordinator.config_entry.title
        return rooms_of(self.coordinator.data).get(self._room_id, f"Room {self._room_id}")

    @property
    def available(self) -> bool:
        """Unavailable while the hub is unreachable, and once a room holds no blinds."""
        return super().available and (self._room_id is None or bool(self._blinds))


@callback
def async_add_scope_entities[D: EntityDescription](
    entry: NormanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    wanted: Callable[[NormanDevices], Iterable[tuple[int | None, D]]],
    factory: Callable[[int | None, D], Entity],
) -> None:
    """Create room and hub-wide entities now, and as the blinds that call for them appear.

    ``wanted`` lists the ``(room id, description)`` pairs the hub's blinds call for -- a
    room id of None meaning the whole hub -- and ``factory`` builds the entity for one. A
    newly paired blind can bring a room, or a rail a room did not have before, so the list
    is re-read on every update; each pair is built once. The listener is detached when the
    entry unloads.
    """
    coordinator = entry.runtime_data
    known: set[tuple[int | None, str]] = set()

    @callback
    def _async_add_new() -> None:
        new: list[Entity] = []
        for room_id, description in wanted(coordinator.data):
            if (room_id, description.key) in known:
                continue
            known.add((room_id, description.key))
            new.append(factory(room_id, description))
        if new:
            async_add_entities(new)

    _async_add_new()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))


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


@callback
def async_remove_entity(
    hass: HomeAssistant, entry: NormanConfigEntry, domain: str, unique_id: str
) -> None:
    """Delete this entry's registry entity ``unique_id``, if it has one.

    For an entity a blind's type no longer provides. The type can change under an existing
    install: a ModuleType first seen unmapped is driven as two-rail, and mapping it later as
    something else drops its middle-rail entities. Home Assistant would keep the old entries
    as "no longer provided" -- and the dashboard card, which reads the registry, would go on
    drawing a middle rail the blind does not have.
    """
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
    if entity_id is None:
        return
    registry_entry = registry.async_get(entity_id)
    if registry_entry is not None and registry_entry.config_entry_id == entry.entry_id:
        registry.async_remove(entity_id)
