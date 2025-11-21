"""Shared BLE image upload protocol (compatible with both ATC and OEPL firmware)."""
import asyncio
import io
import struct
import zlib
import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np
from PIL import Image

from .exceptions import BLEError

_LOGGER = logging.getLogger(__name__)


# BLE Protocol Sizes
BLE_BLOCK_SIZE = 4096
BLE_MAX_PACKET_DATA_SIZE = 230


class BLEResponse(Enum):
    """BLE upload response codes."""

    BLOCK_REQUEST = "00C6"
    BLOCK_PART_ACK = "00C4"
    BLOCK_PART_CONTINUE = "00C5"
    UPLOAD_COMPLETE = "00C7"
    IMAGE_ALREADY_DISPLAYED = "00C8"


class BLECommand(Enum):
    """BLE upload command codes."""

    DATA_INFO = "0064"
    BLOCK_PART = "0065"


class BLEDataType(Enum):
    """BLE image data types."""

    RAW_BW = 0x20  # Uncompressed monochrome
    RAW_COLOR = 0x21  # Uncompressed color (BWR/BWY)
    COMPRESSED = 0x30  # Compressed image


@dataclass
class DeviceMetadata:
    """Device metadata from BLE interrogation."""

    hw_type: int
    fw_version: int
    width: int
    height: int
    color_support: str
    rotatebuffer: int


def _create_data_info(
    checksum: int,
    data_ver: int,
    data_size: int,
    data_type: int,
    data_type_argument: int,
    next_check_in: int,
) -> bytes:
    """Create data info packet for image upload.

    Args:
        checksum: Data checksum (usually 255 placeholder)
        data_ver: CRC32 of image data
        data_size: Image data size in bytes
        data_type: Data type enum value (0x20, 0x21, 0x30)
        data_type_argument: Additional argument (usually 0)
        next_check_in: Next check-in time (usually 0)

    Returns:
        bytes: Packed data info structure
    """
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
    """Create a block part packet for image upload.

    Args:
        block_id: Block identifier
        part_id: Part identifier within block
        data: Packet data (max 230 bytes)

    Returns:
        bytearray: Block part packet with checksum

    Raises:
        ValueError: If data exceeds maximum size
    """
    max_data_size = 230
    data_length = len(data)
    if data_length > max_data_size:
        raise ValueError("Data length exceeds maximum allowed size for a packet.")

    buffer = bytearray(3 + max_data_size)
    buffer[1] = block_id & 0xFF
    buffer[2] = part_id & 0xFF
    buffer[3 : 3 + data_length] = data
    buffer[0] = sum(buffer[1 : 3 + data_length]) & 0xFF
    return buffer


def _convert_image_to_bytes(
    image: Image.Image, multi_color: bool = False, compressed: bool = False
) -> tuple[int, bytes]:
    """Convert a PIL Image to device format.

    Supports:
    - Monochrome (1-bit)
    - Color dual-plane (BWR/BWY)
    - Optional zlib compression

    Args:
        image: PIL Image to convert
        multi_color: Whether to use multi-color mode (BWR/BWY)
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

    # BW Channel
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
        return (
            BLEDataType.COMPRESSED.value,
            struct.pack("<I", len(buffer)) + compressed_data,
        )

    return (
        BLEDataType.RAW_COLOR.value if multi_color else BLEDataType.RAW_BW.value,
        bpp_array,
    )


class BLEImageUploader:
    """Handles BLE image upload with block-based protocol.

    This class is protocol-agnostic and works with both ATC and OEPL firmware.
    """

    def __init__(self, connection, mac_address: str):
        """Initialize image uploader.

        Args:
            connection: Active BLEConnection instance
            mac_address: Device MAC address
        """
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
        """Handle upload responses from notification queue.

        Args:
            data: Response data from device

        Returns:
            bool: True if response was handled successfully
        """
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
                    if len(data) >= 18:
                        requested_parts_hex = data[12:18].hex().upper()
                        _LOGGER.debug(
                            "Device requested block %d, parts bitmask: %s",
                            block_id,
                            requested_parts_hex,
                        )
                    else:
                        _LOGGER.debug(
                            "Device requested block %d (partial block request data)", block_id
                        )
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

    async def upload_image(self, image_data: bytes, metadata: DeviceMetadata, protocol_type: str = "atc") -> bool:
        """Upload image using block-based protocol.

        Args:
            image_data: JPEG image data
            metadata: Device metadata with dimensions and color support
            protocol_type: Protocol type ("atc" or "oepl")

        Returns:
            bool: True if upload succeeded, False otherwise
        """
        try:
            # Convert JPEG to PIL Image
            image = Image.open(io.BytesIO(image_data))
            _LOGGER.debug("Before transpose: image size %dx%d", image.width, image.height)

            # Apply rotation for ATC devices only (OEPL handles rotation firmware-side)
            if protocol_type == "atc" and metadata.rotatebuffer == 1:
                image = image.transpose(Image.Transpose.ROTATE_90)
                _LOGGER.debug("Applied 90° rotation for ATC device: %dx%d", image.width, image.height)
            else:
                _LOGGER.debug("No client-side rotation (protocol=%s, rotatebuffer=%d): %dx%d",
                             protocol_type, metadata.rotatebuffer, image.width, image.height)

            # Determine if device supports color
            multi_color = metadata.color_support in ("red", "bwry")

            # Convert image to device format
            data_type, pixel_array = _convert_image_to_bytes(
                image, multi_color, compressed=True
            )

            _LOGGER.debug(
                "Upload for %s: DataType=0x%02x, DataLen=%d",
                self.mac_address,
                data_type,
                len(pixel_array),
            )
            _LOGGER.info(
                "Starting BLE image upload to %s (%d bytes)", self.mac_address, len(pixel_array)
            )

            self._img_array = pixel_array
            self._img_array_len = len(self._img_array)

            # Send data info to initiate upload
            data_info = _create_data_info(
                255, zlib.crc32(self._img_array) & 0xFFFFFFF, self._img_array_len, data_type, 0, 0
            )
            await self.connection._write_raw(bytes.fromhex(BLECommand.DATA_INFO.value) + data_info)

            # Wait for responses using request-response pattern
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
        """Wait for next upload response with timeout.

        Args:
            timeout: Timeout in seconds

        Returns:
            bytes: Response data or None if timeout
        """
        try:
            response = await asyncio.wait_for(
                self.connection._response_queue.get(), timeout=timeout
            )

            # Basic validation only
            if not response or len(response) < 2:
                return None

            return response

        except asyncio.TimeoutError:
            return None

    async def _send_block_data(self, block_id: int):
        """Send block data for specified block ID.

        Args:
            block_id: Block identifier to send
        """
        _LOGGER.debug("Building block %d for %s", block_id, self.mac_address)
        block_start = block_id * BLE_BLOCK_SIZE
        block_end = block_start + BLE_BLOCK_SIZE
        block_data = self._img_array[block_start:block_end]

        _LOGGER.debug(
            "Sending block %d: %d bytes (offset %d-%d)",
            block_id,
            len(block_data),
            block_start,
            min(block_end, len(self._img_array)),
        )

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
        await self.connection._write_raw(
            bytes.fromhex(BLECommand.BLOCK_PART.value) + self._packets[self._packet_index]
        )
