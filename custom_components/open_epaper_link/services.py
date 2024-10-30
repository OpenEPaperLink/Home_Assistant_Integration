from __future__ import annotations

import logging
from typing import Final
import requests
from datetime import datetime

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError

from .imagegen import customimage, uploadimg, downloadimg, gen5line, gen4line
from .const import DOMAIN
from .tag_types import get_tag_types_manager
from .util import send_tag_cmd, reboot_ap

_LOGGER: Final = logging.getLogger(__name__)

def rgb_to_rgb332(rgb):
    """Convert RGB values to RGB332 format."""
    # Ensure that RGB values are in the range [0, 255]
    r, g, b = [max(0, min(255, x)) for x in rgb]

    # Convert RGB values to RGB332 format
    r = (r // 32) & 0b111  # 3 bits for red
    g = (g // 32) & 0b111  # 3 bits for green
    b = (b // 64) & 0b11   # 2 bits for blue

    # Combine the RGB332 components and convert to hex
    rgb332 = (r << 5) | (g << 2) | b

    return str(hex(rgb332)[2:].zfill(2))

def int_to_hex_string(number: int) -> str:
    """Convert integer to two-digit hex string."""
    hex_string = hex(number)[2:]
    if len(hex_string) == 1:
        hex_string = '0' + hex_string
    return hex_string

async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up the OpenEPaperLink services."""

    async def get_hub():
        """Get the hub instance."""
        if DOMAIN not in hass.data or not hass.data[DOMAIN]:
            raise HomeAssistantError("Integration not configured")
        return next(iter(hass.data[DOMAIN].values()))

    async def drawcustom_service(service: ServiceCall) -> None:
        """Handle draw custom service calls."""
        hub = await get_hub()
        if not hub.online:
            raise HomeAssistantError("AP is offline")

        entity_ids = service.data.get("entity_id")
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        dither = service.data.get("dither", False)
        ttl = service.data.get("ttl", 60)
        preloadtype = service.data.get("preloadtype", 0)
        preloadlut = service.data.get("preloadlut", 0)
        dry_run = service.data.get("dry-run", False)

        for entity_id in entity_ids:
            _LOGGER.info("Processing entity_id: %s", entity_id)
            imgbuff = await hass.async_add_executor_job(customimage, entity_id, service, hass)
            mac = entity_id.split(".")[1]

            if not dry_run:
                await hass.async_add_executor_job(
                    uploadimg, imgbuff, mac, hub.host, dither, ttl, preloadtype, preloadlut, hass
                )
            else:
                _LOGGER.info("Dry-run mode - no upload to AP")

    async def dlimg_service(service: ServiceCall) -> None:
        """Handle download image service calls."""
        hub = await get_hub()
        if not hub.online:
            raise HomeAssistantError("AP is offline")

        entity_ids = service.data.get("entity_id")
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        dither = service.data.get("dither", False)

        for entity_id in entity_ids:
            _LOGGER.info("Processing entity_id: %s", entity_id)
            imgbuff = await hass.async_add_executor_job(downloadimg, entity_id, service, hass)
            mac = entity_id.split(".")[1]
            await hass.async_add_executor_job(
                uploadimg, imgbuff, mac, hub.host, dither, 300, 0, 0, hass
            )

    async def lines5_service(service: ServiceCall) -> None:
        """Handle 5 line display service calls (deprecated)."""
        hub = await get_hub()
        if not hub.online:
            raise HomeAssistantError("AP is offline")

        entity_ids = service.data.get("entity_id")
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        for entity_id in entity_ids:
            _LOGGER.info("Processing entity_id: %s", entity_id)
            imgbuff = gen5line(entity_id, service, hass)
            mac = entity_id.split(".")[1]
            await hass.async_add_executor_job(
                uploadimg, imgbuff, mac, hub.host, False, 300, 0, 0, hass
            )

    async def lines4_service(service: ServiceCall) -> None:
        """Handle 4 line display service calls (deprecated)."""
        hub = await get_hub()
        if not hub.online:
            raise HomeAssistantError("AP is offline")

        entity_ids = service.data.get("entity_id")
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        for entity_id in entity_ids:
            _LOGGER.info("Processing entity_id: %s", entity_id)
            imgbuff = gen4line(entity_id, service, hass)
            mac = entity_id.split(".")[1]
            await hass.async_add_executor_job(
                uploadimg, imgbuff, mac, hub.host, False, 300, 0, 0, hass
            )

    async def setled_service(service: ServiceCall) -> None:
        """Handle LED pattern service calls."""
        hub = await get_hub()
        if not hub.online:
            raise HomeAssistantError("AP is offline")

        entity_ids = service.data.get("entity_id")
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        for entity_id in entity_ids:
            _LOGGER.info("Processing entity_id: %s", entity_id)
            mac = entity_id.split(".")[1].upper()

            mode = service.data.get("mode", "")
            modebyte = "1" if mode == "flash" else "0"
            brightness = service.data.get("brightness", 2)
            modebyte = hex(((brightness - 1) << 4) + int(modebyte))[2:]

            pattern = (
                    modebyte +
                    rgb_to_rgb332(service.data.get("color1", "")) +
                    hex(int(service.data.get("flashSpeed1", 0.2) * 10))[2:] +
                    hex(service.data.get("flashCount1", 2))[2:] +
                    int_to_hex_string(int(service.data.get("delay1", 0.1) * 10)) +
                    rgb_to_rgb332(service.data.get("color2", "")) +
                    hex(int(service.data.get("flashSpeed2", 0.2) * 10))[2:] +
                    hex(service.data.get("flashCount2", 2))[2:] +
                    int_to_hex_string(int(service.data.get("delay2", 0.1) * 10)) +
                    rgb_to_rgb332(service.data.get("color3", "")) +
                    hex(int(service.data.get("flashSpeed3", 0.2) * 10))[2:] +
                    hex(service.data.get("flashCount3", 2))[2:] +
                    int_to_hex_string(int(service.data.get("delay3", 0.0) * 10)) +
                    int_to_hex_string(service.data.get("repeats", 2) - 1) +
                    "00"
            )

            url = f"http://{hub.host}/led_flash?mac={mac}&pattern={pattern}"
            result = await hass.async_add_executor_job(requests.get, url)
            if result.status_code != 200:
                _LOGGER.warning("LED pattern update failed with status code: %s", result.status_code)

    async def clear_pending_service(service: ServiceCall) -> None:
        """Handle clear pending service calls."""
        entity_ids = service.data.get("entity_id")
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        for entity_id in entity_ids:
            await send_tag_cmd(hass, entity_id, "clear")

    async def force_refresh_service(service: ServiceCall) -> None:
        """Handle force refresh service calls."""
        entity_ids = service.data.get("entity_id")
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        for entity_id in entity_ids:
            await send_tag_cmd(hass, entity_id, "refresh")

    async def reboot_tag_service(service: ServiceCall) -> None:
        """Handle tag reboot service calls."""
        entity_ids = service.data.get("entity_id")
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        for entity_id in entity_ids:
            await send_tag_cmd(hass, entity_id, "reboot")

    async def scan_channels_service(service: ServiceCall) -> None:
        """Handle channel scan service calls."""
        entity_ids = service.data.get("entity_id")
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        for entity_id in entity_ids:
            await send_tag_cmd(hass, entity_id, "scan")

    async def reboot_ap_service(service: ServiceCall) -> None:
        """Handle AP reboot service calls."""
        await reboot_ap(hass)

    async def refresh_tag_types_service(service: ServiceCall) -> None:
        """Handle tag type refresh service calls."""
        manager = await get_tag_types_manager(hass)
        manager._last_update = None  # Force refresh
        await manager.ensure_types_loaded()

        tag_types_len = len(manager.get_all_types())
        message = f"Successfully refreshed {tag_types_len} tag types from GitHub"

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Tag Types Refreshed",
                "message": message,
                "notification_id": "tag_types_refresh_notification",
            },
        )

    # Register all services
    hass.services.async_register(DOMAIN, "dlimg", dlimg_service)
    hass.services.async_register(DOMAIN, "lines5", lines5_service)
    hass.services.async_register(DOMAIN, "lines4", lines4_service)
    hass.services.async_register(DOMAIN, "drawcustom", drawcustom_service)
    hass.services.async_register(DOMAIN, "setled", setled_service)
    hass.services.async_register(DOMAIN, "clear_pending", clear_pending_service)
    hass.services.async_register(DOMAIN, "force_refresh", force_refresh_service)
    hass.services.async_register(DOMAIN, "reboot_tag", reboot_tag_service)
    hass.services.async_register(DOMAIN, "scan_channels", scan_channels_service)
    hass.services.async_register(DOMAIN, "reboot_ap", reboot_ap_service)
    hass.services.async_register(DOMAIN, "refresh_tag_types", refresh_tag_types_service)

async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload OpenEPaperLink services."""
    for service in [
        "dlimg", "lines5", "lines4", "drawcustom", "setled", "clear_pending",
        "force_refresh", "reboot_tag", "scan_channels", "reboot_ap", "refresh_tag_types"
    ]:
        hass.services.async_remove(DOMAIN, service)