from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import OpenEPaperLinkAPEntity
from .util import set_ap_config_item
from .runtime_data import OpenEPaperLinkConfigEntry

import logging

_LOGGER = logging.getLogger(__name__)

# Define switch configurations
SWITCH_ENTITIES = [
    {
        "key": "preview",
        "name": "Preview Images",
        "icon": "mdi:eye",
        "description": "Enable/disable preview images on the AP"
    },
    {
        "key": "ble",
        "name": "Bluetooth",
        "icon": "mdi:bluetooth",
        "description": "Enable/disable Bluetooth"
    },
    {
        "key": "nightlyreboot",
        "name": "Nightly Reboot",
        "icon": "mdi:restart",
        "description": "Enable/disable automatic nightly reboot of the AP"
    },
    {
        "key": "showtimestamp",
        "name": "Show Timestamp",
        "icon": "mdi:clock",
        "description": "Enable/disable showing timestamps on ESLs"
    }
]
"""Configuration for all switch entities to create for the AP.

This list defines all the switch entities that will be created during
integration setup. Each dictionary contains:

- key: Configuration parameter key in the AP's configuration system,
    matching the key used in HTTP API calls.
- name: Human-readable name for display in the UI. This will be combined
    with "AP" to form the full entity name.
- icon: Material Design Icons identifier for the entity.
    Format is "mdi:icon-name" matching the icon library.
- description: Detailed explanation of what the switch controls,
    used for tooltips and documentation.

Common AP features controlled through switches include:

- preview: Whether to show tag images on the AP's display
- ble: Bluetooth Low Energy functionality
- nightlyreboot: Automatic nightly AP reboot for stability
- showtimestamp: Whether to show timestamps on tag displays
"""

class APConfigSwitch(OpenEPaperLinkAPEntity, SwitchEntity):
    """Switch entity for AP configuration."""

    _attr_entity_registry_enabled_default = True

    def __init__(self, hub, key: str, name: str, icon: str, description: str) -> None:
        """Initialize the switch entity."""
        super().__init__(hub)
        self._key = key
        self._attr_unique_id = f"{hub.entry.entry_id}_{key}"
        self._attr_icon = icon
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_translation_key = key
        self._description = description

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._hub.online and self._key in self._hub.ap_config

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on."""
        if not self.available:
            return None
        return bool(int(self._hub.ap_config.get(self._key, 0)))

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the entity on."""
        await set_ap_config_item(self._hub, self._key, 1)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the entity off."""
        await set_ap_config_item(self._hub, self._key, 0)

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

async def async_setup_entry(hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up switch entities for AP configuration.

    Creates switch entities for all defined AP configuration options
    based on the SWITCH_ENTITIES definition list.

    For each defined switch:

    1. Creates an APConfigSwitch instance with appropriate configuration
    2. Ensures the AP configuration is loaded before creating entities
    3. Adds all created entities to Home Assistant

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

    # Create switch entities from configuration
    for config in SWITCH_ENTITIES:
        entities.append(
            APConfigSwitch(
                hub,
                config["key"],
                config["name"],
                config["icon"],
                config["description"]
            )
        )

    async_add_entities(entities)