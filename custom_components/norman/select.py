"""Each blind's color and its window's divided lights: how the card and the sidebar page draw it.

The hub keeps neither, so these are Home Assistant's own record of what the real window looks
like: a fabric for a shade, a paint or a stain for a Shutter, and the glazing bars that divide
the glass. The card reads them from the blind's select entities (by their translation keys, as
it finds every other entity), and the sidebar page sets them from its buttons, as the device
page does under Configuration.

Nothing is sent to the hub. The choices are kept by Home Assistant and restored at start, and
the selects stay available while the hub is out of reach, so the windows keep their looks then
rather than turning back to the defaults.
"""

from __future__ import annotations

from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import COVER_TYPE_SHUTTER
from .coordinator import NormanConfigEntry, NormanCoordinator
from .entity import NormanEntity, async_add_entities_for_new_devices, async_remove_entity

# Set in Home Assistant alone; nothing to throttle.
PARALLEL_UPDATES = 0

# A shade's fabric. Ivory is the cloth the card has always drawn, so a shade nobody has
# chosen a color for looks as it did. The card draws each of these (norman-shades-card.js,
# SHADE_COLORS), and a two-rail shade's blackout takes the color while its sheer stays white.
SHADE_COLORS = (
    "white",
    "ivory",
    "linen",
    "sand",
    "taupe",
    "gray",
    "slate",
    "charcoal",
    "navy",
    "sage",
    "terracotta",
)
DEFAULT_SHADE_COLOR = "ivory"
# A Shutter's paint or stain. White is the trim the card has always drawn it in.
SHUTTER_COLORS = ("white", "ivory", "gray", "black", "oak", "walnut")
DEFAULT_SHUTTER_COLOR = "white"

SHADE_COLOR = SelectEntityDescription(
    key="shade_color",
    translation_key="shade_color",
    entity_category=EntityCategory.CONFIG,
    options=list(SHADE_COLORS),
)
SHUTTER_COLOR = SelectEntityDescription(
    key="shutter_color",
    translation_key="shutter_color",
    entity_category=EntityCategory.CONFIG,
    options=list(SHUTTER_COLORS),
)
# A window's divided lights: the glazing bars across its glass, as the card draws them
# (norman-shades-card.js, WINDOW_LIGHTS). "Over none" divides only the upper sash. Two over two
# is the glass the card has always drawn.
WINDOW_LIGHTS = (
    "none",
    "one_over_one",
    "side_by_side",
    "two_over_none",
    "two_over_two",
    "three_over_none",
    "four_over_none",
    "four_over_four",
    "six_over_none",
    "six_over_six",
    "prairie",
)
DEFAULT_WINDOW_LIGHTS = "two_over_two"
WINDOW_LIGHTS_SELECT = SelectEntityDescription(
    key="window_lights",
    translation_key="window_lights",
    entity_category=EntityCategory.CONFIG,
    options=list(WINDOW_LIGHTS),
)
SELECTS: tuple[SelectEntityDescription, ...] = (SHADE_COLOR, SHUTTER_COLOR, WINDOW_LIGHTS_SELECT)
_DEFAULTS = {
    SHADE_COLOR.key: DEFAULT_SHADE_COLOR,
    SHUTTER_COLOR.key: DEFAULT_SHUTTER_COLOR,
    WINDOW_LIGHTS_SELECT.key: DEFAULT_WINDOW_LIGHTS,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NormanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Give every blind its color and its window's divided lights, including blinds paired later.

    A Shutter's color is a paint or a stain, any other blind's a fabric. A blind whose type
    changes under an existing install (a ModuleType first seen unmapped, mapped later) loses the
    other one, as the card would otherwise read a color list its picture does not use.
    """
    coordinator = entry.runtime_data

    def _selects_for(device_id: int) -> list[NormanDrawnSelect]:
        shutter = coordinator.data[device_id].type == COVER_TYPE_SHUTTER
        wanted, unwanted = (SHUTTER_COLOR, SHADE_COLOR) if shutter else (SHADE_COLOR, SHUTTER_COLOR)
        async_remove_entity(hass, entry, SELECT_DOMAIN, f"{device_id}_{unwanted.key}")
        return [
            NormanDrawnSelect(coordinator, device_id, entry, wanted),
            NormanDrawnSelect(coordinator, device_id, entry, WINDOW_LIGHTS_SELECT),
        ]

    async_add_entities_for_new_devices(entry, async_add_entities, _selects_for)


class NormanDrawnSelect(NormanEntity, SelectEntity, RestoreEntity):
    """How the card draws a blind: kept by Home Assistant, never sent to the hub."""

    def __init__(
        self,
        coordinator: NormanCoordinator,
        device_id: int,
        entry: NormanConfigEntry,
        description: SelectEntityDescription,
    ) -> None:
        """Start at the default; a choice made earlier comes back once added."""
        super().__init__(coordinator, device_id, entry)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_current_option = _DEFAULTS[description.key]

    @property
    def available(self) -> bool:
        """Always: the choice is Home Assistant's, so a hub out of reach does not change it."""
        return True

    async def async_added_to_hass(self) -> None:
        """Take back the choice made before Home Assistant last stopped."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self.options:
            self._attr_current_option = last.state

    async def async_select_option(self, option: str) -> None:
        """Keep the new choice; the card redraws the window with it."""
        self._attr_current_option = option
        self.async_write_ha_state()
