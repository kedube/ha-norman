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
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
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
    CONF_POLL_INTERVAL,
    CONF_SHOW_SIDEBAR_PANEL,
    CONF_WAKE_INTERVAL,
    DEFAULT_CONTROL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SHOW_SIDEBAR_PANEL,
    DEFAULT_WAKE_INTERVAL,
    DOMAIN,
    MAX_CONTROL_INTERVAL,
    MAX_POLL_INTERVAL,
    MAX_WAKE_INTERVAL,
    MIN_CONTROL_INTERVAL,
    MIN_POLL_INTERVAL,
    MIN_WAKE_INTERVAL,
    POLL_DISABLED,
    WAKE_DISABLED,
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
# that never opens. So the range is expressed by the selector alone, and the one rule it
# cannot express -- "0, or 10 to 300", with a gap -- is enforced in the step handler.
OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): NumberSelector(
            NumberSelectorConfig(
                min=POLL_DISABLED,
                max=MAX_POLL_INTERVAL,
                step=1,
                unit_of_measurement="seconds",
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_WAKE_INTERVAL, default=DEFAULT_WAKE_INTERVAL): NumberSelector(
            NumberSelectorConfig(
                min=WAKE_DISABLED,
                max=MAX_WAKE_INTERVAL,
                step=1,
                unit_of_measurement="seconds",
                mode=NumberSelectorMode.BOX,
            )
        ),
        # Unlike the two above there is no "off" value here: the hub always needs a gap
        # between control sends, so the selector's range is the whole rule and the step
        # handler has nothing extra to check.
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
                self._abort_if_unique_id_mismatch(reason="wrong_hub")
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
    """Let the user tune the two safety nets, the command spacing, and the sidebar entry.

    Updates are pushed, and the listener re-reads every blind each time it cycles the
    stream, so the poll only shortens how long a missed notification goes unnoticed. The
    wake sweep goes further: it asks each blind the hub has not heard from for a day to report
    in, which refreshes the hub's own cache (positions, battery, last seen) for that blind
    rather than re-reading it. The poll costs one request per interval; the sweep one per
    disconnected blind, and none while every blind is connected. The sidebar toggle adds or
    removes the "Norman Shades" panel (frontend.py).
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and store the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # The selector bounds the value to 0-300; the gap between "off" and the floor
            # is checked here because a schema-level validator would not survive being
            # serialized for the frontend (see OPTIONS_SCHEMA).
            seconds = int(user_input[CONF_POLL_INTERVAL])
            wake = int(user_input.get(CONF_WAKE_INTERVAL, DEFAULT_WAKE_INTERVAL))
            if seconds != POLL_DISABLED and not MIN_POLL_INTERVAL <= seconds <= MAX_POLL_INTERVAL:
                errors[CONF_POLL_INTERVAL] = "poll_interval_out_of_range"
            if wake != WAKE_DISABLED and not MIN_WAKE_INTERVAL <= wake <= MAX_WAKE_INTERVAL:
                errors[CONF_WAKE_INTERVAL] = "wake_interval_out_of_range"
            control = float(user_input.get(CONF_CONTROL_INTERVAL, DEFAULT_CONTROL_INTERVAL))
            if not MIN_CONTROL_INTERVAL <= control <= MAX_CONTROL_INTERVAL:
                errors[CONF_CONTROL_INTERVAL] = "control_interval_out_of_range"
            if not errors:
                return self.async_create_entry(
                    data={
                        CONF_POLL_INTERVAL: seconds,
                        CONF_WAKE_INTERVAL: wake,
                        CONF_CONTROL_INTERVAL: control,
                        CONF_SHOW_SIDEBAR_PANEL: bool(
                            user_input.get(CONF_SHOW_SIDEBAR_PANEL, DEFAULT_SHOW_SIDEBAR_PANEL)
                        ),
                    }
                )

        # An entry that has never been configured is offered the defaults, both intervals
        # off. A suggested value is submitted with the form, so suggesting anything else
        # switches it on for whoever saves the form to change something else: suggesting
        # 3600 did that to the wake sweep (issue #5), and 60 to the poll. Options saved
        # before the sidebar toggle existed lack its key, so the form falls back to its
        # default: on.
        suggested = (
            user_input
            or self.config_entry.options
            or {
                CONF_POLL_INTERVAL: POLL_DISABLED,
                CONF_WAKE_INTERVAL: WAKE_DISABLED,
                CONF_CONTROL_INTERVAL: DEFAULT_CONTROL_INTERVAL,
                CONF_SHOW_SIDEBAR_PANEL: DEFAULT_SHOW_SIDEBAR_PANEL,
            }
        )
        # Releases before the ceiling came down to 300 stored up to 3600. The coordinator
        # runs those as off (const.py), so the form shows them as off too, rather than a
        # number its own selector would refuse when the form is saved.
        poll = suggested.get(CONF_POLL_INTERVAL)
        if isinstance(poll, int | float) and poll > MAX_POLL_INTERVAL:
            suggested = {**suggested, CONF_POLL_INTERVAL: POLL_DISABLED}

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, suggested),
            errors=errors,
        )
