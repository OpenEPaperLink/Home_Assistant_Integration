from __future__ import annotations
from .imagegen import *
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from . import hub
from .const import DOMAIN
import logging

_LOGGER = logging.getLogger(__name__)


def setup(hass, config):
    # callback for the image downlaod service
    async def drawcustomservice(call) -> None:
        mac = call.data.get("mac", "000000000000")
        payload = call.data.get("payload", "")
        width = call.data.get("width", "")
        height = call.data.get("height", "")
        background = call.data.get("background","white")
        ip = hass.states.get(DOMAIN + ".ip").state
        imgbuff = customimage(payload,width,height,background,mac)
        result = await hass.async_add_executor_job(uploadimg, imgbuff, mac, ip)

    # callback for the image downlaod service
    async def dlimg(call) -> None:
        mac = call.data.get("mac", "000000000000")
        url = call.data.get("url", "")
        rotate = call.data.get("rotation", 0)
        ip = hass.states.get(DOMAIN + ".ip").state
        # we neet to know the esl type for resizing
        hwtype = hass.states.get(DOMAIN + "." + mac.lower() + "hwtype").state
        imgbuff = await hass.async_add_executor_job(downloadimg, url, hwtype, rotate)
        result = await hass.async_add_executor_job(uploadimg, imgbuff, mac, ip)

    # callback for the 5 line service
    async def lines5service(call) -> None:
        mac = call.data.get("mac", "000000000000")
        line1 = call.data.get("line1", "")
        line2 = call.data.get("line2", "")
        line3 = call.data.get("line3", "")
        line4 = call.data.get("line4", "")
        line5 = call.data.get("line5", "")
        border = call.data.get("border", "w")
        format1 = call.data.get("format1", "mwwb")
        format2 = call.data.get("format2", "mwwb")
        format3 = call.data.get("format3", "mwwb")
        format4 = call.data.get("format4", "mwwb")
        format5 = call.data.get("format5", "mwwb")
        ip = hass.states.get(DOMAIN + ".ip").state
        imgbuff = gen5line(line1, line2, line3, line4, line5, border, format1, format2, format3, format4, format5)
        result = await hass.async_add_executor_job(uploadimg, imgbuff, mac, ip)

    # callback for the 4 line service
    async def lines4service(call) -> None:
        mac = call.data.get("mac", "000000000000")
        line1 = call.data.get("line1", "")
        line2 = call.data.get("line2", "")
        line3 = call.data.get("line3", "")
        line4 = call.data.get("line4", "")
        border = call.data.get("border", "w")
        format1 = call.data.get("format1", "mwwb")
        format2 = call.data.get("format2", "mwwb")
        format3 = call.data.get("format3", "mwwb")
        format4 = call.data.get("format4", "mwwb")
        ip = hass.states.get(DOMAIN + ".ip").state
        imgbuff = gen4line(line1, line2, line3, line4, border, format1, format2, format3, format4)
        result = await hass.async_add_executor_job(uploadimg, imgbuff, mac, ip)

    # register the services
    hass.services.register(DOMAIN, "dlimg", dlimg)
    hass.services.register(DOMAIN, "lines5", lines5service)
    hass.services.register(DOMAIN, "lines4", lines4service)
    hass.services.register(DOMAIN, "drawcustom", drawcustomservice)

    # error haneling needs to be improved
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub.Hub(hass, entry.data["host"], entry)
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
