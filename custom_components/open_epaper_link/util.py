from __future__ import annotations

from .const import DOMAIN
import requests
import logging
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .runtime_data import OpenEPaperLinkBLERuntimeData

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
    return hass.config.path("www/open_epaper_link/open_epaper_link." + str(entity_id).lower() + ".jpg")


async def send_tag_cmd(hass: HomeAssistant, entity_id: str, cmd: str) -> bool:
    """Send command to tag via AP.

    Raises:
        HomeAssistantError: If command fails to send or AP returns error
    """
    hub = get_hub_from_hass(hass)  # Raises if no hub configured
    # Note: hub.online check removed - caller should use @require_hub_online decorator

    mac = entity_id.split(".")[1].upper()
    url = f"http://{hub.host}/tag_cmd"
    data = {'mac': mac, 'cmd': cmd}

    try:
        result = await hass.async_add_executor_job(
            lambda: requests.post(url, data=data, timeout=10)
        )
        if result.status_code != 200:
            raise HomeAssistantError(
                f"Failed to send {cmd} command to {entity_id}: "
                f"HTTP {result.status_code} - {result.text}"
            )
        _LOGGER.info("Sent %s command to %s", cmd, entity_id)
        return True

    except requests.exceptions.Timeout:
        raise HomeAssistantError(
            f"Timeout sending {cmd} command to {entity_id}"
        ) from None
    except requests.exceptions.RequestException as err:
        raise HomeAssistantError(
            f"Network error sending {cmd} command to {entity_id}: {str(err)}"
        ) from err


async def reboot_ap(hass: HomeAssistant) -> bool:
    """Reboot the OpenEPaperLink Access Point.

    Raises:
        HomeAssistantError: If reboot command fails
    """
    hub = get_hub_from_hass(hass)  # Raises if no hub configured
    # Note: hub.online check removed - caller should use @require_hub_online decorator

    url = f"http://{hub.host}/reboot"

    try:
        result = await hass.async_add_executor_job(
            lambda: requests.post(url, timeout=10)
        )
        if result.status_code != 200:
            raise HomeAssistantError(
                f"Failed to reboot OEPL Access Point: "
                f"HTTP {result.status_code} - {result.text}"
            )
        _LOGGER.info("Rebooted OEPL Access Point")
        return True

    except requests.exceptions.Timeout:
        raise HomeAssistantError(
            "Timeout rebooting OEPL Access Point"
        ) from None
    except requests.exceptions.RequestException as err:
        raise HomeAssistantError(
            f"Network error rebooting OEPL Access Point: {str(err)}"
        ) from err


async def set_ap_config_item(hub, key: str, value: str | int) -> bool:
    """Set AP configuration item.

    Raises:
        HomeAssistantError: If config update fails
    """
    # Note: hub.online check removed - caller should use @require_hub_online decorator

    data = {"key": key, "value": str(value)}

    try:
        response = await hub.hass.async_add_executor_job(
            lambda: requests.post(f"http://{hub.host}/save_apcfg", data=data, timeout=10)
        )
        if response.status_code != 200:
            raise HomeAssistantError(
                f"Failed to set AP config {key}: "
                f"HTTP {response.status_code} - {response.text}"
            )

        # Update cache
        hub.apconfig[key] = value
        _LOGGER.info("Set AP config %s = %s", key, value)
        return True

    except requests.exceptions.Timeout:
        raise HomeAssistantError(
            f"Timeout setting AP config {key}"
        ) from None
    except requests.exceptions.RequestException as err:
        raise HomeAssistantError(
            f"Network error setting AP config {key}: {str(err)}"
        ) from err


def get_hub_from_hass(hass: HomeAssistant):
    """
    Get the AP Hub instance from config entries.

    Iterates through all integration config entries to find the AP Hub object,
    filtering out BLE entries which are OpenEPaperLinkBLEData instances.

    Args:
        hass: Home Assistant instance

    Returns:
        Hub: The OpenEPaperLink AP Hub instance

    Raises:
        HomeAssistantError: If no AP hub is configured
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        if hasattr(entry, 'runtime_data') and entry.runtime_data is not None:
            if not isinstance(entry.runtime_data, OpenEPaperLinkBLERuntimeData):
                return entry.runtime_data

    raise HomeAssistantError("No AP hub configured. Only BLE devices found.")


def is_ble_entry(entry_data) -> bool:
    """
    Check if entry data represents a BLE device.

    Args:
        entry_data: Runtime data from entry.runtime_data

    Returns:
        bool: True if the entry represents a BLE device
    """
    return isinstance(entry_data, OpenEPaperLinkBLERuntimeData)


def rgb_to_rgb332(rgb: tuple[int, int, int]) -> str:
    """Convert RGB values to RGB332 format.

    Converts a standard RGB color tuple (0-255 for each component)
    to the 8-bit RGB332 format used by OpenEPaperLink for LED patterns.

    Args:
        rgb: Tuple of (r, g, b) values, each 0-255

    Returns:
        str: Hexadecimal string representation of the RGB332 value
    """
    r, g, b = [max(0, min(255, x)) for x in rgb]
    r = (r // 32) & 0b111
    g = (g // 32) & 0b111
    b = (b // 64) & 0b11
    rgb332 = (r << 5) | (g << 2) | b
    return str(hex(rgb332)[2:].zfill(2))


def int_to_hex_string(number: int) -> str:
    """Convert integer to two-digit hex string.

    Args:
        number: Integer value to convert

    Returns:
        str: Two-digit hexadecimal string
    """
    hex_string = hex(number)[2:]
    return '0' + hex_string if len(hex_string) == 1 else hex_string


def get_mac_from_entity_id(entity_id: str) -> str:
    """Extract MAC address from entity_id.

    Args:
        entity_id: Entity ID in format 'domain.mac_address'

    Returns:
        str: Uppercase MAC address
    """
    return entity_id.split(".")[1].upper()


def is_ble_device(hass: HomeAssistant, entity_id: str) -> bool:
    """Check if entity represents a BLE device (vs AP/Hub device).

    Looks up device in registry and checks if identifier starts with 'ble_'.

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID in format 'domain.mac_address'

    Returns:
        bool: True if BLE device, False if Hub device or not found
    """
    from homeassistant.helpers import device_registry as dr

    mac = entity_id.split(".")[1].upper()
    device_registry = dr.async_get(hass)

    for device in device_registry.devices.values():
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:
                device_mac = identifier[1]
                if device_mac.startswith("ble_"):
                    device_mac = device_mac[4:]
                if device_mac.upper() == mac:
                    return identifier[1].startswith("ble_")

    return False
