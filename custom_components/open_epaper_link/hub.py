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
from threading import Thread
from typing import Any
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr
from .const import DOMAIN
_LOGGER: Final = logging.getLogger(__name__)
#Hub class for handeling communication
class Hub:
    #the init function starts the tread for all other communication
    def __init__(self, hass: HomeAssistant, host: str) -> None:
        self._host = host
        self._hass = hass
        self._name = host
        self._id = host.lower()
        self.esls = []
        thread = Thread(target=self.establish_connection)
        thread.start()
        self.online = True
    #parses websocket messages
    def on_message(self,ws, message) -> None:
        data = json.loads(message)
        if 'sys' in data:
            sys = data.get('sys')
            systime = sys.get('currtime')
            self._hass.states.set(DOMAIN + ".lastsl", systime,{"icon": "mdi:clock-outline","friendly_name": "Last Syslog MSG","should_poll": False})
            self._hass.states.set(DOMAIN + ".ip", self._host,{"icon": "mdi:ip","friendly_name": "AP IP","should_poll": False})
        elif 'tags' in data:
            tag = data.get('tags')[0]
            tagmac = tag.get('mac')
            lastseen = tag.get('lastseen')
            nextupdate = tag.get('nextupdate')
            nextcheckin = tag.get('nextcheckin')
            LQI = tag.get('LQI')
            RSSI = tag.get('RSSI')
            temperature = tag.get('temperature')
            batteryMv = tag.get('batteryMv')
            pending = tag.get('pending')
            hwType = tag.get('hwType')
            contentMode = tag.get('contentMode')
            #this needs to be improved
            self._hass.states.set(DOMAIN + "." + tagmac + "lastseen", lastseen,{"icon": "mdi:clock-outline","friendly_name": "Last seen","should_poll": False})
            self._hass.states.set(DOMAIN + "." + tagmac + "nextupdate", nextupdate,{"icon": "mdi:clock-outline","friendly_name": "Next Update","should_poll": False})
            self._hass.states.set(DOMAIN + "." + tagmac + "nextcheckin", nextcheckin,{"icon": "mdi:clock-outline","friendly_name": "Next Checkin","should_poll": False})
            self._hass.states.set(DOMAIN + "." + tagmac + "lqi", LQI,{"icon": "mdi:network-strength-1","friendly_name": "Link quality index","should_poll": False})
            self._hass.states.set(DOMAIN + "." + tagmac + "rssi", RSSI,{"icon": "mdi:network-strength-1","friendly_name": "RSSI","device_class": "signal_strength","unit_of_measurement": "dB","should_poll": False})
            self._hass.states.set(DOMAIN + "." + tagmac + "temperature", temperature,{"icon": "mdi:thermometer","friendly_name": "Temperature","device_class": "temperature","unit_of_measurement": "°C","should_poll": False})
            self._hass.states.set(DOMAIN + "." + tagmac + "battery", batteryMv / 1000,{"icon": "mdi:battery","friendly_name": "Battery Voltage","device_class": "voltage","unit_of_measurement": "V","should_poll": False})
            self._hass.states.set(DOMAIN + "." + tagmac + "pending", pending,{"icon": "mdi:fullscreen","friendly_name": "Pending content","should_poll": False})
            self._hass.states.set(DOMAIN + "." + tagmac + "hwtype", hwType,{"icon": "mdi:fullscreen","friendly_name": "Hardware Type","should_poll": False})
            self._hass.states.set(DOMAIN + "." + tagmac + "contentMode", contentMode,{"icon": "mdi:fullscreen","friendly_name": "Content mode","should_poll": False})
            #maintains a list of all tags, new entetys should be generated here
            if tagmac not in self.esls:
                self.esls.append(tagmac)
        elif 'errMsg' in data:
            ermsg = data.get('errMsg');
        elif 'logMsg' in data:
            logmsg = data.get('logMsg');
        else:
            _LOGGER.warning("Unknown msg")
            _LOGGER.warning(data)
    #log websocket errors
    def on_error(self,ws, error) -> None:
        _LOGGER.warning("Websocket error")
        _LOGGER.warning(error)
    #try to reconnect after 5 munutes
    def on_close(self,ws, error, a) -> None:
        _LOGGER.warning("Websocket connection lost")
        print("Connection lost")
        print("Waiting 300 seconds")
        time.sleep(300)
        self.establish_connection()
    #we could do smething here
    def on_open(self,ws) -> None:
        time.sleep(1)
    #starts the websocket
    def establish_connection(self) -> None:
        ws_url = "ws://" + self._host + "/ws"
        ws = websocket.WebSocketApp(ws_url,on_message=self.on_message,on_error=self.on_error,on_close=self.on_close,on_open=self.on_open)
        ws.run_forever()
        _LOGGER.warning("This should not happen")
    #we should do more here
    async def test_connection(self) -> bool:
        return True
