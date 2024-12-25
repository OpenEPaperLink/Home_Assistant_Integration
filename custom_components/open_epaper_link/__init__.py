from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

import logging

from . import hub
from .const import DOMAIN
from .imagegen import *
from .tag_types import get_tag_types_manager
from .util import send_tag_cmd, reboot_ap

_LOGGER = logging.getLogger(__name__)


def rgb_to_rgb332(rgb):
    # Ensure that RGB values are in the range [0, 255]
    r, g, b = [max(0, min(255, x)) for x in rgb]

    # Convert RGB values to RGB332 format
    r = (r // 32) & 0b111  # 3 bits for red
    g = (g // 32) & 0b111  # 3 bits for green
    b = (b // 64) & 0b11  # 2 bits for blue

    # Combine the RGB332 components and convert to hex
    rgb332 = (r << 5) | (g << 2) | b

    return str(hex(rgb332)[2:].zfill(2))


def setup(hass, config):
    # callback for the draw custom service
    async def draw_custom_service(service: ServiceCall) -> None:
        ip = hass.states.get(DOMAIN + ".ip").state
        entity_ids = service.data.get("entity_id")
        # sometimes you get a string, that's not nice to iterate over for ids....
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        dither = service.data.get("dither", False)
        ttl = service.data.get("ttl", 60)
        preload_type = service.data.get("preloadtype", 0)
        preload_lut = service.data.get("preloadlut", 0)
        dry_run = service.data.get("dry-run", False)
        for entity_id in entity_ids:
            _LOGGER.info("Called entity_id: %s" % entity_id)
            img_buff = await hass.async_add_executor_job(generate_custom_image, entity_id, service, hass)
            id_parts = entity_id.split(".")
            if dry_run is False:
                result = await hass.async_add_executor_job(upload_image, img_buff, id_parts[1], ip, dither, ttl,
                                                           preload_type,
                                                           preload_lut, hass)
            else:
                _LOGGER.info("Running dry-run - no upload to AP!")
                result = True

    # callback for the image download service
    async def download_img_service(service: ServiceCall) -> None:
        ip = hass.states.get(DOMAIN + ".ip").state
        entity_ids = service.data.get("entity_id")
        dither = service.data.get("dither", False)
        for entity_id in entity_ids:
            _LOGGER.info("Called entity_id: %s" % entity_id)
            id_parts = entity_id.split(".")
            imgbuff = await hass.async_add_executor_job(download_img, entity_id, service, hass)
            result = await hass.async_add_executor_job(upload_image, imgbuff, id_parts[1], ip, dither, 300, 0, 0, hass)

    # callback for the 5 line service(deprecated)
    async def lines5_service(service: ServiceCall) -> None:
        ip = hass.states.get(DOMAIN + ".ip").state
        entity_ids = service.data.get("entity_id")
        for entity_id in entity_ids:
            _LOGGER.info("Called entity_id: %s" % (entity_id))
            img_buff = generate_5_line(entity_id, service, hass)
            id_parts = entity_id.split(".")
            result = await hass.async_add_executor_job(upload_image, img_buff, id_parts[1], ip, False, 300, 0, 0, hass)

    # callback for the 4 line service(deprecated)
    async def lines4_service(service: ServiceCall) -> None:
        ip = hass.states.get(DOMAIN + ".ip").state
        entity_ids = service.data.get("entity_id")
        for entity_id in entity_ids:
            _LOGGER.info("Called entity_id: %s" % (entity_id))
            img_buff = generate_4_line(entity_id, service, hass)
            entity_id = entity_id.split(".")
            result = await hass.async_add_executor_job(upload_image, img_buff, entity_id[1], ip, False, 300, 0, 0, hass)

    # callback for the set_led_service service
    async def set_led_service(service: ServiceCall) -> None:
        ip = hass.states.get(DOMAIN + ".ip").state
        entity_ids = service.data.get("entity_id")
        for entity_id in entity_ids:
            _LOGGER.info("Called entity_id: %s" % (entity_id))
            mac = entity_id.split(".")[1].upper()
            mode = service.data.get("mode", "")
            mode_byte = "0"
            if mode == "off": mode_byte = "0"
            if mode == "flash": mode_byte = "1"
            mode_byte = hex(int((int(service.data.get("brightness", 2) - 1) << 4)) + int(mode_byte))[2:]
            repeats = int_to_hex_string(service.data.get("repeats", 2) - 1)
            color1 = rgb_to_rgb332(service.data.get("color1", ""))
            color2 = rgb_to_rgb332(service.data.get("color2", ""))
            color3 = rgb_to_rgb332(service.data.get("color3", ""))
            flash_speed_1 = hex(int(service.data.get("flash_speed_1", 2) * 10))[2:]
            flash_speed_2 = hex(int(service.data.get("flashSpeed2", 2) * 10))[2:]
            flash_speed_3 = hex(int(service.data.get("flashSpeed3", 2) * 10))[2:]
            flash_count_1 = hex(int(service.data.get("flashCount1", 2)))[2:]
            flash_count_2 = hex(int(service.data.get("flashCount2", 2)))[2:]
            flash_count_3 = hex(int(service.data.get("flashCount3", 2)))[2:]
            delay1 = int_to_hex_string(int(service.data.get("delay1", 2) * 10))
            delay2 = int_to_hex_string(int(service.data.get("delay2", 2) * 10))
            delay3 = int_to_hex_string(int(service.data.get("delay3", 2) * 10))
            url = "http://" + ip + "/led_flash?mac=" + mac + "&pattern=" + mode_byte + color1 + flash_speed_1 + flash_count_1 + delay1 + color2 + flash_speed_2 + flash_count_2 + delay2 + color3 + flash_speed_3 + flash_count_3 + delay3 + repeats + "00";
            result = await hass.async_add_executor_job(requests.get, url)
            if result.status_code != 200:
                _LOGGER.warning(result.status_code)

    async def clear_pending_service(service: ServiceCall) -> None:
        entity_ids = service.data.get("entity_id")

        for entity_id in entity_ids:
            await send_tag_cmd(hass, entity_id, "clear")

    async def force_refresh_service(service: ServiceCall) -> None:
        entity_ids = service.data.get("entity_id")

        for entity_id in entity_ids:
            await send_tag_cmd(hass, entity_id, "refresh")

    async def reboot_tag_service(service: ServiceCall) -> None:
        entity_ids = service.data.get("entity_id")

        for entity_id in entity_ids:
            await send_tag_cmd(hass, entity_id, "reboot")

    async def scan_channels_service(service: ServiceCall) -> None:
        entity_ids = service.data.get("entity_id")

        for entity_id in entity_ids:
            await send_tag_cmd(hass, entity_id, "scan")

    async def reboot_ap_service(service: ServiceCall) -> None:
        await reboot_ap(hass)

    async def refresh_tag_types_service(service: ServiceCall) -> None:
        """Service to force refresh of tag types."""
        manager = await get_tag_types_manager(hass)
        # Force a refresh by clearing the last update timestamp
        manager._last_update = None
        await manager.ensure_types_loaded()
        tag_types_len = len(manager.get_all_types())
        message = f"Successfully refreshed {tag_types_len} tag types from GitHub"
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Tag Types Refreshed",
                "message:": message,
                "notification_id": "tag_types_refresh_notification",
            },
        )

    # register the services
    hass.services.register(DOMAIN, "dlimg", download_img_service)
    hass.services.register(DOMAIN, "lines5", lines5_service)
    hass.services.register(DOMAIN, "lines4", lines4_service)
    hass.services.register(DOMAIN, "drawcustom", draw_custom_service)
    hass.services.register(DOMAIN, "setled", set_led_service)
    hass.services.register(DOMAIN, "clear_pending", clear_pending_service)
    hass.services.register(DOMAIN, "force_refresh", force_refresh_service)
    hass.services.register(DOMAIN, "reboot_tag", reboot_tag_service)
    hass.services.register(DOMAIN, "scan_channels", scan_channels_service)
    hass.services.register(DOMAIN, "reboot_ap", reboot_ap_service)
    hass.services.register(DOMAIN, "refresh_tag_types", refresh_tag_types_service)
    # error handling needs to be improved
    return True


def int_to_hex_string(number):
    hex_string = hex(number)[2:]
    if len(hex_string) == 1:
        hex_string = '0' + hex_string
    return hex_string


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub.Hub(hass, entry.data["host"], entry)
    await hass.config_entries.async_forward_entry_setups(entry,
                                                         ["sensor", "button", "camera", "select", "switch", "text"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry,
                                                                 ["sensor", "button", "camera", "select", "switch",
                                                                  "text"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
