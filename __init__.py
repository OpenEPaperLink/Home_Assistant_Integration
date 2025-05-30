"""The OpenEPaperLink integration."""
from __future__ import annotations

import logging
import os
from typing import Final, Any
import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from .const import DOMAIN
from .hub import Hub
from .services import async_setup_services, async_unload_services
_LOGGER: Final = logging.getLogger(__name__)

# Base platforms for AP devices
AP_PLATFORMS = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.TEXT,
]

# Additional platforms for BLE devices
BLE_PLATFORMS = [
    Platform.LIGHT,
    Platform.SENSOR,
]

async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update.

    Called when the integration options are updated through the UI.
    Reloads the integration to apply the new settings.

    Args:
        hass: Home Assistant instance
        entry: Updated configuration entry
    """
    await hass.config_entries.async_reload(entry.entry_id)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OpenEPaperLink from a config entry."""
    try:
        # Create hub instance
        hub = Hub(hass, entry)
        
        # Set up the hub
        _LOGGER.debug("Setting up hub initial configuration")
        if not await hub.async_setup_initial():
            _LOGGER.error("Failed to set up hub initial configuration")
            raise ConfigEntryNotReady("Failed to set up hub")
        
        # Store hub in hass.data
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = hub
        
        # Set up services
        await async_setup_services(hass)
        
        # Set up platforms based on device type
        if "mac" in entry.data:
            # BLE device
            _LOGGER.debug("Setting up BLE device with MAC: %s", entry.data["mac"])
            await hass.config_entries.async_forward_entry_setups(entry, BLE_PLATFORMS)
            if not await hub._ble_hub.async_setup():
                _LOGGER.error("Failed to set up BLE hub")
                raise ConfigEntryNotReady("Failed to set up BLE hub")
            # Add the BLE device
            await hub._ble_hub.add_device(entry.data["mac"])
        else:
            # AP device
            _LOGGER.debug("Setting up AP device with host: %s", entry.data["host"])
            await hass.config_entries.async_forward_entry_setups(entry, AP_PLATFORMS)
            # Start WebSocket connection
            if not await hub.async_start_websocket():
                _LOGGER.error("Failed to establish WebSocket connection")
                raise ConfigEntryNotReady("Failed to establish WebSocket connection")
        
        # Set up unload listener
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        
        return True
    except Exception as err:
        _LOGGER.error("Error setting up OpenEPaperLink: %s", err)
        raise ConfigEntryNotReady from err

async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle updates to integration options.

    Called when the user updates integration options through the UI.
    Reloads configuration settings such as:

    - Tag blacklist
    - Button/NFC debounce intervals
    - Font directories

    Args:
        hass: Home Assistant instance
        entry: Updated configuration entry
    """
    hub = hass.data[DOMAIN][entry.entry_id]
    await hub.async_reload_config()

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload services
    await async_unload_services(hass)
    
    # Unload platforms
    if "mac" in entry.data:
        # BLE device
        unload_ok = await hass.config_entries.async_unload_platforms(entry, BLE_PLATFORMS)
    else:
        # AP device
        unload_ok = await hass.config_entries.async_unload_platforms(entry, AP_PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok

async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle complete removal of integration.

    Called when the integration is completely removed from Home Assistant
    (not during restarts). Performs cleanup of persistent storage files.

    Args:
        hass: Home Assistant instance
        entry: Configuration entry being removed
    """
    await async_remove_storage_files(hass)

async def async_remove_storage_files(hass: HomeAssistant) -> None:
    """Remove persistent storage files when removing integration.

    Cleans up files created by the integration:

    1. Tag types file (open_epaper_link_tagtypes.json)
    2. Tag storage file (.storage/open_epaper_link_tags)
    3. Image directory (www/open_epaper_link)

    This prevents orphaned files when the integration is removed
    and ensures a clean reinstallation if needed.

    Args:
        hass: Home Assistant instance
    """

    # Remove tag types file
    tag_types_file = hass.config.path("open_epaper_link_tagtypes.json")
    if await hass.async_add_executor_job(os.path.exists, tag_types_file):
        try:
            await hass.async_add_executor_job(os.remove, tag_types_file)
            _LOGGER.debug("Removed tag types file")
        except OSError as err:
            _LOGGER.error("Error removing tag types file: %s", err)

    # Remove tag storage file
    storage_dir = hass.config.path(".storage")
    tags_file = os.path.join(storage_dir, f"{DOMAIN}_tags")
    if await hass.async_add_executor_job(os.path.exists, tags_file):
        try:
            await hass.async_add_executor_job(os.remove, tags_file)
            _LOGGER.debug("Removed tag storage file")
        except OSError as err:
            _LOGGER.error("Error removing tag storage file: %s", err)

    # Remove image directory
    image_dir = hass.config.path("www/open_epaper_link")
    if await hass.async_add_executor_job(os.path.exists, image_dir):
        try:
            # Get file list in executor
            files = await hass.async_add_executor_job(os.listdir, image_dir)

            # Remove each file in executor
            for file in files:
                file_path = os.path.join(image_dir, file)
                await hass.async_add_executor_job(os.remove, file_path)

            # Remove directory in executor
            await hass.async_add_executor_job(os.rmdir, image_dir)
            _LOGGER.debug("Removed image directory")
        except OSError as err:
            _LOGGER.error("Error removing image directory: %s", err)