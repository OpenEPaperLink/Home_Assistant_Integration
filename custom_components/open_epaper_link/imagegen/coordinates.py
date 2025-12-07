class CoordinateParser:
    """Helper class for parsing coordinates with percentage support.

    This class handles the conversion of coordinates from different formats
    (absolute pixels or percentages) to absolute pixel values based on the
    canvas dimensions. It simplifies positioning elements in relation to
    the canvas size.

    Attributes:
        width: Canvas width in pixels
        height: Canvas height in pixels
    """

    def __init__(self, canvas_width: int, canvas_height: int):
        """Initialize with canvas dimensions.

        Args:
            canvas_width: Width of the canvas in pixels
            canvas_height: Height of the canvas in pixels
        """
        self.width = canvas_width
        self.height = canvas_height

    @staticmethod
    def _parse_dimension(value: str | int | float, total_dimension: int) -> int:
        """Convert a dimension value (pixels or percentage) to absolute pixels.

        Args:
            value: The dimension value (e.g., "50%", 50, "50")
            total_dimension: The total available dimension (width or height)

        Returns:
            int: The calculated pixel value
        """
        if isinstance(value, (int, float)):
            return int(value)

        value = str(value).strip()
        if value.endswith('%'):
            try:
                percentage = float(value[:-1])
                return int((percentage / 100) * total_dimension)
            except ValueError:
                return 0
        try:
            return int(float(value))
        except ValueError:
            return 0

    def parse_x(self, value: str | int | float) -> int:
        """Parse x coordinate value.

        Converts an x-coordinate from any supported format to absolute pixels.
        Handles percentage values relative to canvas width.

        Args:
            value: The x coordinate in pixels or percentage

        Returns:
            int: The x coordinate in absolute pixels
        """
        return self._parse_dimension(value, self.width)

    def parse_y(self, value: str | int | float) -> int:
        """Parse y coordinate value.

        Converts a y-coordinate from any supported format to absolute pixels.
        Handles percentage values relative to canvas height.

        Args:
            value: The y coordinate in pixels or percentage

        Returns:
            int: The y coordinate in absolute pixels
        """
        return self._parse_dimension(value, self.height)

    def parse_size(self, value: str | int | float, is_width: bool = True) -> int:
        """Parse size value.

        Converts a size value from any supported format to absolute pixels.
        For percentage sizes, uses the appropriate dimension (width or height)
        as the base for calculation.

        Args:
            value: The size in pixels or percentage
            is_width: Whether this is a width (True) or height (False) value

        Returns:
            int: The size in absolute pixels
        """
        return self._parse_dimension(value, self.width if is_width else self.height)

    def parse_coordinates(self, element: dict, prefix: str = '') -> tuple[int, int]:
        """Parse x,y coordinates from element with given prefix.

        Args:
            element: Element dictionary
            prefix: Optional prefix for coordinate keys (e.g., 'start_' or 'end_')

        Returns:
            tuple: (x, y) coordinates in pixels
        """
        x_key = f"{prefix}x"
        y_key = f"{prefix}y"

        x = self.parse_x(element.get(x_key, 0))
        y = self.parse_y(element.get(y_key, 0))

        return x, y