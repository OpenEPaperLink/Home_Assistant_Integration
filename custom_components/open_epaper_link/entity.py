"""Entity base classes."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import (
    CONNECTION_BLUETOOTH,
    ChildDeviceInfo,
    DeviceInfo,
    async_get_device_id_by_identifier,
)
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from oepl import Tag, format_hw_type, format_tag_firmware_version
from py_atc_ble_oepl import DEVICE_TYPES, AdvertisingData
from py_atc_ble_oepl import guess_manufacturer as guess_atc_manufacturer

from .atc_coordinator import ATCCoordinator
from .const import DOMAIN
from .coordinator import APCoordinator

# The screen type of a tag configured by hand rather than from the type list.
_ATC_DYNAMIC_TYPE = 65535


class OpenEPaperLinkEntity(CoordinatorEntity[APCoordinator]):
    """Shared behaviour for every entity backed by an Access Point."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: APCoordinator, key: str) -> None:
        """Set up the entity."""
        super().__init__(coordinator)
        self._attr_translation_key = key


class OpenEPaperLinkAPEntity(OpenEPaperLinkEntity):
    """An entity describing the Access Point itself."""

    def __init__(self, coordinator: APCoordinator, key: str) -> None:
        """Set up the entity."""
        super().__init__(coordinator, key)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{key}"
        # Scoped to the entry rather than a shared (DOMAIN, "ap") identifier,
        # which used to make a second Access Point collide with the first.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_ap")},
            name=coordinator.ap_name,
            manufacturer="OpenEPaperLink",
            model=coordinator.ap_info.env if coordinator.ap_info else None,
            sw_version=coordinator.ap_info.build_version
            if coordinator.ap_info
            else None,
            configuration_url=f"http://{coordinator.host}",
            connections={("mac", coordinator.ap_mac)},
        )

    @property
    def available(self) -> bool:
        """Whether the Access Point is currently connected."""
        return self.coordinator.online


class OpenEPaperLinkTagEntity(OpenEPaperLinkEntity):
    """An entity describing a single tag."""

    def __init__(self, coordinator: APCoordinator, mac: str, key: str) -> None:
        """Set up the entity."""
        super().__init__(coordinator, key)
        self._mac = mac
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{mac}_{key}"
        # The coordinator registers the Access Point during setup, so this
        # resolves by the time entities are built.
        ap_device_id = async_get_device_id_by_identifier(
            coordinator.hass,
            (DOMAIN, f"{entry_id}_ap"),
            config_entry_id=entry_id,
        )
        if coordinator.is_ap_display(mac):
            # The display is part of the Access Point, not a tag it reaches,
            # so it is a child device: it goes wherever the Access Point does.
            self._attr_device_info = ChildDeviceInfo(
                identifiers={(DOMAIN, f"{entry_id}_{mac}")},
                parent_device_id=ap_device_id,
                translation_key="ap_display",
            )
            return
        tag = self.tag
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{mac}")},
            name=self._tag_name(),
            manufacturer=coordinator.tag_manufacturer(mac),
            model=coordinator.tag_type_name(mac),
            sw_version=(
                format_tag_firmware_version(tag.firmware_version) if tag else None
            ),
            hw_version=format_hw_type(tag.hw_type) if tag else None,
            via_device_id=ap_device_id,
        )

    def _tag_name(self) -> str:
        """The tag's alias, falling back to its MAC."""
        tag = self.tag
        return tag.alias if tag and tag.alias else self._mac

    @property
    def tag(self) -> Tag | None:
        """The current tag state, or None if it is no longer reported."""
        return self.coordinator.data.get(self._mac)

    @property
    def available(self) -> bool:
        """Whether the Access Point is connected and still knows this tag."""
        return self.coordinator.online and self.tag is not None


@callback
def async_remove_ap_display_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    mac: str,
    platform: Platform,
    keys: Iterable[str],
) -> None:
    """Remove entities registered for the display before it was recognised.

    Earlier versions gave the Access Point's display everything a tag gets,
    and the registry keeps an entity whether or not anything still provides
    it, so they would linger as unavailable.
    """
    registry = er.async_get(hass)
    for key in keys:
        unique_id = f"{entry.entry_id}_{mac}_{key}"
        if entity_id := registry.async_get_entity_id(platform, DOMAIN, unique_id):
            registry.async_remove(entity_id)


class ATCEntity(PassiveBluetoothCoordinatorEntity[ATCCoordinator]):
    """Base class for entities of a tag running ATC firmware.

    Unlike the Access Point entities these are not backed by a polling or
    push coordinator over the network; state arrives in Bluetooth
    advertisements, which is what PassiveBluetoothCoordinatorEntity models.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ATCCoordinator,
        entry_id: str,
        description: EntityDescription,
    ) -> None:
        """Set up the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        # Entry-scoped, matching the Access Point entities and what the
        # registry migration rewrites the old oepl_ble_ ids to.
        self._attr_unique_id = f"{entry_id}_{description.key}"
        config = coordinator.device_config
        screen_type = config.screen_type if config else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{coordinator.address}")},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            # The maker, guessed from the screen type's name where it says.
            manufacturer=(
                guess_atc_manufacturer(screen_type) if screen_type is not None else None
            )
            or "OpenEPaperLink",
            model=(
                DEVICE_TYPES[screen_type]
                if screen_type in DEVICE_TYPES and screen_type != _ATC_DYNAMIC_TYPE
                else None
            ),
            # As tags behind an Access Point show theirs; the firmware version
            # is only known from advertisements and follows them.
            hw_version=format_hw_type(config.hw_type) if config else None,
        )

    @property
    def advertisement(self) -> AdvertisingData | None:
        """The most recent advertisement, if one has been seen."""
        return self.coordinator.data.advertisement if self.coordinator.data else None
