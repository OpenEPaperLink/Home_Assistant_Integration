from __future__ import annotations

PARALLEL_UPDATES = 1

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass, SwitchEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import OpenEPaperLinkAPEntity
from .runtime_data import OpenEPaperLinkConfigEntry

import logging

_LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True, kw_only=True)
class OpenEPaperLinkSwitchDescription(SwitchEntityDescription):
    """Switch description with explicit default enable flag."""

    description: str
    entity_registry_enabled_default: bool = False


# Define switch configurations
SWITCH_ENTITIES: tuple[OpenEPaperLinkSwitchDescription, ...] = (
    OpenEPaperLinkSwitchDescription(
        key="preview",
        translation_key="preview",
        name="Preview Images",
        description="Enable/disable preview images on the AP",
        entity_registry_enabled_default=True,
    ),
    OpenEPaperLinkSwitchDescription(
        key="ble",
        translation_key="ble",
        name="Bluetooth",
        description="Enable/disable Bluetooth",
        entity_registry_enabled_default=True,
    ),
    OpenEPaperLinkSwitchDescription(
        key="nightlyreboot",
        translation_key="nightlyreboot",
        name="Nightly Reboot",
        description="Enable/disable automatic nightly reboot of the AP",
        entity_registry_enabled_default=True,
    ),
    OpenEPaperLinkSwitchDescription(
        key="showtimestamp",
        translation_key="showtimestamp",
        name="Show Timestamp",
        description="Enable/disable showing timestamps on ESLs",
        entity_registry_enabled_default=True,
    ),
)
"""Configuration for all switch entities to create for the AP."""


class APConfigSwitch(OpenEPaperLinkAPEntity, SwitchEntity):
    """Switch entity for AP configuration."""

    entity_description: OpenEPaperLinkSwitchDescription

    def __init__(self, hub, description: OpenEPaperLinkSwitchDescription) -> None:
        """Initialize the switch entity."""
        super().__init__(hub)
        self.entity_description = description
        self._key = description.key
        self._attr_unique_id = f"{hub.entry.entry_id}_{description.key}"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_translation_key = description.translation_key or description.key
        self._description = description.description
        self._attr_device_class = SwitchDeviceClass.SWITCH
        self._attr_entity_registry_enabled_default = description.entity_registry_enabled_default

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
        await self._hub.set_ap_config_item(self._key, 1)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the entity off."""
        await self._hub.set_ap_config_item(self._key, 0)

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


async def async_setup_entry(hass: HomeAssistant, entry: OpenEPaperLinkConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
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
    for description in SWITCH_ENTITIES:
        entities.append(APConfigSwitch(hub, description))

    async_add_entities(entities)
