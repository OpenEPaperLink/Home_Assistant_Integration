"""Config flow for OpenEPaperLink integration."""
from __future__ import annotations

from typing import Any, Final, Mapping
import asyncio

import aiohttp
import voluptuous as vol
from habluetooth.models import BluetoothServiceInfoBleak
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelectorType

from .const import DOMAIN
from .ble import (
    get_protocol_by_manufacturer_id,
    BLEConnection,
    UnsupportedProtocolError,
    ConfigValidationError,
    BLEConnectionError,
    BLEProtocolError,
)
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

    Implements the flow for initial integration setup.
    The flow validates that the provided AP host is reachable and responds
    correctly before creating a configuration entry.

    The class stores connection state throughout the flow steps to maintain
    context between user interactions.
    """

    VERSION = 4

    def __init__(self) -> None:
        """Initialize flow."""
        self._host: str | None = None
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_device: dict[str, Any] | None = {}
        self._dhcp_discovery_info: DhcpServiceInfo | None = None

    async def _validate_input(self, host: str) -> tuple[dict[str, str], str | None]:
        """Validate the user input allows us to connect.

        Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
        """
        errors = {}

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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle reconfiguration of the AP host."""
        entry = self._get_reconfigure_entry()

        # BLE entries do not expose reconfiguration
        if entry.data.get("device_type") == "ble":
            return self.async_abort(reason="no_reconfigure_ble")

        errors: dict[str, str] = {}

        if user_input is not None:
            info, error = await self._validate_input(user_input[CONF_HOST])
            if not error:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=self._host,
                    title=info.get("title"),
                    data_updates={CONF_HOST: self._host},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=entry.data.get(CONF_HOST, ""),
                    ): str
                }
            ),
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

        # Detect protocol from manufacturer data
        manufacturer_id = None
        manufacturer_data = b''

        # Check for known manufacturer IDs (ATC: 4919, OEPL: 9286)
        for mfg_id, mfg_data in discovery_info.manufacturer_data.items():
            if mfg_id in (4919, 9286):
                manufacturer_id = mfg_id
                manufacturer_data = mfg_data
                break

        if manufacturer_id is None:
            _LOGGER.error("No supported manufacturer ID found in advertising data")
            return self.async_abort(reason="unsupported_protocol")

        # Get protocol handler
        try:
            protocol = get_protocol_by_manufacturer_id(manufacturer_id)
            _LOGGER.debug("Detected protocol: %s (manufacturer ID: 0x%04X)",
                         protocol.protocol_name, manufacturer_id)
        except UnsupportedProtocolError:
            _LOGGER.error("Unsupported manufacturer ID: 0x%04X", manufacturer_id)
            return self.async_abort(reason="unsupported_protocol")

        # Parse advertising data using protocol-specific parser
        try:
            advertising_data = protocol.parse_advertising_data(manufacturer_data)
            if not advertising_data:
                raise ValueError("Failed to parse advertising data")
        except Exception as e:
            _LOGGER.error("Failed to parse advertising data: %s", e)
            return self.async_abort(reason="invalid_advertising_data")

        device_name = discovery_info.name or f"OEPL_BLE_{discovery_info.address[-8:].replace(':', '')}"

        self._discovered_device = {
            "address": discovery_info.address,
            "name": device_name,
            "rssi": discovery_info.rssi,
            "hw_type": advertising_data.hw_type,
            "battery_mv": advertising_data.battery_mv,
            "fw_version": advertising_data.fw_version,
            "version": advertising_data.version,
            "protocol_type": protocol.protocol_name,  # Store protocol type
        }
        _LOGGER.debug("Discovered device info: %s", self._discovered_device)

        # Set discovery context for proper display in UI
        self.context["title_placeholders"] = {
            "name": self._discovered_device["name"],
        }

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
            self, user_input: dict[str, Any] | None = None
    ):
        """Confirm discovery of Bluetooth device."""
        if user_input is not None:

            # Perform device interrogation to get real metadata
            _LOGGER.debug("Interrogating device %s for metadata", self._discovered_device["address"])

            try:
                # Get protocol handler for this device
                protocol = get_protocol_by_manufacturer_id(
                    9286 if self._discovered_device["protocol_type"] == "oepl" else 4919
                )

                # Interrogate device using protocol-specific method
                fw_info: dict[str, Any] | None = None

                async with BLEConnection(
                    self.hass,
                    self._discovered_device["address"],
                    protocol.service_uuid,
                    protocol
                ) as conn:
                    capabilities = await protocol.interrogate_device(conn)
                    # OEPL devices expose firmware version via 0x0043
                    if self._discovered_device["protocol_type"] == "oepl":
                        try:
                            fw_info = await protocol.read_firmware_version(conn)
                        except Exception as fw_err:
                            _LOGGER.warning(
                                "Failed to read firmware version for %s: %s",
                                self._discovered_device["address"],
                                fw_err,
                            )

                _LOGGER.debug("Device capabilities: %s", capabilities)

                # Interrogation must succeed - no fallback
                if not capabilities:
                    raise ConfigValidationError(
                        translation_domain=DOMAIN,
                        translation_key="config_flow_invalid_config"
                    )

                # Generate model name based on protocol type
                hw_type = self._discovered_device["hw_type"]

                if self._discovered_device["protocol_type"] == "oepl":
                    # OEPL devices: Store complete config, generate model name from DisplayConfig
                    from .ble.tlv_parser import config_to_dict, generate_model_name

                    if hasattr(protocol, '_last_config') and protocol._last_config:
                        # Store complete OEPL config for future use
                        device_metadata = {
                            "oepl_config": config_to_dict(protocol._last_config),
                        }
                        if fw_info:
                            device_metadata["fw_version"] = fw_info.get("version")
                            device_metadata["fw_version_raw"] = fw_info.get("raw")
                            if fw_info.get("sha"):
                                device_metadata["fw_sha"] = fw_info["sha"]

                        # Generate model name from display config
                        if protocol._last_config.displays:
                            model_name = generate_model_name(protocol._last_config.displays[0])
                            device_metadata["model_name"] = model_name
                            _LOGGER.debug("Generated model name from config: %s", model_name)
                        else:
                            _LOGGER.warning("OEPL config has no display config")
                    else:
                        # Fallback if config unavailable (shouldn't happen for OEPL)
                        model_name = get_hw_string(hw_type) if hw_type else "Unknown"
                        _LOGGER.warning("OEPL config unavailable, using tagtypes fallback: %s", model_name)
                        # Store individual fields as fallback
                        device_metadata = {
                            "hw_type": hw_type,
                            "fw_version": self._discovered_device["fw_version"],
                            "width": capabilities.width,
                            "height": capabilities.height,
                            "rotatebuffer": capabilities.rotatebuffer,
                            "color_scheme": capabilities.color_scheme,
                            "model_name": model_name,
                        }
                else:
                    # ATC devices: Use tagtypes.json lookup and store individual fields
                    tag_types_manager = await get_tag_types_manager(self.hass)
                    model_name = get_hw_string(hw_type) if hw_type else "Unknown"
                    _LOGGER.debug("Resolved hw_type %s to model: %s", hw_type, model_name)

                    # Refine color_scheme using TagTypes db
                    if tag_types_manager.is_in_hw_map(hw_type):
                        tag_type = await tag_types_manager.get_tag_info(hw_type)
                        color_table = tag_type.color_table

                        if 'yellow' in color_table and 'red' in color_table:
                            color_scheme = 3 # BWRY
                        elif 'yellow' in color_table:
                            color_scheme = 2 # BWY
                        elif 'red' in color_table:
                            color_scheme = 1 # BWR
                        else:
                            color_scheme = 0 # BW
                    else:
                        # Fallback to protocol detection
                        color_scheme = capabilities.color_scheme
                        _LOGGER.warning(
                            "hw_type %s not in TagTypes, using protocol color_scheme: %d",
                            hw_type, color_scheme
                        )

                    # Build device metadata from capabilities
                    device_metadata = {
                        "hw_type": hw_type,
                        "fw_version": self._discovered_device["fw_version"],
                        "width": capabilities.width,
                        "height": capabilities.height,
                        "rotatebuffer": capabilities.rotatebuffer,
                        "color_scheme": color_scheme,
                        "model_name": model_name,
                    }

                return self.async_create_entry(
                    title=self._discovered_device['name'],
                    data={
                        "mac_address": self._discovered_device["address"],
                        "name": self._discovered_device["name"],
                        "device_metadata": device_metadata,
                        "device_type": "ble",
                        "protocol_type": self._discovered_device["protocol_type"],  # Store protocol
                        "send_welcome_image": True,
                    }
                )

            except ConfigValidationError as e:
                _LOGGER.error("Invalid device configuration: %s", e)
                return self.async_show_form(
                    step_id="bluetooth_confirm",
                    errors={"base": "invalid_device_config"},
                    description_placeholders={
                        "name": self._discovered_device["name"],
                        "address": self._discovered_device["address"],
                        "rssi": str(self._discovered_device["rssi"]),
                        "battery": f"{self._discovered_device['battery_mv']/1000:.2f}V" if self._discovered_device["battery_mv"] > 0 else "Unknown",
                        "fw_version": str(self._discovered_device["fw_version"]) if self._discovered_device["fw_version"] > 0 else "Unknown",
                        "config_version": str(self._discovered_device["version"]) if self._discovered_device["version"] > 0 else "Unknown",
                    },
                )

            except (BLEConnectionError, BLEProtocolError) as e:
                _LOGGER.error("Error during device interrogation: %s", e)
                return self.async_show_form(
                    step_id="bluetooth_confirm",
                    errors={"base": "interrogation_failed"},
                    description_placeholders={
                        "name": self._discovered_device["name"],
                        "address": self._discovered_device["address"],
                        "rssi": str(self._discovered_device["rssi"]),
                        "battery": f"{self._discovered_device['battery_mv']/1000:.2f}V" if self._discovered_device["battery_mv"] > 0 else "Unknown",
                        "fw_version": str(self._discovered_device["fw_version"]) if self._discovered_device["fw_version"] > 0 else "Unknown",
                        "config_version": str(self._discovered_device["version"]) if self._discovered_device["version"] > 0 else "Unknown",
                        "error": str(e),
                    },
                )

            except Exception as e:
                _LOGGER.error("Unexpected error during device interrogation: %s", e)
                return self.async_show_form(
                    step_id="bluetooth_confirm",
                    errors={"base": "interrogation_failed"},
                    description_placeholders={
                        "name": self._discovered_device["name"],
                        "address": self._discovered_device["address"],
                        "rssi": str(self._discovered_device["rssi"]),
                        "battery": f"{self._discovered_device['battery_mv']/1000:.2f}V" if self._discovered_device["battery_mv"] > 0 else "Unknown",
                        "fw_version": str(self._discovered_device["fw_version"]) if self._discovered_device["fw_version"] > 0 else "Unknown",
                        "config_version": str(self._discovered_device["version"]) if self._discovered_device["version"] > 0 else "Unknown",
                        "error": str(e),
                    },
                )

        # Build description placeholders from advertising data
        description_placeholders = {
            "name": self._discovered_device["name"],
            "address": self._discovered_device["address"],
            "rssi": str(self._discovered_device["rssi"]),
            "battery": f"{self._discovered_device['battery_mv']/1000:.2f}V" if self._discovered_device["battery_mv"] > 0 else "Unknown",
            "fw_version": str(self._discovered_device["fw_version"]) if self._discovered_device["fw_version"] > 0 else "Unknown",
            "config_version": str(self._discovered_device["version"]) if self._discovered_device["version"] > 0 else "Unknown",
        }

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders=description_placeholders,
        )

    async def async_step_dhcp(
            self, discovery_info: DhcpServiceInfo
    ):
        """Handle DHCP discovery of OpenEPaperLink AP."""
        _LOGGER.debug(
            "DHCP Discovery - Hostname: '%s', IP: %s, MAC: %s",
            discovery_info.hostname,
            discovery_info.ip,
            discovery_info.macaddress,
        )

        # Extract host IP from discovery info
        host = discovery_info.ip

        # Check for existing AP entries in config entries
        # AP entries have CONF_HOST in data, BLE entries have device_type
        for entry in self._async_current_entries():
            if CONF_HOST in entry.data:
                return self.async_abort(reason="single_instance_allowed")

        # Set unique_id to IP address (same as manual setup)
        # This ensures DHCP and manual discoveries are treated as the same entry
        await self.async_set_unique_id(host)

        # Check if this IP was already configured
        self._abort_if_unique_id_configured()

        # Store discovery info for confirmation step
        self._dhcp_discovery_info = discovery_info
        self._host = host

        # Validate connectivity before showing confirmation
        info, error = await self._validate_input(host)

        if error:
            _LOGGER.warning(
                "DHCP discovered AP at %s failed validation: %s",
                host,
                error,
            )
            return self.async_abort(reason="cannot_connect")

        # Set discovery context for proper display in UI
        self.context["title_placeholders"] = {
            "name": f"OEPL AP ({host})",
        }

        return await self.async_step_dhcp_confirm()

    async def async_step_dhcp_confirm(
            self, user_input: dict[str, Any] | None = None
    ):
        """Confirm DHCP discovery of OpenEPaperLink AP."""
        if user_input is not None:
            # User confirmed - create the config entry
            return self.async_create_entry(
                title=f"OpenEPaperLink AP ({self._host})",
                data={CONF_HOST: self._host},
            )

        # Build description placeholders for the confirmation form
        description_placeholders = {
            "hostname": self._dhcp_discovery_info.hostname,
            "ip": self._host,
            "mac": self._dhcp_discovery_info.macaddress,
        }

        return self.async_show_form(
            step_id="dhcp_confirm",
            description_placeholders=description_placeholders,
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
        entry_data = self.config_entry.runtime_data
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
