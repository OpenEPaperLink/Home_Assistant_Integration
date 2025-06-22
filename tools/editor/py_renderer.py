import io
import base64
import yaml
from PIL import Image, ImageDraw, ImageFont

# Use the integration's default font if available
DEFAULT_FONT = "ppb.ttf"


def _load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a truetype font, falling back to PIL's default."""
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def _draw_text(draw: ImageDraw.ImageDraw, el: dict) -> None:
    font = _load_font(el.get("font", DEFAULT_FONT), el.get("size", 12))
    anchor = el.get("anchor", "lt")
    draw.text(
        (el.get("x", 0), el.get("y", 0)),
        str(el.get("value", "")),
        fill=el.get("color", "black"),
        font=font,
        anchor=anchor,
    )


def _draw_multiline(draw: ImageDraw.ImageDraw, el: dict) -> None:
    font = _load_font(el.get("font", DEFAULT_FONT), el.get("size", 12))
    anchor = el.get("anchor", "lt")
    y = el.get("start_y", el.get("y", 0))
    for idx, line in enumerate(str(el.get("value", "")).split(el.get("delimiter", "|"))):
        draw.text(
            (el.get("x", 0), y + idx * el.get("offset_y", 20)),
            line,
            fill=el.get("color", "black"),
            font=font,
            anchor=anchor,
        )


def render_image(yaml_text: str) -> str:
    data = yaml.safe_load(yaml_text)
    width = data.get("width", 296)
    height = data.get("height", 128)
    background = data.get("background", "white")
    img = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(img)
    for el in data.get("payload", []):
        t = el.get("type")
        if t == "text":
            _draw_text(draw, el)
        elif t == "multiline":
            _draw_multiline(draw, el)
        elif t == "line":
            draw.line(
                [
                    (el.get("x_start", 0), el.get("y_start", 0)),
                    (el.get("x_end", 0), el.get("y_end", 0)),
                ],
                fill=el.get("color", "black"),
                width=el.get("width", 1),
            )
        elif t == "rectangle":
            draw.rectangle(
                [
                    el.get("x_start", 0),
                    el.get("y_start", 0),
                    el.get("x_end", 0),
                    el.get("y_end", 0),
                ],
                outline=el.get("outline", "black"),
                fill=el.get("fill"),
                width=el.get("width", 1),
            )
        elif t == "rectangle_pattern":
            for xi in range(el.get("x_repeat", 1)):
                for yi in range(el.get("y_repeat", 1)):
                    x = el.get("x_start", 0) + xi * el.get("x_size", 10) + el.get("x_offset", 0)
                    y = el.get("y_start", 0) + yi * el.get("y_size", 10) + el.get("y_offset", 0)
                    draw.rectangle(
                        [x, y, x + el.get("x_size", 10), y + el.get("y_size", 10)],
                        outline=el.get("outline", "black"),
                        width=el.get("width", 1),
                    )
        elif t == "polygon":
            pts = el.get("points", [])
            if pts:
                draw.polygon(
                    pts,
                    outline=el.get("outline", "black"),
                    fill=el.get("fill"),
                )
        elif t == "circle":
            r = el.get("radius", 10)
            x = el.get("x", 0)
            y = el.get("y", 0)
            draw.ellipse(
                [x - r, y - r, x + r, y + r],
                outline=el.get("outline", "black"),
                fill=el.get("fill"),
                width=el.get("width", 1),
            )
        elif t == "ellipse":
            draw.ellipse(
                [
                    el.get("x_start", 0),
                    el.get("y_start", 0),
                    el.get("x_end", 0),
                    el.get("y_end", 0),
                ],
                outline=el.get("outline", "black"),
                fill=el.get("fill"),
                width=el.get("width", 1),
            )
        elif t == "arc":
            r = el.get("radius", 10)
            x = el.get("x", 0)
            y = el.get("y", 0)
            draw.arc(
                [x - r, y - r, x + r, y + r],
                el.get("start_angle", 0),
                el.get("end_angle", 180),
                fill=el.get("color", "black"),
                width=el.get("width", 1),
            )
        elif t == "progress_bar":
            x0, y0 = el.get("x_start", 0), el.get("y_start", 0)
            x1, y1 = el.get("x_end", 0), el.get("y_end", 0)
            draw.rectangle([x0, y0, x1, y1], outline=el.get("outline", "black"), width=1)
            prog = max(0, min(1, el.get("progress", 0) / 100))
            fill_w = x0 + (x1 - x0) * prog
            draw.rectangle([x0, y0, fill_w, y1], fill=el.get("fill", "black"))
        elif t == "debug_grid":
            for x in range(0, img.width, 10):
                draw.line([(x, 0), (x, img.height)], fill="#cccccc", width=1)
            for y in range(0, img.height, 10):
                draw.line([(0, y), (img.width, y)], fill="#cccccc", width=1)

    rotate = data.get("rotate", 0)
    if rotate:
        img = img.rotate(rotate, expand=True)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
