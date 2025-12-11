from __future__ import annotations

import requests

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .entity import OpenEPaperLinkAPEntity, OpenEPaperLinkTagEntity
from .runtime_data import OpenEPaperLinkConfigEntry

from .const import DOMAIN
from .util import set_ap_config_item

import logging

_LOGGER = logging.getLogger(__name__)

# Define text field configurations
AP_TEXT_ENTITIES = [
    {
        "key": "alias",
        "name": "Alias",
        "icon": "mdi:rename-box",
        "description": "AP display name"
    },
    {
        "key": "repo",
        "name": "Repository",
        "icon": "mdi:source-repository",
        "description": "GitHub repository for tag type definitions"
    }
]
"""Configuration for text entities to create for the AP.

This list defines the text input entities created during setup that 
control Access Point text-based settings. Each dictionary contains:

- key: Configuration parameter key in the AP's configuration system
- name: Human-readable name for display in the UI
- icon: Material Design Icons identifier for the entity
- description: Detailed explanation of the setting's purpose
"""
TAG_TEXT_ENTITIES = [
    {
        "key": "alias",
        "name": "Alias",
        "icon": "mdi:rename-box",
        "description": "Tag display name"
    }
]
"""Configuration for text entities to create for each tag.

This list defines the text input entities that will be created for
each discovered tag. Currently, this includes only the tag's alias,
which allows customizing the display name shown in Home Assistant and which also updates the tags alias on the AP.
"""

class APConfigText(OpenEPaperLinkAPEntity, TextEntity):
    """Text entity for AP configuration."""

    _attr_entity_registry_enabled_default = True

    def __init__(self, hub, key: str, name: str, icon: str, description: str) -> None:
        """Initialize the text entity."""
        super().__init__(hub)
        self._key = key
        self._attr_unique_id = f"{hub.entry.entry_id}_{key}"
        self._attr_icon = icon
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_translation_key = key
        self._attr_native_max = 32
        self._attr_native_min = 0
        self._attr_mode = "text"
        self._description = description

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._hub.online and self._key in self._hub.ap_config

    @property
    def native_value(self) -> str | None:
        """Return the current value."""
        if not self.available:
            return None
        return str(self._hub.ap_config.get(self._key, ""))

    async def async_set_value(self, value: str) -> None:
        """Set the text value."""
        if value != self.native_value:
            await set_ap_config_item(self._hub, self._key, value)

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added to Home Assistant."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_ap_config_update",
                self._handle_update,
            )
        )


class TagNameText(OpenEPaperLinkTagEntity, TextEntity):
    """Text entity for tag name/alias."""

    _attr_entity_registry_enabled_default = True

    def __init__(self, hub, tag_mac: str) -> None:
        """Initialize the text entity."""
        super().__init__(hub, tag_mac)
        self._attr_unique_id = f"{tag_mac}_alias"
        self._attr_translation_key = "tag_alias"
        self._attr_native_min = 0
        self._attr_mode = TextMode.TEXT
        self._attr_icon = "mdi:rename"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
                super().available
                and self._tag_mac in self._hub.tags
        )

    @property
    def native_value(self) -> str | None:
        """Return the current value."""
        if not self.available:
            return None
        tag_data = self._hub.get_tag_data(self._tag_mac)
        return tag_data.get("tag_name", "")

    async def async_set_value(self, value: str) -> None:
        """Set the text value."""
        if not value:
            value = self._tag_mac
        if value != self.native_value:
            url = f"http://{self._hub.host}/save_cfg"
            data = {'mac': self._tag_mac, 'alias': value}
            try:
                result = await self.hass.async_add_executor_job(
                    lambda: requests.post(url, data=data)
                )
                if result.status_code != 200:
                    _LOGGER.error("Failed to update tag name %s: HTTP %s", self._tag_mac, result.status_code)
            except Exception as err:
                _LOGGER.error("Error updating tag name for %s: %s", self._tag_mac, str(err))

async def async_setup_entry(hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up text entities for AP configuration and tag names.

    Creates text input entities for:

    1. AP configuration settings defined in AP_TEXT_ENTITIES
    2. Tag name/alias for each discovered tag

    For the AP entities, first ensures the AP configuration is loaded.
    For tags, creates an entity for each existing tag and sets up a
    listener to add entities for newly discovered tags.

    Args:
        hass: Home Assistant instance
        entry: Configuration entry
        async_add_entities: Callback to register new entities
    """
    hub = entry.runtime_data

    # Wait for initial AP config to be loaded
    if not hub.ap_config:
        await hub.async_update_ap_config()

    entities = []

    # Create AP text entities from configuration
    for config in AP_TEXT_ENTITIES:
        entities.append(
            APConfigText(
                hub,
                config["key"],
                config["name"],
                config["icon"],
                config["description"]
            )
        )

    # Add tag name/alias text entities
    for tag_mac in hub.tags:
        if tag_mac not in hub.get_blacklisted_tags():
            entities.append(TagNameText(hub, tag_mac))

    async_add_entities(entities)

    # Set up callback for new tag discovery
    async def async_add_tag_text(tag_mac: str) -> None:
        """Add text entities for a newly discovered tag.

        Creates a TagNameText entity for a newly discovered tag,
        allowing the user to set a custom display name for the tag.

        Only adds the entity if the tag is not blacklisted.

        Args:
            tag_mac: MAC address of the newly discovered tag
        """
        if tag_mac not in hub.get_blacklisted_tags():
            async_add_entities([TagNameText(hub, tag_mac)])

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_tag_discovered",
            async_add_tag_text
        )
    )