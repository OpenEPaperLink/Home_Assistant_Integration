"""Config flow for OpenEPaperLink integration."""
from __future__ import annotations

import asyncio
from .ble_device import BLEInstance
from typing import Any, Mapping, Final

import aiohttp
import voluptuous as vol

from bluetooth_data_tools import human_readable_name
from homeassistant.const import CONF_MAC
import voluptuous as vol
from homeassistant.helpers.device_registry import format_mac
from homeassistant.data_entry_flow import FlowResult
from homeassistant.core import callback
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from bluetooth_sensor_state_data import BluetoothData
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import Selector, TextSelectorType

from .const import DOMAIN, CONF_DELAY
import logging

_LOGGER: Final = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
    }
)

class DeviceData(BluetoothData):
    def __init__(self, discovery_info) -> None:
        self._discovery = discovery_info
        manu_data = next(iter(self._discovery.manufacturer_data.values()), None)
        if discovery_info.name.startswith("ATC_"):
            try:
                if manu_data:
                    _LOGGER.debug(f"DeviceData: {discovery_info}")
                    _LOGGER.debug(f"Name: {discovery_info.name}")
                    _LOGGER.debug(f"Manufacturer Data: {manu_data}")
                    _LOGGER.debug(f"Manufacturer Data (hex): {[f'0x{byte:02x}' for byte in manu_data]}")
            except Exception as e:
                _LOGGER.warning(f"Error parsing manufacturer data: {e}")
                # Don't raise the exception, just log it
                pass

    def supported(self):
        return self._discovery.name.startswith("ATC_")

    def address(self):
        return self._discovery.address

    def get_device_name(self):
        return human_readable_name(None, self._discovery.name, self._discovery.address)

    def name(self):
        return human_readable_name(None, self._discovery.name, self._discovery.address)

    def rssi(self):
        return self._discovery.rssi

    def _start_update(self, service_info: BluetoothServiceInfo) -> None:
        """Update from BLE advertisement data."""
        _LOGGER.debug("Parsing BLE advertisement data: %s", service_info)
        
class BLEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        self.mac = None
        self._device = None
        self._instance = None
        self.name = None
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_device: DeviceData | None = None
        self._discovered_devices = []
        self.firmware_version = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        device = DeviceData(discovery_info)
        self.context["title_placeholders"] = {"name": device.name()}
        if device.supported():
            self._discovered_devices.append(device)
            return await self.async_step_bluetooth_confirm()
        return self.async_abort(reason="not_supported")

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        self._set_confirm_only()
        return await self.async_step_user()
    
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the user step to pick discovered device."""
        if user_input is not None:
            self.mac = user_input[CONF_MAC]
            if "title_placeholders" in self.context:
                self.name = self.context["title_placeholders"]["name"]
            if 'source' in self.context.keys() and self.context['source'] == "user":
                for each in self._discovered_devices:
                    if each.address() == self.mac:
                        self.name = each.get_device_name()
            if self.name is None: 
                self.name = self.mac
            await self.async_set_unique_id(self.mac, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_validate()            

        current_addresses = self._async_current_ids()
        for discovery_info in async_discovered_service_info(self.hass):
            self.mac = discovery_info.address
            if self.mac in current_addresses:
                continue
            if (device for device in self._discovered_devices if device.address == self.mac) == ([]):
                continue
            device = DeviceData(discovery_info)
            if device.supported():
                self._discovered_devices.append(device)
        
        if not self._discovered_devices:
            return await self.async_step_manual()

        mac_dict = { dev.address(): dev.name() for dev in self._discovered_devices }
        return self.async_show_form(
            step_id="user", 
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAC): vol.In(mac_dict),
                }
            ),
            description_placeholders={"title": "Select ATC BLE OEPL Device"},
            errors={})

    async def async_step_validate(self, user_input: "dict[str, Any] | None" = None):
        if user_input is not None:
            if "retry" in user_input and not user_input["retry"]:
                return self.async_abort(reason="cannot_connect")

        error = await self.validate_connection()

        if error:
            return self.async_show_form(
                step_id="validate", 
                data_schema=vol.Schema(
                    {
                        vol.Required("retry"): bool
                    }
                ), 
                description_placeholders={"title": "Validate ATC BLE OEPL connection"},
                errors={"base": "connect"})
        
        return self.async_create_entry(title=self.name, data={CONF_MAC: self.mac, "name": self.name})

    async def async_step_manual(self, user_input: "dict[str, Any] | None" = None):
        if user_input is not None:            
            self.mac = user_input[CONF_MAC]
            self.name = user_input["name"]
            await self.async_set_unique_id(format_mac(self.mac))
            return await self.async_step_validate()

        return self.async_show_form(
            step_id="manual", 
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAC): str,
                    vol.Required("name"): str
                }
            ),
            description_placeholders={"title": "Enter bluetooth MAC address"},
            errors={})

    async def validate_connection(self):
        """Validate the connection to the device."""
        if not self._instance:
            self._instance = BLEInstance(self.mac, self.hass)
        try:
            await self._instance.update()
            self.firmware_version = "123"
            self._instance._firmware_version = self.firmware_version
        except Exception as error:
            return error
        finally:
            await self._instance.stop()

    @staticmethod
    @callback
    def async_get_options_flow(entry: config_entries.ConfigEntry):
        return OptionsFlowHandler(entry)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenEPaperLink."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize flow."""
        self._host: str | None = None
        self._setup_type: str | None = None
        # BLE specific attributes
        self.mac = None
        self._device = None
        self._instance = None
        self.name = None
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_device: DeviceData | None = None
        self._discovered_devices = []
        self.firmware_version = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is not None:
            self._setup_type = user_input["setup_type"]
            if self._setup_type == "ap":
                return await self.async_step_ap_setup()
            else:
                return await self.async_step_ble_setup()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("setup_type"): vol.In({
                        "ap": "Access Point Setup",
                        "ble": "Direct BLE Device Setup"
                    })
                }
            ),
            description_placeholders={"title": "Choose Setup Type"},
        )

    async def async_step_ap_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the AP setup step."""
        if user_input is not None:
            self._host = user_input[CONF_HOST]
            info, error = await self._validate_input(self._host)
            if not error:
                await self.async_set_unique_id(self._host)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"OpenEPaperLink AP ({self._host})",
                    data={CONF_HOST: self._host},
                )
            return self.async_show_form(
                step_id="ap_setup",
                data_schema=STEP_USER_DATA_SCHEMA,
                errors={"base": error},
            )

        return self.async_show_form(
            step_id="ap_setup",
            data_schema=STEP_USER_DATA_SCHEMA,
        )

    async def async_step_ble_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the BLE setup step."""
        if user_input is not None:
            self.mac = user_input[CONF_MAC]
            if "title_placeholders" in self.context:
                self.name = self.context["title_placeholders"]["name"]
            if 'source' in self.context.keys() and self.context['source'] == "user":
                for each in self._discovered_devices:
                    if each.address() == self.mac:
                        self.name = each.get_device_name()
            if self.name is None: 
                self.name = self.mac
            await self.async_set_unique_id(self.mac, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_validate()            

        current_addresses = self._async_current_ids()
        for discovery_info in async_discovered_service_info(self.hass):
            self.mac = discovery_info.address
            if self.mac in current_addresses:
                continue
            if any(device.address() == self.mac for device in self._discovered_devices):
                continue
            device = DeviceData(discovery_info)
            if device.supported():
                self._discovered_devices.append(device)
        
        if not self._discovered_devices:
            return await self.async_step_manual()

        mac_dict = { dev.address(): dev.name() for dev in self._discovered_devices }
        return self.async_show_form(
            step_id="ble_setup", 
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAC): vol.In(mac_dict),
                }
            ),
            description_placeholders={"title": "Select ATC BLE OEPL Device"},
            errors={})

    async def async_step_validate(self, user_input: "dict[str, Any] | None" = None):
        """Validate the connection to the device."""
        if user_input is not None:
            if "retry" in user_input and not user_input["retry"]:
                return self.async_abort(reason="cannot_connect")

        error = await self.validate_connection()

        if error:
            return self.async_show_form(
                step_id="validate", 
                data_schema=vol.Schema(
                    {
                        vol.Required("retry"): bool
                    }
                ), 
                description_placeholders={"title": "Validate ATC BLE OEPL connection"},
                errors={"base": "connect"})
        
        return self.async_create_entry(title=self.name, data={CONF_MAC: self.mac, "name": self.name})

    async def async_step_manual(self, user_input: "dict[str, Any] | None" = None):
        """Handle manual entry of BLE device."""
        if user_input is not None:            
            self.mac = user_input[CONF_MAC]
            self.name = user_input["name"]
            await self.async_set_unique_id(format_mac(self.mac))
            return await self.async_step_validate()

        return self.async_show_form(
            step_id="manual", 
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAC): str,
                    vol.Required("name"): str
                }
            ),
            description_placeholders={"title": "Enter bluetooth MAC address"},
            errors={})

    async def validate_connection(self):
        """Validate the connection to the device."""
        if not self._instance:
            self._instance = BLEInstance(self.mac, self.hass)
        try:
            await self._instance.update()
            self.firmware_version = "123"
            self._instance._firmware_version = self.firmware_version
        except Exception as error:
            return error
        finally:
            await self._instance.stop()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        device = DeviceData(discovery_info)
        self.context["title_placeholders"] = {"name": device.name()}
        if device.supported():
            self._discovered_devices.append(device)
            return await self.async_step_bluetooth_confirm()
        return self.async_abort(reason="not_supported")

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        self._set_confirm_only()
        return await self.async_step_ble_setup()

    async def _validate_input(self, host: str) -> tuple[dict[str, str] | None, str | None]:
        """Validate the user input allows us to connect to the OpenEPaperLink AP.

        Tests the connection to the specified host address by:

        1. Sanitizing the input (removing protocol prefixes, trailing slashes)
        2. Attempting an HTTP request to the root endpoint
        3. Verifying the response indicates a valid OpenEPaperLink AP

        Args:
            host: The hostname or IP address of the AP

        Returns:
            tuple: A tuple containing:
                - A dictionary with validated info (empty if validation failed)
                - An error code string if validation failed, None otherwise
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
                        return None, "cannot_connect"
                    else:
                        # Store version info for later display
                        self._host = host
                        return {"title": f"OpenEPaperLink AP ({host})"}, None

        except asyncio.TimeoutError:
            return None, "timeout"
        except aiohttp.ClientError:
            return None, "cannot_connect"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            return None, "unknown"

    async def async_step_reauth(self, entry_data: Mapping[str, Any]):
        """Handle reauthorization flow initiated by connection failure.

        Prepares for reauthorization by extracting the current host from
        the existing config entry data and storing it for validation.

        Args:
            entry_data: Data from the existing config entry

        Returns:
            FlowResult: Flow result directing to the reauth confirmation step
        """
        self._host = entry_data[CONF_HOST]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
            self, user_input: dict[str, Any] | None = None
    ):
        """Handle reauthorization confirmation.

        Validates the connection to the previously configured AP.

        If successful, updates the existing config entry;
        if not, shows an error.

        Args:
            user_input: User input from form, or None on first display

        Returns:
            FlowResult: Flow result object for the next step or completion
        """
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
        return OptionsFlowHandler(config_entry)

class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle OpenEPaperLink integration options.

    Provides a UI for configuring integration options including:

    - Tag blacklisting to hide unwanted devices
    - Button and NFC debounce intervals to prevent duplicate triggers
    - Custom font directories for the image generation system

    The options flow fetches current tag data from the hub to
    populate the selection fields with accurate information.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow with the current configuration.

        Stores references to the current config entry and extracts
        existing option values to use as defaults in the flow.

        Args:
            config_entry: Current configuration entry
        """
        self.config_entry = config_entry
        self._blacklisted_tags = self.config_entry.options.get("blacklisted_tags", [])
        self._button_debounce = self.config_entry.options.get("button_debounce", 0.5)
        self._nfc_debounce = self.config_entry.options.get("nfc_debounce", 1.0)
        self._custom_font_dirs = self.config_entry.options.get("custom_font_dirs", "")

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

        # Get list of all known tags from the hub
        hub = self.hass.data[DOMAIN][self.config_entry.entry_id]
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
