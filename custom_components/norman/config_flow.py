"""Config flow for Norman integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.helpers.typing import UNDEFINED
from homeassistant.util.network import is_host_valid

# Home Assistant 2026.9 replaced voluptuous with probatio, a drop-in for it, and 2026.10 no
# longer installs voluptuous at all; earlier releases have only voluptuous.
try:
    import probatio as vol
except ImportError:  # pragma: no cover - Home Assistant < 2026.9
    import voluptuous as vol  # type: ignore[no-redef]

from .api import NormanApiClient, NormanApiError, NormanConnectionError
from .const import (
    CONF_CONTROL_INTERVAL,
    CONF_SHOW_SIDEBAR_PANEL,
    CONF_SIDEBAR_VIEW,
    CONF_SIDEBAR_VIEW_FORECAST,
    CONF_SIDEBAR_VIEW_MOTION,
    CONF_SIDEBAR_VIEW_WEATHER,
    DEFAULT_CONTROL_INTERVAL,
    DEFAULT_SHOW_SIDEBAR_PANEL,
    DEFAULT_SIDEBAR_VIEW,
    DEFAULT_SIDEBAR_VIEW_FORECAST,
    DEFAULT_SIDEBAR_VIEW_MOTION,
    DOMAIN,
    MAX_CONTROL_INTERVAL,
    MIN_CONTROL_INTERVAL,
    PHOTO_CREDITS_URL,
    SIDEBAR_VIEW_NONE,
    SIDEBAR_VIEWS,
    default_title,
    is_default_title,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
    }
)


# The schema must stay serializable: the frontend fetches it over the websocket API, which
# converts it field by field and understands only selectors and a handful of known
# validators. A plain function anywhere in here (say a vol.All(..., _check) wrapper) fails
# that conversion while the form is being built, which surfaces as a bare 500 and a dialog
# that never opens. So a range is expressed by the selector alone, and checked again in the
# step handler.
OPTIONS_SCHEMA = vol.Schema(
    {
        # The hub always needs a gap between control sends, so there is no "off" here.
        vol.Required(CONF_CONTROL_INTERVAL, default=DEFAULT_CONTROL_INTERVAL): NumberSelector(
            NumberSelectorConfig(
                min=MIN_CONTROL_INTERVAL,
                max=MAX_CONTROL_INTERVAL,
                step=0.1,
                unit_of_measurement="seconds",
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Required(
            CONF_SHOW_SIDEBAR_PANEL, default=DEFAULT_SHOW_SIDEBAR_PANEL
        ): BooleanSelector(),
        # The sidebar page's view: which place, whether it moves, whether the page shows the
        # forecast, and the weather it follows. The weather entity is optional, and so has no
        # default: left empty, the page finds one itself, and a suggested value can be cleared
        # again.
        vol.Required(CONF_SIDEBAR_VIEW, default=DEFAULT_SIDEBAR_VIEW): SelectSelector(
            SelectSelectorConfig(
                options=[*SIDEBAR_VIEWS, SIDEBAR_VIEW_NONE],
                translation_key=CONF_SIDEBAR_VIEW,
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(
            CONF_SIDEBAR_VIEW_MOTION, default=DEFAULT_SIDEBAR_VIEW_MOTION
        ): BooleanSelector(),
        vol.Required(
            CONF_SIDEBAR_VIEW_FORECAST, default=DEFAULT_SIDEBAR_VIEW_FORECAST
        ): BooleanSelector(),
        vol.Optional(CONF_SIDEBAR_VIEW_WEATHER): EntitySelector(
            EntitySelectorConfig(domain="weather")
        ),
    }
)


class NormanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Norman."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NormanOptionsFlow:
        """Return the options flow."""
        return NormanOptionsFlow()

    def __init__(self) -> None:
        """Initialize the flow."""
        self._discovered_host: str | None = None

    async def _async_validate_host(self, host: str, errors: dict[str, str]) -> str | None:
        """Try to register with the hub at ``host``.

        Returns the hub's unique id (its ThingName, falling back to the host) on success;
        on failure, fills ``errors`` and returns None.
        """
        api = NormanApiClient(host, async_get_clientsession(self.hass))
        try:
            thing_name = await api.async_validate_connection()
        except NormanConnectionError:
            errors["base"] = "cannot_connect"
        except NormanApiError:
            errors["base"] = "invalid_response"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected exception validating Norman hub at %s", host)
            errors["base"] = "unknown"
        else:
            return thing_name or host
        return None

    def _abort_if_hub_configured(self, host: str) -> None:
        """Abort for a hub already set up, storing the address it answered at.

        A loaded hub reloads itself when its address changes (its update listener), so it
        is not reloaded here as well; one waiting to retry setup has no listener, and is.
        """
        entry = (
            self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, self.unique_id)
            if self.unique_id is not None
            else None
        )
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: host},
            reload_on_update=entry is None or entry.state is not ConfigEntryState.LOADED,
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            if not is_host_valid(host):
                errors["base"] = "invalid_host"
            elif unique_id := await self._async_validate_host(host, errors):
                # The hub identifies itself by ThingName, so the same hub is recognised
                # even if it is re-added by a different address; the stored host is
                # refreshed in that case instead of creating a duplicate.
                await self.async_set_unique_id(unique_id)
                self._abort_if_hub_configured(host)
                return self.async_create_entry(
                    title=default_title(host),
                    data={CONF_HOST: host},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_DATA_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """Handle a hub found by mDNS.

        The hub announces ``NienMadeLocal._nien_made._tcp.local.`` on port 10123. TXT identity
        fields vary, so registration validates the address and supplies its identity. A hub
        already configured has its stored address refreshed, reloading the entry if changed,
        so a DHCP change heals itself the next time the hub announces.

        Every hub announces itself at each Home Assistant start, so one already loaded at
        this address is left alone without a request. One waiting to retry setup is still
        asked, so that its rediscovery reloads it.
        """
        host = discovery_info.host
        if loaded := next(
            (
                entry
                for entry in self._async_current_entries(include_ignore=False)
                if entry.data.get(CONF_HOST) == host and entry.state is ConfigEntryState.LOADED
            ),
            None,
        ):
            # Claimed for that entry as a full check would, so the discovery is recorded on it.
            await self.async_set_unique_id(loaded.unique_id)
            return self.async_abort(reason="already_configured")
        errors: dict[str, str] = {}
        unique_id = await self._async_validate_host(host, errors)
        if unique_id is None:
            return self.async_abort(reason=errors.get("base", "unknown"))

        await self.async_set_unique_id(unique_id)
        self._abort_if_hub_configured(host)

        self._discovered_host = host
        self.context["title_placeholders"] = {"host": host}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm the discovered hub."""
        host = self._discovered_host
        if host is None:
            # Only reachable if this step is entered without async_step_zeroconf having run
            # (a resumed flow whose context was lost). An assert would be stripped under
            # python -O and leave "Norman Hub (None)" as the entry title instead.
            return self.async_abort(reason="unknown")
        if user_input is not None:
            return self.async_create_entry(
                title=default_title(host),
                data={CONF_HOST: host},
            )
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={"host": host},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user change the hub address (for example after a DHCP change)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            if not is_host_valid(host):
                errors["base"] = "invalid_host"
            elif unique_id := await self._async_validate_host(host, errors):
                await self.async_set_unique_id(unique_id)
                # An entry keyed by its old address (a hub that gave no ThingName, or one
                # added before 0.11) takes the new key; one keyed by a ThingName needs that hub.
                owner = self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, unique_id)
                if owner not in (None, entry) or (
                    entry.unique_id not in (None, entry.data[CONF_HOST])
                    and entry.unique_id != unique_id
                ):
                    return self.async_abort(reason="wrong_hub")
                # A title the integration gave follows the address; one chosen in Home
                # Assistant, or taken from the hub's name, stays. A loaded hub reloads
                # itself when either changes (its update listener); one waiting to retry
                # setup has no listener, so it is reloaded from here.
                update = (
                    self.async_update_and_abort
                    if entry.state is ConfigEntryState.LOADED
                    else self.async_update_reload_and_abort
                )
                return update(
                    entry,
                    unique_id=unique_id,
                    data_updates={CONF_HOST: host},
                    title=default_title(host) if is_default_title(entry.title) else UNDEFINED,
                )

        return self.async_show_form(
            step_id=SOURCE_RECONFIGURE,
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input or entry.data
            ),
            errors=errors,
        )


class NormanOptionsFlow(OptionsFlow):
    """Let the user tune the command spacing and the sidebar page.

    The command spacing is the gap left between commands sent to the hub. The sidebar toggle
    adds or removes the "Norman Shades" panel (frontend.py), and the view options choose the
    photograph behind it, whether it moves, whether the page shows the weather, and the weather
    entity it follows. There is no poll and no timed wake sweep (const.py).
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and store the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # The selector bounds the value; a schema-level validator would not survive being
            # serialized for the frontend (see OPTIONS_SCHEMA), so it is checked again here.
            control = float(user_input.get(CONF_CONTROL_INTERVAL, DEFAULT_CONTROL_INTERVAL))
            if not MIN_CONTROL_INTERVAL <= control <= MAX_CONTROL_INTERVAL:
                errors[CONF_CONTROL_INTERVAL] = "control_interval_out_of_range"
            if not errors:
                data: dict[str, Any] = {
                    CONF_CONTROL_INTERVAL: control,
                    CONF_SHOW_SIDEBAR_PANEL: bool(
                        user_input.get(CONF_SHOW_SIDEBAR_PANEL, DEFAULT_SHOW_SIDEBAR_PANEL)
                    ),
                    CONF_SIDEBAR_VIEW: str(user_input.get(CONF_SIDEBAR_VIEW, DEFAULT_SIDEBAR_VIEW)),
                    CONF_SIDEBAR_VIEW_MOTION: bool(
                        user_input.get(CONF_SIDEBAR_VIEW_MOTION, DEFAULT_SIDEBAR_VIEW_MOTION)
                    ),
                    CONF_SIDEBAR_VIEW_FORECAST: bool(
                        user_input.get(CONF_SIDEBAR_VIEW_FORECAST, DEFAULT_SIDEBAR_VIEW_FORECAST)
                    ),
                }
                # Stored only when one is chosen: a cleared field must not leave the last
                # entity behind, and an absent key is what "find one" means.
                if weather := user_input.get(CONF_SIDEBAR_VIEW_WEATHER):
                    data[CONF_SIDEBAR_VIEW_WEATHER] = str(weather)
                return self.async_create_entry(data=data)

        # An entry that has never been configured is offered the defaults. A suggested value is
        # submitted with the form, so it must be the default: anything else would change the
        # option for whoever saves the form to change something else. Options saved before the
        # sidebar toggle existed lack its key, so the form falls back to its default: on.
        suggested = (
            user_input
            or self.config_entry.options
            or {
                CONF_CONTROL_INTERVAL: DEFAULT_CONTROL_INTERVAL,
                CONF_SHOW_SIDEBAR_PANEL: DEFAULT_SHOW_SIDEBAR_PANEL,
                CONF_SIDEBAR_VIEW: DEFAULT_SIDEBAR_VIEW,
                CONF_SIDEBAR_VIEW_MOTION: DEFAULT_SIDEBAR_VIEW_MOTION,
                CONF_SIDEBAR_VIEW_FORECAST: DEFAULT_SIDEBAR_VIEW_FORECAST,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, suggested),
            errors=errors,
            # The view option's description links to the photographs' credits.
            description_placeholders={"credits": PHOTO_CREDITS_URL},
        )
