from __future__ import annotations

import logging

from PIL import ImageDraw

from .colors import BLACK
from .registry import element_handler
from .types import ElementType, DrawingContext

_LOGGER = logging.getLogger(__name__)


@element_handler(ElementType.LINE, requires=["x_start", "x_end"])
async def draw_line(ctx: DrawingContext, element: dict) -> None:
    """
    Draw line element.

    Renders a straight line between two points, with options for color,
    thickness, and dashed style.

    Args:
        ctx: Drawing context
        element: Element dictionary with line properties
    """
    draw = ImageDraw.Draw(ctx.img)

    # Get vertical position
    if "y_start" not in element:
        y_start = ctx.pos_y + element.get("y_padding", 0)
        y_end = y_start
    else:
        y_start = element["y_start"]
        y_end = element.get("y_end", y_start)

    # Get line properties
    fill = ctx.colors.resolve(element.get('fill', "black"))
    width = element.get('width', 1)
    dashed = element.get('dashed', False)
    dash_length = element.get('dash_length', 5)
    space_length = element.get('space_length', 3)

    x_start = element["x_start"]
    x_end = element["x_end"]

    if dashed:
        draw_dashed_line(
            draw,
            (x_start, y_start),
            (x_end, y_end),
            dash_length,
            space_length,
            fill, width)
    else:
        draw.line(
            [(element['x_start'], y_start), (element['x_end'], y_end)],
            fill=fill,
            width=width
        )

    ctx.pos_y = max(y_start, y_end)


@element_handler(ElementType.RECTANGLE, requires=["x_start", "x_end", "y_start", "y_end"])
async def draw_rectangle(ctx: DrawingContext, element: dict) -> None:
    """
    Draw rectangle element.

    Renders a rectangle with options for fill, outline, and rounded corners.

    Args:
        ctx: Drawing context
        element: Element dictionary with rectangle properties
    """
    draw = ImageDraw.Draw(ctx.img)

    # Coordinates
    x_start = ctx.coords.parse_x(element['x_start'])
    x_end = ctx.coords.parse_x(element['x_end'])
    y_start = ctx.coords.parse_y(element['y_start'])
    y_end = ctx.coords.parse_y(element['y_end'])

    # Get rectangle properties
    rect_fill = ctx.colors.resolve(element.get('fill'))
    rect_outline = ctx.colors.resolve(element.get('outline', "black"))
    rect_width = element.get('width', 1)
    radius = element.get('radius', 10 if 'corners' in element else 0)
    corners = get_rounded_corners(
        element.get('corners', "all" if 'radius' in element else "")
    )

    # Draw rectangle
    draw.rounded_rectangle(
        (x_start, y_start, x_end, y_end),
        fill=rect_fill,
        outline=rect_outline,
        width=rect_width,
        radius=radius,
        corners=corners
    )

    ctx.pos_y = y_end


@element_handler(ElementType.RECTANGLE_PATTERN, requires=["x_start", "x_size", "y_start", "y_size", "x_repeat", "y_repeat", "x_offset", "y_offset"])
async def draw_rectangle_pattern(ctx: DrawingContext, element: dict) -> None:
    """
    Draw repeated rectangle pattern.

    Renders a grid of rectangles with consistent spacing, useful for
    creating regular patterns or grids.

    Args:
        ctx: Drawing context
        element: Element dictionary with rectangle pattern properties
    """
    draw = ImageDraw.Draw(ctx.img)

    # Get pattern properties
    fill = ctx.colors.resolve(element.get('fill'))
    outline = ctx.colors.resolve(element.get('outline', "black"))
    width = element.get('width', 1)
    radius = element.get('radius', 10 if 'corners' in element else 0)
    corners = get_rounded_corners(
        element.get('corners', "all" if 'radius' in element else "")
    )

    max_y = element['y_start']

    # Draw rectangle grid
    for x in range(element["x_repeat"]):
        for y in range(element["y_repeat"]):
            # Calculate rectangle position
            x_pos = element['x_start'] + x * (element['x_offset'] + element['x_size'])
            y_pos = element['y_start'] + y * (element['y_offset'] + element['y_size'])

            # Draw individual rectangle
            draw.rounded_rectangle(
                (x_pos, y_pos,
                 x_pos + element['x_size'],
                 y_pos + element['y_size']),
                fill=fill,
                outline=outline,
                width=width,
                radius=radius,
                corners=corners
            )

            max_y = max(max_y, y_pos + element['y_size'])

    ctx.pos_y = max_y


@element_handler(ElementType.POLYGON, requires=["points"])
async def draw_polygon(ctx: DrawingContext, element: dict) -> None:
    """Draw a polygon.

    Renders a polygon defined by a list of vertex coordinates.

    Args:
        ctx: Drawing context
        element: Element dictionary with polygon properties
    """
    draw = ImageDraw.Draw(ctx.img)

    # Parse vertices
    vertices = [
        (ctx.coords.parse_x(x), ctx.coords.parse_y(y))
        for x, y in element["points"]
    ]

    # Get polygon properties
    fill = ctx.colors.resolve(element.get("fill"))
    outline = ctx.colors.resolve(element.get("outline", "black"))
    width = element.get("width", 1)

    # Draw the polygon
    draw.polygon(vertices, fill=fill, outline=outline)

    if vertices:
        ctx.pos_y = max(v[1] for v in vertices)


@element_handler(ElementType.CIRCLE, requires=["x", "y", "radius"])
async def draw_circle(ctx: DrawingContext, element: dict) -> None:
    """Draw circle element.

    Renders a circle with options for fill and outline.

    Args:
        ctx: Drawing Context
        element: Element dictionary with circle properties
    """
    draw = ImageDraw.Draw(ctx.img)

    # Coordinates
    x = ctx.coords.parse_x(element['x'])
    y = ctx.coords.parse_y(element['y'])

    # Get circle properties
    fill = ctx.colors.resolve(element.get('fill'))
    outline = ctx.colors.resolve(element.get('outline', "black"))
    width = element.get('width', 1)

    # Draw circle
    draw.ellipse(
        [(x - element['radius'], y - element['radius']), (x + element['radius'], y + element['radius'])],
        fill=fill,
        outline=outline,
        width=width
    )

    ctx.pos_y = y + element['radius']


@element_handler(ElementType.ELLIPSE, requires=["x_start", "x_end", "y_start", "y_end"])
async def draw_ellipse(ctx: DrawingContext, element: dict) -> None:
    """
    Draw ellipse element.

    Renders an ellipse with options for fill and outline.

    Args:
        ctx: Drawing context
        element: Element dictionary with ellipse properties
    """
    draw = ImageDraw.Draw(ctx.img)

    # Coordinates
    x_start = ctx.coords.parse_x(element['x_start'])
    x_end = ctx.coords.parse_x(element['x_end'])
    y_start = ctx.coords.parse_y(element['y_start'])
    y_end = ctx.coords.parse_y(element['y_end'])

    # Get ellipse properties
    fill = ctx.colors.resolve(element.get('fill'))
    outline = ctx.colors.resolve(element.get('outline', "black"))
    width = element.get('width', 1)

    # Draw ellipse
    draw.ellipse(
        [(x_start, y_start), (x_end, y_end)],
        fill=fill,
        outline=outline,
        width=width
    )

    ctx.pos_y = y_end


@element_handler(ElementType.ARC, requires=["x", "y", "radius", "start_angle", "end_angle"])
async def draw_arc(ctx: DrawingContext, element: dict) -> None:
    """Draw an arc or pie slice.

    Renders an arc (outline) or pie slice (filled) based on center point,
    radius, and angle range.

    Args:
        ctx: Drawing context
        element: Element dictionary with arc properties
    """
    draw = ImageDraw.Draw(ctx.img)

    # Parse center coordinates and radius
    x = ctx.coords.parse_x(element["x"])
    y = ctx.coords.parse_y(element["y"])
    radius = ctx.coords.parse_size(element["radius"], is_width=True)

    # Parse angles
    start_angle = element["start_angle"]
    end_angle = element["end_angle"]

    # Calculate bounding box of the circle/ellipse
    bbox = [
        (x - radius, y - radius),
        (x + radius, y + radius)
    ]

    # Get arc properties
    fill = ctx.colors.resolve(element.get("fill"))  # Used for pie slices
    outline = ctx.colors.resolve(element.get("outline", "black"))
    width = element.get("width", 1)

    # Draw the arc
    if fill:
        # Filled pie slice
        draw.pieslice(
            bbox,
            start=start_angle,
            end=end_angle,
            fill=fill,
            outline=outline
        )
    else:
        # Outline-only arc
        draw.arc(
            bbox,
            start=start_angle,
            end=end_angle,
            fill=outline,
            width=width
        )

    ctx.pos_y = y + radius



def draw_dashed_line(draw: ImageDraw.ImageDraw,
                      start: tuple[int, int],
                      end: tuple[int, int],
                      dash_length: int,
                      space_length: int,
                      fill: tuple[int, int, int, int] = BLACK,
                      width: int = 1,
                      ) -> None:
    """Draw dashed line.

    Renders a dashed line between two points by drawing alternating
    segments of visible line and invisible space.

    Args:
        draw: PIL ImageDraw object to draw with
        start: Start point coordinates (x, y)
        end: End point coordinates (x, y)
        dash_length: Length of visible line segments
        space_length: Length of invisible space segments
        fill: Line color
        width: Line width
    """
    x1, y1 = start
    x2, y2 = end

    dx = x2 - x1
    dy = y2 - y1
    line_length = (dx ** 2 + dy ** 2) ** 0.5

    step_x = dx / line_length
    step_y = dy / line_length

    current_pos = 0.0

    while True:
        # 1) Draw a dash segment
        dash_end = current_pos + dash_length

        if dash_end >= line_length:
            # A partial dash exists that ends exactly or beyond the line_end
            dash_end = line_length
            segment_len = dash_end - current_pos

            segment_start_x = x1 + step_x * current_pos
            segment_start_y = y1 + step_y * current_pos
            segment_end_x = x1 + step_x * dash_end
            segment_end_y = y1 + step_y * dash_end

            draw.line(
                [(segment_start_x, segment_start_y), (segment_end_x, segment_end_y)],
                fill=fill,
                width=width
            )
            # Process is done because the end of the line has been reached
            break
        else:
            # Normal full dash
            segment_start_x = x1 + step_x * current_pos
            segment_start_y = y1 + step_y * current_pos
            segment_end_x = x1 + step_x * dash_end
            segment_end_y = y1 + step_y * dash_end

            draw.line(
                [(segment_start_x, segment_start_y), (segment_end_x, segment_end_y)],
                fill=fill,
                width=width
            )

            # 2) Move current_pos forward past this dash
            current_pos = dash_end

        # 3) Skip the space segment
        space_end = current_pos + space_length
        if space_end >= line_length:
            # The space would exceed the line's end, so processing is complete
            break
        else:
            # Jump over the space
            current_pos = space_end


def get_rounded_corners(corner_string: str) -> tuple[bool, bool, bool, bool]:
    """Get rounded corner configuration.

    Parses a string specifying which corners of a rectangle should be rounded.

    Args:
        corner_string: String specifying corners to round ("all" or comma-separated list)

    Returns:
        tuple: Boolean flags for (top_left, top_right, bottom_right, bottom_left)
    """
    if corner_string == "all":
        return True, True, True, True

    corners = corner_string.split(",")
    corner_map = {
        "top_left": 0,
        "top_right": 1,
        "bottom_right": 2,
        "bottom_left": 3
    }

    result = [False] * 4
    for corner in corners:
        corner = corner.strip()
        if corner in corner_map:
            result[corner_map[corner]] = True

    return result[0], result[1], result[2], result[3]