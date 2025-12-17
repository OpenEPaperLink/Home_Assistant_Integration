from __future__ import annotations

import logging
import math
from datetime import timedelta, datetime
from functools import partial

from PIL import ImageDraw
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.util import dt

from .registry import element_handler
from .types import ElementType, DrawingContext
from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@element_handler(ElementType.PLOT, requires=["data"])
async def draw_plot(ctx: DrawingContext, element: dict) -> None:
    """
    Draw plot of Home Assistant sensor data.

    Creates a line plot visualization of historical data from Home Assistant
    entities with customizable axes, legends, and styling.

    This is one of the most complex drawing methods, handling data retrieval,
    scaling, and rendering of multiple data series and plot components.

    Args:
        ctx: Drawing context
        element: Element dictionary with plot properties
    Raises:
        HomeAssistantError: If plot generation fails
    """
    try:
        draw = ImageDraw.Draw(ctx.img)

        # Get plot dimensions and position
        x_start = element.get("x_start", 0)
        y_start = element.get("y_start", 0)
        x_end = element.get("x_end", ctx.img.width - 1 - x_start)
        y_end = element.get("y_end", ctx.img.height - 1 - y_start)
        width = x_end - x_start + 1
        height = y_end - y_start + 1

        # Get time range
        duration_seconds = float(element.get("duration", 60 * 60 * 24))
        if duration_seconds <= 0:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="plot_duration_invalid",
            )
        duration = timedelta(seconds=duration_seconds)
        end = dt.now()
        start = end - duration

        # Set up font
        font_name = element.get("font", "ppb.ttf")

        # Get min/max values from config
        min_v = element.get("low")
        max_v = element.get("high")

        # Fetch sensor data
        all_states = await get_instance(ctx.hass).async_add_executor_job(partial(get_significant_states,
                                                                                  ctx.hass,
                                                                                  start_time=start,
                                                                                  entity_ids=[plot["entity"] for
                                                                                              plot in
                                                                                              element["data"]],
                                                                                  significant_changes_only=False,
                                                                                  minimal_response=True,
                                                                                  no_attributes=False
                                                                                  ))

        # Process data and find min/max if not specified
        raw_data = []
        for plot in element["data"]:
            if plot["entity"] not in all_states:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="plot_no_data",
                    translation_placeholders={"entity": plot["entity"]}
                )

            states = all_states[plot["entity"]]
            state_obj = states[0]
            states[0] = {
                "state": state_obj.state,
                "last_changed": str(state_obj.last_changed)
            }

            # Convert states to segments (breaking at gaps)
            segments = []
            current_segment = []
            span_gaps = plot.get("span_gaps", False)
            value_scale = plot.get("value_scale", 1.0)
            prev_timestamp = None
            prev_was_valid = True

            for state in states:
                try:
                    value = float(state["state"]) * value_scale
                    timestamp = datetime.fromisoformat(state["last_changed"])

                    # Check for gap conditions
                    should_break = False

                    if isinstance(span_gaps, (int, float)) and span_gaps is not True and span_gaps is not False:
                        # Time-based gap detection
                        if prev_timestamp:
                            gap_seconds = (timestamp - prev_timestamp).total_seconds()
                            if gap_seconds > span_gaps:
                                should_break = True
                    elif span_gaps is False and not prev_was_valid:
                        # Previous was invalid/null, start new segment
                        should_break = True

                    # Start new segment if needed
                    if should_break and current_segment:
                        segments.append(current_segment)
                        current_segment = []

                    current_segment.append((timestamp, value))
                    prev_timestamp = timestamp
                    prev_was_valid = True

                except (ValueError, TypeError):
                    # Invalid value (null, unavailable, etc.)
                    if span_gaps is False and current_segment:
                        # Close current segment before null
                        segments.append(current_segment)
                        current_segment = []
                    prev_was_valid = False
                    continue

            # Add final segment
            if current_segment:
                segments.append(current_segment)

            if not segments:
                continue

            # Update min/max from all segments
            all_values = [p[1] for segment in segments for p in segment]
            if min_v is None:
                min_v = min(all_values) if all_values else None
            else:
                min_v = min(min_v, min(all_values))

            if max_v is None:
                max_v = max(all_values) if all_values else None
            else:
                max_v = max(max_v, max(all_values))

            raw_data.append(segments)

        if not raw_data:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="plot_no_valid_points"
            )

        # Apply rounding if requested
        if element.get("round_values", False):
            max_v = math.ceil(max_v)
            min_v = math.floor(min_v)
        if max_v == min_v:
            min_v -= 1
        spread = max_v - min_v

        # Configure y legend
        y_legend = element.get("ylegend", {})
        y_legend_width = -1
        y_legend_pos = None
        y_legend_color = None
        y_legend_size = None
        y_legend_font = None

        if y_legend:
            y_legend_width = y_legend.get("width", -1)
            y_legend_color = ctx.colors.resolve(y_legend.get("color", "black"))
            y_legend_pos = y_legend.get("position", "left")
            if y_legend_pos not in ("left", "right", None):
                y_legend_pos = "left"
            y_legend_size = y_legend.get("size", 10)

        # Calculate y legend width if auto width is requested
        if y_legend and y_legend_width == -1:
            y_legend_font = ctx.fonts.get_font(font_name, y_legend_size)
            max_bbox = y_legend_font.getbbox(str(max_v))
            min_bbox = y_legend_font.getbbox(str(min_v))
            max_width = max_bbox[2] - max_bbox[0]
            min_width = min_bbox[2] - min_bbox[0]
            y_legend_width = math.ceil(max(max_width, min_width))  # Add padding

        # Configure y axis
        y_axis = element.get("yaxis")
        y_axis_width = -1
        y_axis_color = None
        y_axis_tick_length = 0
        y_axis_tick_width = 1
        y_axis_tick_every = 0
        y_axis_grid = None
        y_axis_grid_color = None
        y_axis_grid_style = None

        if y_axis:
            y_axis_width = y_axis.get("width", 1)
            y_axis_color = ctx.colors.resolve(y_axis.get("color", "black"))
            y_axis_tick_length = y_axis.get("tick_length", 4)
            y_axis_tick_width = y_axis.get("tick_width", 2)
            y_axis_tick_every = float(y_axis.get("tick_every", 1))
            if y_axis_tick_every <= 0:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="plot_yaxis_invalid"
                )
            y_axis_grid = y_axis.get("grid", True)
            y_axis_grid_color = ctx.colors.resolve(y_axis.get("grid_color", "black"))
            y_axis_grid_style = y_axis.get("grid_style", "dotted")

        # Configure x legend
        x_legend = element.get("xlegend", {})
        time_format = "%H:%M"
        time_interval = duration.total_seconds() / 4  # Default to 4 labels
        time_font = None
        time_color = None
        time_position = None
        x_legend_height = None

        if x_legend:
            time_format = x_legend.get("format", "%H:%M")
            interval = x_legend.get("interval")
            if interval is not None:
                time_interval = float(interval)
            time_size = x_legend.get("size", 10)
            time_font = ctx.fonts.get_font(font_name, time_size)
            time_color = ctx.colors.resolve(x_legend.get("color", "black"))
            time_position = x_legend.get("position", "bottom")
            x_legend_height = x_legend.get("height", -1)
            if time_position not in ("top", "bottom", None):
                time_position = "bottom"
        if time_interval <= 0:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="plot_xlegend_invalid"
            )

        # Configure x axis
        x_axis = element.get("xaxis", {})
        x_axis_width = 1
        x_axis_color = None
        x_axis_tick_length = 0
        x_axis_tick_width = 0
        x_axis_grid = None
        x_axis_grid_color = None
        x_axis_grid_style = None

        if x_axis:
            x_axis_width = x_axis.get("width", 1)
            x_axis_color = ctx.colors.resolve(x_axis.get("color", "black"))
            x_axis_tick_length = x_axis.get("tick_length", 4)
            x_axis_tick_width = x_axis.get("tick_width", 2)
            x_axis_grid = x_axis.get("grid", True)
            x_axis_grid_color = ctx.colors.resolve(x_axis.get("grid_color", "black"))
            x_axis_grid_style = x_axis.get("grid_style", "dotted")

        x_label_height = 0
        if x_legend:
            if x_legend_height == 0:
                x_label_height = 0
            else:
                if x_legend_height > 0:
                    x_label_height = x_legend_height
                else:
                    x_label_height = time_font.getbbox("00:00")[3]
                    x_label_height += x_axis_tick_width + 2

        # Calculate effective diagram dimensions
        diag_x = x_start + (y_legend_width if y_legend_pos == "left" else 0)
        diag_y = y_start + (x_label_height if time_position == "top" and x_legend_height != 0 else 0)
        diag_width = width - (y_legend_width if y_legend_pos == "left" or y_legend_pos == "right" else 0)
        diag_height = height - x_label_height

        # Draw debug borders if requested
        if element.get("debug", False):
            draw.rectangle(
                (x_start, y_start, x_end, y_end),
                fill=None,
                outline=ctx.colors.resolve("black"),
                width=1
            )
            draw.rectangle(
                (diag_x, diag_y, diag_x + diag_width - 1, diag_y + diag_height - 1),
                fill=None,
                outline=ctx.colors.resolve("red"),
                width=1
            )
        # Draw y legend
        if y_legend:

            top_y = y_start
            bottom_y = y_end - x_label_height
            if time_position == "top" and x_legend_height != 0:
                top_y += x_label_height
                bottom_y += x_label_height

            # Draw labels for each grid line
            if y_axis_tick_every > 0:
                curr = min_v
                # Track if the max value has been drawn
                max_value_drawn = False

                while curr <= max_v:
                    # Calculate y position for this value
                    curr_y = round(diag_y + (1 - ((curr - min_v) / spread)) * (diag_height - 1))

                    # Format the value with appropriate rounding
                    formatted_value = curr
                    if isinstance(curr, float):
                        # Check if it's a whole number
                        if curr.is_integer():
                            formatted_value = int(curr)
                        else:
                            # Round to 2 decimal places
                            formatted_value = round(curr, 2)
                            # Remove trailing zeros
                            formatted_value = float(f"{formatted_value:.2f}".rstrip('0').rstrip(
                                '.') if '.' in f"{formatted_value:.2f}" else formatted_value)

                    if y_legend_pos == "left":
                        draw.text(
                            (x_start, curr_y),
                            str(formatted_value),
                            fill=y_legend_color,
                            font=y_legend_font,
                            anchor="lm"  # Left-middle alignment
                        )
                    elif y_legend_pos == "right":
                        draw.text(
                            (x_end, curr_y),
                            str(formatted_value),
                            fill=y_legend_color,
                            font=y_legend_font,
                            anchor="rm"  # Right-middle alignment
                        )

                    # Check if this is the max value or very close to it
                    if abs(curr - max_v) < 0.0001:
                        max_value_drawn = True

                    curr += y_axis_tick_every

                # If the max value hasn't been drawn and it's not equal to min_v, draw it now
                if not max_value_drawn and abs(max_v - min_v) > 0.0001:
                    # Calculate y position for max value
                    max_y = round(diag_y + (1 - ((max_v - min_v) / spread)) * (diag_height - 1))

                    # Format the max value with appropriate rounding
                    formatted_max = max_v
                    if isinstance(max_v, float):
                        # Check if it's a whole number
                        if max_v.is_integer():
                            formatted_max = int(max_v)
                        else:
                            # Round to 2 decimal places
                            formatted_max = round(max_v, 2)
                            # Remove trailing zeros
                            formatted_max = float(f"{formatted_max:.2f}".rstrip('0').rstrip(
                                '.') if '.' in f"{formatted_max:.2f}" else formatted_max)

                    if y_legend_pos == "left":
                        draw.text(
                            (x_start, max_y),
                            str(formatted_max),
                            fill=y_legend_color,
                            font=y_legend_font,
                            anchor="lm"  # Left-middle alignment
                        )
                    elif y_legend_pos == "right":
                        draw.text(
                            (x_end, max_y),
                            str(formatted_max),
                            fill=y_legend_color,
                            font=y_legend_font,
                            anchor="rm"  # Right-middle alignment
                        )
            else:
                # Fallback to just min/max if no tick interval is defined
                # Format the min/max values with appropriate rounding
                formatted_max = max_v
                formatted_min = min_v

                if isinstance(max_v, float):
                    # Check if it's a whole number
                    if max_v.is_integer():
                        formatted_max = int(max_v)
                    else:
                        # Round to 2 decimal places
                        formatted_max = round(max_v, 2)
                        # Remove trailing zeros
                        formatted_max = float(f"{formatted_max:.2f}".rstrip('0').rstrip(
                            '.') if '.' in f"{formatted_max:.2f}" else formatted_max)

                if isinstance(min_v, float):
                    # Check if it's a whole number
                    if min_v.is_integer():
                        formatted_min = int(min_v)
                    else:
                        # Round to 2 decimal places
                        formatted_min = round(min_v, 2)
                        # Remove trailing zeros
                        formatted_min = float(f"{formatted_min:.2f}".rstrip('0').rstrip(
                            '.') if '.' in f"{formatted_min:.2f}" else formatted_min)

                if y_legend_pos == "left":
                    draw.text(
                        (x_start, top_y),
                        str(formatted_max),
                        fill=y_legend_color,
                        font=y_legend_font,
                        anchor="lt"
                    )
                    draw.text(
                        (x_start, bottom_y),
                        str(formatted_min),
                        fill=y_legend_color,
                        font=y_legend_font,
                        anchor="ls"
                    )
                elif y_legend_pos == "right":
                    draw.text(
                        (x_end, top_y),
                        str(formatted_max),
                        fill=y_legend_color,
                        font=y_legend_font,
                        anchor="rt"
                    )
                    draw.text(
                        (x_end, bottom_y),
                        str(formatted_min),
                        fill=y_legend_color,
                        font=y_legend_font,
                        anchor="rs"
                    )

        # Draw y-axis and grid
        if y_axis:
            # Y Axis line
            if y_axis_width > 0 and y_axis_color:
                draw.rectangle(
                    (diag_x, diag_y, diag_x + y_axis_width - 1, diag_y + diag_height - 1),
                    fill=y_axis_color
                )
            # Y Tick marks
            if y_axis_tick_length > 0 and y_axis_color:
                curr = min_v
                while curr <= max_v:
                    curr_y = round(diag_y + (1 - ((curr - min_v) / spread)) * (diag_height - 1))
                    draw.line(
                        (diag_x, curr_y, diag_x + y_axis_tick_length - 1, curr_y),
                        fill=y_axis_color,
                        width=y_axis_tick_width
                    )
                    curr += y_axis_tick_every

            # Y Grid
            if y_axis_grid and y_axis_grid_color:
                curr = min_v
                while curr <= max_v:
                    curr_y = round(diag_y + (1 - ((curr - min_v) / spread)) * (diag_height - 1))

                    if y_axis_grid_style == "lines":
                        # Solid line
                        draw.line(
                            [(diag_x, curr_y), (diag_x + diag_width, curr_y)],
                            fill=y_axis_grid_color,
                            width=1
                        )
                    elif y_axis_grid_style == "dashed":
                        # Dashed line
                        x_pos = diag_x
                        dash_length = 5
                        gap_length = 3
                        while x_pos < diag_x + diag_width:
                            end_x = min(x_pos + dash_length, diag_x + diag_width)
                            draw.line(
                                [(x_pos, curr_y), (end_x, curr_y)],
                                fill=y_axis_grid_color,
                                width=1
                            )
                            x_pos += dash_length + gap_length
                    elif y_axis_grid_style == "dotted":
                        # Dotted line
                        for x in range(int(diag_x), int(diag_x + diag_width), 5):
                            draw.point((x, curr_y), fill=y_axis_grid_color)
                    curr += y_axis_tick_every

        # Determine time range for x-axis labels and grid
        if x_legend and x_legend_height != 0 and x_legend.get("snap_to_hours", True):
            # Round start time to the nearest hour
            curr_time = start.replace(minute=0, second=0, microsecond=0)
            # Round end time to the nearest hour
            end_time = end.replace(minute=0, second=0, microsecond=0)
            if end > end_time:
                end_time += timedelta(hours=1)
        else:
            curr_time = start
            end_time = end

        # Draw X Axis and grid
        if x_axis:
            # X Axis line
            if x_axis_width > 0 and x_axis_color:
                draw.line(
                    [(diag_x, diag_y + diag_height), (diag_x + diag_width, diag_y + diag_height)],
                    fill=x_axis_color,
                    width=x_axis_width
                )
            # X Tick marks
            if x_axis_tick_length > 0 and x_axis_color:
                curr = curr_time
                while curr <= end_time:
                    rel_x = (curr - start) / duration
                    x = round(diag_x + rel_x * (diag_width - 1))
                    # Only draw tick marks within the diagram area
                    if diag_x <= x <= diag_x + diag_width:
                        draw.line(
                            [(x, diag_y + diag_height), (x, diag_y + diag_height - x_axis_tick_length)],
                            fill=x_axis_color,
                            width=x_axis_tick_width
                        )
                    curr += timedelta(seconds=time_interval)
            # X Grid
            if x_axis_grid and x_axis_grid_color:
                curr = curr_time
                while curr <= end_time:
                    rel_x = (curr - start) / duration
                    x = round(diag_x + rel_x * (diag_width - 1))

                    # Only draw grid lines within the diagram area
                    if diag_x <= x <= diag_x + diag_width:
                        if x_axis_grid_style == "lines":
                            # Solid line
                            draw.line(
                                [(x, diag_y), (x, diag_y + diag_height)],
                                fill=x_axis_grid_color,
                                width=1
                            )
                        elif x_axis_grid_style == "dashed":
                            # Dashed line
                            y_pos = diag_y
                            dash_length = 5
                            gap_length = 3
                            while y_pos < diag_y + diag_height:
                                end_y = min(y_pos + dash_length, diag_y + diag_height)
                                draw.line(
                                    [(x, y_pos), (x, end_y)],
                                    fill=x_axis_grid_color,
                                    width=1
                                )
                                y_pos += dash_length + gap_length
                        elif x_axis_grid_style == "dotted":
                            # Dotted line
                            for y in range(int(diag_y), int(diag_y + diag_height), 5):
                                draw.point((x, y), fill=x_axis_grid_color)
                    curr += timedelta(seconds=time_interval)

        # Draw X Axis time labels
        if x_legend and x_legend_height != 0:

            while curr_time <= end_time:
                rel_x = (curr_time - start) / duration
                x = round(diag_x + rel_x * (diag_width - 1))

                if diag_x <= x <= diag_x + diag_width:
                    if time_position == 'bottom':
                        if x_axis_width > 0 and x_axis_color:
                            draw.line(
                                [(x, diag_y + diag_height), (x, diag_y + diag_height - x_axis_tick_width)],
                                fill=x_axis_color,
                                width=x_axis_width
                            )
                        text = curr_time.strftime(time_format)
                        draw.text(
                            (x, diag_y + diag_height + x_axis_tick_width + 2),
                            text,
                            fill=time_color,
                            font=time_font,
                            anchor="mt"
                        )
                    else:  # time_position == "top"
                        # Draw tick mark at top
                        if x_axis_width > 0 and x_axis_color:
                            draw.line(
                                [(x, diag_y), (x, diag_y + x_axis_tick_width)],
                                fill=x_axis_color,
                                width=x_axis_width
                            )
                        # Draw time label above
                        text = curr_time.strftime(time_format)
                        draw.text(
                            (x, y_start),
                            text,
                            fill=time_color,
                            font=time_font,
                            anchor="mt"
                        )
                curr_time += timedelta(seconds=time_interval)

        # Draw data
        for plot_segments, plot_config in zip(raw_data, element["data"]):
            # Get line style (once per entity)
            line_color = ctx.colors.resolve(plot_config.get("color", "black"))
            line_width = plot_config.get("width", 1)
            smooth = plot_config.get("smooth", False)
            line_style = plot_config.get("line_style", "linear")
            steps = plot_config.get("smooth_steps", 10)

            # Catmull-Rom interpolation function
            def catmull_rom(p0, p1, p2, p3, t):
                t2 = t * t
                t3 = t2 * t

                return (
                    int(0.5 * (
                            (-t3 + 2 * t2 - t) * p0[0] +
                            (3 * t3 - 5 * t2 + 2) * p1[0] +
                            (-3 * t3 + 4 * t2 + t) * p2[0] +
                            (t3 - t2) * p3[0]
                    )),
                    int(0.5 * (
                            (-t3 + 2 * t2 - t) * p0[1] +
                            (3 * t3 - 5 * t2 + 2) * p1[1] +
                            (-3 * t3 + 4 * t2 + t) * p2[1] +
                            (t3 - t2) * p3[1]
                    ))
                )

            # Process each segment independently
            all_screen_points = []  # For show_points later
            for segment_data in plot_segments:
                # Convert segment to screen coordinates
                points = []
                for timestamp, value in segment_data:
                    rel_time = (timestamp - start) / duration
                    rel_value = (value - min_v) / spread
                    x = round(diag_x + rel_time * (diag_width - 1))
                    y = round(diag_y + (1 - rel_value) * (diag_height - 1))
                    points.append((x, y))
                    all_screen_points.append((x, y))

                # Draw line for this segment (only if 2+ points)
                if len(points) > 1:
                    # Apply step transformation if requested (takes precedence over smooth)
                    if line_style == "step":
                        step_points = [points[0]]
                        for i in range(1, len(points)):
                            prev_x, prev_y = points[i-1]
                            curr_x, curr_y = points[i]
                            # Horizontal to new x at old y
                            step_points.append((curr_x, prev_y))
                            # Then vertical to new y
                            step_points.append((curr_x, curr_y))
                        points = step_points
                    if smooth and len(points) > 2 and line_style != "step":
                        # Create smoothed line using Catmull-Rom splines
                        smooth_coords = []

                        smooth_coords.append(points[0])
                        # Handle first segment specially (duplicate first point)
                        if len(points) > 3:
                            p0 = points[0]
                            p1 = points[0]
                            p2 = points[1]
                            p3 = points[2]

                            for i in range(1, steps):
                                t = i / steps
                                point = catmull_rom(p0, p1, p2, p3, t)
                                smooth_coords.append(point)

                        # Handle middle segments
                        for i in range(len(points) - 3):
                            p0 = points[i]
                            p1 = points[i + 1]
                            p2 = points[i + 2]
                            p3 = points[i + 3]

                            for j in range(steps):
                                t = j / steps
                                point = catmull_rom(p0, p1, p2, p3, t)
                                smooth_coords.append(point)

                        # Handle last segment specially (duplicate last point)
                        if len(points) > 3:
                            p0 = points[-3]
                            p1 = points[-2]
                            p2 = points[-1]
                            p3 = points[-1]

                            for i in range(1, steps):
                                t = i / steps
                                point = catmull_rom(p0, p1, p2, p3, t)
                                smooth_coords.append(point)

                        # Add last point
                        smooth_coords.append(points[-1])

                        draw.line(
                            smooth_coords,
                            fill=line_color,
                            width=line_width,
                            joint="curve"
                        )
                    else:
                        draw.line(
                            points,
                            fill=line_color,
                            width=line_width
                        )

            # Draw points from all segments (if enabled)
            if plot_config.get("show_points", False):
                point_size = plot_config.get("point_size", 3)
                point_color = ctx.colors.resolve(plot_config.get("point_color", "black"))
                for x, y in all_screen_points:
                    draw.ellipse(
                        [(x - point_size, y - point_size), (x + point_size, y + point_size)],
                        fill=point_color
                    )
        ctx.pos_y = y_end

    except Exception as e:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="plot_draw_failed",
            translation_placeholders={"error": str(e)},
        )


@element_handler(ElementType.PROGRESS_BAR, requires=["x_start", "x_end", "y_start", "y_end", "progress"])
async def draw_progress_bar(ctx: DrawingContext, element: dict) -> None:
    """Draw progress bar with optional percentage text.

    Renders a progress bar to visualize a percentage value, with options
    for fill direction, colors, and text display.

    Args:
        ctx: Drawing context
        element: Element dictionary with progress bar properties
    """
    draw = ImageDraw.Draw(ctx.img)

    x_start = ctx.coords.parse_x(element['x_start'])
    y_start = ctx.coords.parse_y(element['y_start'])
    x_end = ctx.coords.parse_x(element['x_end'])
    y_end = ctx.coords.parse_y(element['y_end'])

    progress = min(100, max(0, element['progress']))  # Clamp to 0-100
    direction = element.get('direction', 'right')
    background = ctx.colors.resolve(element.get('background', 'white'))
    fill = ctx.colors.resolve(element.get('fill', 'red'))
    outline = ctx.colors.resolve(element.get('outline', 'black'))
    width = element.get('width', 1)
    show_percentage = element.get('show_percentage', False)
    font_name = element.get('font_name', 'ppb.ttf')

    # Draw background
    draw.rectangle(
        ((x_start, y_start), (x_end, y_end)),
        fill=background,
        outline=outline,
        width=width
    )

    # Calculate progress dimensions
    if direction in ['right', 'left']:
        progress_width = int((x_end - x_start) * (progress / 100))
        progress_height = y_end - y_start
    else:  # up or down
        progress_width = x_end - x_start
        progress_height = int((y_end - y_start) * (progress / 100))

    # Draw progress
    if direction == 'right':
        draw.rectangle(
            (x_start, y_start, x_start + progress_width, y_end),
            fill=fill
        )
    elif direction == 'left':
        draw.rectangle(
            (x_end - progress_width, y_start, x_end, y_end),
            fill=fill
        )
    elif direction == 'up':
        draw.rectangle(
            (x_start, y_end - progress_height, x_end, y_end),
            fill=fill
        )
    elif direction == 'down':
        draw.rectangle(
            (x_start, y_start, x_end, y_start + progress_height),
            fill=fill
        )

    # Draw outline
    draw.rectangle(
        (x_start, y_start, x_end, y_end),
        fill=None,
        outline=outline,
        width=width
    )

    # Add percentage text if enabled
    if show_percentage:
        # Calculate font size based on bar dimensions
        font_size = min(y_end - y_start - 4, x_end - x_start - 4, 20)
        font = ctx.fonts.get_font(font_name, font_size)

        percentage_text = f"{progress}%"

        # Get text dimensions
        text_bbox = draw.textbbox((0, 0), percentage_text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        # Center text
        text_x = (x_start + x_end - text_width) / 2
        text_y = (y_start + y_end - text_height) / 2

        # Choose text color based on position relative to progress
        if progress > 50:
            text_color = background
        else:
            text_color = fill

        draw.text(
            (text_x, text_y),
            percentage_text,
            font=font,
            fill=text_color,
            anchor='lt'
        )

    ctx.pos_y = y_end


@element_handler(ElementType.DIAGRAM, requires=["x", "height"])
async def draw_diagram(ctx: DrawingContext, element: dict) -> None:
    """Draw diagram with optional bars.

    Renders a basic diagram with axes and optional bar chart elements.

    Args:
        ctx: Drawing context
        element: Element dictionary with diagram properties
    """
    draw = ImageDraw.Draw(ctx.img)
    draw.fontmode = "1"

    # Get base properties
    pos_x = element['x']
    height = element['height']
    width = element.get('width', ctx.img.width)
    offset_lines = element.get('margin', 20)

    # Draw axes
    # X axis
    draw.line(
        [(pos_x + offset_lines, ctx.pos_y + height - offset_lines),
         (pos_x + width, ctx.pos_y + height - offset_lines)],
        fill=ctx.colors.resolve('black'),
        width=1
    )
    # Y axis
    draw.line(
        [(pos_x + offset_lines, ctx.pos_y),
         (pos_x + offset_lines, ctx.pos_y + height - offset_lines)],
        fill=ctx.colors.resolve('black'),
        width=1
    )

    if "bars" in element:
        bar_config = element["bars"]
        bar_margin = bar_config.get('margin', 10)
        bar_data = bar_config["values"].split(";")
        bar_count = len(bar_data)
        font_name = bar_config.get("font", "ppb.ttf")

        # Calculate bar width
        bar_width = math.floor(
            (width - offset_lines - ((bar_count + 1) * bar_margin)) / bar_count
        )

        # Set up font for legends
        size = bar_config.get('legend_size', 10)
        font = ctx.fonts.get_font(font_name, size)
        legend_color = ctx.colors.resolve(bar_config.get('legend_color', "black"))

        # Find maximum value for scaling
        max_val = 0
        for bar in bar_data:
            try:
                name, value = bar.split(",", 1)
                max_val = max(max_val, int(value))
            except (ValueError, IndexError):
                continue

        if max_val == 0:
            ctx.pos_y = ctx.pos_y + height

        height_factor = (height - offset_lines) / max_val

        # Draw bars and legends
        for bar_pos, bar in enumerate(bar_data):
            try:
                name, value = bar.split(",", 1)
                value = int(value)

                # Calculate bar position
                x_pos = ((bar_margin + bar_width) * bar_pos) + offset_lines + pos_x

                # Draw legend
                draw.text(
                    (x_pos + (bar_width / 2), ctx.pos_y + height - offset_lines / 2),
                    str(name),
                    fill=legend_color,
                    font=font,
                    anchor="mm"
                )

                # Draw bar
                bar_height = height_factor * value
                draw.rectangle(
                    (x_pos, ctx.pos_y + height - offset_lines - bar_height,
                     x_pos + bar_width, ctx.pos_y + height - offset_lines),
                    fill=ctx.colors.resolve(bar_config["color"])
                )

            except (ValueError, IndexError, KeyError) as e:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="plot_bar_invalid",
                    translation_placeholders={ "error": str(e)}
                ) from e

    ctx.pos_y = ctx.pos_y + height
