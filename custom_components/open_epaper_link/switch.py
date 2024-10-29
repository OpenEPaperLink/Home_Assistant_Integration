"""Switch implementation for OpenEPaperLink integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Callable, Any

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hub import Hub, SIGNAL_AP_UPDATE
from .sensor import OpenEPaperLinkSensor

_LOGGER: Final = logging.getLogger(__name__)

@dataclass
class OpenEPaperLinkSwitchEntityDescription(SwitchEntityDescription):
    """Class describing OpenEPaperLink switch entities."""
    key: str
    name: str
    icon: str
    entity_category: EntityCategory
    value_fn: Callable[[dict], bool]
    set_fn: Callable[[Any, bool], None]

AP_SWITCHES: tuple[OpenEPaperLinkSwitchEntityDescription, ...] = (
    OpenEPaperLinkSwitchEntityDescription(
        key="preview",
        name="Preview Images",
        icon="mdi:eye",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda config: bool(config.get("preview", 0)),
        set_fn=lambda hub, value: hub.async_set_ap_config("preview", 1 if value else 0)
    ),
    OpenEPaperLinkSwitchEntityDescription(
        key="bluetooth",
        name="Bluetooth",
        icon="mdi:bluetooth",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda config: bool(config.get("ble", 0)),
        set_fn=lambda hub, value: hub.async_set_ap_config("ble", 1 if value else 0),
    )
)
async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the OpenEPaperLink switches."""
    hub: Hub = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[SwitchEntity] = [
        OpenEPaperLinkAPSwitch(hub, description)
        for description in AP_SWITCHES
    ]

    async_add_entities(entities)


class OpenEPaperLinkAPSwitch(SwitchEntity):
    """Switch for AP configuration options."""

    def __init__(
            self,
            hub: Hub,
            description: OpenEPaperLinkSwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        self.entity_description = description
        self._hub = hub
        self._attr_unique_id = f"ap_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "ap")},
            name="OpenEPaperLink AP",
            manufacturer="OpenEPaperLink",
            model="ESP32",
            configuration_url=f"http://{hub.host}",
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on."""
        if self.entity_description.value_fn is None:
            return None
        return self.entity