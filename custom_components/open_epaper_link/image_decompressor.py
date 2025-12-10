"""Image decoder for OpenEPaperLink raw image format."""
from __future__ import annotations

import io
import logging
import zlib

from PIL import Image

from .tag_types import TagType
from .g5_decoder import parse_g5_header, process_g5
_LOGGER = logging.getLogger(__name__)


def decode_esl_raw(data: bytes, tag_type: TagType) -> bytes:
    """Decode an OpenEPaperLink raw file.

    Processes raw image data from the OpenEPaperLink AP, handling:

    - G5 compression detection and decompression
    - Zlib compression detection and decompression
    - BWR/BWY dual-plane formats for 2-bit displays
    - Packed pixel formats for higher color depths
    - Buffer rotation settings from tag type

    The function detects the data format based on the tag type
    information and header data, then processes accordingly.

    Args:
        data: Raw image data bytes from the AP
        tag_type: TagType object containing display specifications

    Returns:
        bytes: Decoded raw bitmap data ready for rendering

    Raises:
        Exception: For decompression errors or invalid data format
    """
    _LOGGER.debug(f"decode_esl_raw received data (first 16 bytes): {data[:16].hex()}")

    # Check for G5 compression using our working decoder
    if len(data) >= 6:
        try:
            header_size, width, height, compression_mode = parse_g5_header(data)
            if compression_mode in [1, 2]:  # Valid G5 compression modes
                _LOGGER.debug(f"Found G5 compressed data: {width}x{height}, mode {compression_mode}")
                tagtype_dict = {
                    'width': tag_type.width,
                    'height': tag_type.height,
                    'bpp': tag_type.bpp,
                    'rotatebuffer': tag_type.rotatebuffer,
                    'colortable': tag_type.color_table
                }
                bitmap_data = process_g5(data, tagtype_dict, output_format='bytes')
                return bitmap_data
        except Exception as e:
            _LOGGER.debug(f"Not G5 format: {e}")
            # Fall through to other decompression methods

    _LOGGER.debug(f"Input size: {len(data)} bytes")
    _LOGGER.debug(f"Tag type: {tag_type.name}")
    _LOGGER.debug(f"Dimensions: {tag_type.width}x{tag_type.height}")
    _LOGGER.debug(f"BPP: {tag_type.bpp}")
    _LOGGER.debug(f"Rotate buffer: {tag_type.rotatebuffer}")

    # Calculate expected sizes
    width = tag_type.height if tag_type.rotatebuffer % 2 else tag_type.width
    height = tag_type.width if tag_type.rotatebuffer % 2 else tag_type.height

    if tag_type.bpp <= 2:  # Traditional 1-2 bit plane-based format
        bytes_per_row = (width + 7) // 8
        bytes_per_plane = bytes_per_row * height
        total_size = bytes_per_plane * (2 if tag_type.bpp == 2 else 1)
    else:  # 3-4 bit packed format
        bits_per_pixel = tag_type.bpp
        bytes_per_row = (width * bits_per_pixel + 7) // 8
        total_size = bytes_per_row * height

    header_size = 6

    _LOGGER.debug(f"Effective dimensions: {width}x{height}")
    _LOGGER.debug(f"Bits per pixel: {tag_type.bpp}")
    _LOGGER.debug(f"Expected total size: {total_size} bytes")

    # Check for compressed data
    try:
        if len(data) >= 4:
            compressed_size = int.from_bytes(data[:4], byteorder='little')
            if compressed_size > 0:  # Compressed data
                _LOGGER.debug(f"Found compressed data, size from header: {compressed_size}")

                compressed_data = data[4:]
                _LOGGER.debug(f"Compressed data size: {len(compressed_data)} bytes")

                # Decompress data
                decompressor = zlib.decompressobj(wbits=15)
                decompressed_data = decompressor.decompress(compressed_data)
                _LOGGER.debug(f"Decompressed size: {len(decompressed_data)} bytes")

                # Handle potential second block for BWY/BWR mode
                if tag_type.bpp == 2 and decompressor.unused_data:
                    remaining_data = decompressor.unused_data
                    _LOGGER.debug(f"Found second compressed block: {len(remaining_data)} bytes")
                    second_decompressor = zlib.decompressobj(wbits=15)
                    second_block = second_decompressor.decompress(remaining_data)

                    # Extract and combine planes
                    # header = decompressed_data[:header_size]
                    first_plane = decompressed_data[header_size:header_size + total_size // 2]
                    second_plane = second_block[header_size:header_size + total_size // 2]
                    data = first_plane + second_plane
                else:
                    # Single block contains all data
                    data = decompressed_data[header_size:]
            else:
                _LOGGER.debug("Data appears to be uncompressed")
                # For uncompressed data, pad if necessary
                if len(data) < total_size:
                    _LOGGER.debug(f"Padding uncompressed data to {total_size} bytes")
                    data = data.ljust(total_size, b'\x00')
                return data

    except Exception as e:
        _LOGGER.debug(f"Processing failed: {e}")
        _LOGGER.debug("Treating as raw data")
        if len(data) < total_size:
            _LOGGER.debug(f"Padding raw data to {total_size} bytes")
            data = data.ljust(total_size, b'\x00')

    return data


def to_image(raw_data: bytes, tag_type: TagType) -> bytes:
    """Convert decoded ESL raw data to JPEG image.

    Transforms the decoded raw bitmap data into a standard JPEG image
    that can be displayed in Home Assistant or saved to disk.

    The conversion process:

    1. Decodes the raw data using decode_esl_raw
    2. Creates a new PIL Image with appropriate dimensions
    3. Processes pixels based on the tag's color depth and format
    4. Applies rotation according to the tag's buffer rotation setting
    5. Converts to JPEG format

    The color mapping depends on the tag type's color table,
    which defines the available colors for different bit values.

    Args:
        raw_data: Raw image data from the AP
        tag_type: TagType object with display specifications

    Returns:
        bytes: JPEG image data

    Raises:
        Exception: For image processing errors or invalid color format
    """
    data = decode_esl_raw(raw_data, tag_type)

    # For 90/270 degree rotated displays, swap width/height before processing
    native_width = tag_type.width
    native_height = tag_type.height
    if tag_type.rotatebuffer % 2:  # 90 or 270 degrees
        native_width, native_height = native_height, native_width

    _LOGGER.debug("\n=== Color Table Information ===")
    _LOGGER.debug(f"Color table contents: {tag_type.color_table}")

    # Create initial image
    img = Image.new('RGB', (native_width, native_height), 'white')
    pixels = img.load()

    # Convert color table to RGB tuples
    color_table = {k: tuple(v) for k, v in tag_type.color_table.items()}

    _LOGGER.debug(f"Available colors: {list(color_table.keys())}")

    # Process pixels based on color depth
    if tag_type.bpp <= 2:  # Traditional 1-2 bit plane-based format
        bytes_per_row = (native_width + 7) // 8
        bytes_per_plane = bytes_per_row * native_height

        # Split into planes for 2bpp mode
        black_plane = data[:bytes_per_plane]
        color_plane = data[bytes_per_plane:bytes_per_plane * 2] if tag_type.bpp == 2 else None

        # Process pixels
        for y in range(native_height):
            row_offset = y * bytes_per_row
            for x in range(native_width):
                byte_offset = row_offset + (x // 8)
                bit_mask = 0x80 >> (x % 8)

                black = bool(black_plane[byte_offset] & bit_mask)
                color = bool(color_plane[byte_offset] & bit_mask) if color_plane else False

                if black and color:
                    pixels[x, y] = color_table['black']  # Overlap
                elif black:
                    pixels[x, y] = color_table['black']
                elif color:
                    # Use first available color that's not black or white
                    color_key = next((k for k in color_table.keys()
                                      if k not in ['black', 'white']), 'white')
                    pixels[x, y] = color_table[color_key]
                else:
                    pixels[x, y] = color_table['white']

    else:  # 3-4 bit packed format
        bits_per_pixel = tag_type.bpp
        # pixels_per_byte = 8 // bits_per_pixel
        bit_mask = (1 << bits_per_pixel) - 1
        bytes_per_row = (native_width * bits_per_pixel + 7) // 8

        # Convert color table to list for indexed access
        colors_list = list(color_table.values())

        for y in range(native_height):
            for x in range(native_width):
                # Calculate byte and bit positions
                bit_position = (x * bits_per_pixel) % 8
                byte_offset = (y * bytes_per_row) + (x * bits_per_pixel) // 8

                if byte_offset < len(data):
                    # Extract the color index
                    if bit_position + bits_per_pixel <= 8:
                        # Color index is contained within a single byte
                        color_index = (data[byte_offset] >> (8 - bit_position - bits_per_pixel)) & bit_mask
                    else:
                        # Color index spans two bytes
                        first_byte = data[byte_offset] & ((1 << (8 - bit_position)) - 1)
                        bits_from_first = 8 - bit_position
                        bits_from_second = bits_per_pixel - bits_from_first
                        if byte_offset + 1 < len(data):
                            second_byte = data[byte_offset + 1] >> (8 - bits_from_second)
                            color_index = (first_byte << bits_from_second) | second_byte
                        else:
                            color_index = first_byte << bits_from_second

                    # Set pixel color
                    if color_index < len(colors_list):
                        pixels[x, y] = colors_list[color_index]

    # Apply rotation
    if tag_type.rotatebuffer == 1:  # 90 degrees CCW
        img = img.transpose(Image.Transpose.ROTATE_270)
    elif tag_type.rotatebuffer == 2:  # 180 degrees
        img = img.transpose(Image.Transpose.ROTATE_180)
    elif tag_type.rotatebuffer == 3:  # 270 degrees CCW (90 CW)
        img = img.transpose(Image.Transpose.ROTATE_90)

    # Convert to JPEG
    output = io.BytesIO()
    img.save(output, format='JPEG', quality=95)
    output.seek(0)
    return output.read()