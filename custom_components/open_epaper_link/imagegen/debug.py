from __future__ import annotations

from PIL import ImageDraw

from .registry import element_handler
from .shapes import draw_dashed_line
from .types import ElementType, DrawingContext


@element_handler(ElementType.DEBUG_GRID)
async def draw_debug_grid(ctx: DrawingContext, element: dict) -> None:
    """
    Draw debug grid for layout assistance.

    Renders a grid with optional coordinate labels to help with positioning
    other elements during development.

    Args:
        ctx: Drawing context
        element: Element dictionary with debug grid properties
    """
    draw = ImageDraw.Draw(ctx.img)
    width, height = ctx.img.size

    spacing = element.get("spacing", 20)
    line_color = ctx.colors.resolve(element.get("line_color", "black"))
    dashed = element.get("dashed", True)
    dash_length = element.get("dash_length", 2)
    space_length = element.get("space_length", 4)

    show_labels = element.get("show_labels", True)
    label_step = element.get("label_step", spacing * 2)
    label_color = ctx.colors.resolve(element.get("label_color", "black"))
    label_font_size = element.get("label_font_size", 12)
    font_name = element.get("font", "ppb.ttf")
    font = ctx.fonts.get_font(font_name, label_font_size)

    # Helper to draw one line as dashed or solid
    def draw_line_segment(p1, p2):
        if dashed:
            draw_dashed_line(
                draw,
                p1,
                p2,
                dash_length,
                space_length,
                fill=line_color,
                width=1
            )
        else:
            draw.line([p1, p2], fill=line_color, width=1)

    # Horizontal lines
    for y in range(0, height, spacing):
        draw_line_segment((0, y), (width, y))

        # Labels
        if show_labels and (y % label_step == 0):
            label_text = str(y)
            # Slight offset so text isn't on the line
            draw.text((2, y + 2), label_text, fill=label_color, font=font)

    # Vertical lines
    for x in range(0, width, spacing):
        draw_line_segment((x, 0), (x, height))

        # Labels
        if show_labels and (x % label_step == 0):
            label_text = str(x)
            draw.text((x + 2, 2), label_text, fill=label_color, font=font)

    ctx.pos_y = height


# TODO: maybe add a debug function for colors?