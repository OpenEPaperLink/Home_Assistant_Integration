"""Config flow for OpenEPaperLink integration."""
from __future__ import annotations

from typing import Any, Final, Mapping
import asyncio

import aiohttp
import voluptuous as vol
from habluetooth.models import BluetoothServiceInfoBleak
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelectorType

from .const import DOMAIN
from .ble_utils import interrogate_ble_device, parse_ble_advertisement
from .tag_types import get_tag_types_manager, get_hw_string
from .util import is_ble_entry
import logging

_LOGGER: Final = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenEPaperLink.

    Implements the flow for initial integration setup and reauthorization.
    The flow validates that the provided AP host is reachable and responds
    correctly before creating a configuration entry.

    The class stores connection state throughout the flow steps to maintain
    context between user interactions.
    """

    VERSION = 2

    def __init__(self) -> None:
        """Initialize flow."""
        self._host: str | None = None
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_device: dict[str, Any] | None = {}

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
    ):
        """Handle the initial step of the config flow.

        Presents a form for the user to enter the AP host address,
        validates the connection, and creates a config entry if successful.

        Args:
            user_input: User-provided configuration data, or None if the
                       form is being shown for the first time

        Returns:
            FlowResult: Result of the flow step, either showing the form
                       again (with errors if applicable) or creating an entry
        """
        # Check for existing AP hub entries immediately (before showing form)
        for entry_id, entry_data in self.hass.data.get(DOMAIN, {}).items():
            if not is_ble_entry(entry_data):  # This is an AP (Hub object)
                return self.async_abort(reason="single_instance_allowed")
        
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

    async def async_step_bluetooth(
            self, discovery_info: BluetoothServiceInfoBleak
    ):
        """Handle bluetooth discovery."""
        _LOGGER.debug("BLE Discovery - Name: '%s', Address: %s", 
                     discovery_info.name, discovery_info.address)


        await self.async_set_unique_id(f"oepl_ble_{discovery_info.address}")
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info

        # Parse advertising data for initial info
        device_info = parse_ble_advertisement(
            discovery_info.manufacturer_data.get(4919, b'')
        )

        device_name = discovery_info.name or f"OEPL_BLE_{discovery_info.address[-8:].replace(':', '')}"

        self._discovered_device = {
            "address": discovery_info.address,
            "name": device_name,
            "rssi": discovery_info.rssi,
            "hw_type": device_info.get("hw_type", 0),
            "battery_mv": device_info.get("battery_mv", 0),
            "fw_version": device_info.get("fw_version", 0),
        }
        _LOGGER.debug("Discovered device info: %s", self._discovered_device)

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
            self, user_input: dict[str, Any] | None = None
    ):
        """Confirm discovery of Bluetooth device."""
        if user_input is not None:

            # Perform device interrogation to get real metadata
            _LOGGER.debug("Interrogating device %s for metadata", self._discovered_device["address"])
            
            try:
                
                # Initialize TagTypesManager to ensure get_hw_string works for BLE devices
                await get_tag_types_manager(self.hass)
                
                # Get display info from device interrogation
                display_info = await interrogate_ble_device(self.hass, self._discovered_device["address"])
                _LOGGER.debug("Display info: %s", display_info)
                
                # Interrogation must succeed - no fallback
                if not display_info:
                    raise RuntimeError("Failed to interrogate device for display specifications")
                
                # Resolve hardware string once using initialized TagTypesManager
                hw_type = self._discovered_device["hw_type"]
                model_name = get_hw_string(hw_type) if hw_type else "Unknown"
                _LOGGER.debug("Resolved hw_type %s to model: %s", hw_type, model_name)
                
                # Width and height are swapped on purpose for parity with AP devices
                device_metadata = {
                    "hw_type": hw_type,
                    "fw_version": self._discovered_device["fw_version"],
                    "width": display_info.width,
                    "height": display_info.height,
                    "rotatebuffer": display_info.rotatebuffer,
                    "color_support": display_info.color_support,
                    "model_name": model_name
                }

                return self.async_create_entry(
                    title=self._discovered_device['name'],
                    data={
                        "mac_address": self._discovered_device["address"],
                        "name": self._discovered_device["name"],
                        "device_metadata": device_metadata,
                        "device_type": "ble"
                    }
                )
                
            except Exception as e:
                _LOGGER.error("Error during device interrogation: %s", e)
                return self.async_show_form(
                    step_id="bluetooth_confirm",
                    errors={"base": "interrogation_failed"},
                    description_placeholders={
                        "name": self._discovered_device["name"],
                        "address": self._discovered_device["address"],
                        "error": str(e),
                    },
                )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._discovered_device["name"],
                "address": self._discovered_device["address"],
                "rssi": str(self._discovered_device["rssi"]),
                "battery": f"{self._discovered_device['battery_mv']/1000:.2f}V" if self._discovered_device["battery_mv"] > 0 else "Unknown",
            },
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Create the options flow handler.

        Returns an instance of the OptionsFlowHandler to manage the
        integration's configuration options.

        Args:
            config_entry: The current configuration entry

        Returns:
            OptionsFlow: The options flow handler
        """
        return OptionsFlowHandler()

class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle OpenEPaperLink integration options.

    Provides a UI for configuring integration options including:

    - Tag blacklisting to hide unwanted devices
    - Button and NFC debounce intervals to prevent duplicate triggers
    - Custom font directories for the image generation system

    The options flow fetches current tag data from the hub to
    populate the selection fields with accurate information.
    """

    def __init__(self) -> None:
        """Initialize options flow.

        The config_entry is now provided automatically by the base OptionsFlow class.
        Option values will be extracted in async_step_init when needed.
        """
        # Option values will be initialized when needed in async_step_init
        self._blacklisted_tags = []
        self._button_debounce = 0.5
        self._nfc_debounce = 1.0
        self._custom_font_dirs = ""

    async def async_step_init(self, user_input=None):
        """Manage OpenEPaperLink options.

        Presents a form with configuration options for the integration.
        When submitted, updates the config entry with the new options.

        This step retrieves a list of available tags from the hub to
        allow selection of tags to blacklist.

        Args:
            user_input: User-provided input data, or None on first display

        Returns:
            FlowResult: Flow result showing the form or saving options
        """
        self._blacklisted_tags = self.config_entry.options.get("blacklisted_tags", [])
        self._button_debounce = self.config_entry.options.get("button_debounce", 0.5)
        self._nfc_debounce = self.config_entry.options.get("nfc_debounce", 1.0)
        self._custom_font_dirs = self.config_entry.options.get("custom_font_dirs", "")

        # Check if this is a BLE device
        entry_data = self.hass.data[DOMAIN][self.config_entry.entry_id]
        is_ble_device = is_ble_entry(entry_data)
        
        if is_ble_device:
            # BLE devices don't have configurable options
            return self.async_abort(reason="no_options_ble")

        if user_input is not None:
            # Update blacklisted tags
            return self.async_create_entry(
                title="",
                data={
                    "blacklisted_tags": user_input.get("blacklisted_tags", []),
                    "button_debounce": user_input.get("button_debounce", 0.5),
                    "nfc_debounce": user_input.get("nfc_debounce", 1.0),
                    "custom_font_dirs": user_input.get("custom_font_dirs", ""),
                }
            )

        # Get list of all known tags from the hub (AP devices only)
        hub = entry_data
        tags = []
        for tag_mac in hub.tags:
            tag_data = hub.get_tag_data(tag_mac)
            tag_name = tag_data.get("tag_name", tag_mac)
            tags.append(
                selector.SelectOptionDict(
                    value=tag_mac,
                    label=f"{tag_name} ({tag_mac})"
                )
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    "blacklisted_tags",
                    default=self._blacklisted_tags,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=tags,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Optional(
                    "button_debounce",
                    default=self._button_debounce,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0,
                        max=5.0,
                        step=0.1,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),
                vol.Optional(
                    "nfc_debounce",
                    default=self._nfc_debounce,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0,
                        max=5.0,
                        step=0.1,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.SLIDER
                    )
                ),
                vol.Optional(
                    "custom_font_dirs",
                    default=self._custom_font_dirs,
                    description={
                        "suggested_value": None
                    }
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=TextSelectorType.TEXT,
                        autocomplete="path"
                    )
                ),
            }),
        )