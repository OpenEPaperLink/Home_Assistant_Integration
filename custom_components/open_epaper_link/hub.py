import asyncio
from datetime import datetime, timezone
from typing import Final

import json

import aiohttp
import async_timeout
import websockets
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, CALLBACK_TYPE, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
import logging

_LOGGER: Final = logging.getLogger(__name__)

from .const import DOMAIN
from .tag_types import get_tag_types_manager, get_hw_string

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_tags"
RECONNECT_INTERVAL = 30
SAVE_DELAY = 10
WEBSOCKET_TIMEOUT = 60
CONNECTION_TIMEOUT = 10


SIGNAL_TAG_UPDATE = f"{DOMAIN}_tag_update"
SIGNAL_AP_UPDATE = f"{DOMAIN}_ap_update"

class Hub:

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the Hub."""
        self.hass = hass
        self.entry = entry
        self.host = entry.data["host"]
        self._ws_task: asyncio.Task | None = None
        self._ws_client: websockets.WebSocketClientProtocol | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._shutdown = asyncio.Event()
        self._session = async_get_clientsession(hass)
        self._shutdown_handler: CALLBACK_TYPE | None = None
        self._shutdown = asyncio.Event()
        self._store = Store[dict[str, any]](
            hass, STORAGE_VERSION, STORAGE_KEY, private=True, atomic_writes=True
        )
        self._data: dict[str, dict] = {}
        self._ap_data: dict[str, any] = {}
        self.ap_config: dict[str, any] = {}
        self._known_tags: set[str] = set()

        self._unsub_callbacks: list[CALLBACK_TYPE] = []
        self.online = False
        self._reconnect_task: asyncio.Task | None = None
        self._tag_manager = None
        self._tag_manager_ready = asyncio.Event()

    async def async_setup_initial(self) -> bool:
        """Set up hub without WebSocket connection."""
        try:
            # Load stored data
            stored = await self._store.async_load()
            if stored:
                self._data = stored.get("tags", {})
                self._known_tags = set(self._data.keys())
                _LOGGER.debug("Restored %d tags from storage", len(self._known_tags))

            # Initialize tag manager
            self._tag_manager = await get_tag_types_manager(self.hass)
            self._tag_manager_ready.set()

            # Register shutdown handler only once
            if self._shutdown_handler is None:
                self._shutdown_handler = self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STOP,
                    self._handle_shutdown
                )

            return True

        except Exception as err:
            _LOGGER.error("Failed to set up hub: %s", err)
            return False
    async def async_start_websocket(self) -> bool:
        """Start WebSocket connection."""
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

        # Clear the shutdown flag when starting
        self._shutdown.clear()

        self._ws_task = self.hass.async_create_task(
            self._websocket_handler(),
            "open_epaper_link_websocket"
        )

        # Wait briefly to ensure connection is established
        try:
            async with async_timeout.timeout(CONNECTION_TIMEOUT):
                while not self.online and not self._shutdown.is_set():
                    await asyncio.sleep(0.1)

                if not self.online:
                    _LOGGER.error("Failed to establish WebSocket connection")
                    return False

                _LOGGER.info("WebSocket connection established successfully")
                return True

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout while establishing WebSocket connection")
            return False


    async def _handle_shutdown(self, _) -> None:
        """Handle shutdown event."""
        _LOGGER.debug("Processing shutdown for OpenEPaperLink hub")
        await self.shutdown()
        self._shutdown_handler = None

    async def shutdown(self) -> None:
        """Shut down the hub."""
        _LOGGER.debug("Shutting down OpenEPaperLink hub")

        # Set shutdown flag first
        self._shutdown.set()

        # Cancel WebSocket task
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

        # Clean up other callbacks
        while self._unsub_callbacks:
            try:
                unsub = self._unsub_callbacks.pop()
                unsub()
            except Exception as err:
                _LOGGER.debug("Error cleaning up callback: %s", err)

        # Mark as offline
        self.online = False
        async_dispatcher_send(self.hass, f"{DOMAIN}_connection_status", False)

        _LOGGER.debug("OpenEPaperLink hub shutdown complete")

    async def _websocket_handler(self) -> None:
        """Handle websocket connection and messages."""
        while not self._shutdown.is_set():
            try:
                ws_url = f"ws://{self.host}/ws"
                async with self._session.ws_connect(ws_url, heartbeat=30) as ws:
                    self.online = True
                    _LOGGER.debug("Connected to websocket at %s", ws_url)
                    async_dispatcher_send(self.hass, f"{DOMAIN}_connection_status", True)

                    while not self._shutdown.is_set():
                        try:
                            msg = await ws.receive()

                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._handle_message(msg.data)
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                _LOGGER.error("WebSocket error: %s", ws.exception())
                                break
                            elif msg.type == aiohttp.WSMsgType.CLOSING:
                                _LOGGER.debug("WebSocket closing")
                                break
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                _LOGGER.debug("WebSocket closed")
                                break
                        except asyncio.CancelledError:
                            _LOGGER.debug("WebSocket task cancelled")
                            raise
                        except Exception as err:
                            _LOGGER.error("Error handling message: %s", err)

            except asyncio.CancelledError:
                _LOGGER.debug("WebSocket connection cancelled")
                raise
            except aiohttp.ClientError as err:
                self.online = False
                _LOGGER.error("WebSocket connection error: %s", err)
                async_dispatcher_send(self.hass, f"{DOMAIN}_connection_status", False)
            except Exception as err:
                self.online = False
                _LOGGER.error("Unexpected WebSocket error: %s", err)
                async_dispatcher_send(self.hass, f"{DOMAIN}_connection_status", False)

            if not self._shutdown.is_set():
                await asyncio.sleep(RECONNECT_INTERVAL)


    def _schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt."""
        async def reconnect():
            await asyncio.sleep(RECONNECT_INTERVAL)
            if not self._shutdown.is_set():
                self._ws_task = self.hass.async_create_task(
                    self._websocket_handler(),
                    f"{DOMAIN}_websocket",
                )

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()

        self._reconnect_task = self.hass.async_create_task(
            reconnect(),
            f"{DOMAIN}_reconnect",
        )

    async def _handle_message(self, message: str) -> None:
        """Process incoming websocket message."""
        try:
            data = json.loads("{" + message.split("{", 1)[-1])

            if "sys" in data:
                _LOGGER.debug("System message: %s", data["sys"])
                await self._handle_system_message(data["sys"])
            elif "tags" in data:
                _LOGGER.debug("Tag message: %s", data["tags"][0])
                await self._handle_tag_message(data["tags"][0])
            elif "logMsg" in data:
                _LOGGER.debug("OEPL Log message: %s", data["logMsg"])
            elif "apitem" in data:
                # Check if this is actually a config change message
                if data.get("apitem", {}).get("type") == "change":
                    await self._handle_ap_config_message(data)
                else:
                    _LOGGER.debug("Ignoring non-change AP message")
            else:
                _LOGGER.debug("Unknown message type: %s", data)

        except json.JSONDecodeError:
            _LOGGER.error("Failed to decode message: %s", message)
        except Exception as err:
            _LOGGER.exception("Error handling message: %s", err)

    @callback
    async def _handle_system_message(self, sys_data: dict) -> None:
        """Process a system message."""
        self._ap_data = {
            "ip": self.host,
            "sys_time": sys_data.get("currtime"),
            "heap": sys_data.get("heap"),
            "record_count": sys_data.get("recordcount"),
            "db_size": sys_data.get("dbsize"),
            "little_fs_free": sys_data.get("littlefsfree"),
            "rssi": sys_data.get("rssi"),
            "ap_state": self._get_ap_state_string(sys_data.get("apstate")),
            "run_state": self._get_ap_run_state_string(sys_data.get("runstate")),
            "temp": sys_data.get("temp"),
            "wifi_status": sys_data.get("wifistatus"),
            "wifi_ssid": sys_data.get("wifissid"),
        }
        async_dispatcher_send(self.hass, SIGNAL_AP_UPDATE)

    @callback
    async def _handle_tag_message(self, tag_data: dict) -> None:
        """Process a tag message."""
        tag_mac = tag_data.get("mac")
        # Fix tag name handling
        tag_name = tag_data.get("alias") or tag_mac
        last_seen = tag_data.get("lastseen")
        next_update = tag_data.get("nextupdate")
        next_checkin = tag_data.get("nextcheckin")
        lqi = tag_data.get("LQI")
        rssi = tag_data.get("RSSI")
        temperature = tag_data.get("temperature")
        battery_mv = tag_data.get("batteryMv")
        pending = tag_data.get("pending")
        hw_type = tag_data.get("hwType")
        hw_string = get_hw_string(hw_type)
        content_mode = tag_data.get("contentMode")
        wakeup_reason = self._get_wakeup_reason_string(tag_data.get("wakeupReason"))
        capabilities = tag_data.get("capabilities")
        hashv = tag_data.get("hash")
        modecfgjson = tag_data.get("modecfgjson")
        is_external = tag_data.get("isexternal")
        rotate = tag_data.get("rotate")
        lut = tag_data.get("lut")
        channel = tag_data.get("ch")
        version = tag_data.get("ver")
        update_count = tag_data.get("updatecount")

        is_new_tag = tag_mac not in self._known_tags

        # Update tag data
        self._data[tag_mac] = {
            "tag_mac": tag_mac,
            "tag_name": tag_name,
            "last_seen": last_seen,
            "next_update": next_update,
            "next_checkin": next_checkin,
            "lqi": lqi,
            "rssi": rssi,
            "temperature": temperature,
            "battery_mv": battery_mv,
            "pending": pending,
            "hw_type": hw_type,
            "hw_string": hw_string,
            "content_mode": self._get_content_mode_string(content_mode),
            "wakeup_reason": wakeup_reason,
            "capabilities": capabilities,
            "hash": hashv,
            "modecfgjson": modecfgjson,
            "is_external": is_external,
            "rotate": rotate,
            "lut": lut,
            "channel": channel,
            "version": version,
            "update_count": update_count
        }

        # Handle new tag discovery
        if is_new_tag:
            self._known_tags.add(tag_mac)
            _LOGGER.debug("Discovered new tag: %s", tag_mac)
            # Fire discovery event before saving
            async_dispatcher_send(self.hass, f"{DOMAIN}_tag_discovered", tag_mac)
            # Save to storage
            await self._store.async_save({
                "tags": self._data
            })

        # Fire state update event
        async_dispatcher_send(self.hass, f"{SIGNAL_TAG_UPDATE}_{tag_mac}")

        # Fire wakeup event if needed
        wakeup_reason = tag_data.get("wakeupReason")
        if wakeup_reason is not None:
            self.hass.bus.async_fire(f"{DOMAIN}_event", {
                "device_id": tag_mac,
                "type": self._get_wakeup_reason_string(wakeup_reason)
            })

    async def _handle_ap_config_message(self, config_data: dict) -> None:
        """Handle AP configuration updates."""
        try:
            if self._shutdown.is_set():
                return

            async with aiohttp.ClientSession() as session:
                async with async_timeout.timeout(10):
                    async with session.get(f"http://{self.host}/get_ap_config") as response:
                        if response.status != 200:
                            _LOGGER.error("Failed to fetch AP config: HTTP %s", response.status)
                            return

                        new_config = await response.json()

                        # Compare with existing config
                        if not hasattr(self, '_last_config_hash'):
                            self._last_config_hash = None

                        # Create hash of new config for comparison
                        new_hash = hash(frozenset(new_config.items()))

                        if new_hash != self._last_config_hash:
                            self.ap_config = new_config
                            self._last_config_hash = new_hash
                            _LOGGER.debug("AP config updated: %s", self.ap_config)
                            async_dispatcher_send(self.hass, f"{DOMAIN}_ap_config_update")
                        else:
                            _LOGGER.debug("AP config unchanged, skipping update")

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout fetching AP config")
        except Exception as err:
            _LOGGER.error("Failed to fetch AP config: %s", err)

    @staticmethod
    def _get_wakeup_reason_string(reason: int) -> str:
        """Convert wakeup reason code to string."""
        reasons = {
            0: "TIMED",
            1: "BOOT",
            2: "GPIO",
            3: "NFC",
            4: "BUTTON1",
            5: "BUTTON2",
            252: "FIRSTBOOT",
            253: "NETWORK_SCAN",
            254: "WDT_RESET"
        }
        return reasons.get(reason, f"UNKNOWN_{reason}")

    @staticmethod
    def _get_ap_state_string(state: int) -> str:
        """Convert AP state code to string."""
        states = {
            0: "Offline",
            1: "Online",
            2: "Flashing",
            3: "Waiting for reset",
            4: "Requires power cycle",
            5: "Failed",
            6: "Coming online",
            7: "No radio"
        }
        return states.get(state, f"Unknown: {state}")

    @staticmethod
    def _get_ap_run_state_string(state: int) -> str:
        """Convert AP run state code to string."""
        states = {
            0: "Stopped",
            1: "Paused",
            2: "Running",
            3: "Initializing",
        }
        return states.get(state, f"Unknown: {state}")

    @staticmethod
    def _get_content_mode_string(mode: int) -> str:
        """Convert content mode code to string."""
        modes = {
            0: "Not configured",
            1: "Current date",
            2: "Count days",
            3: "Count hours",
            4: "Current weather",
            5: "Firmware update",
            7: "Image URL",
            8: "Weather forecast",
            9: "RSS Feed",
            10: "QR Code",
            11: "Google calendar",
            12: "Remote content",
            14: "Set NFC URL",
            15: "Custom LUT",
            16: "Buienradar",
            18: "Tag Config",
            19: "JSON template",
            20: "Display a copy",
            21: "AP Info",
            22: "Static image",
            23: "Image preload",
            24: "External image",
            25: "Home Assistant",
            26: "Timestamp",
            27: "Dayahead prices",


        }
        return modes.get(mode, f"Unknown: {mode}")

    @property
    def tags(self) -> list[str]:
        """Return list of known tag IDs."""
        return list(self._known_tags)

    def get_tag_data(self, tag_mac: str) -> dict:
        """Get data for specific tag."""
        return self._data.get(tag_mac, {})

    @property
    def ap_status(self) -> dict:
        """Get current AP status."""
        return self._ap_data.copy()

    async def async_update_ap_config(self) -> None:
        """Force update of AP configuration."""
        await self._handle_ap_config_message({"apitem": {"type": "change"}})
