from __future__ import annotations

import asyncio
import json
import logging
import time
from threading import Thread
from typing import Final

import aiohttp
import async_timeout
import websocket
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .tag_types import get_hw_string, get_tag_types_manager

_LOGGER: Final = logging.getLogger(__name__)

# Time to wait before trying to reconnect on disconnections.
_RECONNECT_SECONDS: int = 30


# Hub class for handling communication
class Hub:
    # the init function starts the thread for all other communication
    def __init__(self, hass: HomeAssistant, host: str, config_entry: str) -> None:
        self._host = host
        self._config_entry = config_entry
        self._hass = hass
        self._name = host
        self._id = host.lower()
        self.esls = []
        self.data = dict()
        self.data["ap"] = dict()
        self.data["ap"]["ip"] = self._host
        self.data["ap"]["systime"] = None
        self.data["ap"]["heap"] = None
        self.data["ap"]["recordcount"] = None
        self.data["ap"]["dbsize"] = None
        self.data["ap"]["littlefsfree"] = None
        self.ap_config = {}
        self.ap_config_loaded = asyncio.Event()
        self.eventloop = asyncio.get_event_loop()
        self._is_fetching_config = False
        self.eventloop.create_task(self.fetch_ap_config())
        self._tag_manager = None
        self.tag_manager_initialized = asyncio.Event()
        thread = Thread(target=self.connection_thread)
        self._hass.async_create_task(self._init_tag_manager())
        thread.start()
        self.online = True

    async def _init_tag_manager(self) -> None:
        """Initialize tag manager."""
        self._tag_manager = await get_tag_types_manager(self._hass)
        self.tag_manager_initialized.set()  # Signal that initialization is complete

    # parses websocket messages
    def on_message(self, ws, message) -> None:
        # Wait for the tag manager to initialize if needed
        if not self.tag_manager_initialized.is_set():
            future = asyncio.run_coroutine_threadsafe(self.tag_manager_initialized.wait(), self.eventloop)
            future.result()  # Wait until the event is set, blocking only this call
        data = json.loads('{' + message.split("{", 1)[-1])
        if 'sys' in data:
            sys = data.get('sys')
            systime = sys.get('currtime')
            heap = sys.get('heap')
            record_count = sys.get('recordcount')
            db_size = sys.get('dbsize')
            littlefs_free = sys.get('littlefsfree')
            ap_state = sys.get('apstate')
            run_state = sys.get('runstate')
            temp = sys.get('temp')
            rssi = sys.get('rssi')
            wifi_status = sys.get('wifistatus')
            wifissid = sys.get('wifissid')
            self._hass.states.set(DOMAIN + ".ip", self._host,
                                  {"icon": "mdi:ip", "friendly_name": "AP IP", "should_poll": False})
            self.data["ap"] = dict()
            self.data["ap"]["ip"] = self._host
            self.data["ap"]["systime"] = systime
            self.data["ap"]["heap"] = heap
            self.data["ap"]["recordcount"] = record_count
            self.data["ap"]["dbsize"] = db_size
            self.data["ap"]["littlefsfree"] = littlefs_free
            self.data["ap"]["rssi"] = rssi
            self.data["ap"]["apstate"] = ap_state
            self.data["ap"]["runstate"] = run_state
            self.data["ap"]["temp"] = temp
            self.data["ap"]["wifistatus"] = wifi_status
            self.data["ap"]["wifissid"] = wifissid
        elif 'tags' in data:
            tag = data.get('tags')[0]
            tag_mac = tag.get('mac')
            last_seen = tag.get('lastseen')
            next_update = tag.get('nextupdate')
            next_checkin = tag.get('nextcheckin')
            lqi = tag.get('LQI')
            rssi = tag.get('RSSI')
            temperature = tag.get('temperature')
            battery_mv = tag.get('batteryMv')
            pending = tag.get('pending')
            hw_type = tag.get('hwType')
            content_mode = tag.get('contentMode')
            alias = tag.get('alias')
            wakeup_reason = tag.get('wakeupReason')
            capabilities = tag.get('capabilities')
            hash_v = tag.get('hash')
            mode_cfg_json = tag.get('modecfgjson')
            is_external = tag.get('isexternal')
            rotate = tag.get('rotate')
            lut = tag.get('lut')
            ch = tag.get('ch')
            ver = tag.get('ver')
            tag_name = alias if alias else tag_mac
            # required for automations
            if self._tag_manager.is_in_hw_map(hw_type):
                width, height = self._tag_manager.get_hw_dimensions(hw_type)
                self._hass.states.set(DOMAIN + "." + tag_mac, hw_type, {
                    "icon": "mdi:fullscreen",
                    "friendly_name": tag_name,
                    "attr_unique_id": tag_mac,
                    "unique_id": tag_mac,
                    "device_class": "sensor",
                    "device_info": {
                        "identifiers": {(DOMAIN, tag_mac)}
                    },
                    "should_poll": False,
                    "hwtype": hw_type,
                    "hwstring": self._tag_manager.get_hw_string(hw_type),
                    "width": width,
                    "height": height,
                })
            else:
                _LOGGER.warning(
                    f"ID {hw_type} not in hwmap, please try refreshing tagtypes, if it persists open an issue on github about this.")

            self.data[tag_mac] = dict()
            self.data[tag_mac]["temperature"] = temperature
            self.data[tag_mac]["rssi"] = rssi
            self.data[tag_mac]["battery"] = battery_mv
            self.data[tag_mac]["lqi"] = lqi
            self.data[tag_mac]["hwtype"] = hw_type
            self.data[tag_mac]["hwstring"] = get_hw_string(hw_type)
            self.data[tag_mac]["contentmode"] = content_mode
            self.data[tag_mac]["lastseen"] = last_seen
            self.data[tag_mac]["nextupdate"] = next_update
            self.data[tag_mac]["nextcheckin"] = next_checkin
            self.data[tag_mac]["pending"] = pending
            self.data[tag_mac]["wakeupReason"] = wakeup_reason
            self.data[tag_mac]["capabilities"] = capabilities
            self.data[tag_mac]["external"] = is_external
            self.data[tag_mac]["alias"] = alias
            self.data[tag_mac]["hashv"] = hash_v
            self.data[tag_mac]["modecfgjson"] = mode_cfg_json
            self.data[tag_mac]["rotate"] = rotate
            self.data[tag_mac]["lut"] = lut
            self.data[tag_mac]["ch"] = ch
            self.data[tag_mac]["ver"] = ver
            self.data[tag_mac]["tagname"] = tag_name
            # maintains a list of all tags, new entities should be generated here
            if tag_mac not in self.esls:
                self.esls.append(tag_mac)
                loop = self.eventloop
                asyncio.run_coroutine_threadsafe(self.reload_cfg_ett(), loop)
                # fire event with the wakeup reason
            lut = {0: "TIMED", 1: "BOOT", 2: "GPIO", 3: "NFC", 4: "BUTTON1", 5: "BUTTON2", 252: "FIRSTBOOT",
                   253: "NETWORK_SCAN", 254: "WDT_RESET"}
            event_data = {
                "device_id": tag_mac,
                "type": lut[wakeup_reason],
            }
            self._hass.bus.fire(DOMAIN + "_event", event_data)
        elif 'errMsg' in data:
            errmsg = data.get('errMsg')
        elif 'logMsg' in data:
            logmsg = data.get('logMsg')
        elif 'apitem' in data:
            _LOGGER.debug(f"AP item: {data.get('apitem')}")
            if not self._is_fetching_config:
                self.eventloop.call_soon_threadsafe(
                    lambda: self.eventloop.create_task(self.fetch_ap_config())
                )
            logmsg = data.get('apitem')
        else:
            _LOGGER.debug("Unknown msg")
            _LOGGER.debug(data)

    # log websocket errors
    def on_error(self, ws, error) -> None:
        _LOGGER.debug("Websocket error, most likely on_message crashed")
        _LOGGER.debug(error)

    def on_close(self, ws, close_status_code, close_msg) -> None:
        _LOGGER.warning(
            f"Websocket connection lost to url={ws.url} "
            f"(close_status_code={close_status_code}, close_msg={close_msg}), "
            f"trying to reconnect every {_RECONNECT_SECONDS} seconds")

    # we could do something here
    def on_open(self, ws) -> None:
        _LOGGER.debug("WS started")

    # starts the websocket
    def connection_thread(self) -> None:
        while True:
            try:
                ws_url = "ws://" + self._host + "/ws"
                ws = websocket.WebSocketApp(
                    ws_url,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                    on_open=self.on_open)
                ws.run_forever(reconnect=_RECONNECT_SECONDS)
            except Exception as e:
                _LOGGER.exception(e)

            _LOGGER.error(f"open_epaper_link WebSocketApp crashed, reconnecting in {_RECONNECT_SECONDS} seconds")
            time.sleep(_RECONNECT_SECONDS)

    # we should do more here
    async def test_connection(self) -> bool:
        return True

    # reload is required to add new entities
    async def reload_cfg_ett(self) -> bool:
        await self._hass.config_entries.async_unload_platforms(self._config_entry, ["sensor", "camera", "button"])
        await self._hass.config_entries.async_forward_entry_setups(self._config_entry, ["sensor", "camera", "button"])
        return True

    async def fetch_ap_config(self):
        if self._is_fetching_config:
            return

        try:
            self._is_fetching_config = True
            async with aiohttp.ClientSession() as session:
                async with async_timeout.timeout(10):
                    response = await session.get(f"http://{self._host}/get_ap_config")
                    if response.status == 200:
                        data = await response.json()
                        if self.ap_config != data:
                            _LOGGER.debug(f"AP config updated: {data}")
                            self.ap_config = data
                            self.ap_config_loaded.set()
                    else:
                        _LOGGER.warning(f"Failed to fetch AP config: {response.status}")
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout while fetching AP config")
        except Exception as e:
            _LOGGER.error(f"Error fetching AP config: {e}")
        finally:
            self._is_fetching_config = False
