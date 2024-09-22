from __future__ import annotations
from .const import DOMAIN
import requests
import logging
from homeassistant.core import HomeAssistant

_LOGGER: Final = logging.getLogger(__name__)

def get_image_folder(hass):
    """Return the folder where images are stored."""
    return hass.config.path("www/open_epaper_link")

def get_image_path(hass, entity_id):
    """Return the path to the image for a specific tag."""
    return hass.config.path("www/open_epaper_link/open_epaper_link."+ str(entity_id).lower() + ".jpg")

async def clear_pending(hass: HomeAssistant, entity_id: str) -> bool:
    """Clear the pending image for an ESL Tag."""
    ip = hass.states.get(DOMAIN + ".ip").state
    mac = entity_id.split(".")[1].upper()
    url = f"http://{ip}/tag_cmd"

    data = {
        'mac': mac,
        'cmd': 'clear'
    }

    try:
        result = await hass.async_add_executor_job(lambda : requests.post(url, data=data))
        if result.status_code == 200:
            _LOGGER.info("Cleared pending for %s", entity_id)
        else:
            _LOGGER.warning("Failed to clear pending for %s", entity_id)
    except Exception as e:
        _LOGGER.error("Failed to clear pending for %s: %s", entity_id, e)
        return False

