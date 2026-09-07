"""Config flow for Norman integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import SOURCE_RECONFIGURE, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util.network import is_host_valid
import voluptuous as vol

from .api import NormanApiClient, NormanApiError, NormanConnectionError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
    }
)


class NormanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Norman."""

    VERSION = 1

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
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=f"Norman Hub ({host})",
                    data={CONF_HOST: host},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_DATA_SCHEMA, user_input),
            errors=errors,
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
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: host}, title=f"Norman Hub ({host})"
                )

        return self.async_show_form(
            step_id=SOURCE_RECONFIGURE,
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input or entry.data
            ),
            errors=errors,
        )
