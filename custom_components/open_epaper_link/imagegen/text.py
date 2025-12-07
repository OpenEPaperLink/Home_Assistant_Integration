from __future__ import annotations

import re
import logging
from typing import List, Tuple

from PIL import ImageDraw, ImageFont

from .registry import element_handler
from .types import ElementType, DrawingContext, TextSegment

_LOGGER = logging.getLogger(__name__)


@element_handler(ElementType.TEXT, requires=["x", "value"])
async def draw_text(ctx: DrawingContext, element: dict) -> None:
    """Draw (coloured) text with optional wrapping or ellipsis.

    Renders text with support for multiple formatting options:

    - Color markup with [color]text[/color] syntax
    - Text wrapping based on max_width
    - Text truncation with ellipsis
    - Multiple anchoring options
    - Font selection and sizing

    Args:
        ctx: Drawing context
        element: Element dictionary with text properties
    """
    draw = ImageDraw.Draw(ctx.img)
    draw.fontmode = "1"

    x = ctx.coords.parse_x(element['x'])
    if "y" not in element:
        y = ctx.pos_y + element.get('y_padding', 10)
    else:
        y = ctx.coords.parse_y(element['y'])
    # Get text properties
    size = ctx.coords.parse_size(element.get('size', 20), is_width=False)
    font_name = element.get('font', "ppb.ttf")
    font = ctx.fonts.get_font(font_name, size)

    # Get alignment and default color
    align = element.get('align', "left")
    default_color = ctx.colors.resolve(element.get('color', "black"))
    anchor = element.get('anchor')
    spacing = element.get('spacing', 5)
    stroke_width = element.get('stroke_width', 0)
    stroke_fill = ctx.colors.resolve(element.get('stroke_fill', 'white'))

    # Process text content
    text = str(element['value'])
    max_width = element.get('max_width')

    # Handle text wrapping if max_width is specified
    final_text = text
    if max_width is not None:
        if element.get('truncate', False):
            if draw.textlength(text, font=font) > max_width:
                ellipsis = "..."
                truncated = text
                while truncated and draw.textlength(truncated + ellipsis, font=font) > max_width:
                    truncated = truncated[:-1]
                final_text = truncated + ellipsis
        else:
            words = text.split()
            lines = []
            current_line = []

            for word in words:
                test_line = ' '.join(current_line + [word])
                if not current_line or draw.textlength(test_line, font=font) <= max_width:
                    current_line.append(word)
                else:
                    lines.append(' '.join(current_line))
                    current_line = [word]

            if current_line:
                lines.append(' '.join(current_line))
            final_text = '\n'.join(lines)

    # Set appropriate anchor based on line count
    if not anchor:
        anchor = 'la' if '\n' in final_text else 'lt'

    # Draw the text
    if element.get('parse_colors', False):
        segments = parse_colored_text(final_text)
        segments, total_width = calculate_segment_positions(
            segments, font, x, align
        )

        max_y = y
        for segment in segments:
            color = ctx.colors.resolve(segment.color)
            bbox = draw.textbbox(
                (segment.start_x, y),
                segment.text,
                font=font,
                anchor=anchor
            )
            draw.text(
                (segment.start_x, y),
                segment.text,
                fill=color,
                font=font,
                anchor=anchor,
                spacing=spacing,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill
            )
            max_y = max(max_y, bbox[3])
        ctx.pos_y = max_y
    else:
        bbox = draw.textbbox(
            (x, y),
            final_text,
            font=font,
            anchor=anchor,
            spacing=spacing,
            align=align
        )
        draw.text(
            (x, y),
            final_text,
            fill=default_color,
            font=font,
            anchor=anchor,
            align=align,
            spacing=spacing,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill
        )
        ctx.pos_y = bbox[3]


@element_handler(ElementType.MULTILINE, requires=["x", "value", "delimiter", "offset_y"])
async def draw_multiline(ctx: DrawingContext, element: dict) -> None:
    """Draw multiline text with delimiter.

    Renders multiple lines of text separated by a delimiter character.
    Supports similar formatting options as the _draw_text method.

    Args:
        ctx: Drawing context
        element: Element dictionary with multiline text properties
    """
    draw = ImageDraw.Draw(ctx.img)
    draw.fontmode = "1"

    # Get text properties
    size = element.get('size', 20)
    font_name = element.get('font', "ppb.ttf")
    font = ctx.fonts.get_font(font_name, size)
    color = ctx.colors.resolve(element.get('color', "black"))
    align = element.get('align', "left")
    anchor = element.get('anchor', "lm")
    stroke_width = element.get('stroke_width', 0)
    stroke_fill = ctx.colors.resolve(element.get('stroke_fill', 'white'))

    # Split text using delimiter
    lines = element['value'].replace("\n", "").split(element["delimiter"])
    current_y = element.get('start_y', ctx.pos_y + element.get('y_padding', 10))

    max_y = current_y
    for line in lines:
        if element.get('parse_colors', False):
            segments = parse_colored_text(str(line))
            segments, total_width = calculate_segment_positions(
                segments, font, element["x"], align
            )

            for segment in segments:
                color = ctx.colors.resolve(segment.color)
                bbox = draw.textbbox(
                    (segment.start_x, current_y),
                    segment.text,
                    font=font,
                    anchor=anchor
                )
                draw.text(
                    (segment.start_x, current_y),
                    segment.text,
                    fill=color,
                    font=font,
                    anchor=anchor,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_fill
                )
        else:
            bbox = draw.textbbox(
                (element['x'], current_y),
                str(line),
                font=font,
                anchor=anchor,
                align=align
            )
            draw.text(
                (element['x'], current_y),
                str(line),
                fill=color,
                font=font,
                anchor=anchor,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill
            )
        current_y += element['offset_y']
        max_y = current_y

    ctx.pos_y = max_y


def get_wrapped_text(text: str, font: ImageFont.ImageFont, line_length: int) -> str:
    """Wrap text to fit within a given width.

    Breaks text into multiple lines to fit within the specified width.

    Args:
        text: Text to wrap
        font: Font to measure text width with
        line_length: Maximum line length in pixels

    Returns:
        str: Text with newlines inserted for wrapping
    """
    lines = ['']
    for word in text.split():
        line = f'{lines[-1]} {word}'.strip()
        if font.getlength(line) <= line_length:
            lines[-1] = line
        else:
            lines.append(word)
    return '\n'.join(lines)


def parse_colored_text(text: str) -> List[TextSegment]:
    """Parse text with color markup into text segments.

    Breaks text with color markup like "[red]text[/red]" into segments
    with associated colors.

    Args:
        text: Text with color markup

    Returns:
        List[TextSegment]: List of text segments with colors
    """

    segments = []
    current_pos = 0
    pattern = r'\[(black|white|red|yellow|accent|half_black|half_red|half_yellow|half_accent|gray|grey|g|hb|hr|hy|ha)\](.*?)\[/\1\]'

    for match in re.finditer(pattern, text):
        # Add any text before the match with default color
        if match.start() > current_pos:
            segments.append(
                TextSegment(
                    text=text[current_pos:match.start()],
                    color="black"
                ))
        # Add the matched text with the specified color
        segments.append(
            TextSegment(
                text=match.group(2),
                color=match.group(1)
            )
        )
        current_pos = match.end()

    # Add any remaining text with default color
    if current_pos < len(text):
        segments.append(TextSegment(
            text=text[current_pos:],
            color="black"
        ))

    return segments


def calculate_segment_positions(
        segments: List[TextSegment],
        font: ImageFont.FreeTypeFont,
        start_x: int,
        alignment: str = "left"
) -> Tuple[List[TextSegment], float]:
    """Calculate x positions for each text segment based on alignment.

    Determines the starting x position for each text segment based on
    the overall alignment and font metrics.

    Args:
        segments: List of text segments
        font: Font to measure text width with
        start_x: Base starting x position
        alignment: Text alignment (left, center, right)

    Returns:
        tuple: (modified segments with positions, total width)
    """

    total_width = sum(font.getlength(segment.text) for segment in segments)

    current_x = start_x
    match alignment.lower():
        case "left":
            pass  # start_x is already correct
        case "center":
            current_x -= total_width / 2
        case "right":
            current_x -= total_width
        case _:
            # Default to left alignment for unknown values
            _LOGGER.warning("Unknown alignment '%s', defaulting to left", alignment)

    for segment in segments:
        segment.start_x = int(current_x)
        current_x += font.getlength(segment.text)

    return segments, total_width
