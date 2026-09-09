"""Buttons for the hub verbs that have no cover equivalent."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import NormanApiError, NormanConnectionError
from .const import (
    DOMAIN,
    HUB_CMD_FAVORITE,
    HUB_CMD_JOG_DOWN,
    HUB_CMD_JOG_UP,
    HUB_CMD_TO_BOTTOM_LIMIT,
    HUB_CMD_TO_TOP_LIMIT,
    HUB_COMMAND_SETTING,
    HUB_COMMAND_TRIGGER,
)
from .coordinator import NormanConfigEntry, NormanCoordinator
from .entity import NormanEntity, async_add_entities_for_new_devices

_LOGGER = logging.getLogger(__name__)

# Commands are not throttled; each press is one request.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NormanButtonDescription(ButtonEntityDescription):
    """A button that sends one verb field to the hub's control call."""

    fields: dict[str, Any]


# Every button is EntityCategory.CONFIG. That is not a claim that they are rarely used --
# favorite and jog are everyday controls -- but a layout decision: the device page groups
# uncategorised entities first, then configuration, then diagnostics, and sorts by entity id
# within a group. Leaving the buttons uncategorised put them between the two covers ("Middle
# rail" sorts after "Jog up"), which reads as though the second cover belongs to the buttons.
# With the buttons categorised, a two-rail blind shows its bottom-rail and middle-rail covers
# together at the top, then the divider, then every button.
#
# Best privacy and Best view are the app's room buttons, per blind. The hub's own `Switch`
# verb has only ever been seen room-wide or hub-wide -- the app has no per-blind version and
# `{"Switch": …, "PeripheralUID": …}` has never been captured -- so rather than guess at that
# form these send the rail positions the captured room command produces:
# privacy = bottom 0 / middle 100, view = both 100. Same result, over the position path the
# covers already use. Single-rail blinds ignore the middle value, so both still work there.
BUTTONS: tuple[NormanButtonDescription, ...] = (
    NormanButtonDescription(
        key="best_privacy",
        translation_key="best_privacy",
        entity_category=EntityCategory.CONFIG,
        fields={"BottomRailPosition": 0, "MiddleRailPosition": 100},
    ),
    NormanButtonDescription(
        key="best_view",
        translation_key="best_view",
        entity_category=EntityCategory.CONFIG,
        fields={"BottomRailPosition": 100, "MiddleRailPosition": 100},
    ),
    NormanButtonDescription(
        key="favorite",
        translation_key="favorite",
        entity_category=EntityCategory.CONFIG,
        fields={HUB_CMD_FAVORITE: HUB_COMMAND_SETTING},
    ),
    NormanButtonDescription(
        key="jog_up",
        translation_key="jog_up",
        entity_category=EntityCategory.CONFIG,
        fields={HUB_CMD_JOG_UP: HUB_COMMAND_TRIGGER},
    ),
    NormanButtonDescription(
        key="jog_down",
        translation_key="jog_down",
        entity_category=EntityCategory.CONFIG,
        fields={HUB_CMD_JOG_DOWN: HUB_COMMAND_TRIGGER},
    ),
    # Run-to-limit drives the motor to its stored mechanical limit, which is not the same
    # path as a position move: it can still work on a blind whose position tracking has
    # drifted.
    NormanButtonDescription(
        key="run_to_top_limit",
        translation_key="run_to_top_limit",
        entity_category=EntityCategory.CONFIG,
        fields={HUB_CMD_TO_TOP_LIMIT: HUB_COMMAND_TRIGGER},
    ),
    NormanButtonDescription(
        key="run_to_bottom_limit",
        translation_key="run_to_bottom_limit",
        entity_category=EntityCategory.CONFIG,
        fields={HUB_CMD_TO_BOTTOM_LIMIT: HUB_COMMAND_TRIGGER},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NormanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons for every blind, including ones paired later."""
    coordinator = entry.runtime_data

    def _buttons_for(device_id: int) -> list[NormanButton]:
        return [NormanButton(coordinator, device_id, entry, description) for description in BUTTONS]

    async_add_entities_for_new_devices(entry, async_add_entities, _buttons_for)


class NormanButton(NormanEntity, ButtonEntity):
    """One hub verb for one blind."""

    entity_description: NormanButtonDescription

    def __init__(
        self,
        coordinator: NormanCoordinator,
        device_id: int,
        entry: NormanConfigEntry,
        description: NormanButtonDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, device_id, entry)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    async def async_press(self) -> None:
        """Send the verb, then re-read the hub so the cover follows the motor."""
        try:
            await self.coordinator.api.async_send_control(
                self._device_id, dict(self.entity_description.fields)
            )
        except (NormanApiError, NormanConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="button_failed",
                translation_placeholders={
                    "command": self.entity_description.key,
                    "name": self._device_name,
                    "error": str(err),
                },
            ) from err
        await self.coordinator.async_request_refresh()
