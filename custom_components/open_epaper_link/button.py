from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
import logging

from .tag_types import get_tag_types_manager
from .util import send_tag_cmd, reboot_ap, is_ble_entry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up button entities from a config entry.

    Creates button entities based on device type:
    
    For BLE devices:
    - Set clock mode button
    - Disable clock mode button

    For AP devices and tags:
    - Clear pending updates button
    - Force refresh button
    - Reboot tag button
    - Scan channels button
    - Deep sleep button
    - Reboot AP button
    - Refresh tag types button

    Also sets up listeners for new tag discovery and blacklist updates
    to dynamically add and remove buttons as needed.

    Args:
        hass: Home Assistant instance
        entry: Configuration entry
        async_add_entities: Callback to register new entities
    """
    entry_data = hass.data[DOMAIN][entry.entry_id]
    
    # Check if this is a BLE device
    is_ble_device = is_ble_entry(entry_data)
    
    if is_ble_device:
        # BLE device setup - create clock mode buttons
        mac_address = entry_data["mac_address"]
        name = entry_data["name"]
        device_metadata = entry_data.get("device_metadata", {})
        
        ble_buttons = [
            SetClockModeButton(mac_address, name, device_metadata, entry.entry_id),
            DisableClockModeButton(mac_address, name, device_metadata, entry.entry_id),
        ]
        async_add_entities(ble_buttons)
        return
    
    # AP device setup (original logic)
    hub = entry_data

    # Track added tags to prevent duplicates
    added_tags = set()

    async def async_add_tag_buttons(tag_mac: str) -> None:
        """Add buttons for a newly discovered tag.

        Creates and registers button entities for a specific tag:

        - Clear pending updates button
        - Force refresh button
        - Reboot tag button
        - Scan channels button
        - Deep sleep button

        This function is called both during initial setup for existing
        tags and dynamically when new tags are discovered.

        The function includes deduplication logic to prevent creating
        multiple button sets for the same tag, and filtering to avoid
        creating buttons for blacklisted tags.

        Args:
            tag_mac: MAC address of the tag to create buttons for
        """

        # Skip if tag is blacklisted
        if tag_mac in hub.get_blacklisted_tags():
            _LOGGER.debug("Skipping button creation for blacklisted tag: %s", tag_mac)
            return

        if tag_mac in added_tags:
            return

        added_tags.add(tag_mac)
        new_buttons = [
            ClearPendingTagButton(hass, tag_mac, hub),
            ForceRefreshButton(hass, tag_mac, hub),
            RebootTagButton(hass, tag_mac, hub),
            ScanChannelsButton(hass, tag_mac, hub),
            DeepSleepButton(hass, tag_mac, hub),
        ]
        async_add_entities(new_buttons)

    # Add buttons for existing tags
    for tag_mac in hub.tags:
        await async_add_tag_buttons(tag_mac)

    # Add AP-level buttons
    async_add_entities([
        RebootAPButton(hass, hub),
        RefreshTagTypesButton(hass),
    ])

    # Listen for new tag discoveries
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_tag_discovered",
            async_add_tag_buttons
        )
    )

    # Listen for blacklist updates
    async def handle_blacklist_update() -> None:
        """Handle blacklist updates by removing buttons for blacklisted tags.

        When tags are added to the blacklist, this removes their
        associated button entities and devices from Home Assistant.

        This ensures that blacklisted tags don't appear in the UI
        and don't consume resources in Home Assistant.
        """
        # Get all buttons registered for this entry
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)

        # Track which devices need to be removed
        devices_to_remove = set()

        # Find and remove entities for blacklisted tags
        entities_to_remove = []
        for entity in entity_registry.entities.values():
            if entity.config_entry_id == entry.entry_id:
                # Check if this entity belongs to a blacklisted tag
                device = device_registry.async_get(entity.device_id) if entity.device_id else None
                if device:
                    for identifier in device.identifiers:
                        if identifier[0] == DOMAIN and identifier[1] in hub.get_blacklisted_tags():
                            entities_to_remove.append(entity.entity_id)
                            # Add device to removal list
                            devices_to_remove.add(device.id)
                            break

        # Remove the entities
        for entity_id in entities_to_remove:
            entity_registry.async_remove(entity_id)
            _LOGGER.debug("Removed entity %s for blacklisted tag", entity_id)

        # Remove the devices
        for device_id in devices_to_remove:
            device_registry.async_remove_device(device_id)
            _LOGGER.debug("Removed device %s for blacklisted tag", device_id)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_blacklist_update",
            handle_blacklist_update
        )
    )

class ClearPendingTagButton(ButtonEntity):
    """Button to clear pending updates for a tag.

    Creates a button entity that clears any pending content updates
    for a specific tag. This is useful when a tag has queued updates
    that are not being applied or need to be canceled.
    """
    def __init__(self, hass: HomeAssistant, tag_mac: str, hub) -> None:
        """Initialize the button entity.

        Sets up the button entity with appropriate name, icon, and identifiers.

        Args:
            hass: Home Assistant instance
            tag_mac: MAC address of the tag
            hub: Hub instance for AP communication
        """
        self.hass = hass
        self._tag_mac = tag_mac
        self._entity_id = f"{DOMAIN}.{tag_mac}"
        self._hub = hub
        self._attr_has_entity_name = True
        self._attr_translation_key = "clear_pending"
        # self._attr_name = f"{hub._data[tag_mac]['tag_name']} Clear Pending"
        self._attr_unique_id = f"{tag_mac}_clear_pending"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:broom"

    @property
    def device_info(self):
        """Return device info for the tag.

        Associates this button with the tag device in Home Assistant
        using the tag MAC address as the identifier.

        Returns:
            dict: Device information dictionary
        """
        tag_name = self._hub._data[self._tag_mac]['tag_name']
        return {
            "identifiers": {(DOMAIN, self._tag_mac)},
            "name": tag_name,
        }

    @property
    def available(self) -> bool:
        """Return if entity is available.

        A button is available if its associated tag is known to the AP
        and not blacklisted in the integration options.

        Returns:
            bool: True if the tag is available, False otherwise
        """
        return self._tag_mac not in self._hub.get_blacklisted_tags()

    async def async_press(self) -> None:
        """Handle the button press.

        Sends the "clear" command to the tag via the AP when the
        button is pressed in the UI.
        """
        await send_tag_cmd(self.hass, self._entity_id, "clear")

class ForceRefreshButton(ButtonEntity):
    """Button to force refresh a tag's display.

    Creates a button entity that triggers an immediate display update
    on the tag, forcing it to refresh with the current content.
    This is useful when a tag's display hasn't updated as expected.
    """
    def __init__(self, hass: HomeAssistant, tag_mac: str, hub) -> None:
        """Initialize the button entity.

        Sets up the button entity with appropriate name, icon, and identifiers.

        Args:
            hass: Home Assistant instance
            tag_mac: MAC address of the tag
            hub: Hub instance for AP communication
        """
        self.hass = hass
        self._tag_mac = tag_mac
        self._entity_id = f"{DOMAIN}.{tag_mac}"
        self._hub = hub
        self._attr_has_entity_name = True
        self._attr_translation_key = "force_refresh"
        # self._attr_name = f"{hub._data[tag_mac]['tag_name']} Force Refresh"
        self._attr_unique_id = f"{tag_mac}_force_refresh"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:refresh"

    @property
    def device_info(self):
        """Return device info for the tag.

        Associates this button with the tag device in Home Assistant
        using the tag MAC address as the identifier.

        Returns:
            dict: Device information dictionary
        """
        tag_name = self._hub._data[self._tag_mac]['tag_name']
        return {
            "identifiers": {(DOMAIN, self._tag_mac)},
            "name": tag_name,
        }

    @property
    def available(self) -> bool:
        """Return if entity is available.

        A button is available if its associated tag is known to the AP
        and not blacklisted in the integration options.

        Returns:
            bool: True if the tag is available, False otherwise
        """
        return self._tag_mac not in self._hub.get_blacklisted_tags()

    async def async_press(self) -> None:
        """Handle the button press.

        Sends the "refresh" command to the tag via the AP when the
        button is pressed in the UI.
        """
        await send_tag_cmd(self.hass, self._entity_id, "refresh")

class RebootTagButton(ButtonEntity):
    """Button to reboot a tag.

    Creates a button entity that sends a reboot command to the tag,
    forcing a complete restart of the tag's firmware.
    """
    def __init__(self, hass: HomeAssistant, tag_mac: str, hub) -> None:
        """Initialize the button entity.

        Sets up the button entity with appropriate name, icon, and identifiers.

        Args:
            hass: Home Assistant instance
            tag_mac: MAC address of the tag
            hub: Hub instance for AP communication
        """
        self.hass = hass
        self._tag_mac = tag_mac
        self._entity_id = f"{DOMAIN}.{tag_mac}"
        self._hub = hub
        self._attr_has_entity_name = True
        self._attr_translation_key = "reboot_tag"
        # self._attr_name = f"{hub._data[tag_mac]['tag_name']} Reboot"
        self._attr_unique_id = f"{tag_mac}_reboot"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:restart"

    @property
    def device_info(self):
        """Return device info for the tag.

        Associates this button with the tag device in Home Assistant
        using the tag MAC address as the identifier.

        Returns:
            dict: Device information dictionary
        """
        tag_name = self._hub._data[self._tag_mac]['tag_name']
        return {
            "identifiers": {(DOMAIN, self._tag_mac)},
            "name": tag_name,
        }

    @property
    def available(self) -> bool:
        """Return if entity is available.

        A button is available if its associated tag is known to the AP
        and not blacklisted in the integration options.

        Returns:
            bool: True if the tag is available, False otherwise
        """
        return self._tag_mac not in self._hub.get_blacklisted_tags()

    async def async_press(self) -> None:
        """Handle the button press.

        Sends the "reboot" command to the tag via the AP when the
        button is pressed in the UI.
        """
        await send_tag_cmd(self.hass, self._entity_id, "reboot")

class ScanChannelsButton(ButtonEntity):
    """Button to initiate channel scanning on a tag.

    Creates a button entity that triggers an IEEE 802.15.4 channel scan
    on the tag.
    """
    def __init__(self, hass: HomeAssistant, tag_mac: str, hub) -> None:
        """Initialize the button entity.

        Sets up the button entity with appropriate name, icon, and identifiers.

        Args:
            hass: Home Assistant instance
            tag_mac: MAC address of the tag
            hub: Hub instance for AP communication
        """
        self.hass = hass
        self._tag_mac = tag_mac
        self._entity_id = f"{DOMAIN}.{tag_mac}"
        self._hub = hub
        self._attr_has_entity_name = True
        self._attr_translation_key = "scan_channels"
        # self._attr_name = f"{hub._data[tag_mac]['tag_name']} Scan Channels"
        self._attr_unique_id = f"{tag_mac}_scan_channels"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:wifi"

    @property
    def device_info(self):
        """Return device info for the tag.

        Associates this button with the tag device in Home Assistant
        using the tag MAC address as the identifier.

        Returns:
            dict: Device information dictionary
        """
        tag_name = self._hub._data[self._tag_mac]['tag_name']
        return {
            "identifiers": {(DOMAIN, self._tag_mac)},
            "name": tag_name,
        }

    @property
    def available(self) -> bool:
        """Return if entity is available.

        A button is available if its associated tag is known to the AP
        and not blacklisted in the integration options.

        Returns:
            bool: True if the tag is available, False otherwise
        """
        return self._tag_mac not in self._hub.get_blacklisted_tags()

    async def async_press(self) -> None:
        """Handle the button press.

        Sends the "scan" command to the tag via the AP when the
        button is pressed in the UI.
        """
        await send_tag_cmd(self.hass, self._entity_id, "scan")

class DeepSleepButton(ButtonEntity):
    """Button to put a tag into deep sleep mode.

    Creates a button entity that sends a deep sleep command to the tag,
    putting it into a low-power state to conserve battery.
    """
    def __init__(self, hass: HomeAssistant, tag_mac: str, hub) -> None:
        """Initialize the button entity.

        Sets up the button entity with appropriate name, icon, and identifiers.

        Args:
            hass: Home Assistant instance
            tag_mac: MAC address of the tag
            hub: Hub instance for AP communication
        """
        self.hass = hass
        self._tag_mac = tag_mac
        self._entity_id = f"{DOMAIN}.{tag_mac}"
        self._hub = hub
        self._attr_has_entity_name = True
        self._attr_translation_key = "deep_sleep"
        # self._attr_name = f"{hub._data[tag_mac]['tag_name']} Scan Channels"
        self._attr_unique_id = f"{tag_mac}_deep_sleep"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:sleep"

    @property
    def device_info(self):
        """Return device info for the tag.

        Associates this button with the tag device in Home Assistant
        using the tag MAC address as the identifier.

        Returns:
            dict: Device information dictionary
        """
        tag_name = self._hub._data[self._tag_mac]['tag_name']
        return {
            "identifiers": {(DOMAIN, self._tag_mac)},
            "name": tag_name,
        }

    @property
    def available(self) -> bool:
        """Return if entity is available.

        A button is available if its associated tag is known to the AP
        and not blacklisted in the integration options.

        Returns:
            bool: True if the tag is available, False otherwise
        """
        return self._tag_mac not in self._hub.get_blacklisted_tags()

    async def async_press(self) -> None:
        """Handle the button press.

        Sends the "deepsleep" command to the tag via the AP when the
        button is pressed in the UI.
        """
        await send_tag_cmd(self.hass, self._entity_id, "deepsleep")

class RebootAPButton(ButtonEntity):
    """Button to reboot the Access Point.

    Creates a button entity that triggers a reboot of the OpenEPaperLink
    Access Point, restarting all AP services and connections.

    Note: Rebooting the AP will temporarily disconnect all tags
    until they reconnect after the AP comes back online.
    """
    def __init__(self, hass: HomeAssistant, hub) -> None:
        """Initialize the button entity.

        Sets up the button with appropriate name, icon, and device association.

        Args:
            hass: Home Assistant instance
            hub: Hub instance for AP communication
        """
        self.hass = hass
        self._hub = hub
        # self._attr_name = "Reboot AP"
        self._attr_has_entity_name = True
        self._attr_translation_key = "reboot_ap"
        self._attr_unique_id = "reboot_ap"
        self._attr_icon = "mdi:restart"

    @property
    def device_info(self):
        """Return device info for the AP.

        Associates this button with the AP device in Home Assistant.

        Returns:
            dict: Device information dictionary
        """
        return {
            "identifiers": {(DOMAIN, "ap")},
        }

    async def async_press(self) -> None:
        """Handle the button press.

        Sends a reboot command to the AP when the button is pressed
        in the UI. The AP will disconnect and restart all services.
        """
        await reboot_ap(self.hass)

class RefreshTagTypesButton(ButtonEntity):
    """Button to manually refresh tag types from GitHub.

    Creates a button entity that triggers a refresh of the tag type
    definitions from the OpenEPaperLink GitHub repository.

    This is useful when new tag models are added to the repository
    or when the local cache needs to be updated for any reason.

    A persistent notification is shown when the refresh completes
    to inform the user of the result.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the button entity.

        Sets up the button with appropriate name, icon, and device association.

        Args:
            hass: Home Assistant instance
        """
        self._hass = hass
        self._attr_unique_id = "refresh_tag_types"
        # self._attr_name = "Refresh Tag Types"
        self._attr_has_entity_name = True
        self._attr_translation_key = "refresh_tag_types"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:refresh"

    @property
    def device_info(self):
        """Return device info for the AP.

        Associates this button with the AP device in Home Assistant,
        adding manufacturer and model information.

        Returns:
            dict: Device information dictionary
        """
        return {
            "identifiers": {(DOMAIN, "ap")},
            "name": "OpenEPaperLink AP",
            # "model": self._hub.ap_model,
            "manufacturer": "OpenEPaperLink",
        }

    async def async_press(self) -> None:
        """Handle the button press.

        Triggers a refresh of tag type definitions from GitHub
        and displays a notification with the result.

        The refresh process:

        1. Clears the cache timestamp to force a new GitHub fetch
        2. Calls the tag types manager to load the latest definitions
        3. Shows a notification with the number of tag types loaded
        """
        manager = await get_tag_types_manager(self._hass)
        # Force a refresh by clearing the last update timestamp
        manager._last_update = None
        await manager.ensure_types_loaded()
        tag_types_len = len(manager.get_all_types())
        message = f"Successfully refreshed {tag_types_len} tag types from GitHub"
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Tag Types Refreshed",
                "message": message,
                "notification_id": "tag_types_refresh_notification",
            },
        )


class SetClockModeButton(ButtonEntity):
    """Button to set clock mode on BLE device.

    Creates a button entity that sends the clock mode command to a BLE device,
    setting it to display the current time.
    """
    def __init__(self, mac_address: str, name: str, device_metadata: dict, entry_id: str) -> None:
        """Initialize the button entity.

        Args:
            mac_address: MAC address of the BLE device
            name: Human-readable name for the device
            device_metadata: Device metadata dictionary
            entry_id: Configuration entry ID
        """
        self._mac_address = mac_address
        self._name = name
        self._device_metadata = device_metadata
        self._entry_id = entry_id
        self._attr_has_entity_name = True
        self._attr_translation_key = "set_clock_mode"
        self._attr_unique_id = f"ble_{mac_address}_set_clock_mode"
        self._attr_icon = "mdi:clock"

    @property
    def device_info(self):
        """Return device info for the BLE device."""
        model_string = self._device_metadata.get('model_name', 'Unknown')
        height = self._device_metadata.get('height', 0)
        width = self._device_metadata.get('width', 0)
        
        return {
            "identifiers": {(DOMAIN, f"ble_{self._mac_address}")},
            "name": self._name,
            "manufacturer": "OpenEPaperLink",
            "model": model_string,
            "sw_version": f"0x{self._device_metadata.get('fw_version', 0):04x}",
            "hw_version": f"{width}x{height}" if width and height else None,
        }

    async def async_press(self) -> None:
        """Handle the button press."""
        from .ble_utils import set_clock_mode
        success = await set_clock_mode(self.hass, self._mac_address)
        if not success:
            raise HomeAssistantError(f"Failed to set clock mode on {self._mac_address}")


class DisableClockModeButton(ButtonEntity):
    """Button to disable clock mode on BLE device.

    Creates a button entity that sends the disable clock mode command to a BLE device,
    returning it to normal operation.
    """
    def __init__(self, mac_address: str, name: str, device_metadata: dict, entry_id: str) -> None:
        """Initialize the button entity.

        Args:
            mac_address: MAC address of the BLE device
            name: Human-readable name for the device
            device_metadata: Device metadata dictionary
            entry_id: Configuration entry ID
        """
        self._mac_address = mac_address
        self._name = name
        self._device_metadata = device_metadata
        self._entry_id = entry_id
        self._attr_has_entity_name = True
        self._attr_translation_key = "disable_clock_mode"
        self._attr_unique_id = f"ble_{mac_address}_disable_clock_mode"
        self._attr_icon = "mdi:clock-remove"

    @property
    def device_info(self):
        """Return device info for the BLE device."""
        model_string = self._device_metadata.get('model_name', 'Unknown')
        height = self._device_metadata.get('height', 0)
        width = self._device_metadata.get('width', 0)
        
        return {
            "identifiers": {(DOMAIN, f"ble_{self._mac_address}")},
            "name": self._name,
            "manufacturer": "OpenEPaperLink",
            "model": model_string,
            "sw_version": f"0x{self._device_metadata.get('fw_version', 0):04x}",
            "hw_version": f"{width}x{height}" if width and height else None,
        }

    async def async_press(self) -> None:
        """Handle the button press."""
        from .ble_utils import disable_clock_mode
        success = await disable_clock_mode(self.hass, self._mac_address)
        if not success:
            raise HomeAssistantError(f"Failed to disable clock mode on {self._mac_address}")