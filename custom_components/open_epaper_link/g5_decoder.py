#!/usr/bin/env python3
"""
G5 Image Decoder - Python port of JavaScript G5 decoder
A 1-bpp image decoder for OpenEPaperLink displays

Original JavaScript version by Larry Bank, Nic Limper
Python port with complete image assembly pipeline
"""

import ctypes
import struct
import numpy as np
from PIL import Image
from typing import Union, Tuple, Dict, Any
import json


# ============================================================================
# Exception Classes
# ============================================================================

class G5DecoderError(Exception):
    """Base exception for G5 decoder errors"""
    pass


class G5InvalidParameterError(G5DecoderError):
    """Invalid parameters provided to decoder"""
    pass


class G5DecodeError(G5DecoderError):
    """Error during G5 decoding process"""
    pass


class G5UnsupportedFeatureError(G5DecoderError):
    """Unsupported G5 feature encountered"""
    pass


class G5DataOverflowError(G5DecoderError):
    """Data overflow during decoding"""
    pass


class G5MaxFlipsExceededError(G5DecoderError):
    """Maximum flips exceeded during decoding"""
    pass


# ============================================================================
# Constants
# ============================================================================

# Return codes (matching JavaScript)
G5_SUCCESS = 0
G5_INVALID_PARAMETER = 1
G5_DECODE_ERROR = 2
G5_UNSUPPORTED_FEATURE = 3
G5_ENCODE_COMPLETE = 4
G5_DECODE_COMPLETE = 5
G5_NOT_INITIALIZED = 6
G5_DATA_OVERFLOW = 7
G5_MAX_FLIPS_EXCEEDED = 8

# Decoder configuration
MAX_IMAGE_FLIPS = 640
REGISTER_WIDTH = 32

# Horizontal prefix bits
HORIZ_SHORT_SHORT = 0
HORIZ_SHORT_LONG = 1
HORIZ_LONG_SHORT = 2
HORIZ_LONG_LONG = 3

# Code table for Group 4 (MMR) decoding
# Format: code, bit_length pairs
CODE_TABLE = [
    0x90, 0, 0x40, 0,          # trash, uncompressed mode - codes 0 and 1
    3, 7,                       # V(-3) pos = 2
    0x13, 7,                    # V(3)  pos = 3
    2, 6, 2, 6,                 # V(-2) pos = 4,5
    0x12, 6, 0x12, 6,          # V(2)  pos = 6,7
    0x30, 4, 0x30, 4, 0x30, 4, 0x30, 4,    # pass  pos = 8->F
    0x30, 4, 0x30, 4, 0x30, 4, 0x30, 4,
    0x20, 3, 0x20, 3, 0x20, 3, 0x20, 3,    # horiz pos = 10->1F
    0x20, 3, 0x20, 3, 0x20, 3, 0x20, 3,
    0x20, 3, 0x20, 3, 0x20, 3, 0x20, 3,
    0x20, 3, 0x20, 3, 0x20, 3, 0x20, 3,    # V(-1) pos = 20->2F
    1, 3, 1, 3, 1, 3, 1, 3,
    1, 3, 1, 3, 1, 3, 1, 3,
    1, 3, 1, 3, 1, 3, 1, 3,
    1, 3, 1, 3, 1, 3, 1, 3,
    0x11, 3, 0x11, 3, 0x11, 3, 0x11, 3,   # V(1)   pos = 30->3F
    0x11, 3, 0x11, 3, 0x11, 3, 0x11, 3,
    0x11, 3, 0x11, 3, 0x11, 3, 0x11, 3,
    0x11, 3, 0x11, 3, 0x11, 3, 0x11, 3
]


# ============================================================================
# Utility Functions
# ============================================================================

def read_motorola_long(data: bytes, offset: int) -> int:
    """
    Read 32-bit big-endian integer from bytes, equivalent to TIFFMOTOLONG
    Handles partial reads when near end of data
    """
    value = 0
    for i in range(4):
        if offset + i < len(data):
            value |= data[offset + i] << (24 - i * 8)
    return value


def parse_g5_header(data: bytes) -> Tuple[int, int, int, int]:
    """
    Parse G5 header and return (header_size, width, height, compression_mode)
    
    Header format (matching JavaScript drawCanvas.js):
    - data[0]: header size
    - data[1:3]: width (data[2] << 8 | data[1])  
    - data[3:5]: height (data[4] << 8 | data[3])
    - data[5]: compression mode (0-3)
    """
    if len(data) < 6:
        raise G5InvalidParameterError("Data too short for G5 header")
    
    header_size = data[0]
    width = (data[2] << 8) | data[1]   # Matching JavaScript: (data[2] << 8) | data[1]
    height = (data[4] << 8) | data[3]  # Matching JavaScript: (data[4] << 8) | data[3]
    compression_mode = data[5]
    
    if compression_mode > 3:
        raise G5UnsupportedFeatureError(f"Unsupported compression mode: {compression_mode}")
    
    # Note: compression mode 2 doubling is handled AFTER validation in process_g5()
    return header_size, width, height, compression_mode


def validate_header_against_tagtype(width: int, height: int, tagtype: Dict[str, Any]) -> None:
    """Validate parsed header against tagtype specifications"""
    tagtype_width = tagtype.get('width', 0)
    tagtype_height = tagtype.get('height', 0)
    
    width_valid = (width == tagtype_width or width == tagtype_height)
    height_valid = (height == tagtype_width or height == tagtype_height)
    
    if not (width_valid and height_valid):
        raise G5InvalidParameterError(
            f"Header dimensions {width}x{height} don't match tagtype {tagtype_width}x{tagtype_height}"
        )


# ============================================================================
# G5 Decoder Class
# ============================================================================

class G5Decoder:
    """Main G5 decoder class with precise 32-bit arithmetic"""
    
    def __init__(self):
        self.width = 0
        self.height = 0
        self.error = 0
        self.y = 0
        self.vlc_size = 0
        self.h_len = 0
        self.pitch = 0
        
        # Use ctypes for precise 32-bit arithmetic
        self.u32_accum = ctypes.c_uint32(0)
        self.bit_off = ctypes.c_uint32(0)
        self.bits = ctypes.c_uint32(0)
        
        # Buffer management
        self.src_data: bytes = None
        self.buf_index = 0
        
        # Flip tracking arrays
        self.cur_flips = np.zeros(MAX_IMAGE_FLIPS, dtype=np.int16)
        self.ref_flips = np.zeros(MAX_IMAGE_FLIPS, dtype=np.int16)
    
    def init_decoder(self, width: int, height: int, data: bytes) -> int:
        """Initialize decoder with image parameters"""
        if not data or width < 1 or height < 1 or len(data) < 1:
            return G5_INVALID_PARAMETER
        
        self.vlc_size = len(data)
        self.src_data = data
        self.bit_off = ctypes.c_uint32(0)
        self.y = 0
        self.bits = ctypes.c_uint32(read_motorola_long(data, 0))
        self.width = width
        self.height = height
        
        return G5_SUCCESS
    
    def decode_begin(self) -> None:
        """Initialize internal structures for decoding"""
        xsize = self.width
        
        # Seed current and reference lines with xsize for V(0) codes  
        # JavaScript: for (let i = 0; i < MAX_IMAGE_FLIPS - 2; i++)
        for i in range(MAX_IMAGE_FLIPS - 2):
            self.ref_flips[i] = xsize
            self.cur_flips[i] = xsize
        
        # Prefill with 0x7fff to prevent walking off the end
        self.cur_flips[MAX_IMAGE_FLIPS - 2] = 0x7fff
        self.cur_flips[MAX_IMAGE_FLIPS - 1] = 0x7fff
        self.ref_flips[MAX_IMAGE_FLIPS - 2] = 0x7fff  
        self.ref_flips[MAX_IMAGE_FLIPS - 1] = 0x7fff
        
        # Initialize buffer
        self.buf_index = 0
        self.bits = ctypes.c_uint32(read_motorola_long(self.src_data, 0))
        self.bit_off = ctypes.c_uint32(0)
        
        # Calculate bits needed for long horizontal code (matching JavaScript)
        # JavaScript: 32 - Math.clz32(width) = bit length needed to represent width
        if self.width == 0:
            self.h_len = 0
        else:
            self.h_len = self.width.bit_length()
    
    def decode_line(self) -> int:
        """Decode a single line of G5 data"""
        a0 = -1
        cur_index = 0
        ref_index = 0
        xsize = self.width
        h_len = self.h_len
        h_mask = (1 << h_len) - 1
        
        # Local copies - use Python ints for simpler arithmetic, wrap at the end
        bits = self.bits.value
        bit_off = self.bit_off.value  
        buf_index = self.buf_index
        
        while a0 < xsize:
            # Refill buffer if needed
            if bit_off > (REGISTER_WIDTH - 8):
                buf_index += (bit_off >> 3)
                bit_off &= 7
                if buf_index < len(self.src_data):
                    bits = read_motorola_long(self.src_data, buf_index)
            
            # Check for V(0) code (most significant bit after offset)
            # JavaScript: ((ulBits << ulBitOff) & 0x80000000) !== 0
            # Ensure 32-bit arithmetic with proper wrapping
            shifted_bits = (bits << bit_off) & 0xFFFFFFFF
            test_bit = shifted_bits & 0x80000000
            if test_bit != 0:
                # V(0) code
                a0 = self.ref_flips[ref_index]
                ref_index += 1
                self.cur_flips[cur_index] = a0
                cur_index += 1
                bit_off += 1
            else:
                # Extract code from lookup table
                # JavaScript: (ulBits >> (REGISTER_WIDTH - 8 - ulBitOff)) & 0xfe
                l_bits = (bits >> (REGISTER_WIDTH - 8 - bit_off)) & 0xfe
                s_code = CODE_TABLE[l_bits]
                bit_off += CODE_TABLE[l_bits + 1]
                
                if s_code in [1, 2, 3]:  # V(-1), V(-2), V(-3)
                    a0 = self.ref_flips[ref_index] - s_code
                    self.cur_flips[cur_index] = a0
                    cur_index += 1
                    if ref_index == 0:
                        ref_index += 2
                    ref_index -= 1
                    while a0 >= self.ref_flips[ref_index]:
                        ref_index += 2
                        
                elif s_code in [0x11, 0x12, 0x13]:  # V(1), V(2), V(3)
                    a0 = self.ref_flips[ref_index]
                    ref_index += 1
                    b1 = a0
                    a0 += s_code & 7
                    if b1 != xsize and a0 < xsize:
                        while a0 >= self.ref_flips[ref_index]:
                            ref_index += 2
                    if a0 > xsize:
                        a0 = xsize
                    self.cur_flips[cur_index] = a0
                    cur_index += 1
                    
                elif s_code == 0x20:  # Horizontal codes
                    if bit_off > (REGISTER_WIDTH - 16):
                        buf_index += (bit_off >> 3)
                        bit_off &= 7
                        if buf_index < len(self.src_data):
                            bits = read_motorola_long(self.src_data, buf_index)
                    
                    a0_p = max(0, a0)
                    l_bits = (bits >> ((REGISTER_WIDTH - 2) - bit_off)) & 0x3
                    bit_off += 2
                    
                    # Handle different horizontal code types
                    if l_bits == HORIZ_SHORT_SHORT:
                        tot_run = (bits >> ((REGISTER_WIDTH - 3) - bit_off)) & 0x7
                        bit_off += 3
                        tot_run1 = (bits >> ((REGISTER_WIDTH - 3) - bit_off)) & 0x7
                        bit_off += 3
                    elif l_bits == HORIZ_SHORT_LONG:
                        tot_run = (bits >> ((REGISTER_WIDTH - 3) - bit_off)) & 0x7
                        bit_off += 3
                        tot_run1 = (bits >> ((REGISTER_WIDTH - h_len) - bit_off)) & h_mask
                        bit_off += h_len
                    elif l_bits == HORIZ_LONG_SHORT:
                        tot_run = (bits >> ((REGISTER_WIDTH - h_len) - bit_off)) & h_mask
                        bit_off += h_len
                        tot_run1 = (bits >> ((REGISTER_WIDTH - 3) - bit_off)) & 0x7
                        bit_off += 3
                    else:  # HORIZ_LONG_LONG
                        tot_run = (bits >> ((REGISTER_WIDTH - h_len) - bit_off)) & h_mask
                        bit_off += h_len
                        if bit_off > (REGISTER_WIDTH - 16):
                            buf_index += (bit_off >> 3)
                            bit_off &= 7
                            if buf_index < len(self.src_data):
                                bits = read_motorola_long(self.src_data, buf_index)
                        tot_run1 = (bits >> ((REGISTER_WIDTH - h_len) - bit_off)) & h_mask
                        bit_off += h_len
                    
                    a0 = a0_p + tot_run
                    self.cur_flips[cur_index] = a0
                    cur_index += 1
                    a0 += tot_run1
                    
                    if a0 < xsize:
                        while a0 >= self.ref_flips[ref_index]:
                            ref_index += 2
                    self.cur_flips[cur_index] = a0
                    cur_index += 1
                    
                elif s_code == 0x30:  # Pass code
                    ref_index += 1
                    a0 = self.ref_flips[ref_index]
                    ref_index += 1
                    
                else:  # ERROR
                    self.error = G5_DECODE_ERROR
                    return self.error
        
        # Finalize line
        self.cur_flips[cur_index] = xsize
        self.cur_flips[cur_index + 1] = xsize
        
        # Update state - convert back to ctypes
        self.bits = ctypes.c_uint32(bits & 0xFFFFFFFF)
        self.bit_off = ctypes.c_uint32(bit_off)
        self.buf_index = buf_index
        
        return self.error
    
    def draw_line(self, output_buffer: bytearray, line_offset: int) -> None:
        """Draw decoded line to output buffer"""
        xright = self.width
        cur_index = 0
        
        # Calculate line length in bytes
        line_len = (xright + 7) >> 3
        
        # Initialize line to white (0xff)
        for i in range(line_len):
            output_buffer[line_offset + i] = 0xff
        
        # Note: x is not incremented in the loop, like JavaScript
        x = 0
        while x < xright:  # This continues until break condition
            start_x = self.cur_flips[cur_index]
            cur_index += 1
            run = self.cur_flips[cur_index] - start_x
            cur_index += 1
            
            if start_x >= xright or run <= 0:
                break
            
            # Calculate visible run
            visible_x = max(0, start_x)
            visible_run = min(xright, start_x + run) - visible_x
            
            if visible_run > 0:
                start_byte = visible_x >> 3
                end_byte = (visible_x + visible_run) >> 3
                
                l_bit = (0xff << (8 - (visible_x & 7))) & 0xff
                r_bit = 0xff >> ((visible_x + visible_run) & 7)
                
                if end_byte == start_byte:
                    # Run fits in single byte
                    output_buffer[line_offset + start_byte] &= (l_bit | r_bit)
                else:
                    # Mask left-most byte
                    output_buffer[line_offset + start_byte] &= l_bit
                    
                    # Set intermediate bytes to 0
                    for i in range(start_byte + 1, end_byte):
                        output_buffer[line_offset + i] = 0x00
                    
                    # Mask right-most byte if not fully aligned
                    if end_byte < line_len:
                        output_buffer[line_offset + end_byte] &= r_bit


# ============================================================================
# Image Assembly Functions
# ============================================================================

def render_16bit_rgb565(data: bytes, width: int, height: int) -> Image.Image:
    """Render 16-bit RGB565 format with scaling factors"""
    is_16_bit = len(data) == width * height * 2
    img_array = np.zeros((height, width, 3), dtype=np.uint8)
    
    for i in range(min(width * height, len(data) // (2 if is_16_bit else 1))):
        y, x = divmod(i, width)
        
        if is_16_bit:
            data_index = i * 2
            rgb = (data[data_index] << 8) | data[data_index + 1]
            
            r = ((rgb >> 11) & 0x1F) << 3
            g = ((rgb >> 5) & 0x3F) << 2
            b = (rgb & 0x1F) << 3
        else:
            rgb = data[i]
            r = int((((rgb >> 5) & 0x07) << 5) * 1.13)
            g = int((((rgb >> 2) & 0x07) << 5) * 1.13)
            b = int(((rgb & 0x03) << 6) * 1.3)
        
        img_array[y, x] = [r, g, b]
    
    return Image.fromarray(img_array, 'RGB')


def render_indexed_color(data: bytes, width: int, height: int, bpp: int, colortable: Dict[str, Any]) -> Image.Image:
    """Render 3-4 bit indexed color with bit-packed pixels"""
    img_array = np.zeros((height, width, 3), dtype=np.uint8)
    
    # Convert colortable to list format for indexing
    if isinstance(colortable, dict):
        # Handle both string keys and direct color arrays
        if 'white' in colortable:
            # Named colors
            color_list = [colortable.get('white', [255, 255, 255]),
                         colortable.get('black', [0, 0, 0]),
                         colortable.get('red', [255, 0, 0])]
        else:
            # Direct color arrays
            color_list = list(colortable.values())
    else:
        color_list = colortable
    
    pixel_index = 0
    bit_offset = 0
    
    while bit_offset < len(data) * 8 and pixel_index < width * height:
        byte_index = bit_offset >> 3
        start_bit = bit_offset & 7
        
        # Extract pixel value
        if byte_index + 1 < len(data):
            word = (data[byte_index] << 8) | data[byte_index + 1]
        else:
            word = data[byte_index] << 8
        
        pixel_value = (word >> (16 - bpp - start_bit)) & ((1 << bpp) - 1)
        
        # Map to color
        if pixel_value < len(color_list):
            color = color_list[pixel_value]
            y, x = divmod(pixel_index, width)
            img_array[y, x] = color[:3]
        
        pixel_index += 1
        bit_offset += bpp
    
    return Image.fromarray(img_array, 'RGB')


def render_monochrome_or_tricolor(data: bytes, width: int, height: int, bpp: int, colortable: Dict[str, Any]) -> Image.Image:
    """Render 1-2 bit monochrome or tricolor (B/W/R) displays"""
    img_array = np.zeros((height, width, 3), dtype=np.uint8)
    
    # Convert colortable to list format
    if isinstance(colortable, dict):
        if 'white' in colortable:
            color_list = [colortable.get('white', [255, 255, 255]),
                         colortable.get('black', [0, 0, 0]),
                         colortable.get('red', [255, 0, 0])]
        else:
            color_list = list(colortable.values())
    else:
        color_list = colortable
    
    # Detect dual-plane format - use DISPLAY dimensions like JavaScript
    # JavaScript: (data.length >= (canvas.width * canvas.height / 8) * 2)
    expected_size = (width * height) // 8
    offset_red = expected_size if len(data) >= expected_size * 2 else 0
    
    # JavaScript: for (let i = 0; i < data.length; i++)
    # But limit to canvas bounds like JavaScript imageData 
    for i in range(len(data)):
        for j in range(8):
            pixel_index = i * 8 + j
            
            # Bounds check - don't go beyond canvas
            if pixel_index >= width * height:
                continue
                
            y, x = divmod(pixel_index, width)
            
            if offset_red:
                # Dual-plane: combine black and red planes
                black_bit = 1 if (data[i] & (1 << (7 - j))) else 0
                red_bit = 1 if (data[i + offset_red] & (1 << (7 - j))) else 0
                pixel_value = black_bit | (red_bit << 1)
            else:
                # Single plane
                pixel_value = 1 if (data[i] & (1 << (7 - j))) else 0
            
            # Map to color
            if pixel_value < len(color_list):
                img_array[y, x] = color_list[pixel_value][:3]
    
    return Image.fromarray(img_array, 'RGB')



def assemble_image_from_bitmap(bitmap_data: bytes, tagtype: Dict[str, Any]) -> Image.Image:
    """
    Assemble final image from decoded bitmap data using tagtype specifications
    Supports all rendering paths: 16-bit RGB565, 3-4 bit indexed, 1-2 bit B/W/R
    """
    # JavaScript canvas dimension logic:
    # [canvas.width, canvas.height] = [tagTypes[hwtype].width, tagTypes[hwtype].height]
    canvas_width = tagtype['width']
    canvas_height = tagtype['height'] 
    
    # if (tagTypes[hwtype].rotatebuffer % 2) [canvas.width, canvas.height] = [canvas.height, canvas.width]
    rotatebuffer = tagtype.get('rotatebuffer', 0)
    if rotatebuffer % 2:
        canvas_width, canvas_height = canvas_height, canvas_width
    
    bpp = tagtype['bpp']
    colortable = tagtype.get('colortable', {})
    
    if bpp == 16:
        image = render_16bit_rgb565(bitmap_data, canvas_width, canvas_height)
    elif bpp in [3, 4]:
        image = render_indexed_color(bitmap_data, canvas_width, canvas_height, bpp, colortable)
    else:  # bpp in [1, 2]
        image = render_monochrome_or_tricolor(bitmap_data, canvas_width, canvas_height, bpp, colortable)
    
    # Apply final rotation for display based on rotatebuffer
    # JavaScript: if (doRotate == false && tagTypes[hwtype].rotatebuffer == 1) canvas.style.transform = 'rotate(90deg)'
    if rotatebuffer == 1:
        # 90 degrees clockwise (to the right)
        image = image.transpose(Image.ROTATE_270)  # PIL ROTATE_270 = 90° clockwise
    elif rotatebuffer == 2:
        # 180 degrees
        image = image.transpose(Image.ROTATE_180)
    elif rotatebuffer == 3:
        # 270 degrees clockwise = 90 degrees counter-clockwise  
        image = image.transpose(Image.ROTATE_90)
    
    return image


# ============================================================================
# Main Interface
# ============================================================================

def decode_g5_to_bitmap(data: bytes, width: int, height: int) -> bytes:
    """Core G5 decoding function - returns raw bitmap bytes"""
    decoder = G5Decoder()
    
    # Initialize decoder
    init_result = decoder.init_decoder(width, height, data)
    if init_result != G5_SUCCESS:
        error_map = {
            G5_INVALID_PARAMETER: G5InvalidParameterError("Invalid decoder parameters")
        }
        raise error_map.get(init_result, G5DecoderError(f"Decoder initialization failed: {init_result}"))
    
    # Begin decoding
    decoder.decode_begin()
    
    # Calculate output buffer size (1 bit per pixel, padded to byte boundary)
    bytes_per_line = (width + 7) // 8
    output_buffer = bytearray(height * bytes_per_line)
    
    # Decode each line
    for y in range(height):
        decoder.y = y
        decode_result = decoder.decode_line()
        
        if decode_result != G5_SUCCESS:
            raise G5DecodeError(f"Decoding error on line {y}: {decode_result}")
        
        decoder.draw_line(output_buffer, y * bytes_per_line)
        
        # Swap current and reference flip arrays
        decoder.cur_flips, decoder.ref_flips = decoder.ref_flips, decoder.cur_flips
    
    return bytes(output_buffer)


def process_g5(data: bytes, tagtype: Dict[str, Any], output_format: str = 'pil') -> Union[Image.Image, bytes]:
    """
    Main entry point for G5 decoding and image assembly
    
    Args:
        data: Raw G5 compressed image data
        tagtype: Tag type specification dictionary
        output_format: 'pil' for PIL Image, 'bytes' for raw bitmap
        
    Returns:
        PIL Image or raw bytes depending on output_format
    """
    if not data or not tagtype:
        raise G5InvalidParameterError("Data and tagtype must be provided")
    
    # Parse header
    header_size, width, height, compression_mode = parse_g5_header(data)
    
    # Validate against tagtype (before doubling, matching JavaScript)
    validate_header_against_tagtype(width, height, tagtype)
    
    # Apply compression mode 2 doubling AFTER validation (matching JavaScript)
    if compression_mode == 2:
        height *= 2
    
    # Extract payload data (skip header)
    payload_data = data[header_size:]
    
    # Decode G5 compressed data to bitmap
    bitmap_data = decode_g5_to_bitmap(payload_data, width, height)
    
    if output_format == 'bytes':
        return bitmap_data
    elif output_format == 'pil':
        # JavaScript uses tagtype dimensions for offsetRed calculation and display
        return assemble_image_from_bitmap(bitmap_data, tagtype)
    else:
        raise G5InvalidParameterError(f"Unsupported output format: {output_format}")


def load_tagtype_from_file(filename: str) -> Dict[str, Any]:
    """Load tagtype specification from JSON file"""
    with open(filename, 'r') as f:
        return json.load(f)


# ============================================================================
# Testing/CLI Interface
# ============================================================================

def main():
    """Command-line interface for testing"""
    import sys
    
    if len(sys.argv) != 3:
        print("Usage: python g5_decoder.py <g5_file> <tagtype_file>")
        sys.exit(1)
    
    g5_file, tagtype_file = sys.argv[1], sys.argv[2]
    
    try:
        # Load files
        with open(g5_file, 'rb') as f:
            g5_data = f.read()
        
        tagtype = load_tagtype_from_file(tagtype_file)
        
        # Process G5 image
        image = process_g5(g5_data, tagtype)
        
        # Save result
        output_file = f"{g5_file}_decoded.png"
        image.save(output_file)
        print(f"Decoded image saved as: {output_file}")
        print(f"Image size: {image.size}")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()