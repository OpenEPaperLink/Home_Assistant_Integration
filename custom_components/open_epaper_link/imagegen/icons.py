from __future__ import annotations

import os
import json
import logging

from PIL import ImageDraw, ImageFont
from homeassistant.exceptions import HomeAssistantError

from .registry import element_handler
from .types import ElementType, DrawingContext
from ..const import DOMAIN


_LOGGER = logging.getLogger(__name__)
_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")


@element_handler(ElementType.ICON, requires=["x", "y", "value", "size"])
async def draw_icon(ctx: DrawingContext, element: dict) -> None:
    """
    Draw Material Design Icons.

    Renders an icon from the Material Design Icons font at the specified
    position and size.

    Args:
        ctx: Drawing context
        element: Element dictionary with icon properties
        pos_y: Current Y position for automatic positioning
    Raises:
        HomeAssistantError: If icon name is invalid or rendering fails
    """
    draw = ImageDraw.Draw(ctx.img)
    draw.fontmode = "1"  # Enable high quality font rendering

    # Coordinates
    x = ctx.coords.parse_x(element['x'])
    y = ctx.coords.parse_y(element['y'])

    # Load MDI font and metadata
    font_file = os.path.join(_ASSETS_DIR, "materialdesignicons-webfont.ttf")
    meta_file = os.path.join(_ASSETS_DIR, "materialdesignicons-webfont_meta.json")

    try:
        def load_meta():
            with open(meta_file, 'r', encoding='utf-8') as f:
                return json.load(f)

        mdi_data = await ctx.hass.async_add_executor_job(load_meta)
    except Exception as e:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="mdi_metadata_failed",
            translation_placeholders={"error": str(e)}
        )

    # Find icon codepoint
    icon_name = element['value']
    if icon_name.startswith("mdi:"):
        icon_name = icon_name[4:]

    chr_hex = None
    # Search direct matches
    for icon in mdi_data:
        if icon['name'] == icon_name:
            chr_hex = icon['codepoint']
            break

    # Search aliases if no direct match
    if not chr_hex:
        for icon in mdi_data:
            if 'aliases' in icon and icon_name in icon['aliases']:
                chr_hex = icon['codepoint']
                break

    if not chr_hex:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="icon_name_invalid",
            translation_placeholders={"icon_name": icon_name}
        )

    # Get icon properties
    def load_font():
        return ImageFont.truetype(font_file, element['size'])

    font = await ctx.hass.async_add_executor_job(load_font)
    anchor = element.get('anchor', "la")
    fill = ctx.colors.resolve(
        element.get('color') or element.get('fill', "black")
    )
    stroke_width = element.get('stroke_width', 0)
    stroke_fill = ctx.colors.resolve(element.get('stroke_fill', 'white'))

    # Draw icon
    try:
        draw.text(
            (x, y),
            chr(int(chr_hex, 16)),
            fill=fill,
            font=font,
            anchor=anchor,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill
        )
    except ValueError as e:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="icon_draw_failed",
            translation_placeholders={"error": str(e)}
        )

    # Calculate vertical position using text bounds
    bbox = draw.textbbox(
        (x, y),
        chr(int(chr_hex, 16)),
        font=font,
        anchor=anchor
    )
    ctx.pos_y = bbox[3]

    #TODO ask if things could be simplified by reusing icon sequence for single icon or too much overhead?


@element_handler(ElementType.ICON_SEQUENCE, requires=["x", "y", "icons", "size"])
async def draw_icon_sequence(ctx: DrawingContext, element: dict) -> None:
    """
    Draw a sequence of icons in a specified direction.

    Renders multiple icons in a sequence with consistent spacing,
    useful for creating icon-based status indicators or legends.

    Args:
        ctx: Drawing context
        element: Element dictionary with icon sequence properties
    Raises:
        HomeAssistantError: If icon names are invalid or rendering fails
    """
    draw = ImageDraw.Draw(ctx.img)
    draw.fontmode = "1"  # Enable high quality font rendering

    # Get basic coordinates and properties
    x_start = ctx.coords.parse_x(element['x'])
    y_start = ctx.coords.parse_y(element['y'])
    size = element['size']
    spacing = element.get('spacing', size // 4)  # Default spacing is 1/4 of icon size
    fill = ctx.colors.resolve(element.get('fill', "black"))
    anchor = element.get('anchor', "la")
    stroke_width = element.get('stroke_width', 0)
    stroke_fill = ctx.colors.resolve(element.get('stroke_fill', 'white'))
    direction = element.get('direction', 'right')  # right, down, up, left

    # Load MDI font and metadata
    font_file = os.path.join(_ASSETS_DIR, "materialdesignicons-webfont.ttf")
    meta_file = os.path.join(_ASSETS_DIR, "materialdesignicons-webfont_meta.json")

    try:
        def load_meta():
            with open(meta_file, 'r', encoding='utf-8') as f:
                return json.load(f)

        mdi_data = await ctx.hass.async_add_executor_job(load_meta)
    except Exception as e:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="mdi_metadata_failed",
            translation_placeholders={"error": str(e)}
        )

    # Load font
    def load_font():
        return ImageFont.truetype(font_file, size)

    font = await ctx.hass.async_add_executor_job(load_font)

    max_y = y_start
    max_x = x_start
    current_x = x_start
    current_y = y_start

    # Draw each icon in sequence
    for icon_name in element['icons']:
        if icon_name.startswith("mdi:"):
            icon_name = icon_name[4:]

        # Find icon codepoint
        chr_hex = None
        # Search direct matches
        for icon in mdi_data:
            if icon['name'] == icon_name:
                chr_hex = icon['codepoint']
                break

        # Search aliases if no direct match
        if not chr_hex:
            for icon in mdi_data:
                if 'aliases' in icon and icon_name in icon['aliases']:
                    chr_hex = icon['codepoint']
                    break

        if not chr_hex:
            _LOGGER.warning(f"Invalid icon name: {icon_name}")
            continue

        # Draw icon
        try:
            draw.text(
                (current_x, current_y),
                chr(int(chr_hex, 16)),
                fill=fill,
                font=font,
                anchor=anchor,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill
            )
            # Calculate bounds for this icon
            bbox = draw.textbbox(
                (current_x, current_y),
                chr(int(chr_hex, 16)),
                font=font,
                anchor=anchor
            )
            max_y = max(max_y, bbox[3])
            max_x = max(max_x, bbox[2])

            # Move to next position based on direction
            if direction == 'right':
                current_x += size + spacing
            elif direction == 'left':
                current_x -= size + spacing
            elif direction == 'down':
                current_y += size + spacing
            elif direction == 'up':
                current_y -= size + spacing

        except ValueError as e:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="icon_draw_failed_named",
                translation_placeholders={"icon_name": icon_name, "error": str(e)}
            )

    ctx.pos_y = max(max_y, current_y)
