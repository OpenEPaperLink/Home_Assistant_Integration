from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image
    from .colors import ColorResolver
    from .coordinates import CoordinateParser
    from .fonts import FontManager
    from homeassistant.core import HomeAssistant

class ElementType(str, Enum):
    """Enum for supported element types.

    Defines all the drawable element types supported by the ImageGen class.
    Each type corresponds to a specific drawing method that handles the
    rendering of that element type.

    The enum values are used in the payload to identify the type of each element.
    """

    TEXT = "text"
    MULTILINE = "multiline"
    LINE = "line"
    RECTANGLE = "rectangle"
    RECTANGLE_PATTERN = "rectangle_pattern"
    POLYGON = "polygon"
    CIRCLE = "circle"
    ELLIPSE = "ellipse"
    ARC = "arc"
    ICON = "icon"
    DLIMG = "dlimg"
    QRCODE = "qrcode"
    PLOT = "plot"
    PROGRESS_BAR = "progress_bar"
    DIAGRAM = "diagram"
    ICON_SEQUENCE = "icon_sequence"
    DEBUG_GRID = "debug_grid"

    def __str__(self) -> str:
        """Return the string value of the enum.

        Returns:
            str: The string value of the enum
        """

        return self.value

@dataclass
class TextSegment:
    """Represents a segment of text with its color.

    Used for handling colored text markup, where different parts of a text
    string can have different colors (e.g., "[red]Text[/red]").

    Attributes:
        text: The text content
        color: The color name for this segment
        start_x: Starting x position for rendering (calculated during layout)
    """
    text: str
    color: str
    start_x: int = 0

@dataclass
class DrawingContext:
    """
    Context passed to all draw handlers.

    Holds all shared state for a single drawcustom() call.
    Handlers update pos_y directly rather than returning it.
    """
    img: "Image.Image"
    colors: "ColorResolver"
    coords: "CoordinateParser"
    fonts: "FontManager"
    hass: "HomeAssistant"
    pos_y: int = 0