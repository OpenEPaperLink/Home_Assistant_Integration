import io
import base64
import yaml
from PIL import Image, ImageDraw, ImageFont

DEFAULT_FONT = "DejaVuSans.ttf"


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
            font = ImageFont.truetype(el.get("font", DEFAULT_FONT), el.get("size", 12))
            draw.text((el.get("x", 0), el.get("y", 0)), el.get("value", ""), fill=el.get("color", "black"), font=font)
        elif t == "line":
            draw.line([(el.get("x_start", 0), el.get("y_start", 0)), (el.get("x_end", 0), el.get("y_end", 0))], fill=el.get("color", "black"), width=el.get("width", 1))
        elif t == "rectangle":
            draw.rectangle([(el.get("x_start", 0), el.get("y_start", 0)), (el.get("x_end", 0), el.get("y_end", 0))], outline=el.get("outline", "black"), fill=el.get("fill"))
        elif t == "circle":
            r = el.get("radius", 10)
            x = el.get("x", 0)
            y = el.get("y", 0)
            draw.ellipse([x - r, y - r, x + r, y + r], outline=el.get("outline", "black"), fill=el.get("fill"))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
