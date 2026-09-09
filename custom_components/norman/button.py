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
    HUB_CMD_SWITCH,
    HUB_COMMAND_SETTING,
    HUB_COMMAND_TRIGGER,
    HUB_SWITCH_CLOSE,
    HUB_SWITCH_OPEN,
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
    # Switch and Favorite are addressed by RoomID + GroupID, not PeripheralUID; the motor
    # verbs (jog, run-to-limit) take PeripheralUID as usual.
    addressed: bool = False


# Every button is EntityCategory.CONFIG. That is not a claim that they are rarely used --
# favorite and jog are everyday controls -- but a layout decision: the device page groups
# uncategorised entities first, then configuration, then diagnostics, and sorts by entity id
# within a group. Leaving the buttons uncategorised put them between the two covers ("Middle
# rail" sorts after "Jog up"), which reads as though the second cover belongs to the buttons.
# With the buttons categorised, a two-rail blind shows its bottom-rail and middle-rail covers
# together at the top, then the divider, then every button.
#
# Best privacy, Best view and Favorite are addressed by RoomID + GroupID rather than by
# PeripheralUID -- that pair is unique per blind and is what the app's own per-blind buttons
# send (captured). `addressed=True` marks the ones that need it.
BUTTONS: tuple[NormanButtonDescription, ...] = (
    NormanButtonDescription(
        key="best_privacy",
        translation_key="best_privacy",
        entity_category=EntityCategory.CONFIG,
        fields={HUB_CMD_SWITCH: HUB_SWITCH_CLOSE},
        addressed=True,
    ),
    NormanButtonDescription(
        key="best_view",
        translation_key="best_view",
        entity_category=EntityCategory.CONFIG,
        fields={HUB_CMD_SWITCH: HUB_SWITCH_OPEN},
        addressed=True,
    ),
    NormanButtonDescription(
        key="favorite",
        translation_key="favorite",
        entity_category=EntityCategory.CONFIG,
        fields={HUB_CMD_FAVORITE: HUB_COMMAND_SETTING},
        addressed=True,
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
)

# There are no "run to top/bottom limit" buttons. `SetMotorToTopLimit` /
# `SetMotorToBottomLimit` are not one-shot moves: the app sends them every ~0.3 s for as long
# as its OPEN/CLOSE control is *held*, and only inside the Shade Limit Setting screen (the one
# behind "contact your dealer if you are unfamiliar with this advanced feature"), interleaved
# with jog, clean-limit and set-limit. A single press is one pulse of a hold-to-run signal, so
# a button is both misleading and redundant: Best view and Best privacy reach the same end
# positions through the hub's own verb. `send_hub_command` can still send them.


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
        fields = dict(self.entity_description.fields)
        data = self._data
        try:
            if self.entity_description.addressed:
                if data is None or data.room_id is None or data.group_id is None:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="button_needs_room",
                        translation_placeholders={
                            "command": self.entity_description.key,
                            "name": self._device_name,
                        },
                    )
                await self.coordinator.api.async_send_blind_control(
                    data.room_id, data.group_id, fields, self._device_id
                )
            else:
                await self.coordinator.api.async_send_control(self._device_id, fields)
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
