"""BLE utilities for OpenEPaperLink integration.

Implements direct Bluetooth communication with OEPL devices using the official protocol.
"""
from __future__ import annotations

import asyncio
import logging
import struct
import zlib
import io
from functools import wraps
from typing import Dict
from dataclasses import dataclass
from datetime import datetime, timezone
from bleak import BleakClient
from bleak_retry_connector import establish_connection, BleakClientWithServiceCache, BleakOutOfConnectionSlotsError
from habluetooth.scanner import BleakError

from homeassistant.components import bluetooth
from PIL import Image
import numpy as np

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from .const import (
    SERVICE_UUID, MANUFACTURER_ID, CMD_INIT, CMD_GET_DISPLAY_INFO,
    CMD_LED_ON, CMD_LED_OFF, CMD_LED_OFF_FINAL, CMD_SET_CLOCK_MODE, CMD_DISABLE_CLOCK_MODE,
    BLEResponse, BLECommand, BLEDataType,
    BLE_BLOCK_SIZE, BLE_MAX_PACKET_DATA_SIZE, BLE_MIN_RESPONSE_LENGTH
)

_LOGGER = logging.getLogger(__name__)

# Per-device connection locks to prevent conflicts
_device_locks: Dict[str, asyncio.Lock] = {}

@dataclass
class DeviceMetadata:
    """Device metadata from BLE interrogation."""
    hw_type: int
    fw_version: int
    width: int
    height: int
    color_support: str
    rotatebuffer: int


class BLEError(Exception):
    """Base BLE operation error."""
    pass


class BLEConnectionError(BLEError):
    """Connection to device failed."""
    pass


class BLEProtocolError(BLEError):
    """Protocol communication error."""
    pass


class BLETimeoutError(BLEError):
    """Operation timed out."""
    pass


class BLEConnection:
    """Context manager for BLE connections with OEPL protocol support."""
    
    def __init__(self, hass: HomeAssistant, mac_address: str):
        self.hass = hass
        self.mac_address = mac_address
        self.client: BleakClient | None = None
        self.write_char = None
        self._response_queue = asyncio.Queue()
        self._notification_active = False
        
    async def __aenter__(self):
        """Establish BLE connection and initialize OEPL BLE protocol."""
        try:
            device = bluetooth.async_ble_device_from_address(
                self.hass, self.mac_address, connectable=True
            )
            if not device:
                raise BLEConnectionError(f"Device {self.mac_address} not found")
                
            self.client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                f"BLE-{self.mac_address}",
                self._disconnected_callback,
                timeout=15.0,
            )
            
            # Resolve OEPL service characteristic
            if not self._resolve_characteristic():
                await self.client.disconnect()
                raise BLEConnectionError("Could not resolve BLE characteristic")
            
            # Enable notifications for protocol responses
            await self.client.start_notify(self.write_char, self._notification_callback)
            self._notification_active = True
            
            # Send initialization command as required by protocol
            await self._write_raw(CMD_INIT)
            await asyncio.sleep(2.0)  # Wait as specified in protocol
                
            return self

        except BleakOutOfConnectionSlotsError as e:
            if self.client and self.client.is_connected:
                if self._notification_active:
                    try:
                        await self.client.stop_notify(self.write_char)
                    except Exception:
                        _LOGGER.debug("Failed to stop notifications during cleanup")
                await self.client.disconnect()
            raise BLEConnectionError(
                f"No available Bluetooth connection slots for {self.mac_address}. "
                f"Add more ESPHome Bluetooth proxies near this device or wait for existing connections to free up. "
                f"Details: {e}"
            )
        except (BleakError, asyncio.TimeoutError) as e:
            if self.client and self.client.is_connected:
                if self._notification_active:
                    try:
                        await self.client.stop_notify(self.write_char)
                    except Exception:
                        _LOGGER.debug("Failed to stop notifications during cleanup")
                await self.client.disconnect()
            raise BLEConnectionError(f"Failed to connect to {self.mac_address}: {e}")
            
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up BLE connection."""
        if self.client and self.client.is_connected:
            if self._notification_active:
                try:
                    await self.client.stop_notify(self.write_char)
                except Exception:
                    _LOGGER.debug("Failed to stop notifications during disconnect")
            await self.client.disconnect()
            
    def _resolve_characteristic(self) -> bool:
        """Resolve BLE characteristic using simplified pattern."""
        try:
            if not self.client or not self.client.services:
                return False
                
            # Find the OEPL service characteristic
            char = self.client.services.get_characteristic(SERVICE_UUID)
            if char:
                self.write_char = char
                return True
                
            _LOGGER.error("Could not find characteristic %s", SERVICE_UUID)
            return False
            
        except Exception as e:
            _LOGGER.error("Error resolving characteristic: %s", e)
            return False
    
    def _notification_callback(self, sender, data: bytearray) -> None:
        """Handle notification from device."""
        try:
            self._response_queue.put_nowait(bytes(data))
        except asyncio.QueueFull:
            _LOGGER.warning("Response queue full, dropping notification")
    
    async def _write_raw(self, data: bytes) -> None:
        """Write raw command to device."""
        if not self.write_char:
            raise BLEProtocolError("Write characteristic not available")
            
        await self.client.write_gatt_char(self.write_char, data, response=False)
        
    async def write_command_with_response(self, command: bytes, timeout: float = 10.0) -> bytes:
        """Write command and wait for response."""
        # Clear any pending responses
        while not self._response_queue.empty():
            try:
                self._response_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        
        await self._write_raw(command)
        
        try:
            response = await asyncio.wait_for(self._response_queue.get(), timeout=timeout)
            return response
        except asyncio.TimeoutError:
            raise BLETimeoutError(f"No response received within {timeout}s")
        
    async def write_command(self, data: bytes) -> None:
        """Write command to device without expecting response."""
        await self._write_raw(data)
        
    def _disconnected_callback(self, client: BleakClient) -> None:
        """Handle disconnection."""
        _LOGGER.debug("Device %s disconnected", self.mac_address)

def ble_device_operation(func):
    """
    Decorator to handle locking and retries for a BLE device operation.
    It assumes that the wrapped function has 'mac_address' as its second argument.
    """

    @wraps(func)
    async def wrapper(hass, mac_address, *args, **kwargs):

        lock = _device_locks.setdefault(mac_address, asyncio.Lock())

        async with lock:
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    async with BLEConnection(hass, mac_address) as conn:
                        return await func(conn, *args, **kwargs)
                except BLEConnectionError as e:
                    # Check if it's a connection slots error specifically
                    if "No available Bluetooth connection slots" in str(e):
                        _LOGGER.error(
                            "BLE operation %s failed: %s",
                            func.__name__, e
                        )
                        raise HomeAssistantError(str(e))
                    # For other connection errors, retry
                    if attempt == max_attempts - 1:
                        _LOGGER.error(
                            "BLE operation %s failed after %d attempts: %s",
                            func.__name__, max_attempts, e
                        )
                        raise HomeAssistantError(str(e))
                    backoff_time = 0.25 * (attempt + 1)
                    _LOGGER.warning(
                        "BLE operation %s failed on attempt %d: %s. Retrying in %.2f seconds...",
                        func.__name__, attempt + 1, e, backoff_time
                    )
                    await asyncio.sleep(backoff_time)
                except BleakError as e:
                    if attempt == max_attempts - 1:
                        _LOGGER.error(
                            "BLE operation %s failed after %d attempts: %s",
                            func.__name__, max_attempts, e
                        )
                        raise
                    backoff_time = 0.25 * (attempt + 1)
                    _LOGGER.warning(
                        "BLE operation %s failed on attempt %d: %s. Retrying in %.2f seconds...",
                        func.__name__, attempt + 1, e, backoff_time
                    )
                    await asyncio.sleep(backoff_time)
            return None
    return wrapper

@ble_device_operation
async def turn_led_on(conn: BLEConnection) -> bool:
    """Turn on LED for specified device using OEPL protocol."""
    await conn.write_command(CMD_LED_ON)
    return True

@ble_device_operation
async def turn_led_off(conn: BLEConnection) -> bool:
    """Turn off LED for specified device using OEPL protocol."""
    await conn.write_command(CMD_LED_OFF)
    await conn.write_command(CMD_LED_OFF_FINAL)  # Required finalization command?
    return True


@ble_device_operation
async def set_clock_mode(conn: BLEConnection) -> bool:
    """Set device to clock mode with current timestamp.
    
    Uses BLE protocol command 000B with 4-byte Unix timestamp payload.
    Sends local time (not UTC) to match the device's expected timezone.
    """
    timestamp = int(datetime.now().replace(tzinfo=timezone.utc).timestamp())

    payload = struct.pack('<I', timestamp)  # 4-byte little-endian
    command = CMD_SET_CLOCK_MODE + payload
    await conn.write_command(command)
    return True

@ble_device_operation
async def disable_clock_mode(conn: BLEConnection) -> bool:
    """Disable clock mode on device.
    
    Uses BLE protocol command 000C with no payload.
    """
    await conn.write_command(CMD_DISABLE_CLOCK_MODE)
    return True

@ble_device_operation
async def ping_device(conn: BLEConnection) -> bool:
    """Test device connectivity."""
    # If connection and initialization succeed, device is reachable
    return True


@dataclass
class DisplayInfo:
    """Display information from device interrogation (0005 command)."""
    width: int
    height: int
    color_support: str
    rotatebuffer: int

@ble_device_operation
async def interrogate_ble_device(conn: BLEConnection) -> DisplayInfo | None:
    """Connect and interrogate device for display specifications.
    
    Uses the 0005 command to get accurate display information:
    - Display dimensions (width, height) 
    - Color support capabilities
    - Buffer rotation requirement
    """
    # Request display information using protocol command 0005
    response = await conn.write_command_with_response(CMD_GET_DISPLAY_INFO)

    _LOGGER.debug("Device interrogation for %s: received %d bytes: %s",
                 conn.mac_address, len(response), response[:10].hex() + "..." if len(response) > 10 else response.hex())

    # Verify response format: 00 05 + payload (based on real data analysis)
    if len(response) < BLE_MIN_RESPONSE_LENGTH:
        raise BLEProtocolError(f"Invalid display info response length: {len(response)} for {conn.mac_address}")

    # Verify command ID (should be 0005)
    if response[0] != 0x00 or response[1] != 0x05:
        raise BLEProtocolError(f"Invalid command ID in response: {response[0]:02x}{response[1]:02x}")

    # Skip command ID (first 2 bytes) and parse payload
    payload = response[2:]

    if len(payload) < 31:
        raise BLEProtocolError("Display info payload too short")

    # Parse display specifications from 0005 response:

    # Offset 19: Width/Height inversion flag
    wh_inverted = payload[19] == 1

    # Offset 22-23: Height (uint16, little-endian)
    height = struct.unpack("<H", payload[22:24])[0]

    # Offset 24-25: Width (uint16, little-endian)
    width = struct.unpack("<H", payload[24:26])[0]

    # Keep original dimensions, store rotation flag for later processing
    # Don't swap here - let the image processing pipeline handle rotation consistently

    # Offset 30: Color count (1=BW, 2=BWR/BWY, 3=BWRY)
    colors = payload[30]

    # Determine color support from actual device response
    if colors >= 3:
        color_support = "bwry"  # Black, white, red, yellow
    elif colors >= 2:
        color_support = "red"   # Black, white, red (or yellow)
    else:
        color_support = "mono"  # Monochrome

    # Store dimensions exactly as device reports them - keep it simple
    _LOGGER.debug("Device %s dimensions: %dx%d, colors=%d",
                conn.mac_address, width, height, colors)

    return DisplayInfo(
        width=width if wh_inverted else height,
        height=height if wh_inverted else width,
        color_support=color_support,
        rotatebuffer=wh_inverted
    )


# Helper functions for image upload protocol
def _create_data_info(checksum: int, data_ver: int, data_size: int, 
                      data_type: int, data_type_argument: int, next_check_in: int) -> bytes:
    """Create data info packet for image upload."""
    return struct.pack(
        "<BQIBBH",
        checksum,
        data_ver,
        data_size,
        data_type,
        data_type_argument,
        next_check_in,
    )


def _create_block_part(block_id: int, part_id: int, data: bytes) -> bytearray:
    """Create a block part packet for image upload."""
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


def _convert_image_to_bytes(image: Image.Image, multi_color: bool = False, compressed: bool = False) -> tuple[int, bytes]:
    """Convert a PIL Image to device format.

    Args:
        image: PIL Image to convert
        multi_color: Whether to use multi-color mode
        compressed: Whether to compress the data

    Returns:
        tuple: (data_type, pixel_array)
    """
    pixel_array = np.array(image.convert("RGB"))
    height, width, _ = pixel_array.shape

    # Get RGB channels as float arrays
    r, g, b = (
        pixel_array[:, :, 0].astype(np.float32),
        pixel_array[:, :, 1].astype(np.float32),
        pixel_array[:, :, 2].astype(np.float32),
    )

    # Calculate luminance for the whole image
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b

    #BW Channel
    white_pixels = luminance > 128
    bw_channel_bits = ~white_pixels

    byte_data = np.packbits(bw_channel_bits).tobytes()

    # Red channel (if multi-color)
    bpp_array = bytearray(byte_data)
    if multi_color:
        red_pixels = (pixel_array[:, :, 0] > 170) & ~white_pixels
        byte_data_red = np.packbits(red_pixels).tobytes()
        bpp_array += byte_data_red

    if compressed:
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
        return BLEDataType.COMPRESSED.value, struct.pack('<I', len(buffer)) + compressed_data

    return BLEDataType.RAW_COLOR.value if multi_color else BLEDataType.RAW_BW.value, bpp_array


class BLEImageUploader:
    """Handles BLE image upload with block-based protocol."""
    
    def __init__(self, connection: BLEConnection, mac_address: str):
        self.connection = connection
        self.mac_address = mac_address
        self._img_array = b""
        self._img_array_len = 0
        self._packets = []
        self._packet_index = 0
        self._upload_complete = asyncio.Event()
        self._upload_error = None
        self._upload_task = None
        
    async def _handle_response(self, data: bytes) -> bool:
        """Handle upload responses from notification queue."""
        if len(data) < 2:
            return False

        response_code = data[:2].hex().upper()
        _LOGGER.debug("Upload response for %s: %s", self.mac_address, response_code)

        try:
            response_enum = BLEResponse(response_code)
            match response_enum:
                case BLEResponse.BLOCK_REQUEST:
                    _LOGGER.debug("Received block request")
                    block_id = data[11]
                    # Parse requested parts from block request (6 bytes starting at offset 12)
                    if len(data) >= 18:
                        requested_parts_hex = data[12:18].hex().upper()
                        _LOGGER.debug("Device requested block %d, parts bitmask: %s", block_id, requested_parts_hex)
                    else:
                        _LOGGER.debug("Device requested block %d (partial block request data)", block_id)
                    await self._send_block_data(block_id)
                    return True

                case BLEResponse.BLOCK_PART_ACK:
                    _LOGGER.debug("Block part acknowledged")
                    await self._send_next_block_part()
                    return True

                case BLEResponse.BLOCK_PART_CONTINUE:
                    _LOGGER.debug("Block part acknowledged, continuing")
                    if self._packet_index >= len(self._packets):
                        _LOGGER.error("Packet index out of range")
                        return True
                    self._packet_index += 1
                    await self._send_next_block_part()
                    return True

                case BLEResponse.UPLOAD_COMPLETE:
                    _LOGGER.debug("Image upload completed successfully")
                    self._upload_complete.set()
                    return True

                case BLEResponse.IMAGE_ALREADY_DISPLAYED:
                    _LOGGER.debug("Image already displayed")
                    self._upload_complete.set()
                    return True

        except ValueError:
            return False  # Unknown response code

    async def upload_image(self, image_data: bytes, metadata: DeviceMetadata) -> bool:
        """Upload image using block-based protocol with existing notification system."""
        try:
            # Convert JPEG to PIL Image
            image = Image.open(io.BytesIO(image_data))
            _LOGGER.debug("Before transpose: image size %dx%d", image.width, image.height)
            
            # Apply rotation to match AP device orientation  
            image = image.transpose(Image.Transpose.ROTATE_90)  # -90° rotation
            _LOGGER.debug("After transpose: image size %dx%d", image.width, image.height)
            
            # Determine if device supports color
            multi_color = metadata.color_support in ("red", "bwry")
            
            # Convert image to device format
            data_type, pixel_array = _convert_image_to_bytes(image, multi_color, compressed=True)
            
            _LOGGER.debug("Upload for %s: DataType=0x%02x, DataLen=%d",
                         self.mac_address, data_type, len(pixel_array))
            _LOGGER.info("Starting BLE image upload to %s (%d bytes)", self.mac_address, len(pixel_array))

            self._img_array = pixel_array
            self._img_array_len = len(self._img_array)

            # Send data info to initiate upload
            data_info = _create_data_info(255, zlib.crc32(self._img_array) & 0xfffffff, self._img_array_len, data_type, 0, 0)
            await self.connection._write_raw(bytes.fromhex(BLECommand.DATA_INFO.value) + data_info)

            # Wait for responses using request-response pattern instead of continuous monitoring
            while not self._upload_complete.is_set():
                response = await self._wait_for_response()
                if response and await self._handle_response(response):
                    continue
                elif response is None:
                    # Timeout - this is a failure
                    _LOGGER.error("Upload failed for %s: timeout waiting for response", self.mac_address)
                    return False

            if self._upload_error:
                raise BLEError(f"Upload failed: {self._upload_error}")

            # Only reach here if upload_complete was set by a success response
            _LOGGER.info("BLE image upload completed successfully for %s", self.mac_address)
            return True
                
        except Exception as e:
            _LOGGER.error("Image upload failed for %s: %s", self.mac_address, e)
            return False
    
    async def _wait_for_response(self, timeout: float = 10.0) -> bytes | None:
        """Wait for next upload response with timeout."""
        try:
            response = await asyncio.wait_for(
                self.connection._response_queue.get(),
                timeout=timeout
            )

            # Basic validation only
            if not response or len(response) < 2:
                return None

            return response

        except asyncio.TimeoutError:
            return None
    
    async def _send_block_data(self, block_id: int):
        """Send block data for specified block ID."""
        _LOGGER.debug("Building block %d for %s", block_id, self.mac_address)
        block_start = block_id * BLE_BLOCK_SIZE
        block_end = block_start + BLE_BLOCK_SIZE
        block_data = self._img_array[block_start:block_end]

        _LOGGER.debug("Sending block %d: %d bytes (offset %d-%d)",
                     block_id, len(block_data), block_start, min(block_end, len(self._img_array)))
        
        crc_block = sum(block_data) & 0xFFFF
        buffer = bytearray(4)
        buffer[0] = len(block_data) & 0xFF
        buffer[1] = (len(block_data) >> 8) & 0xFF
        buffer[2] = crc_block & 0xFF
        buffer[3] = (crc_block >> 8) & 0xFF
        block_data = buffer + block_data
        
        # Create packets
        packet_count = (len(block_data) + BLE_MAX_PACKET_DATA_SIZE - 1) // BLE_MAX_PACKET_DATA_SIZE
        self._packets = []
        for i in range(packet_count):
            start = i * BLE_MAX_PACKET_DATA_SIZE
            end = start + BLE_MAX_PACKET_DATA_SIZE
            slice_data = block_data[start:end]
            packet = _create_block_part(block_id, i, slice_data)
            self._packets.append(packet)
        
        _LOGGER.debug("Created %d packets for block %d", len(self._packets), block_id)
        self._packet_index = 0
        if self._packets:
            await self._send_next_block_part()
    
    async def _send_next_block_part(self):
        """Send next block part packet."""
        if not self._packets or self._packet_index >= len(self._packets):
            _LOGGER.debug("No more packets to send")
            return
        
        _LOGGER.debug("Sending packet %d/%d", self._packet_index + 1, len(self._packets))
        await self.connection._write_raw(bytes.fromhex(BLECommand.BLOCK_PART.value) + self._packets[self._packet_index])

@ble_device_operation
async def upload_image(conn: BLEConnection, image_data: bytes, metadata: DeviceMetadata) -> bool:
    """Upload image to specified BLE device using block-based protocol."""
    try:
        uploader = BLEImageUploader(conn, conn.mac_address)
        return await uploader.upload_image(image_data, metadata)
    except BLEError as e:
        _LOGGER.error("Image upload failed for %s: %s", conn.mac_address, e)
        return False



def parse_ble_advertisement(manufacturer_data: bytes) -> dict:
    """Parse manufacturer data for device state updates."""
    if not manufacturer_data:
        return {}

    try:
        version = manufacturer_data[0]
        if version == 1:
            if len(manufacturer_data) < 10:
                return {}
            return {
                "version": version,
                "hw_type": int.from_bytes(manufacturer_data[1:3], 'little'),
                "fw_version": int.from_bytes(manufacturer_data[3:5], 'little'),
                "capabilities": int.from_bytes(manufacturer_data[5:7], 'little'),
                "battery_mv": int.from_bytes(manufacturer_data[7:9], 'little'),
                "counter": manufacturer_data[9],
            }
        elif version == 2:
            if len(manufacturer_data) < 11:
                return {}
            return {
                "version": version,
                "hw_type": int.from_bytes(manufacturer_data[1:3], 'little'),
                "fw_version": int.from_bytes(manufacturer_data[3:5], 'little'),
                "capabilities": int.from_bytes(manufacturer_data[5:7], 'little'),
                "battery_mv": int.from_bytes(manufacturer_data[7:9], 'little'),
                "temperature": struct.unpack('<b', manufacturer_data[9:10])[0],
                "counter": manufacturer_data[10],
            }
        else:
            _LOGGER.debug("Unsupported manufacturer data version: %d", version)
            return {}

    except (IndexError, struct.error) as e:
        _LOGGER.warning("Error parsing BLE advertising data: %s", e)
    
    return {}


def calculate_battery_percentage(voltage_mv: int) -> int:
    """Convert battery voltage (mV) to percentage estimate."""
    if voltage_mv == 0:
        return 0  # Unknown battery level
        
    voltage = voltage_mv / 1000.0
    min_voltage, max_voltage = 2.6, 3.2  # Battery voltage range for OEPL devices
    percentage = min(100, max(0, int((voltage - min_voltage) * 100 / (max_voltage - min_voltage))))
    return percentage

