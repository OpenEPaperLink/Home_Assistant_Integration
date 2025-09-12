from __future__ import annotations
import logging
from datetime import datetime
from typing import Final
import requests

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .const import DOMAIN, SIGNAL_TAG_IMAGE_UPDATE
from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .image_decompressor import to_image
from .tag_types import TagType, get_tag_types_manager

_LOGGER: Final = logging.getLogger(__name__)

async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up the OpenEPaperLink image platform."""

    hub = hass.data[DOMAIN][entry.entry_id]

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

class ESLImage(ImageEntity):
    """Image entity class for OpenEPaperLink tags.

    Provides an image entity that shows the current content displayed
    on a tag by fetching its raw image data from the AP and
    converting it to a standard image format.

    The image:

    - Fetches raw image data on demand
    - Converts proprietary tag-specific formats to JPEG
    - Caches converted images for performance
    - Updates when tag content changes
    """
    def __init__(self, hass: HomeAssistant, tag_mac: str, hub) -> None:
        """Initialize the image entity.

       Sets up the image with appropriate name, ID, and device association.
       Also initializes paths for image storage and establishes the JPEG
       content type for browser compatibility.

       Args:
           hass: Home Assistant instance
           tag_mac: MAC address of the tag
           hub: Hub instance for AP communication
       """
        super().__init__(hass)
        self._tag_mac = tag_mac
        self._hub = hub
        self._attr_has_entity_name = True
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
    def device_info(self):
        """Return device info for the tag.

        Associates this camera with the tag device in Home Assistant
        using the tag MAC address as the identifier.

        Returns:
            dict: Device information dictionary
        """
        return {
            "identifiers": {(DOMAIN, self._tag_mac)},
            "name": self._name,
        }

    @property
    def available(self) -> bool:
        """Return if entity is available.

        A camera is available if:

        - The AP is online
        - The tag is known to the AP
        - The tag is not blacklisted

        Returns:
            bool: True if the camera is available, False otherwise
        """
        return (
                self._hub.online and
                self._tag_mac in self._hub.tags and
                self._tag_mac not in self._hub.get_blacklisted_tags()
        )

    @property
    def image_last_updated(self) -> datetime | None:
        """Return the last updated image timestamp."""
        return self._last_updated

    async def _fetch_raw_image(self) -> bytes | None:
        """Fetch raw image data from AP.

        Retrieves the current raw image data for the tag from the AP's
        HTTP API. The raw format is specific to the tag's hardware and
        requires further processing to be displayed.

        Returns:
            bytes: Raw image data if successful
            None: If no image exists or an error occurred

        Raises:
            Exception: If HTTP request fails
        """
        url = f"http://{self._hub.host}/current/{self._tag_mac}.raw"
        try:
            result = await self.hass.async_add_executor_job(lambda: requests.get(url))
            if result.status_code == 200:
                return result.content
            if result.status_code == 404:
                _LOGGER.debug("No image found for %s", self._tag_mac)
                return None

            _LOGGER.error(
                "Failed to fetch image for %s: HTTP %d",
                self._tag_mac,
                result.status_code
            )
            return None
        except Exception as err:
            _LOGGER.error(
                "Error fetching image for %s: %s",
                self._tag_mac,
                str(err)
            )
            return None

    async def _get_tag_def(self) -> TagType | None:
        """Get tag definition for image decoding.

        Retrieves the tag type definition needed to properly decode the
        raw image data. The definition includes critical information like:

        - Display dimensions
        - Color depth and color table
        - Buffer rotation settings

        This is cached after the first call for performance.

        Returns:
            TagType: Tag type definition if found
            None: If tag type is unknown or cannot be determined

        Raises:
            Exception: If fetching tag definition fails
        """
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
                _LOGGER.error(
                    "Error getting tag definition for %s: %s",
                    self._tag_mac,
                    str(err)
                )
                return None

        return self._tag_type

    async  def async_image(self) -> bytes | None:
        """Return cached image bytes, fetching if needed."""
        if self._cached_image is None:
            await self._refresh_image()
        return self._cached_image

    async def _refresh_image(self) -> None:
        """Refresh the cached image data.

        Fetches new raw image data, processes it, and updates the cache.
        Only called when tag content changes.
        """
        try:
            raw_data = await self._fetch_raw_image()
            if raw_data:
                tag_def = await self._get_tag_def()
                if tag_def:
                    try:
                        jpeg_data = await self.hass.async_add_executor_job(
                            lambda: to_image(raw_data, tag_def)
                        )

                        # Update cache and timestamp
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

        # Update image on tag updates
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_TAG_IMAGE_UPDATE}_{self._tag_mac}",
                self._handle_tag_update
            )
        )

        # Update state on connection status changes
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_connection_status",
                self._handle_connection_status
            )
        )

    @callback
    def _handle_tag_update(self, data) -> None:
        """Handle tag data updates."""
        if isinstance(data, bytes):
            # Dry run
            self._cached_image = data
            self._last_updated = datetime.now()
            self.async_write_ha_state()
        elif data:
            # Update from AP
            self.hass.async_create_task(self._refresh_image())
            self.async_write_ha_state()

        self.async_write_ha_state()


    @callback
    def _handle_connection_status(self, is_online: bool) -> None:
        """Handle connection status updates."""
        self.async_write_ha_state()