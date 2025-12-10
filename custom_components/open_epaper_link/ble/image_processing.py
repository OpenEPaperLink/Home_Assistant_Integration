import numpy as np
from PIL import Image

from .color_scheme import ColorScheme


def perceptual_color_distance(c1_rgb: tuple[int, int, int], c2_rgb: tuple[int, int, int]) -> float:
    """
    Calculate weighted perceptual RGB distance with grayscale protection.

    Uses the formula from makeimage.cpp: 3×Δr² + 5.47×Δg² + 1.53×Δb²
    This weights green heavily (human eyes are most sensitive to green).

    Grayscale protection prevents gray pixels from matching to colors,
    which would cause unwanted color tinting in neutral areas.

    Args:
        c1_rgb: Source pixel RGB tuple
        c2_rgb: Palette color RGB tuple

    Returns:
        Perceptual distance, or infinity if grayscale protection triggers
    """

    r1, g1, b1 = int(c1_rgb[0]), int(c1_rgb[1]), int(c1_rgb[2])
    r2, g2, b2 = int(c2_rgb[0]), int(c2_rgb[1]), int(c2_rgb[2])

    # Grayscale protection: reject color matches for grayscale source pixels
    # A pixel is considered grayscale if R, G, B are all within 20 of each other
    is_source_gray = abs(r1 - g1) < 20 and abs(b1 - g1) < 20
    # A palette color is considered chromatic if any channel differs by >20
    is_target_color = abs(r2 - g2) > 20 or abs(b2 - g2) > 20

    if is_source_gray and is_target_color:
        return float('inf')

    # Perceptual weighting from makeimage.cpp
    return 3.0 * (r1 - r2) ** 2 + 5.47 * (g1 - g2) ** 2 + 1.53 * (b1 - b2) ** 2


def find_closest_color(pixel_rgb: tuple[int, int, int], palette: list[tuple[int, int, int]]) -> tuple[tuple[int, int, int], int]:
    """
    Find the closest palette color using perceptual distance.

    Args:
        pixel_rgb: Source pixel RGB tuple
        palette: List of palette RGB tuples

    Returns:
        Tuple of (closest_color_rgb, palette_index)
    """

    min_dist = float('inf')
    closest = palette[0]
    closest_idx = 0

    for idx, color in enumerate(palette):
        dist = perceptual_color_distance(pixel_rgb, color)
        if dist < min_dist:
            min_dist = dist
            closest = color
            closest_idx = idx

    return closest, closest_idx

def apply_direct_mapping(image: Image.Image, color_scheme: ColorScheme) -> Image.Image:
    """
    Apply direct color mapping without dithering.

    Each pixel is mapped to its perceptually closest palette color.
    Fast but can produce harsh banding on gradients.

    Args:
        image: PIL Image in RGB mode
        color_scheme: ColorScheme enum for palette

    Returns:
        Quantized PIL Image
    """
    # Convert to RGB if needed
    if image.mode != 'RGB':
        image = image.convert('RGB')

    # Get palette as list of RGB tuples
    palette = list(color_scheme.palette.colors.values())

    pixels = np.array(image)
    height, width = pixels.shape[:2]
    result = np.zeros_like(pixels)

    for y in range(height):
        for x in range(width):
            pixel = tuple(int(x) for x in pixels[y, x])
            closest, _ = find_closest_color(pixel, palette)
            result[y, x] = closest

    return Image.fromarray(result, 'RGB')

def apply_burkes_dithering(image: Image.Image, color_scheme: ColorScheme) -> Image.Image:
    """
    Apply Burkes error diffusion dithering.

    Burkes dithering distributes quantization error to neighboring pixels,
    creating smooth gradients. Best for photographs and images with gradients.

    Error diffusion pattern (Burkes):
              X   8/32  4/32
      2/32  4/32  8/32  4/32  2/32

    Args:
        image: PIL Image in RGB mode
        color_scheme: ColorScheme enum for palette

    Returns:
        Dithered PIL Image quantized to palette colors
    """

    # Convert to RGB if needed
    if image.mode != 'RGB':
        image = image.convert('RGB')

    # Get palette as list of RGB tuples
    palette = list(color_scheme.palette.colors.values())

    # Convert to float array for error accumulation
    pixels = np.array(image, dtype=np.float32)
    height, width = pixels.shape[:2]

    # Process each pixel
    for y in range(height):
        for x in range(width):
            old_pixel = tuple(int(c) for c in np.clip(pixels[y, x], 0, 255))
            new_pixel, _ = find_closest_color(old_pixel, palette)

            # Calculate quantization error
            error = np.array(old_pixel, dtype=np.float32) - np.array(new_pixel, dtype=np.float32)

            # Set the quantized pixel
            pixels[y, x] = new_pixel

            # Distribute error using Burkes pattern
            if x + 1 < width:
                pixels[y, x + 1] += error * (8 / 32)
            if x + 2 < width:
                pixels[y, x + 2] += error * (4 / 32)

            if y + 1 < height:
                if x - 2 >= 0:
                    pixels[y + 1, x - 2] += error * (2 / 32)
                if x - 1 >= 0:
                    pixels[y + 1, x - 1] += error * (4 / 32)
                pixels[y + 1, x] += error * (8 / 32)
                if x + 1 < width:
                    pixels[y + 1, x + 1] += error * (4 / 32)
                if x + 2 < width:
                    pixels[y + 1, x + 2] += error * (2 / 32)

    # Convert back to uint8 image
    result = np.clip(pixels, 0, 255).astype(np.uint8)
    return Image.fromarray(result, 'RGB')


def apply_ordered_dithering(image: Image.Image, color_scheme: ColorScheme) -> Image.Image:
    """
    Apply ordered (Bayer) dithering with adaptive thresholds.

    Ordered dithering uses a fixed threshold pattern, creating regular
    halftone-like patterns. Best for text, icons, and sharp edges.

    Uses a 4x4 Bayer matrix for threshold generation.

    Args:
        image: PIL Image in RGB mode
        color_scheme: ColorScheme enum for palette

    Returns:
        Dithered PIL Image quantized to palette colors
    """
    # Convert to RGB if needed
    if image.mode != 'RGB':
        image = image.convert('RGB')

    # Get palette as list of RGB tuples
    palette = list(color_scheme.palette.colors.values())

    # 4x4 Bayer matrix (normalized to 0-1 range)
    bayer_4x4 = np.array([
        [0, 8, 2, 10],
        [12, 4, 14, 6],
        [3, 11, 1, 9],
        [15, 7, 13, 5]
    ], dtype=np.float32) / 16.0

    pixels = np.array(image, dtype=np.float32)
    height, width = pixels.shape[:2]

    # Tile the Bayer matrix across the image
    bayer_tiled = np.tile(bayer_4x4, (height // 4 + 1, width // 4 + 1))[:height, :width]

    # Apply threshold adjustment per channel
    # Scale factor determines dithering intensity (32 is moderate)
    scale = 32.0
    for c in range(3):
        pixels[:, :, c] += (bayer_tiled - 0.5) * scale

    # Quantize each pixel to nearest palette color
    result = np.zeros_like(pixels, dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            pixel = tuple(int(c) for c in np.clip(pixels[y, x], 0, 255))
            closest, _ = find_closest_color(pixel, palette)
            result[y, x] = closest

    return Image.fromarray(result, 'RGB')


def process_image_for_device(image, color_scheme: int, dither: int = 2) -> Image.Image:
    """
    Process image for BLE device display.

    Main entry point for image processing. Applies dithering and color
    quantization based on device color scheme and dither mode.

    Args:
        image: PIL Image to process
        color_scheme: Color scheme int (0-5) matching ColorScheme enum values
        dither: Dithering mode:
            0 = None (direct mapping)
            1 = Burkes error diffusion (best for photos)
            2 = Ordered/Bayer (best for text/icons, default)

    Returns:
        Processed PIL Image with pixels quantized to palette colors
    """
    scheme = ColorScheme.from_int(color_scheme)

    if dither == 1:
        return apply_burkes_dithering(image, scheme)
    elif dither == 2:
        return apply_ordered_dithering(image, scheme)
    else:
        return apply_direct_mapping(image, scheme)
