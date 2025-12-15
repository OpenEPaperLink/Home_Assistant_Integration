from __future__ import annotations

PARALLEL_UPDATES = 0

import logging
from datetime import datetime
from typing import Final
import requests

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .util import is_ble_entry
from .entity import OpenEPaperLinkTagEntity, OpenEPaperLinkBLEEntity
from .runtime_data import OpenEPaperLinkConfigEntry
from .const import DOMAIN, SIGNAL_TAG_IMAGE_UPDATE
from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .image_decompressor import to_image
from .tag_types import TagType, get_tag_types_manager

_LOGGER: Final = logging.getLogger(__name__)

async def async_setup_entry(
        hass: HomeAssistant,
        entry: OpenEPaperLinkConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up the OpenEPaperLink image platform."""

    entry_data = entry.runtime_data

    if is_ble_entry(entry_data):
        mac_address = entry_data.mac_address
        name = entry_data.name
        device_metadata = entry_data.device_metadata

        image_entity = OpenEPaperLinkBLEImage(
            hass=hass,
            mac_address=mac_address,
            name=name,
            device_metadata=device_metadata,
            entry=entry,
        )
        async_add_entities([image_entity], True)
        return True

    hub = entry.runtime_data

    # Track added image entities to prevent duplicates
    added_image_entities = set()

    async def async_add_image_entity(tag_mac: str) -> None:

        # Skip if image entity already exists
        if tag_mac in added_image_entities:
            return

        # Skip if tag is blacklisted
        if tag_mac in hub.get_blacklisted_tags():
            _LOGGER.debug("Skipping image entity creation for blacklisted tag: %s", tag_mac)
            return

        # Skip AP (it's not a tag)
        if tag_mac == "ap":
            return

        image_entity = ESLImage(hass, tag_mac, hub)
        added_image_entities.add(tag_mac)
        async_add_entities([image_entity], True)

    # Add image entity for existing tags
    for tag_mac in hub.tags:
        await async_add_image_entity(tag_mac)

    # Register callback for new tag discovery
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_tag_discovered",
            async_add_image_entity
        )
    )

    # Register callback for blacklist updates
    async def handle_blacklist_update() -> None:
        """Handle updates to the tag blacklist.

    Processes changes to the blacklisted tags configuration by
    removing image entities for tags that have been blacklisted.

        When a tag is added to the blacklist:

        1. Its entry is removed from the 'added_image_entities' set
        2. Its corresponding image entity is removed from Home Assistant
        3. The image entity will automatically be excluded from future discoveries

        This ensures blacklisted tags don't appear in the UI and
        don't consume resources with unnecessary image processing.
        """
        for tag_mac in hub.get_blacklisted_tags():
            if tag_mac in added_image_entities:
                added_image_entities.remove(tag_mac)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_blacklist_update",
            handle_blacklist_update
        )
    )

    return True

class ESLImage(OpenEPaperLinkTagEntity, ImageEntity):
    """Image entity class for OpenEPaperLink tags.

    Provides an image entity that shows the current content displayed
    on a tag by fetching its raw image data from the AP and
    converting it to a standard image format.
    """

    _attr_entity_registry_enabled_default = True
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, tag_mac: str, hub) -> None:
        """Initialize the image entity."""
        ImageEntity.__init__(self, hass)
        OpenEPaperLinkTagEntity.__init__(self, hub, tag_mac)
        self._attr_translation_key = "content"
        self._attr_unique_id = f"{tag_mac}_display_content"
        tag_data = hub.get_tag_data(tag_mac)
        self._name = f"{tag_data.get('tag_name', tag_mac)}"
        self._attr_content_type = "image/jpeg"
        self._cached_image: bytes | None = None
        self._last_updated: datetime | None = None
        self._tag_type = None
        self._last_error = None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
                super().available
                and self._tag_mac in self._hub.tags
        )

    @property
    def image_last_updated(self) -> datetime | None:
        """Return the last updated image timestamp."""
        return self._last_updated

    async def _fetch_raw_image(self) -> bytes | None:
        """Fetch raw image data from AP."""
        url = f"http://{self._hub.host}/current/{self._tag_mac}.raw"
        try:
            result = await self.hass.async_add_executor_job(lambda: requests.get(url))
            if result.status_code == 200:
                return result.content
            if result.status_code == 404:
                _LOGGER.debug("No image found for %s", self._tag_mac)
                return None
            _LOGGER.error("Failed to fetch image for %s: HTTP %d", self._tag_mac, result.status_code)
            return None
        except Exception as err:
            _LOGGER.error("Error fetching image for %s: %s", self._tag_mac, str(err))
            return None

    async def _get_tag_def(self) -> TagType | None:
        """Get tag definition for image decoding."""
        if self._tag_type is None:
            try:
                tag_data = self._hub.get_tag_data(self._tag_mac)
                hw_type = tag_data.get("hw_type")
                if hw_type is None:
                    return None
                tag_manager = await get_tag_types_manager(self.hass)
                tag_type = await tag_manager.get_tag_info(hw_type)
                if tag_type is None:
                    return None
                self._tag_type = tag_type
            except Exception as err:
                _LOGGER.error("Error getting tag definition for %s: %s", self._tag_mac, str(err))
                return None
        return self._tag_type

    async def async_image(self) -> bytes | None:
        """Return cached image bytes, fetching if needed."""
        if self._cached_image is None:
            await self._refresh_image()
        return self._cached_image

    async def _refresh_image(self) -> None:
        """Refresh the cached image data."""
        try:
            raw_data = await self._fetch_raw_image()
            if raw_data:
                tag_def = await self._get_tag_def()
                if tag_def:
                    try:
                        jpeg_data = await self.hass.async_add_executor_job(
                            lambda: to_image(raw_data, tag_def)
                        )
                        self._cached_image = jpeg_data
                        self._last_updated = datetime.now()
                        self.async_write_ha_state()
                    except Exception as err:
                        _LOGGER.error("Error decoding image for %s: %s", self._tag_mac, str(err))
                        self._cached_image = None
            else:
                self._cached_image = None
        except Exception as err:
            _LOGGER.error("Error refreshing image for %s: %s", self._tag_mac, str(err))
            self._cached_image = None

    async def async_added_to_hass(self) -> None:
        """Register callback when entity is added."""
        # Don't call super() - different signals are used for image updates
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_TAG_IMAGE_UPDATE}_{self._tag_mac}",
                self._handle_tag_image_update
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_connection_status",
                self._handle_connection_status
            )
        )

    @callback
    def _handle_tag_image_update(self, data) -> None:
        """Handle tag image updates."""
        if isinstance(data, bytes):
            self._cached_image = data
            self._last_updated = datetime.now()
            self.async_write_ha_state()
        elif data:
            self.hass.async_create_task(self._refresh_image())
            self.async_write_ha_state()
        self.async_write_ha_state()


class OpenEPaperLinkBLEImage(OpenEPaperLinkBLEEntity, ImageEntity):
    """Image entity for BLE OpenEPaperLink devices.

    Captures and displays the content generated by drawcustom service calls.
    """

    _attr_entity_registry_enabled_default = True
    _attr_has_entity_name = True

    def __init__(
            self,
            hass: HomeAssistant,
            mac_address: str,
            name: str,
            device_metadata: dict,
            entry: OpenEPaperLinkConfigEntry,
    ):
        """Initialize the BLE image entity."""
        ImageEntity.__init__(self, hass)
        OpenEPaperLinkBLEEntity.__init__(self, mac_address, name, entry)
        self._device_metadata = device_metadata
        self._attr_translation_key = "content"
        self._attr_unique_id = f"oepl_ble_{mac_address}_display_content"
        self._attr_content_type = "image/jpeg"
        self._cached_image: bytes | None = None
        self._last_updated: datetime | None = None

    @property
    def image_last_updated(self) -> datetime | None:
        """Return the last updated image timestamp."""
        return self._last_updated

    async def async_image(self) -> bytes | None:
        """Return cached image bytes."""
        return self._cached_image

    async def async_added_to_hass(self) -> None:
        """Register callback when entity is added."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_TAG_IMAGE_UPDATE}_{self._mac_address}",
                self._handle_image_update
            )
        )

    @callback
    def _handle_image_update(self, data) -> None:
        """Handle image data updates."""
        if isinstance(data, bytes):
            self._cached_image = data
            self._last_updated = datetime.now()
            self.async_write_ha_state()