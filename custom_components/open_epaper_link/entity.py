"""Entity base classes."""

from __future__ import annotations

from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.helpers.device_registry import (
    CONNECTION_BLUETOOTH,
    ChildDeviceInfo,
    DeviceInfo,
    async_get_device_id_by_identifier,
)
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from oepl import Tag
from py_atc_ble_oepl import AdvertisingData

from .atc_coordinator import ATCCoordinator
from .const import DOMAIN
from .coordinator import APCoordinator


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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{mac}")},
            name=self._tag_name(),
            manufacturer="OpenEPaperLink",
            model=coordinator.tag_type_name(mac),
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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{coordinator.address}")},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            manufacturer="OpenEPaperLink",
        )

    @property
    def advertisement(self) -> AdvertisingData | None:
        """The most recent advertisement, if one has been seen."""
        return self.coordinator.data.advertisement if self.coordinator.data else None
