from __future__ import annotations
import asyncio
import random
import websocket
import socket
import aiohttp
import async_timeout
import backoff
import time
import json
import logging
import os
from threading import Thread
from typing import Any, Final
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr

from .button import ClearPendingTagButton
from .const import DOMAIN
from .tag_types import get_hw_dimensions, get_hw_string, is_in_hw_map, get_tag_types_manager

_LOGGER: Final = logging.getLogger(__name__)

# Time to wait before trying to reconnect on disconnections.
_RECONNECT_SECONDS : int = 30

#Hub class for handling communication
class Hub:
    #the init function starts the thread for all other communication
    def __init__(self, hass: HomeAssistant, host: str, cfgentry: str) -> None:
        self._host = host
        self._cfgenty = cfgentry
        self._hass = hass
        self._name = host
        self._id = host.lower()
        self.esls = []
        self.data = dict()
        self.data["ap"] = dict()
        self.data["ap"]["ip"] =  self._host
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
        self._attempted_tag_type_refreshes = set()
        self._pending_states = {}
        thread = Thread(target=self.connection_thread)
        self._hass.async_create_task(self._init_tag_manager())
        thread.start()
        self.online = True

    async def _init_tag_manager(self) -> None:
        """Initialize tag manager."""
        self._tag_manager = await get_tag_types_manager(self._hass)
        self.tag_manager_initialized.set()  # Signal that initialization is complete

    async def _try_refresh_hw_type(self, hw_type: int) -> bool:
        """Try to refresh tag types from GitHub for a missing hardware type."""
        if hw_type in self._attempted_tag_type_refreshes:
            return False

        self._attempted_tag_type_refreshes.add(hw_type)
        _LOGGER.info(f"Attempting to refresh tag types for unknown hardware type {hw_type}")

        # Force a refresh of tag types
        manager = self._tag_manager
        manager._last_update = None
        await manager.ensure_types_loaded()

        # Check if the hardware type is now available
        success = manager.is_in_hw_map(hw_type)
        if success:
            _LOGGER.info(f"Successfully retrieved definition for hardware type {hw_type}")

            # Apply any pending states for this hardware type
            if hw_type in self._pending_states:
                for state_info in self._pending_states[hw_type]:
                    await self._apply_tag_state(state_info)
                del self._pending_states[hw_type]
        else:
            _LOGGER.warning(
                f"Hardware type {hw_type} not found in definitions, even after refresh attempt. "
                f"Please report this to the OpenEPaperLink project if this is a valid tag type."
            )
        return success

    async def _set_tag_state(self, tag_mac: str, hw_type: int, tag_name: str) -> None:
        """Set up the entity state for a tag."""
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

    async def _apply_tag_state(self, state_info: dict) -> None:
        """Apply a pending tag state."""
        await self._set_tag_state(
            state_info["tagmac"],
            state_info["hwType"],
            state_info["tagname"]
        )

    def _store_tag_data(self, tag_mac: str, tag_data: dict, tag_name: str) -> None:
        """Store tag data in the hub's data dictionary."""
        self.data[tag_mac] = {
            "temperature": tag_data.get('temperature'),
            "rssi": tag_data.get('RSSI'),
            "battery": tag_data.get('batteryMv'),
            "lqi": tag_data.get('LQI'),
            "hwtype": tag_data.get('hwType'),
            "hwstring": self._tag_manager.get_hw_string(tag_data.get('hwType')),
            "contentmode": tag_data.get('contentMode'),
            "lastseen": tag_data.get('lastseen'),
            "nextupdate": tag_data.get('nextupdate'),
            "nextcheckin": tag_data.get('nextcheckin'),
            "pending": tag_data.get('pending'),
            "wakeupReason": tag_data.get('wakeupReason'),
            "capabilities": tag_data.get('capabilities'),
            "external": tag_data.get('isexternal'),
            "alias": tag_data.get('alias'),
            "hashv": tag_data.get('hash'),
            "modecfgjson": tag_data.get('modecfgjson'),
            "rotate": tag_data.get('rotate'),
            "lut": tag_data.get('lut'),
            "ch": tag_data.get('ch'),
            "ver": tag_data.get('ver'),
            "tagname": tag_name
        }

    def on_message(self, ws, message) -> None:
        # Wait for the tag manager to initialize if needed
        if not self.tag_manager_initialized.is_set():
            future = asyncio.run_coroutine_threadsafe(self.tag_manager_initialized.wait(), self.eventloop)
            future.result()

        data = json.loads('{' + message.split("{", 1)[-1])
        if 'sys' in data:
            # Handle system data
            sys = data.get('sys')
            self._handle_sys_data(sys)
        elif 'tags' in data:
            tag = data.get('tags')[0]
            tagmac = tag.get('mac')

            # Handle tag data asynchronously
            asyncio.run_coroutine_threadsafe(
                self._handle_tag_data(tagmac, tag),
                self.eventloop
            )

            # Handle tag registration if needed
            if tagmac not in self.esls:
                self.esls.append(tagmac)
                asyncio.run_coroutine_threadsafe(
                    self.reloadcfgett(),
                    self.eventloop
                )

            # Fire wakeup event
            lut = {0: "TIMED", 1: "BOOT", 2: "GPIO", 3: "NFC", 4: "BUTTON1", 5: "BUTTON2",
                   252: "FIRSTBOOT", 253: "NETWORK_SCAN", 254: "WDT_RESET"}
            event_data = {
                "device_id": tagmac,
                "type": lut[tag.get('wakeupReason')],
            }
            self._hass.bus.fire(DOMAIN + "_event", event_data)

    def _handle_sys_data(self, sys: dict) -> None:
        """Handle system data updates."""
        self.data["ap"] = {
            "ip": self._host,
            "systime": sys.get('currtime'),
            "heap": sys.get('heap'),
            "recordcount": sys.get('recordcount'),
            "dbsize": sys.get('dbsize'),
            "littlefsfree": sys.get('littlefsfree'),
            "rssi": sys.get('rssi'),
            "apstate": sys.get('apstate'),
            "runstate": sys.get('runstate'),
            "temp": sys.get('temp'),
            "wifistatus": sys.get('wifistatus'),
            "wifissid": sys.get('wifissid')
        }
        self._hass.states.set(
            DOMAIN + ".ip",
            self._host,
            {
                "icon": "mdi:ip",
                "friendly_name": "AP IP",
                "should_poll": False
            }
        )

    async def _handle_tag_data(self, tagmac: str, tag_data: dict) -> None:
        """Handle incoming tag data and manage hardware type verification."""
        hwType = tag_data.get('hwType')
        tagname = tag_data.get('alias') or tagmac

        # Store basic tag data regardless of hardware type status
        self._store_tag_data(tagmac, tag_data, tagname)

        # Check if we need to handle the hardware type
        if not self._tag_manager.is_in_hw_map(hwType):
            # Try refreshing if we haven't attempted for this type before
            if hwType not in self._attempted_tag_type_refreshes:
                state_info = {
                    "tagmac": tagmac,
                    "hwType": hwType,
                    "tagname": tagname,
                }

                # Store the pending state
                if hwType not in self._pending_states:
                    self._pending_states[hwType] = []
                self._pending_states[hwType].append(state_info)

                # Attempt refresh
                success = await self._try_refresh_hw_type(hwType)
                if not success:
                    return  # Warning will have been logged by _try_refresh_hw_type

        # If we have the hardware type definition, set up the entity
        if self._tag_manager.is_in_hw_map(hwType):
            await self._set_tag_state(tagmac, hwType, tagname)

    # log websocket errors
    def on_error(self,ws, error) -> None:
        _LOGGER.debug("Websocket error, most likely on_message crashed")
        _LOGGER.debug(error)
    def on_close(self, ws, close_status_code, close_msg) -> None:
        _LOGGER.warning(
            f"Websocket connection lost to url={ws.url} "
            f"(close_status_code={close_status_code}, close_msg={close_msg}), "
            f"trying to reconnect every {_RECONNECT_SECONDS} seconds")
    #we could do something here
    def on_open(self,ws) -> None:
        _LOGGER.debug("WS started")

    # starts the websocket
    def connection_thread(self) -> None:
        while True:
            try:
                ws_url = "ws://" + self._host + "/ws"
                ws = websocket.WebSocketApp(
                    ws_url, on_message=self.on_message, on_error=self.on_error,
                    on_close=self.on_close, on_open=self.on_open)
                ws.run_forever(reconnect=_RECONNECT_SECONDS)
            except Exception as e:
                _LOGGER.exception(e)

            _LOGGER.error(f"open_epaper_link WebSocketApp crashed, reconnecting in {_RECONNECT_SECONDS} seconds")
            time.sleep(_RECONNECT_SECONDS)

    #we should do more here
    async def test_connection(self) -> bool:
        return True
    #reload is reqired to add new entities
    async def reloadcfgett(self) -> bool:
        await self._hass.config_entries.async_unload_platforms(self._cfgenty, ["sensor","camera","button"])
        await self._hass.config_entries.async_forward_entry_setups(self._cfgenty, ["sensor","camera","button"])
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
