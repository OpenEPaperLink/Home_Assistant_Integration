from __future__ import annotations

from .const import DOMAIN
import requests
import logging
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
_LOGGER = logging.getLogger(__name__)

def is_bluetooth_available(hass: HomeAssistant) -> bool:
    """Check if Bluetooth integration is available with working scanners.
    
    Args:
        hass: Home Assistant instance
        
    Returns:
        bool: True if Bluetooth integration is loaded with available scanners, False otherwise
    """
    try:
        # First check if bluetooth integration is loaded
        if "bluetooth" not in hass.config.components:
            return False
        
        # Then check if connectable Bluetooth scanners are available
        from homeassistant.components import bluetooth
        scanner_count = bluetooth.async_scanner_count(hass, connectable=True)
        return scanner_count > 0
        
    except (ImportError, AttributeError, Exception) as err:
        _LOGGER.debug("Bluetooth availability check failed: %s", err)
        return False

def get_image_folder(hass: HomeAssistant) -> str:
    """Return the folder where images are stored.

    Provides the path to the www/open_epaper_link directory where
    generated images are stored. This allows image access through
    Home Assistant's web server.

    Args:
        hass: Home Assistant instance for config path access

    Returns:
        str: Absolute path to the image storage directory
    """
    return hass.config.path("www/open_epaper_link")

def get_image_path(hass: HomeAssistant, entity_id: str) -> str:
    """Return the path to the image file for a specific tag.

    Generates the full path to a tag's image file, following the
    naming convention: open_epaper_link.<tag_mac>.jpg

    Args:
        hass: Home Assistant instance for config path access
        entity_id: The entity ID for the tag (domain.tag_mac)

    Returns:
        str: Absolute path to the tag's image file
    """
    return hass.config.path("www/open_epaper_link/open_epaper_link."+ str(entity_id).lower() + ".jpg")

async def send_tag_cmd(hass: HomeAssistant, entity_id: str, cmd: str) -> bool:
    """Send a command to an ESL Tag.

    Sends control commands to a specific tag through the AP's HTTP API.
    Supported commands include:

    - "clear": Clear pending updates
    - "refresh": Force content refresh
    - "reboot": Reboot the tag
    - "scan": Trigger channel scan
    - "deepsleep": Put tag in deep sleep mode

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID of the tag (domain.tag_mac)
        cmd: Command string to send

    Returns:
        bool: True if command was sent successfully, False otherwise

    Raises:
        HomeAssistantError: If the AP is offline or entity_id is invalid
    """
    # Get the hub from the entity_id's domain
    hub = get_hub_from_hass(hass)

    if not hub.online:
        _LOGGER.error("Cannot send command: AP is offline")
        return False

    mac = entity_id.split(".")[1].upper()
    url = f"http://{hub.host}/tag_cmd"

    data = {
        'mac': mac,
        'cmd': cmd
    }

    try:
        result = await hass.async_add_executor_job(lambda: requests.post(url, data=data))
        if result.status_code == 200:
            _LOGGER.info("Sent %s command to %s", cmd, entity_id)
            return True
        else:
            _LOGGER.error("Failed to send %s command to %s: HTTP %s", cmd, entity_id, result.status_code)
            return False
    except Exception as e:
        _LOGGER.error("Failed to send %s command to %s: %s", cmd, entity_id, str(e))
        return False

async def reboot_ap(hass: HomeAssistant) -> bool:
    """Reboot the ESL Access Point.

    Sends a reboot command to the AP via its HTTP API.
    This causes the AP to restart, temporarily disconnecting
    all tags and services until it comes back online.

    Args:
        hass: Home Assistant instance

    Returns:
        bool: True if reboot command was sent successfully, False otherwise

    Raises:
        HomeAssistantError: If the AP is offline or cannot be reached
    """
    # Get the hub instance
    hub = get_hub_from_hass(hass)

    if not hub.online:
        _LOGGER.error("Cannot reboot AP: AP is offline")
        return False

    url = f"http://{hub.host}/reboot"

    try:
        result = await hass.async_add_executor_job(lambda: requests.post(url))
        if result.status_code == 200:
            _LOGGER.info("Rebooted OEPL Access Point")
            return True
        else:
            _LOGGER.error("Failed to reboot OEPL Access Point: HTTP %s", result.status_code)
            return False
    except Exception as e:
        _LOGGER.error("Failed to reboot OEPL Access Point: %s", str(e))
        return False

async def set_ap_config_item(hub, key: str, value: str | int) -> bool:
    """Set a configuration item on the Access Point.

    Updates a specific configuration setting on the AP via HTTP.
    Only sends the update if the value has actually changed to
    reduce unnecessary network requests.

    After updating, it refreshes the local cache and notifies
    entities of the configuration change.

    Args:
        hub: Hub instance with connection details
        key: Configuration key to update
        value: New value to set (string or integer)

    Returns:
        bool: True if update was successful, False otherwise

    Raises:
        HomeAssistantError: If the AP is offline or request fails
    """
    if not hub.online:
        _LOGGER.error("Cannot set config: AP is offline")
        return False

    # Only send update if value actually changed
    current_value = hub.ap_config.get(key)
    if current_value == value:
        _LOGGER.debug("Value unchanged, skipping update for %s = %s", key, value)
        return True

    data = {
        key: value
    }
    _LOGGER.debug("Setting AP config %s = %s", key, value)
    try:
        response = await hub.hass.async_add_executor_job(
            lambda: requests.post(f"http://{hub.host}/save_apcfg", data=data)
        )
        if response.status_code == 200:
            # Update local cache immediately to prevent race conditions
            hub.ap_config[key] = value
            # Only dispatch update for this specific change
            async_dispatcher_send(hub.hass, f"{DOMAIN}_ap_config_update")
            return True
        else:
            _LOGGER.error("Failed to set AP config %s: HTTP %s", key, response.status_code)
            return False
    except Exception as e:
        _LOGGER.error("Failed to set AP config %s: %s", key, str(e))
        return False


def get_hub_from_hass(hass: HomeAssistant):
    """Get the AP Hub instance from Home Assistant data.
    
    Searches through all integration entries to find the AP Hub object,
    filtering out BLE entries which are dictionaries.
    
    Args:
        hass: Home Assistant instance
    
    Returns:
        Hub: The OpenEPaperLink AP Hub instance
        
    Raises:
        HomeAssistantError: If no AP hub is configured
    """
    if DOMAIN not in hass.data or not hass.data[DOMAIN]:
        raise HomeAssistantError("OpenEPaperLink integration not configured")
    
    for entry_data in hass.data[DOMAIN].values():
        if not is_ble_entry(entry_data):
            return entry_data  # This is the Hub object
    
    raise HomeAssistantError("No AP hub configured. Only BLE devices found.")


def is_ble_entry(entry_data) -> bool:
    """Check if entry data represents a BLE device.
    
    Args:
        entry_data: Entry data from hass.data[DOMAIN][entry_id]
        
    Returns:
        bool: True if the entry represents a BLE device
    """
    return isinstance(entry_data, dict) and entry_data.get("type") == "ble"
