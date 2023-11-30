"""Platform for sensor integration."""
from __future__ import annotations
from .const import DOMAIN
import logging
import datetime
import logging
import mimetypes
import os

import voluptuous as vol

_LOGGER: Final = logging.getLogger(__name__)

DATA_LOCAL_FILE = "local_file_cameras"

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import TEMP_CELSIUS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.components.camera import Camera
from homeassistant.const import ATTR_ENTITY_ID, CONF_FILE_PATH, CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

async def async_setup_entry(hass, config_entry, async_add_entities):
    hub = hass.data[DOMAIN][config_entry.entry_id]
    new_devices = []
    for esls in hub.esls:
        if hub.data[esls]["lqi"] != 100 or hub.data[esls]["rssi"] != 100:
            camera = LocalFile(esls, "/config/www/open_epaper_link/open_epaper_link."+ str(esls).lower() + ".jpg", hub)
            new_devices.append(camera)
    async_add_entities(new_devices,True)

class LocalFile(Camera):
    """Representation of a local file camera."""

    def __init__(self, esls, file_path,hub):
        """Initialize Local File Camera component."""
        super().__init__()
        Camera.__init__(self)
        self._name = f"{esls}_cam"
        self._attr_unique_id = f"{esls}_cam"
        self._hub = hub
        self._attr_name = f"{esls} Cam"
        self._name = f"{esls} Cam"
        self._eslid = esls
        self.check_file_path_access(file_path)
        self._file_path = file_path
        # Set content type of local file
        content, _ = mimetypes.guess_type(file_path)
        if content is not None:
            self.content_type = content

    #def device_info(self) -> DeviceInfo:
    #    return {
    #        "identifiers": {(DOMAIN, self._eslid)},
    #        "name": self._eslid,
    #        "sw_version": self._hub.data[self._eslid]["ver"],
    #        "model": self._hub.data[self._eslid]["hwstring"],
    #        "manufacturer": "OpenEpaperLink",
    #        "via_device": (DOMAIN, "ap")
    #    }

    @property
    def name(self):
        """Return the name of this camera."""
        return self._name
        
    def camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return image response."""
        try:
            with open(self._file_path, "rb") as file:
                return file.read()
        except FileNotFoundError:
            _LOGGER.warning(
                "Could not read image from file: %s",
                self._file_path,
            )
        return None

    def check_file_path_access(self, file_path):
        """Check that filepath given is readable."""
        #if not os.access(file_path, os.R_OK):
        #    _LOGGER.warning("Could not read image from file: %s", file_path)
        #else:
        #    _LOGGER.warning("found %s", file_path)
    def update_file_path(self, file_path):
        """Update the file_path."""
        self.check_file_path_access(file_path)
        self._file_path = file_path
        self.schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return the camera state attributes."""
        return {"file_path": self._file_path}
