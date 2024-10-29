"""Config flow for OpenEPaperLink integration."""
from __future__ import annotations

import asyncio
from typing import Any, Mapping, Final

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN
import logging

_LOGGER: Final = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenEPaperLink."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize flow."""
        self._host: str | None = None

    async def _validate_input(self, host: str) -> tuple[dict[str, str], str | None]:
        """Validate the user input allows us to connect.

        Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
        """
        errors = {}
        info = None

        # Remove any http:// or https:// prefix
        host = host.replace("http://", "").replace("https://", "")
        # Remove any trailing slashes
        host = host.rstrip("/")

        try:
            session = async_get_clientsession(self.hass)
            async with asyncio.timeout(10):
                async with session.get(f"http://{host}") as response:
                    if response.status != 200:
                        errors["base"] = "cannot_connect"
                    else:
                        # Store version info for later display
                        self._host = host
                        return {"title": f"OpenEPaperLink AP ({host})"}, None

        except asyncio.TimeoutError:
            errors["base"] = "timeout"
        except aiohttp.ClientError:
            errors["base"] = "cannot_connect"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"

        return {}, errors.get("base", "unknown")

    async def async_step_user(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            info, error = await self._validate_input(user_input[CONF_HOST])
            if not error:
                await self.async_set_unique_id(self._host)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=info["title"],
                    data={CONF_HOST: self._host}
                )

            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Handle reauthorization."""
        self._host = entry_data[CONF_HOST]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
            self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reauthorization confirmation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            info, error = await self._validate_input(self._host)
            if not error:
                entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
                if entry:
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={**entry.data, CONF_HOST: self._host},
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"host": self._host},
            errors=errors,
        )