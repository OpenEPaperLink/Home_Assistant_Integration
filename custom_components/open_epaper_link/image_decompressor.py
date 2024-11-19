import zlib
from typing import Tuple, Optional, List, Dict
import numpy as np
from PIL import Image
from .tag_types import get_tag_types_manager

class ImageDecompressor:
    """Handles decompression of OpenEPaperLink compressed and uncompressed images."""

    # Fallback palette in case tag type information is unavailable
    FALLBACK_PALETTE = [
        (255, 255, 255),  # White
        (0, 0, 0),        # Black
        (255, 0, 0),      # Red
    ]

    def __init__(self, hass, hw_type: Optional[int] = None):
        """Initialize decompressor with optional hardware type."""
        self._hass = hass
        self._hw_type = hw_type
        self._tag_type = None
        self._color_table = None

    async def load_tag_type(self):
        """Load tag type information and color table."""
        if self._hw_type is not None and self._tag_type is None:
            try:
                tag_manager = await get_tag_types_manager(self._hass)
                self._tag_type = await tag_manager.get_tag_info(self._hw_type)

                # Get color table from tag type
                if hasattr(self._tag_type, 'color_table'):
                    # Convert color table to RGB tuples
                    self._color_table = [
                        tuple(color) for color in self._tag_type.color_table.values()
                    ]

            except Exception as e:
                print(f"Error loading tag type {self._hw_type}: {str(e)}")

    def get_color_table(self) -> List[Tuple[int, int, int]]:
        """Get the appropriate color table.

        Returns the tag type's color table if available, otherwise returns fallback palette.
        """
        if self._color_table:
            return self._color_table
        return self.FALLBACK_PALETTE

    @staticmethod
    def is_compressed(data: bytes) -> bool:
        """Determine if the image data is compressed."""
        if len(data) < 4:
            return False

        total_size = int.from_bytes(data[0:4], byteorder='big')
        if total_size == 0 or total_size > len(data):
            return False

        return True

    def read_header(self, data: bytes, is_compressed: bool) -> Tuple[int, int, int, int]:
        """Read the image header."""
        if is_compressed:
            header_data = self.decompress_image(data)
            if not header_data:
                raise ValueError("Failed to decompress header")
        else:
            header_data = data

        header_size = header_data[0]
        width = int.from_bytes(header_data[1:3], byteorder='big')
        height = int.from_bytes(header_data[3:5], byteorder='big')
        bpp = header_data[5]
        return header_size, width, height, bpp

    @staticmethod
    def decompress_image(data: bytes) -> Optional[bytes]:
        """Decompress zlib compressed image data."""
        try:
            total_size = int.from_bytes(data[0:4], byteorder='big')
            compressed_data = data[4:]

            decompressor = zlib.decompressobj()
            decompressed_data = decompressor.decompress(compressed_data)
            return decompressed_data

        except zlib.error as e:
            print(f"Zlib decompression failed: {str(e)}")
            return None
        except Exception as e:
            print(f"Error decompressing image: {str(e)}")
            return None

    @staticmethod
    def unpack_monochrome(data: bytes, width: int, height: int, invert: bool = False) -> np.ndarray:
        """Unpack 1-bit monochrome image data into a numpy array."""
        img = np.zeros((height, width), dtype=np.uint8)

        for y in range(height):
            for x in range(0, width, 8):
                byte_idx = (y * width + x) // 8
                if byte_idx >= len(data):
                    break

                byte = data[byte_idx]
                for bit in range(min(8, width - x)):
                    value = (byte >> (7 - bit)) & 1
                    if invert:
                        value = 1 - value
                    img[y, x + bit] = value * 255

        return img

    @staticmethod
    def unpack_3bit_color(data: bytes, width: int, height: int) -> np.ndarray:
        """Unpack 3-bit color image data into a numpy array of color indices."""
        img = np.zeros((height, width), dtype=np.uint8)
        bit_position = 0

        for y in range(height):
            for x in range(width):
                byte_idx = bit_position // 8
                bit_offset = bit_position % 8

                if byte_idx >= len(data):
                    break

                if bit_offset <= 5:
                    value = (data[byte_idx] >> (5 - bit_offset)) & 0x7
                else:
                    bits_from_first = 8 - bit_offset
                    first_part = (data[byte_idx] & ((1 << bits_from_first) - 1)) << (3 - bits_from_first)
                    if byte_idx + 1 < len(data):
                        second_part = (data[byte_idx + 1] >> (8 - (3 - bits_from_first))) & ((1 << (3 - bits_from_first)) - 1)
                        value = first_part | second_part
                    else:
                        value = first_part

                img[y, x] = value
                bit_position += 3

        return img

    def combine_layers(self, black_layer: np.ndarray, red_layer: Optional[np.ndarray] = None) -> Image.Image:
        """Combine black and optional red layers into a final image."""
        height, width = black_layer.shape
        rgb = np.zeros((height, width, 3), dtype=np.uint8)

        # Get colors from tag type if available
        colors = self.get_color_table()
        white_color = colors[0]  # Usually white
        black_color = colors[1]  # Usually black
        red_color = colors[2] if len(colors) > 2 else (255, 0, 0)  # Red or default red

        # Set colors based on tag type's color table
        black_mask = (black_layer == 255)
        rgb[black_mask] = black_color

        white_mask = (black_layer == 0)
        rgb[white_mask] = white_color

        if red_layer is not None:
            red_mask = (red_layer == 255)
            rgb[red_mask] = red_color

            # Handle overlap (black + red = black)
            overlap_mask = (black_layer == 255) & (red_layer == 255)
            rgb[overlap_mask] = black_color

        return Image.fromarray(rgb)

    def create_color_image(self, color_indices: np.ndarray) -> Image.Image:
        """Create RGB image from color indices using the tag type's color table."""
        colors = self.get_color_table()
        height, width = color_indices.shape
        rgb = np.zeros((height, width, 3), dtype=np.uint8)

        # Apply colors from tag type's color table
        for i, color in enumerate(colors):
            mask = (color_indices == i)
            rgb[mask] = color

        return Image.fromarray(rgb)

    async def process_image(self, data: bytes, invert: bool = False) -> Optional[Image.Image]:
        """Process a compressed or uncompressed OpenEPaperLink image.

        Args:
            data: Raw image data (compressed or uncompressed)
            invert: Whether to invert black/white values

        Returns:
            PIL Image or None if processing fails
        """
        try:
            # Load tag type information if available
            await self.load_tag_type()

            # Detect if data is compressed
            is_compressed = self.is_compressed(data)

            # Read header
            header_size, width, height, bpp = self.read_header(data, is_compressed)

            # Get image data
            if is_compressed:
                decompressed = self.decompress_image(data)
                if not decompressed:
                    return None
                image_data = decompressed[header_size:]
            else:
                image_data = data[header_size:]

            # Calculate plane size
            plane_size = (width * height + 7) // 8

            # Process based on color mode
            if bpp == 1:  # Monochrome
                black_layer = self.unpack_monochrome(image_data, width, height, invert)
                return self.combine_layers(black_layer)

            elif bpp == 2:  # Black + Red
                black_layer = self.unpack_monochrome(image_data[:plane_size], width, height, invert)
                red_layer = self.unpack_monochrome(image_data[plane_size:], width, height, invert)
                return self.combine_layers(black_layer, red_layer)

            elif bpp == 3:  # 3-bit color
                color_indices = self.unpack_3bit_color(image_data, width, height)
                return self.create_color_image(color_indices)

            else:
                print(f"Unsupported bits per pixel: {bpp}")
                return None

        except Exception as e:
            print(f"Error processing image: {str(e)}")
            return None