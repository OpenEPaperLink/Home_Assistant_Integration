PARALLEL_UPDATES = 1

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
import logging

from .entity import OpenEPaperLinkTagEntity, OpenEPaperLinkAPEntity, OpenEPaperLinkBLEEntity
from .runtime_data import OpenEPaperLinkConfigEntry
from .tag_types import get_tag_types_manager
from .util import is_ble_entry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
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
    entry_data = entry.runtime_data

    # Check if this is a BLE device
    is_ble_device = is_ble_entry(entry_data)

    if is_ble_device:
        # BLE devices have no button entities
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
            OpenEPaperLinkTagButton(hass, tag_mac, hub, description)
            for description in TAG_BUTTON_TYPES
        ]
        async_add_entities(new_buttons)

    # Add buttons for existing tags
    for tag_mac in hub.tags:
        await async_add_tag_buttons(tag_mac)

    # Add AP-level buttons
    async_add_entities([
        RebootAPButton(hass, hub),
        RefreshTagTypesButton(hass, hub),
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


@dataclass(frozen=True, kw_only=True)
class OpenEPaperLinkTagButtonDescription(ButtonEntityDescription):
    """Describes an OpenEPaperLink tag button."""
    command: str


TAG_BUTTON_TYPES: tuple[OpenEPaperLinkTagButtonDescription, ...] = (
    OpenEPaperLinkTagButtonDescription(
        key="clear_pending",
        translation_key="clear_pending",
        entity_category=EntityCategory.DIAGNOSTIC,
        command="clear",
        entity_registry_enabled_default=True
    ),
    OpenEPaperLinkTagButtonDescription(
        key="force_refresh",
        translation_key="force_refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        command="refresh",
        entity_registry_enabled_default=True
    ),
    OpenEPaperLinkTagButtonDescription(
        key="reboot_tag",
        translation_key="reboot_tag",
        entity_category=EntityCategory.DIAGNOSTIC,
        command="reboot",
    ),
    OpenEPaperLinkTagButtonDescription(
        key="scan_channels",
        translation_key="scan_channels",
        entity_category=EntityCategory.DIAGNOSTIC,
        command="scan",
    ),
    OpenEPaperLinkTagButtonDescription(
        key="deep_sleep",
        translation_key="deep_sleep",
        entity_category=EntityCategory.DIAGNOSTIC,
        command="deepsleep",
    ),
)


class OpenEPaperLinkTagButton(OpenEPaperLinkTagEntity, ButtonEntity):
    """Generic tag button entity."""

    entity_description: OpenEPaperLinkTagButtonDescription

    def __init__(self, hass: HomeAssistant, tag_mac: str, hub, description: OpenEPaperLinkTagButtonDescription) -> None:
        """Initialize the button entity."""
        super().__init__(hub, tag_mac)
        self.hass = hass
        self._entity_id = f"{DOMAIN}.{tag_mac}"
        self.entity_description = description
        self._attr_unique_id = f"{tag_mac}_{description.key}"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._hub.send_tag_cmd(self._entity_id, self.entity_description.command)


class RebootAPButton(OpenEPaperLinkAPEntity, ButtonEntity):
    """Button to reboot the Access Point."""

    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, hub) -> None:
        """Initialize the button entity."""
        super().__init__(hub)
        self.hass = hass
        self._attr_translation_key = "reboot_ap"
        self._attr_unique_id = f"{hub.entry.entry_id}_reboot_ap"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._hub.reboot_ap()


class RefreshTagTypesButton(OpenEPaperLinkAPEntity, ButtonEntity):
    """Button to manually refresh tag types from GitHub."""

    def __init__(self, hass: HomeAssistant, hub) -> None:
        """Initialize the button entity."""
        super().__init__(hub)
        self._hass = hass
        self._attr_translation_key = "refresh_tag_types"
        self._attr_unique_id = f"{hub.entry.entry_id}_refresh_tag_types"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

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


