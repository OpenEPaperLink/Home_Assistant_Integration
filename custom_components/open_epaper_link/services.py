"""Services for OpenEPaperLink integration."""
from __future__ import annotations

import logging
from typing import Final

from .util import send_tag_cmd
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.helpers.config_validation import entity_ids, service

from .const import DOMAIN
from .imagegen import downloadimg, gen5line, gen4line, customimage, uploadimg, uploadcfg

_LOGGER: Final = logging.getLogger(__name__)

def get_tag_mac_from_entity_id(entity_id: str) -> str:
    """Extract tag MAC from entity ID."""
    return entity_id.split(".")[1].upper()

async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for OpenEPaperLink integration."""

    async def handle_draw_custom(call: ServiceCall) -> None:
        """Handle draw_custom service."""
        ip = hass.states.get(DOMAIN + ".ip").state
        if not (entity_id := call.data.get(ATTR_ENTITY_ID)):
            return

        for config_entry_id in hass.data[DOMAIN]:
            hub = hass.data[DOMAIN][config_entry_id]
            tag_mac = get_tag_mac_from_entity_id(entity_id[0])

            if tag_mac in hub.tags:
                img = await hass.async_add_executor_job(
                    customimage, entity_id[0], call, hass
                )
                if not call.data.get("dry-run", False):
                    await hass.async_add_executor_job(
                        uploadimg, img, tag_mac, hub.host,
                        False, 300, 0, 0, hass
                    )
                break
    async def handle_clear_pending_service(call: ServiceCall) -> None:
        """Handle clear_pending service."""
        entity_ids = call.data.get("entity_id")
        for entity_id in entity_ids:
            await send_tag_cmd(hass, entity_id, "clear")

    hass.services.async_register(
        DOMAIN, "drawcustom", handle_draw_custom
    )
    hass.services.async_register(
        DOMAIN, "clear_pending", handle_clear_pending_service
    )

async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload OpenEPaperLink services."""
    for service in ["drawcustom", "clear_pending"]:
        hass.services.async_remove(DOMAIN, service)