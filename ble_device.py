import asyncio
from homeassistant.components import bluetooth
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.components.light import ColorMode
from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTCharacteristic, BleakGATTServiceCollection
from bleak.exc import BleakDBusError
from bleak_retry_connector import BLEAK_RETRY_EXCEPTIONS as BLEAK_EXCEPTIONS
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakNotFoundError,
    establish_connection,
)
from typing import Any, TypeVar, cast
from collections.abc import Callable
import traceback
import logging
import struct
import zlib
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import datetime
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import io

from .const import DOMAIN

LOGGER = logging.getLogger(__name__)

DEFAULT_ATTEMPTS = 3
BLEAK_BACKOFF_TIME = 0.25
RETRY_BACKOFF_EXCEPTIONS = BleakDBusError

WrapFuncType = TypeVar("WrapFuncType", bound=Callable[..., Any])

class BleAdvDataStruct:
    def __init__(self, data: bytes):
        self.version = data[0]
        self.hw_type = int.from_bytes(data[1:3], byteorder='little')
        self.fw_version = int.from_bytes(data[3:5], byteorder='little')
        self.capabilities = int.from_bytes(data[5:7], byteorder='little')
        self.battery_mv = int.from_bytes(data[7:9], byteorder='little') if len(data) > 7 else 0
        self.counter = data[9] if len(data) > 9 else 0

    def __str__(self):
        return (
            f"Version: {self.version}\n"
            f"Hardware Type: 0x{self.hw_type:04x}\n"
            f"Firmware Version: 0x{self.fw_version:04x}\n"
            f"Capabilities: 0x{self.capabilities:04x}\n"
            f"Battery: {self.battery_mv}mV\n"
            f"Counter: {self.counter}"
        )

def bytearray_to_hex_format(byte_array):
    hex_strings = ["0x{:02x}".format(byte) for byte in byte_array]
    return hex_strings

def retry_bluetooth_connection_error(func: WrapFuncType) -> WrapFuncType:
    async def _async_wrap_retry_bluetooth_connection_error(
        self: "BLEInstance", *args: Any, **kwargs: Any
    ) -> Any:
        attempts = DEFAULT_ATTEMPTS
        max_attempts = attempts - 1

        for attempt in range(attempts):
            try:
                return await func(self, *args, **kwargs)
            except BleakNotFoundError:
                raise
            except RETRY_BACKOFF_EXCEPTIONS as err:
                if attempt >= max_attempts:
                    LOGGER.debug(
                        "%s: %s error calling %s, reach max attempts (%s/%s)",
                        self.name,
                        type(err),
                        func,
                        attempt,
                        max_attempts,
                        exc_info=True,
                    )
                    raise
                LOGGER.debug(
                    "%s: %s error calling %s, backing off %ss, retrying (%s/%s)...",
                    self.name,
                    type(err),
                    func,
                    BLEAK_BACKOFF_TIME,
                    attempt,
                    max_attempts,
                    exc_info=True,
                )
                await asyncio.sleep(BLEAK_BACKOFF_TIME)
            except BLEAK_EXCEPTIONS as err:
                if attempt >= max_attempts:
                    LOGGER.debug(
                        "%s: %s error calling %s, reach max attempts (%s/%s): %s",
                        self.name,
                        type(err),
                        func,
                        attempt,
                        max_attempts,
                        err,
                        exc_info=True,
                    )
                    raise
                LOGGER.debug(
                    "%s: %s error calling %s, retrying  (%s/%s)...: %s",
                    self.name,
                    type(err),
                    func,
                    attempt,
                    max_attempts,
                    err,
                    exc_info=True,
                )
    return cast(WrapFuncType, _async_wrap_retry_bluetooth_connection_error)

class BLEInstance:
    def __init__(self, address, hass) -> None:
        LOGGER.debug("Initializing BLEInstance for address %s", address)
        self.loop = asyncio.get_running_loop()
        self._mac = address
        self._delay = 15
        self._hass = hass
        self._device: BLEDevice | None = None
        self._device = bluetooth.async_ble_device_from_address(self._hass, address)
        if not self._device:
            LOGGER.error("Could not find device with address %s", address)
            raise ConfigEntryNotReady(
                f"You need to add bluetooth integration (https://www.home-assistant.io/integrations/bluetooth) or couldn't find a nearby device with address: {address}"
            )
        LOGGER.debug("Found device: %s", self._device)
        self._connect_lock: asyncio.Lock = asyncio.Lock()
        self._client: BleakClientWithServiceCache | None = None
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._cached_services: BleakGATTServiceCollection | None = None
        self._expected_disconnect = False
        self._is_on = None
        self._hs_color = (0, 0)
        self._brightness = 255
        self._color_mode = ColorMode.HS
        self._write_uuid = None
        self._turn_on_cmd = None
        self._turn_off_cmd = None
        self._command_type = "TYPE2"
        self._model = None
        self._on_update_callbacks = []
        self._packets = []
        self._packet_index = 0
        self._img_array = b""
        self._img_array_len = 0
        self._shutdown = False
        self._adv_data = None

        self._coordinator_data = {
            "battery_mv": None,
            "hw_type": None,
            "fw_version": None,
            "capabilities": None,
            "counter": None,
            "rssi": None,
        }
        
        self.coordinator = DataUpdateCoordinator(
            hass,
            LOGGER,
            name=f"{self._device.name} Coordinator",
            update_method=self._async_update,
            update_interval=datetime.timedelta(seconds=30),
        )
        
        self._parse_adv_data()
        LOGGER.debug(
            "Initialized BLEInstance for device %s: ModelNo %s, MAC: %s, Delay: %s",
            self._device.name,
            self._model,
            self._mac,
            self._delay
        )
    
    def _parse_adv_data(self):
        """Parse the advertising data from live scan results."""
        try:
            service_info = bluetooth.async_last_service_info(self._hass, self._mac, connectable=True)
            if not service_info or not service_info.manufacturer_data or 4919 not in service_info.manufacturer_data:
                LOGGER.debug("No valid advertising data found for device %s", self._mac)
                return

            self._adv_data = BleAdvDataStruct(service_info.manufacturer_data[4919])
            self._coordinator_data.update({
                "battery_mv": self._adv_data.battery_mv,
                "hw_type": self._adv_data.hw_type,
                "fw_version": self._adv_data.fw_version,
                "capabilities": self._adv_data.capabilities,
                "counter": self._adv_data.counter,
                "rssi": service_info.rssi,
            })
            LOGGER.debug("Updated coordinator data for device %s: %s", self._mac, self._coordinator_data)
        except Exception as err:
            LOGGER.error("Error parsing advertising data for device %s: %s", self._mac, err)

    @property
    def coordinator_data(self) -> dict:
        """Return the coordinator data."""
        return self._coordinator_data

    @property
    def device_info(self) -> dict:
        """Return device info for the device registry."""
        info = {
            "identifiers": {(DOMAIN, self._mac)},
            "name": self.name,
            "manufacturer": "OpenEPaperLink",
            "model": f"HW: 0x{self._adv_data.hw_type:04x}" if self._adv_data else "Unknown",
            "sw_version": f"FW: 0x{self._adv_data.fw_version:04x}" if self._adv_data else "Unknown",
            "hw_version": f"0x{self._adv_data.hw_type:04x}" if self._adv_data else "Unknown",
        }
        LOGGER.debug("Device info for %s: %s", self._mac, info)
        return info

    @property
    def battery_level(self) -> int:
        """Return the battery level in percentage."""
        if not self._adv_data:
            LOGGER.debug("No advertising data available for battery level of %s", self._mac)
            return None
        try:
            voltage = self._adv_data.battery_mv / 1000.0
            min_voltage = 2.6
            max_voltage = 3.2
            voltage_range = max_voltage - min_voltage
            percentage = min(100, max(0, int((voltage - min_voltage) * 100 / voltage_range)))
            LOGGER.debug("Battery calculation for %s: %.3fV -> %d%%", 
                        self._mac, voltage, percentage)
            return percentage
        except Exception as e:
            LOGGER.error("Error calculating battery level for %s: %s", self._mac, e)
            return None

    @property
    def capabilities(self) -> dict:
        """Return device capabilities."""
        if not self._adv_data:
            LOGGER.debug("No advertising data available for capabilities of %s", self._mac)
            return {}
        capabilities = {
            "version": self._adv_data.version,
            "hw_type": self._adv_data.hw_type,
            "fw_version": self._adv_data.fw_version,
            "capabilities": self._adv_data.capabilities,
            "battery_mv": self._adv_data.battery_mv,
            "counter": self._adv_data.counter
        }
        LOGGER.debug("Capabilities for %s: %s", self._mac, capabilities)
        return capabilities

    async def _write(self, data: bytearray):
        """Send command to device and read response."""
        await self._ensure_connected()
        await self._write_while_connected(data)

    async def _write_while_connected(self, data: bytearray):
        LOGGER.debug(f"Writing data to {self.name}: {data}")
        await self._client.write_gatt_char(self._write_uuid, data, False)

    def _notification_handler(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle BLE notifications from the device."""
        LOGGER.debug(f"BLE Notification raw: {self.name}: {bytearray_to_hex_format(data)}")
        response_code = data[:2].hex().upper()
        if response_code == "00C6":
            LOGGER.debug("Received block request")
            block_id = data[11]
            asyncio.create_task(self.send_block_data(block_id))
        elif response_code == "00C4":
            LOGGER.debug("Block part acknowledged")
            asyncio.create_task(self.send_next_block_part())
        elif response_code == "00C5":
            LOGGER.debug("Block part acknowledged")
            if self._packet_index > len(self._packets):
                LOGGER.error("Something went wrong, not so many packets available")
                return
            self._packet_index += 1
            asyncio.create_task(self.send_next_block_part())
        elif response_code == "00C7":
            LOGGER.debug("Image will now be displayed")
        elif response_code == "00C8":
            LOGGER.debug("Image already displayed")
        else:
            LOGGER.debug(f"Unknown response: {response_code}")

    @property
    def mac(self):
        return self._device.address

    @property
    def name(self):
        return self._device.name

    @property
    def firmware_version(self):
        return "123"
    
    @property
    def rssi(self):
        return self._device.rssi

    @property
    def is_on(self):
        return self._is_on

    @property
    def brightness(self):
        return self._brightness

    @property
    def hs_color(self):
        return self._hs_color

    @property
    def color_mode(self):
        return self._color_mode

    async def set_brightness(self, brightness: int):
        LOGGER.debug("Brightness only requested: " + str(brightness))
        LOGGER.debug("Current brightness: " + str(self._brightness))
        if brightness == self._brightness:
            return

    @retry_bluetooth_connection_error
    async def turn_on(self) -> None:
        """Turn on the light and upload current date/time image."""
        if not self._write_uuid:
            raise RuntimeError("Write UUID not set")
            
        # First turn on the light
        await self._write_while_connected(bytes([0x01, 0x01]))
        
        try:
            await self.upload_image(width=128, height=296, multi_color=True, compressed=True)
        except Exception as e:
            LOGGER.error("Failed to upload image: %s", e)
            # Don't raise the error - we want the light to stay on even if image upload fails

    @retry_bluetooth_connection_error
    async def turn_off(self):
        LOGGER.debug("Turn off")
        await self._write(bytearray.fromhex("000100"))
        await self._write(bytearray.fromhex("0000"))
        self._is_on = False

    async def update(self):
        """Update the device state."""
        LOGGER.debug("%s: Update called", self.name)
        try:
            await self._ensure_connected()
            if not self._adv_data:
                LOGGER.debug("No advertising data available, trying to get it from device")
            self._is_on = False
        except Exception as error:
            self._is_on = None
            LOGGER.error("Error getting status: %s", error)
            track = traceback.format_exc()
            LOGGER.debug(track)

    async def _ensure_connected(self) -> None:
        """Ensure connection to device is established."""
        LOGGER.debug(f"{self.name}: Ensure connected")
        if self._connect_lock.locked():
            LOGGER.debug(
                "%s: Connection already in progress, waiting for it to complete",
                self.name,
            )
        if self._client and self._client.is_connected:
            self._reset_disconnect_timer()
            return
        async with self._connect_lock:
            if self._client and self._client.is_connected:
                self._reset_disconnect_timer()
                return
            LOGGER.debug("%s: Connecting", self.name)
            try:
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    self._device,
                    self.name,
                    self._disconnected,
                    cached_services=self._cached_services,
                    ble_device_callback=lambda: self._device,
                )
                LOGGER.debug("%s: Connected", self.name)
                resolved = self._resolve_characteristics(client.services)
                if not resolved:
                    resolved = self._resolve_characteristics(client.services)
                self._cached_services = client.services if resolved else None
                self._client = client
                self._reset_disconnect_timer()
                self._notification_callback = self._notification_handler
                await client.start_notify(self._write_uuid, self._notification_callback)
                LOGGER.debug("%s: Subscribed to notifications", self.name)
            except Exception as e:
                LOGGER.error("%s: Connection failed: %s", self.name, e, exc_info=True)
                raise

    def _resolve_characteristics(self, services: BleakGATTServiceCollection) -> bool:
        """Resolve characteristics."""
        if char := services.get_characteristic("00001337-0000-1000-8000-00805f9b34fb"):
            self._write_uuid = char
            LOGGER.debug("%s: Write UUID: %s", self.name, self._write_uuid)
            return True
        return False

    def _reset_disconnect_timer(self) -> None:
        """Reset disconnect timer."""
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
        self._expected_disconnect = False
        if self._delay is not None and self._delay != 0:
            LOGGER.debug(
                "%s: Configured disconnect from device in %s seconds",
                self.name,
                self._delay,
            )
            self._disconnect_timer = self.loop.call_later(self._delay, self._disconnect)

    def _disconnected(self, client: BleakClientWithServiceCache) -> None:
        """Disconnected callback."""
        if self._expected_disconnect:
            LOGGER.debug("%s: Disconnected from device", self.name)
            return
        LOGGER.warning("%s: Device unexpectedly disconnected", self.name)

    def _disconnect(self) -> None:
        """Disconnect from device."""
        self._disconnect_timer = None
        asyncio.create_task(self._execute_timed_disconnect())

    async def stop(self) -> None:
        """Stop the BLE connection."""
        LOGGER.debug("%s: Stop", self.name)
        await self._execute_disconnect()

    async def _execute_timed_disconnect(self) -> None:
        """Execute timed disconnection."""
        LOGGER.debug("%s: Disconnecting after timeout of %s", self.name, self._delay)
        await self._execute_disconnect()

    async def _execute_disconnect(self) -> None:
        """Execute disconnection."""
        async with self._connect_lock:
            read_char = self._write_uuid
            client = self._client
            self._expected_disconnect = True
            self._client = None
            self._write_uuid = None
            if client and client.is_connected:
                await client.stop_notify(read_char)
                await client.disconnect()
            LOGGER.debug("%s: Disconnected", self.name)

    def local_callback(self):
        return

    def create_image_with_date(self, width, height, multi_color=False, compressed=False):
        """Create a default image with current date/time."""
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        date_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Use default font to avoid blocking I/O
        font = ImageFont.load_default()
        text_size = draw.textbbox((0, 0), date_text, font=font)
        text_xy = (
            (image.width - (text_size[2] - text_size[0])) // 2,
            (image.height - (text_size[3] - text_size[1])) // 2,
        )
        draw.text(text_xy, date_text, fill="black", font=font)
        if multi_color:
            draw.text((text_xy[0], text_xy[1] + 15), "Second Color", fill="red", font=font)
        return self._convert_image_to_bytes(image, multi_color, compressed)

    def _convert_image_to_bytes(self, image: Image.Image, multi_color: bool = False, compressed: bool = False) -> tuple[int, bytes]:
        """Convert a PIL Image to device format.

        Args:
            image: PIL Image to convert
            multi_color: Whether to use multi-color mode
            compressed: Whether to compress the data

        Returns:
            tuple: (data_type, pixel_array)
        """
        pixel_array = np.array(image)
        height, width, _ = pixel_array.shape
        byte_data = []
        byte_data_red = []
        current_byte = 0
        current_byte_red = 0
        bit_position = 7
        for y in range(height):
            for x in range(width):
                r, g, b = pixel_array[y, x]
                luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
                if luminance > 128:
                    current_byte |= (1 << bit_position)
                elif r > 170:
                    current_byte_red |= (1 << bit_position)
                bit_position -= 1
                if bit_position < 0:
                    byte_data.append(~current_byte & 0xFF)
                    byte_data_red.append(current_byte_red)
                    current_byte = 0
                    current_byte_red = 0
                    bit_position = 7
        if bit_position != 7:
            byte_data.append(~current_byte & 0xFF)
            byte_data_red.append(current_byte_red)
        bpp_array = bytearray(byte_data)
        if multi_color:
            bpp_array += bytearray(byte_data_red)
        if compressed:
            LOGGER.debug("Doing compression")
            buffer = bytearray(6)
            buffer[0] = 6
            buffer[1] = width & 0xFF
            buffer[2] = (width >> 8) & 0xFF
            buffer[3] = height & 0xFF
            buffer[4] = (height >> 8) & 0xFF
            buffer[5] = 0x02 if multi_color else 0x01
            buffer += bpp_array
            the_compressor = zlib.compressobj(wbits=12)
            compressed_data = the_compressor.compress(buffer)
            compressed_data += the_compressor.flush()
            return 0x30, struct.pack('<I', len(buffer)) + compressed_data
        return 0x21 if multi_color else 0x20, bpp_array

    def crc32(self, input_data):
        table = []
        polynomial = 0xEDB88320
        for i in range(256):
            crc = i
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ polynomial
                else:
                    crc >>= 1
            table.append(crc)
        crc = 0xFFFFFFFF
        for byte in input_data:
            table_index = (crc ^ byte) & 0xFF
            crc = (crc >> 8) ^ table[table_index]
        return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF

    def create_data_info(self, checksum, data_ver, data_size, data_type, data_type_argument, next_check_in):
        return struct.pack(
            "<BQIBBH",
            checksum,
            data_ver,
            data_size,
            data_type,
            data_type_argument,
            next_check_in,
        )

    def create_block_part(self, block_id, part_id, data):
        max_data_size = 230
        data_length = len(data)
        if data_length > max_data_size:
            raise ValueError("Data length exceeds maximum allowed size for a packet.")
        buffer = bytearray(3 + max_data_size)
        buffer[1] = block_id & 0xFF
        buffer[2] = part_id & 0xFF
        buffer[3:3 + data_length] = data
        buffer[0] = sum(buffer[1:3 + data_length]) & 0xFF
        return buffer

    @retry_bluetooth_connection_error
    async def upload_image(self, width=184, height=384, multi_color=True, compressed=True, image_data=None):
        """Upload an image to the device.

        Args:
            width: Image width
            height: Image height
            multi_color: Whether to use multi-color mode
            compressed: Whether to compress the data
            image_data: Optional JPEG image data to use instead of default image
        """
        LOGGER.debug("Starting image upload")
        
        if image_data:
            # Convert JPEG to PIL Image
            image = Image.open(io.BytesIO(image_data))
            # Resize to device dimensions
            image = image.resize((width, height), Image.Resampling.LANCZOS)
            data_type, pixel_array = self._convert_image_to_bytes(image, multi_color, compressed)
        else:
            # Use default date/time image
            data_type, pixel_array = self.create_image_with_date(width, height, multi_color, compressed)
            
        LOGGER.debug(f"DataType: {data_type:0x} DataLen: {len(pixel_array)}")
        
        self._img_array = pixel_array
        self._img_array_len = len(self._img_array)
        LOGGER.debug(f"Sending image of size {self._img_array_len} bytes")
        
        data_info = self.create_data_info(255, self.crc32(self._img_array), self._img_array_len, data_type, 0, 0)
        await self._write(bytes.fromhex("0064") + data_info)

    async def send_block_data(self, block_id):
        LOGGER.debug("Building block id: %s", block_id)
        block_size = 4096
        block_start = block_id * block_size
        block_end = block_start + block_size
        block_data = self._img_array[block_start:block_end]
        crcBlock = sum(block_data[0:len(block_data)]) & 0xffff
        buffer = bytearray(4)
        buffer[0] = len(block_data) & 0xff
        buffer[1] = (len(block_data) >> 8) & 0xff
        buffer[2] = crcBlock & 0xff
        buffer[3] = (crcBlock >> 8) & 0xff
        block_data = buffer + block_data
        LOGGER.debug(f"Block data length: {len(block_data)} bytes")
        packet_count = (len(block_data) + 229) // 230
        self._packets = []
        for i in range(packet_count):
            start = i * 230
            end = start + 230
            slice_data = block_data[start:end]
            packet = self.create_block_part(block_id, i, slice_data)
            self._packets.append(packet)
        LOGGER.debug(f"Total packets created: {len(self._packets)}")
        self._packet_index = 0
        if self._packets:
            await self.send_next_block_part()
        else:
            LOGGER.error("No packets created for block %d", block_id)

    async def send_next_block_part(self):
        if not self._packets:
            LOGGER.error("No packets available to send")
            return
            
        if self._packet_index >= len(self._packets):
            LOGGER.error("Packet index %d out of range (total packets: %d)", 
                        self._packet_index, len(self._packets))
            return
            
        LOGGER.debug("Sending packet %d of %d", self._packet_index + 1, len(self._packets))
        await self._write(bytes.fromhex("0065") + self._packets[self._packet_index])

    async def _async_update(self):
        """Update the coordinator data."""
        try:
            # Parse advertising data to update coordinator data
            self._parse_adv_data()
            
            # Notify all listeners of the update
            for callback in self._on_update_callbacks:
                callback()
                
            return self._coordinator_data
        except Exception as err:
            LOGGER.error("Error updating BLE device data: %s", err)
            return None

    async def async_add_listener(self, update_callback, context=None):
        """Add a listener for coordinator updates.
        
        Args:
            update_callback: The callback to call when data is updated
            context: Optional context for the callback
        """
        if not hasattr(self, '_listeners'):
            self._listeners = []
        self._listeners.append((update_callback, context))

    async def async_remove_listener(self, update_callback, context=None):
        """Remove a listener for coordinator updates.
        
        Args:
            update_callback: The callback to remove
            context: Optional context for the callback
        """
        if hasattr(self, '_listeners'):
            self._listeners = [(cb, ctx) for cb, ctx in self._listeners 
                             if cb != update_callback or ctx != context]

    async def async_request_refresh(self):
        """Request a refresh of the coordinator data."""
        await self._async_update()
        if hasattr(self, '_listeners'):
            for callback, context in self._listeners:
                await callback(context)
