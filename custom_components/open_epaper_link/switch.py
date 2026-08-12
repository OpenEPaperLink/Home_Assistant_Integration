"""Switches for boolean Access Point settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import APCoordinator, OpenEPaperLinkConfigEntry
from .entity import OpenEPaperLinkAPEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class APSwitchDescription(SwitchEntityDescription):
    """Describes a boolean Access Point setting.

    ``key`` is both the translation key and the wire key the Access Point
    expects, which is why they are not spelled separately.
    """


AP_SWITCHES: tuple[APSwitchDescription, ...] = (
    APSwitchDescription(key="preview", entity_category=EntityCategory.CONFIG),
    APSwitchDescription(key="nightlyreboot", entity_category=EntityCategory.CONFIG),
    APSwitchDescription(key="showtimestamp", entity_category=EntityCategory.CONFIG),
    APSwitchDescription(key="ble", entity_category=EntityCategory.CONFIG),
)

# The APConfig attribute behind each wire key.
_ATTRIBUTES = {
    "preview": "preview",
    "nightlyreboot": "nightly_reboot",
    "showtimestamp": "show_timestamp",
    "ble": "ble_enabled",
}


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001  (signature fixed by Home Assistant)
    entry: OpenEPaperLinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Access Point switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        APSwitch(coordinator, description)
        for description in AP_SWITCHES
        # Bluetooth cannot be switched on hardware that does not have it.
        if description.key != "ble"
        or (coordinator.ap_config and coordinator.ap_config.has_ble)
    )


class APSwitch(OpenEPaperLinkAPEntity, SwitchEntity):
    """A boolean Access Point setting."""

    entity_description: APSwitchDescription
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self, coordinator: APCoordinator, description: APSwitchDescription
    ) -> None:
        """Set up the switch."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return whether the setting is enabled."""
        config = self.coordinator.ap_config
        if config is None:
            return None
        return bool(getattr(config, _ATTRIBUTES[self.entity_description.key]))

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Enable the setting."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Disable the setting."""
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        """Write the setting to the Access Point."""
        await self.coordinator.async_set_ap_config_item(
            self.entity_description.key, int(value)
        )
