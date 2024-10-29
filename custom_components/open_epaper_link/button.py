from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
import requests
import json
import logging

from .tag_types import get_hw_dimensions, get_tag_types_manager
from .util import send_tag_cmd, reboot_ap
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub = hass.data[DOMAIN][entry.entry_id]

    # Track added tags to prevent duplicates
    added_tags = set()

    async def async_add_tag_buttons(tag_mac: str) -> None:
        """Add buttons for a newly discovered tag."""
        if tag_mac in added_tags:
            return

        added_tags.add(tag_mac)
        new_buttons = [
            ClearPendingTagButton(hass, tag_mac, hub),
            ForceRefreshButton(hass, tag_mac, hub),
            RebootTagButton(hass, tag_mac, hub),
            ScanChannelsButton(hass, tag_mac, hub),
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

class ClearPendingTagButton(ButtonEntity):
    def __init__(self, hass: HomeAssistant, tag_mac: str, hub) -> None:
        """Initialize the button."""
        self.hass = hass
        self._tag_mac = tag_mac
        self._entity_id = f"{DOMAIN}.{tag_mac}"
        self._hub = hub
        self._attr_name = f"{hub._data[tag_mac]['tag_name']} Clear Pending"
        self._attr_unique_id = f"{tag_mac}_clear_pending"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:broom"

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._tag_mac)},
        }

    async def async_press(self) -> None:
        await send_tag_cmd(self.hass, self._entity_id, "clear")

class ForceRefreshButton(ButtonEntity):
    def __init__(self, hass: HomeAssistant, tag_mac: str, hub) -> None:
        """Initialize the button."""
        self.hass = hass
        self._tag_mac = tag_mac
        self._entity_id = f"{DOMAIN}.{tag_mac}"
        self._hub = hub
        self._attr_name = f"{hub._data[tag_mac]['tag_name']} Force Refresh"
        self._attr_unique_id = f"{tag_mac}_force_refresh"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:refresh"

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._tag_mac)},
        }

    async def async_press(self) -> None:
        await send_tag_cmd(self.hass, self._entity_id, "refresh")

class RebootTagButton(ButtonEntity):
    def __init__(self, hass: HomeAssistant, tag_mac: str, hub) -> None:
        """Initialize the button."""
        self.hass = hass
        self._tag_mac = tag_mac
        self._entity_id = f"{DOMAIN}.{tag_mac}"
        self._hub = hub
        self._attr_name = f"{hub._data[tag_mac]['tag_name']} Reboot"
        self._attr_unique_id = f"{tag_mac}_reboot"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:restart"

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._tag_mac)},
        }

    async def async_press(self) -> None:
        await send_tag_cmd(self.hass, self._entity_id, "reboot")

class ScanChannelsButton(ButtonEntity):
    def __init__(self, hass: HomeAssistant, tag_mac: str, hub) -> None:
        """Initialize the button."""
        self.hass = hass
        self._tag_mac = tag_mac
        self._entity_id = f"{DOMAIN}.{tag_mac}"
        self._hub = hub
        self._attr_name = f"{hub._data[tag_mac]['tag_name']} Scan Channels"
        self._attr_unique_id = f"{tag_mac}_scan_channels"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:wifi"

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._tag_mac)},
        }

    async def async_press(self) -> None:
        await send_tag_cmd(self.hass, self._entity_id, "scan")

class RebootAPButton(ButtonEntity):
    def __init__(self, hass: HomeAssistant, hub) -> None:
        """Initialize the button."""
        self.hass = hass
        self._hub = hub
        self._attr_name = "Reboot AP"
        self._attr_unique_id = "reboot_ap"
        self._attr_icon = "mdi:restart"

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, "ap")},
        }

    async def async_press(self) -> None:
        await reboot_ap(self.hass)

class RefreshTagTypesButton(ButtonEntity):
    """Button to manually refresh tag types from GitHub."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._attr_unique_id = "refresh_tag_types"
        self._attr_name = "Refresh Tag Types"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:refresh"

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, "ap")},
            "name": "OpenEPaperLink AP",
            "model": "esp32",
            "manufacturer": "OpenEPaperLink",
        }

    async def async_press(self) -> None:
        """Trigger a manual refresh of tag types."""
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