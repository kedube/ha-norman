"""Scenes saved on the Norman hub.

A room scene goes on its room's device, beside the room's preset buttons, and a scene group
-- room scenes in several rooms, run together -- on the hub's. Running one is a single
request; the hub sends each blind to the position the scene stored for it, and the
coordinator then watches every blind and sends any that missed it its own position
(``NormanCoordinator.async_run_scene``).

Scenes are read from the hub's device list, so one added, renamed or deleted in the Norman
app follows on the next read of it. The integration never writes them: a run of scene
writes was followed by the hub failing to read its own configuration, and recovering lost
the scene it had (docs/NORMAN_API.md, "Configuration endpoints").
"""

from __future__ import annotations

from collections.abc import Callable
import functools
from typing import Any

from homeassistant.components.scene import DOMAIN as SCENE_DOMAIN
from homeassistant.components.scene import Scene
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import UndefinedType

from .api import NormanApiError, NormanConnectionError
from .const import DOMAIN
from .coordinator import NormanConfigEntry, NormanCoordinator
from .entity import NormanScopeEntity, scope_unique_id
from .models import NormanScene, NormanSceneGroup

PARALLEL_UPDATES = 0

# The scenes' translation keys (strings.json, entity.scene).
ROOM_SCENE_KEY = "room_scene"
SCENE_GROUP_KEY = "scene_group"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NormanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a scene for each one saved on the hub, following the hub's list as it changes."""
    coordinator = entry.runtime_data
    added: set[str] = set()
    synced: tuple[frozenset[str], bool] | None = None

    @callback
    def _async_sync() -> None:
        nonlocal synced
        wanted: dict[str, Callable[[], NormanSceneEntity]] = {}
        for scene in coordinator.scenes.values():
            unique_id = scope_unique_id(entry, scene.room_id, _scene_key(scene))
            wanted[unique_id] = functools.partial(NormanRoomScene, coordinator, entry, scene)
        for group in coordinator.scene_groups.values():
            unique_id = scope_unique_id(entry, None, _group_key(group))
            wanted[unique_id] = functools.partial(NormanSceneGroupEntity, coordinator, entry, group)
        # The list read is part of what was synced: the first good read after a failed one
        # still clears away scenes deleted meanwhile, even when it finds none at all.
        state = (frozenset(wanted), coordinator.has_device_list)
        if state == synced:
            return
        synced = state
        # A scene deleted in the Norman app, while Home Assistant was running or not. The
        # scenes only change on a successful read of the hub's device list, so a hub that
        # cannot read its configuration for a while does not take them away.
        if coordinator.has_device_list:
            registry = er.async_get(hass)
            for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
                if registry_entry.domain == SCENE_DOMAIN and registry_entry.unique_id not in wanted:
                    registry.async_remove(registry_entry.entity_id)
                    added.discard(registry_entry.unique_id)
        new = [make() for unique_id, make in wanted.items() if unique_id not in added]
        added.update(wanted)
        if new:
            async_add_entities(new)

    _async_sync()
    entry.async_on_unload(coordinator.async_add_listener(_async_sync))


def _scene_key(scene: NormanScene) -> str:
    return f"scene_{scene.scene_id}"


def _group_key(group: NormanSceneGroup) -> str:
    return f"scene_group_{group.group_id}"


class NormanSceneEntity(NormanScopeEntity, Scene):
    """A scene saved on the hub, named as the Norman app names it."""

    def __init__(
        self,
        coordinator: NormanCoordinator,
        entry: NormanConfigEntry,
        room_id: int | None,
        key: str,
        name: str,
    ) -> None:
        """Attach the scene to its room's device, or to the hub's for a scene group."""
        super().__init__(coordinator, entry, room_id, EntityDescription(key=key))
        # Kept for while the scene is missing from the hub's list, until it is removed.
        self._name = name

    @property
    def name(self) -> str | UndefinedType | None:
        """The scene's name in the Norman app, following renames there.

        A scene saved without one is called what its kind is called ("Scene", "Scene
        group"), in the user's language, through its translation key.
        """
        saved = self._saved
        if saved is not None:
            self._name = saved.name
        return self._name or super().name

    @property
    def available(self) -> bool:
        """Unavailable while the hub is unreachable or no longer lists the scene."""
        return super().available and self._saved is not None

    @property
    def _saved(self) -> NormanScene | NormanSceneGroup | None:
        raise NotImplementedError


class NormanRoomScene(NormanSceneEntity):
    """A scene saved in one of the hub's rooms."""

    # The name is the app's; the translated one is only for a scene saved without one. The
    # key is also how the dashboard card tells a room's scenes from the hub's scene groups:
    # the registry it reads carries no unique id.
    _attr_translation_key = ROOM_SCENE_KEY

    def __init__(
        self, coordinator: NormanCoordinator, entry: NormanConfigEntry, scene: NormanScene
    ) -> None:
        """Attach the scene to its room's device."""
        super().__init__(coordinator, entry, scene.room_id, _scene_key(scene), scene.name)
        self._key = scene.key

    @property
    def _saved(self) -> NormanScene | None:
        return self.coordinator.scenes.get(self._key)

    @property
    def available(self) -> bool:
        """As for any scene; a room scene does not need its room to hold a blind."""
        return self.coordinator.last_update_success and self._saved is not None

    async def async_activate(self, **kwargs: Any) -> None:
        """Run the scene on the hub; each of its blinds is then watched."""
        scene = self._saved
        if scene is None:
            return
        try:
            await self.coordinator.async_run_scene(scene)
        except (NormanApiError, NormanConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="scene_failed",
                translation_placeholders={"name": scene.name, "error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()


class NormanSceneGroupEntity(NormanSceneEntity):
    """A group of room scenes saved on the hub, run together across rooms."""

    _attr_translation_key = SCENE_GROUP_KEY

    def __init__(
        self, coordinator: NormanCoordinator, entry: NormanConfigEntry, group: NormanSceneGroup
    ) -> None:
        """Attach the group to the hub's device: its scenes span rooms."""
        super().__init__(coordinator, entry, None, _group_key(group), group.name)
        self._group_id = group.group_id

    @property
    def _saved(self) -> NormanSceneGroup | None:
        return self.coordinator.scene_groups.get(self._group_id)

    async def async_activate(self, **kwargs: Any) -> None:
        """Run the scene group on the hub; every blind its scenes send is then watched."""
        group = self._saved
        if group is None:
            return
        try:
            await self.coordinator.async_run_scene_group(group)
        except (NormanApiError, NormanConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="scene_failed",
                translation_placeholders={"name": group.name, "error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
