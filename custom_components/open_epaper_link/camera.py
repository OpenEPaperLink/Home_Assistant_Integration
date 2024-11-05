"""Camera implementation for OpenEPaperLink integration."""
from __future__ import annotations

import logging
import os
from typing import Final

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .tag_types import get_hw_string
from .util import get_image_path

_LOGGER: Final = logging.getLogger(__name__)

async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up EPD cameras from a config entry."""
    hub = hass.data[DOMAIN][entry.entry_id]

    # Track added cameras to prevent duplicates
    added_cameras = set()

    async def async_add_camera(tag_mac: str) -> None:
        """Add camera for a newly discovered tag."""
        # Skip if camera already exists
        if tag_mac in added_cameras:
            return

        # Skip if tag is blacklisted
        if tag_mac in hub.get_blacklisted_tags():
            _LOGGER.debug("Skipping camera creation for blacklisted tag: %s", tag_mac)
            return

        # Skip AP (it's not a tag)
        if tag_mac == "ap":
            return

        camera = EPDCamera(hass, tag_mac, hub)
        added_cameras.add(tag_mac)
        async_add_entities([camera], True)

    # Add cameras for existing tags
    for tag_mac in hub.tags:
        await async_add_camera(tag_mac)

    # Register callback for new tag discovery
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_tag_discovered",
            async_add_camera
        )
    )

    # Register callback for blacklist updates
    async def handle_blacklist_update() -> None:
        """Handle updates to the tag blacklist."""
        for tag_mac in hub.get_blacklisted_tags():
            if tag_mac in added_cameras:
                added_cameras.remove(tag_mac)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_blacklist_update",
            handle_blacklist_update
        )
    )

    return True

class EPDCamera(Camera):
    """Camera class for OpenEPaperLink tags."""

    def __init__(self, hass: HomeAssistant, tag_mac: str, hub) -> None:
        """Initialize the camera."""
        super().__init__()
        self.hass = hass
        self._hub = hub
        self._tag_mac = tag_mac
        self._attr_unique_id = f"{tag_mac}_content"

        # Get initial tag data
        tag_data = hub.get_tag_data(tag_mac)
        self._name = f"{tag_data.get('tag_name', tag_mac)} Content"

        # Set up device info
        firmware_version = str(tag_data.get("version", ""))
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._tag_mac)},
            name=self._name,
            manufacturer="OpenEPaperLink",
            model=get_hw_string(tag_data.get("hw_type", 0)),
            via_device=(DOMAIN, "ap"),
            sw_version=f"0x{int(firmware_version, 16):X}" if firmware_version else "Unknown",
        )

        self.content_type = "image/jpeg"
        self._image_path = get_image_path(hass, f"{DOMAIN}.{tag_mac}")
        self._last_image = None

    @property
    def name(self) -> str:
        """Return the camera name."""
        return self._name

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
                self._hub.online and
                self._tag_mac in self._hub.tags and
                self._tag_mac not in self._hub.get_blacklisted_tags()
        )

    async def async_camera_image(
            self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return locally generated image."""
        if not self.available:
            return self._last_image

        try:
            # Check if image file exists
            if not os.path.exists(self._image_path):
                return self._last_image

            # Get file modification time
            mod_time = os.path.getmtime(self._image_path)

            # If we have a cached image, check if the file has been modified
            if self._last_image is not None:
                if hasattr(self, '_last_mod_time') and mod_time <= self._last_mod_time:
                    return self._last_image

            # Read and cache the new image
            def read_image():
                with open(self._image_path, 'rb') as f:
                    return f.read()

            self._last_image = await self.hass.async_add_executor_job(read_image)
            self._last_mod_time = mod_time

            return self._last_image

        except Exception as err:
            _LOGGER.error(
                "Error reading image file for %s: %s",
                self._tag_mac,
                str(err)
            )
            return self._last_image

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        # Update state on tag updates
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_tag_update_{self._tag_mac}",
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
    def _handle_tag_update(self) -> None:
        """Handle tag data updates."""
        if self._tag_mac in self._hub.tags:
            tag_data = self._hub.get_tag_data(self._tag_mac)
            self._name = f"{tag_data.get('tag_name', self._tag_mac)} Display"
        self.async_write_ha_state()

    @callback
    def _handle_connection_status(self, is_online: bool) -> None:
        """Handle connection status updates."""
        self.async_write_ha_state()