"""Buttons for the hub verbs that have no cover equivalent."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import functools
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
    HUB_CMD_REQUEST_STATUS,
    HUB_CMD_SWITCH,
    HUB_COMMAND_SETTING,
    HUB_COMMAND_TRIGGER,
    HUB_SWITCH_CLOSE,
    HUB_SWITCH_OPEN,
)
from .coordinator import NormanConfigEntry, NormanCoordinator
from .entity import NormanEntity, NormanHubEntity, async_add_entities_for_new_devices

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
    # Asks this blind to report in. A battery blind's radio sleeps between commands and the
    # hub stops hearing from it; the app then shows it as "Disconnect" and offers a refresh.
    # This is the per-blind form of that refresh, taken from the app's network library:
    # the blind answered within 5 s each time it was tried (docs/NORMAN_API.md, "Waking a
    # blind"). The follow-up refresh below is usually too early to see the answer; the
    # hub's own notification for the blind brings it a few seconds later.
    NormanButtonDescription(
        key="request_status",
        translation_key="request_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        fields={HUB_CMD_REQUEST_STATUS: HUB_COMMAND_SETTING},
    ),
)


@dataclass(frozen=True, kw_only=True)
class NormanHubButtonDescription(ButtonEntityDescription):
    """A button on the hub device and what pressing it does.

    ``press_fn`` may return the hub's reply; nothing here reads it, so the type is left
    open rather than forcing every action to be wrapped in a discarding lambda.
    """

    press_fn: Callable[[NormanCoordinator], Awaitable[Any]]


# The hub's own buttons. Refresh blinds is the app's refresh on its device & battery status
# screen: the hub polls every battery blind in turn (~30 s for the reference hub's nine),
# and the coordinator follows up with a status request to each wired blind, which the
# hub-wide sweep skips. Room scope is `norman.room_command` with `refresh`. Start pairing
# opens the hub's ten-minute pairing window (the Pairing mode sensor shows it); the rest of
# pairing happens at the blind and in the app.
HUB_BUTTONS: tuple[NormanHubButtonDescription, ...] = (
    # The app's All Rooms header offers the same three buttons for the whole house, and the
    # hub takes them with no scope field at all (docs/NORMAN_API.md, "Room-wide and hub-wide
    # control"). One request moves every blind: the hub fans out over its own radio, so
    # these are not paced from here the way thirteen per-blind commands would be. Verified
    # on the reference hub with every blind staged at 50/50 first -- all thirteen moved,
    # including the four single-rail ones, which the original capture could not settle
    # because they were already at their end position when it fired.
    NormanHubButtonDescription(
        key="all_best_privacy",
        translation_key="all_best_privacy",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda coordinator: coordinator.api.async_send_room_control(
            None, {HUB_CMD_SWITCH: HUB_SWITCH_CLOSE}
        ),
    ),
    NormanHubButtonDescription(
        key="all_best_view",
        translation_key="all_best_view",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda coordinator: coordinator.api.async_send_room_control(
            None, {HUB_CMD_SWITCH: HUB_SWITCH_OPEN}
        ),
    ),
    NormanHubButtonDescription(
        key="all_favorite",
        translation_key="all_favorite",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda coordinator: coordinator.api.async_send_room_control(
            None, {HUB_CMD_FAVORITE: HUB_COMMAND_SETTING}
        ),
    ),
    NormanHubButtonDescription(
        key="refresh_blinds",
        translation_key="refresh_blinds",
        entity_category=EntityCategory.DIAGNOSTIC,
        press_fn=lambda coordinator: coordinator.async_refresh_blinds(),
    ),
    NormanHubButtonDescription(
        key="start_pairing",
        translation_key="start_pairing",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda coordinator: coordinator.api.async_start_pairing(),
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

    async_add_entities(
        NormanHubButton(coordinator, entry, description) for description in HUB_BUTTONS
    )

    def _buttons_for(device_id: int) -> list[NormanButton]:
        return [NormanButton(coordinator, device_id, entry, description) for description in BUTTONS]

    async_add_entities_for_new_devices(entry, async_add_entities, _buttons_for)


class NormanHubButton(NormanHubEntity, ButtonEntity):
    """One hub-wide action."""

    entity_description: NormanHubButtonDescription

    def __init__(
        self,
        coordinator: NormanCoordinator,
        entry: NormanConfigEntry,
        description: NormanHubButtonDescription,
    ) -> None:
        """Attach the button to the hub device."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    async def async_press(self) -> None:
        """Run the hub action.

        A status re-read follows so the Pairing mode sensor flips at once; a refresh's
        answers arrive later, one notification per blind, each with its own refresh.
        """
        try:
            await self.entity_description.press_fn(self.coordinator)
        except (NormanApiError, NormanConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="hub_button_failed",
                translation_placeholders={
                    "command": self.entity_description.key,
                    "error": str(err),
                },
            ) from err
        await self.coordinator.async_request_refresh()


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
                send = functools.partial(
                    self.coordinator.api.async_send_blind_control,
                    data.room_id,
                    data.group_id,
                    fields,
                    self._device_id,
                )
            else:
                send = functools.partial(
                    self.coordinator.api.async_send_control, self._device_id, fields
                )
            await send()
            # The addressed verbs (Best Privacy, Best View, Favorite) send the blind to a
            # stored position, and the hub acks a command it never delivers, so the move is
            # supervised the way a position move is (coordinator.async_watch_preset). The
            # rest -- jog, run-to-limit, status -- either do not move the blind or are held
            # rather than aimed, so there is no target to chase.
            if self.entity_description.addressed:
                self.coordinator.async_watch_preset(self._device_id, send)
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
