from __future__ import annotations

import logging
import mimetypes
import os
from typing import Final

from homeassistant.components.camera import Camera, CameraEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DOMAIN
from .util import get_image_path, get_image_folder

_LOGGER: Final = logging.getLogger(__name__)

async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback
) -> None:
    """Set up cameras for current ESL displays."""
    hub = hass.data[DOMAIN][entry.entry_id]

    # Track added cameras to prevent duplicates
    added_cameras = set()

    async def async_add_camera(tag_mac: str) -> None:
        """Add camera for a newly discovered tag."""
        if tag_mac in added_cameras:
            return

        # Only create camera for ESLs with valid signal strength
        tag_data = hub.get_tag_data(tag_mac)
        if not tag_data:
            return

        if tag_data.get("lqi") == 100 and tag_data.get("rssi") == 100:
            _LOGGER.debug("Skipping camera for tag %s with perfect signal", tag_mac)
            return

        # Get image path
        image_folder = get_image_folder(hass)
        if not os.path.exists(image_folder):
            os.makedirs(image_folder)

        image_path = get_image_path(hass, f"open_epaper_link.{tag_mac.lower()}")

        # Create camera entity if image exists
        if os.path.exists(image_path):
            camera = ESLCameraEntity(
                hass=hass,
                hub=hub,
                tag_mac=tag_mac,
                image_path=image_path
            )
            added_cameras.add(tag_mac)
            async_add_entities([camera])
        else:
            _LOGGER.debug(
                "No image found for ESL %s at %s",
                tag_mac,
                image_path
            )

    # Set up cameras for existing tags
    for tag_mac in hub.tags:
        await async_add_camera(tag_mac)

    # Listen for new tag discoveries
    entry.async_on_remove(
        async_dispatcher_connect(
            hass,
            f"{DOMAIN}_tag_discovered",
            async_add_camera
        )
    )

class ESLCameraEntity(Camera):
    """Camera entity showing current ESL display content."""

    def __init__(
            self,
            hass: HomeAssistant,
            hub,
            tag_mac: str,
            image_path: str
    ) -> None:
        """Initialize the camera entity."""
        super().__init__()

        self.hass = hass
        self._hub = hub
        self._tag_mac = tag_mac
        self._image_path = image_path
        self._last_image: bytes | None = None
        self._content_type: str | None = None

        # Entity attributes
        tag_data = hub.get_tag_data(tag_mac)
        self._attr_name = f"{tag_data.get('tag_name', tag_mac)} Content"
        self._attr_unique_id = f"{tag_mac}_camera"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_should_poll = False

        # Set content type based on file extension
        content_type, _ = mimetypes.guess_type(image_path)
        if content_type:
            self.content_type = content_type
            _LOGGER.debug(
                "Set content type %s for camera %s",
                content_type,
                self._attr_name
            )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._tag_mac)},
            "name": self._hub.get_tag_data(self._tag_mac).get("tag_name", self._tag_mac),
            "manufacturer": "OpenEPaperLink",
            "model": self._hub.get_tag_data(self._tag_mac).get("hw_string", "Unknown ESL"),
            "sw_version": self._hub.get_tag_data(self._tag_mac).get("version"),
            "via_device": (DOMAIN, "ap"),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
                self._hub.online
                and self._tag_mac in self._hub.tags
                and os.path.exists(self._image_path)
        )

    async def async_camera_image(
            self,
            width: int | None = None,
            height: int | None = None,
    ) -> bytes | None:
        """Return image response."""
        try:
            # Use async file operations
            def read_image():
                with open(self._image_path, "rb") as file:
                    return file.read()

            self._last_image = await self.hass.async_add_executor_job(read_image)
            return self._last_image

        except FileNotFoundError:
            _LOGGER.warning(
                "Image file not found: %s",
                self._image_path
            )
            return None

        except Exception as err:
            _LOGGER.error(
                "Error reading camera image %s: %s",
                self._image_path,
                str(err)
            )
            return None

    @callback
    def _handle_tag_update(self):
        """Handle tag data updates."""
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Register callbacks."""
        # Listen for tag updates
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"open_epaper_link_tag_update_{self._tag_mac}",
                self._handle_tag_update,
            )
        )

    @property
    def extra_state_attributes(self):
        """Return entity specific state attributes."""
        return {
            "file_path": self._image_path,
            "last_update": self._hub.get_tag_data(self._tag_mac).get("last_seen"),
        }