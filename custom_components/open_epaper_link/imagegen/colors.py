# Color constants with alpha channel
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
HALF_BLACK = (127, 127, 127, 255)
RED = (255, 0, 0, 255)
HALF_RED = (255, 127, 127, 255)
YELLOW = (255, 255, 0, 255)
HALF_YELLOW = (255, 255, 127, 255)


class ColorResolver:
    """Resolves color inputs to RGBA tuples."""

    def __init__(self, accent_color: str = "red"):
        self.accent_color = accent_color

    def resolve(self, color: str | None) -> tuple[int, int, int, int] | None:
        """Resolve color input to RGBA tuple."""
        if color is None:
            return None

        color_str = str(color).lower()

        # Hex color support: #RGB or #RRGGBB
        if color_str.startswith('#'):
            return self._parse_hex(color_str[1:])

        return self._resolve_named(color_str)

    @staticmethod
    def _parse_hex(hex_val: str) -> tuple[int, int, int, int]:
        """Parse hex color string to RGBA tuple."""
        if len(hex_val) == 3:
            r = int(hex_val[0] * 2, 16)
            g = int(hex_val[1] * 2, 16)
            b = int(hex_val[2] * 2, 16)
        elif len(hex_val) == 6:
            r = int(hex_val[0:2], 16)
            g = int(hex_val[2:4], 16)
            b = int(hex_val[4:6], 16)
        else:
            return WHITE
        return r, g, b, 255

    def _resolve_named(self, color_str: str) -> tuple[int, int, int, int]:
        """Resolve named color to RGBA tuple."""
        if color_str in ("black", "b"):
            return BLACK
        if color_str in ("half_black", "hb", "gray", "grey", "half_white",
                         "hw"):
            return HALF_BLACK
        if color_str in ("accent", "a"):
            return YELLOW if self.accent_color == "yellow" else RED
        if color_str in ("half_accent", "ha"):
            return HALF_YELLOW if self.accent_color == "yellow" else HALF_RED
        if color_str in ("red", "r"):
            return RED
        if color_str in ("half_red", "hr"):
            return HALF_RED
        if color_str in ("yellow", "y"):
            return YELLOW
        if color_str in ("half_yellow", "hy"):
            return HALF_YELLOW
        return WHITE
