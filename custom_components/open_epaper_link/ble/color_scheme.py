from dataclasses import dataclass
from enum import Enum
from typing import Tuple, Dict


@dataclass(frozen=True)
class ColorPalette:
    """Color palette for a display type."""
    colors: Dict[str, Tuple[int, int, int]]  # name -> RGB tuple
    accent: str


class ColorScheme(Enum):
    """
    Display color scheme with associated palette.

    Usage:
        scheme = ColorScheme.from_int(2)  # Get BWY from firmware value
        scheme.name          # "BWY"
        scheme.value         # 2
        scheme.accent_color  # "yellow"
        scheme.palette.colors  # {'black': ..., 'white': ..., 'yellow': ...}
    """
    MONO = (0, ColorPalette(
        colors={
            'black': (0, 0, 0),
            'white': (255, 255, 255),
        },
        accent='black'
    ))

    BWR = (1, ColorPalette(
        colors={
            'black': (0, 0, 0),
            'white': (255, 255, 255),
            'red': (255, 0, 0),
        },
        accent='red'
    ))

    BWY = (2, ColorPalette(
        colors={
            'black': (0, 0, 0),
            'white': (255, 255, 255),
            'yellow': (255, 255, 0),
        },
        accent='yellow'
    ))

    BWRY = (3, ColorPalette(
        colors={
            'black': (0, 0, 0),
            'white': (255, 255, 255),
            'red': (255, 0, 0),
            'yellow': (255, 255, 0),
        },
        accent='red'
    ))

    BWGBRY = (4, ColorPalette(
        colors={
            'black': (0, 0, 0),
            'white': (255, 255, 255),
            'green': (0, 255, 0),
            'blue': (0, 0, 255),
            'red': (255, 0, 0),
            'yellow': (255, 255, 0),
        },
        accent='red'
    ))

    GRAYSCALE_4 = (5, ColorPalette(
        colors={
            'black': (0, 0, 0),
            'gray1': (85, 85, 85),
            'gray2': (170, 170, 170),
            'white': (255, 255, 255)
        },
        accent='black'
    ))

    def __init__(self, value: int, palette: ColorPalette):
        self._value_ = value
        self.palette = palette

    @classmethod
    def from_int(cls, value: int) -> 'ColorScheme':
        """Get ColorScheme from firmware int value."""
        for scheme in cls:
            if scheme.value == value:
                return scheme
        return cls.MONO  # Default fallback

    @property
    def accent_color(self) -> str:
        """Accent color name for this scheme."""
        return self.palette.accent

    @property
    def has_red(self) -> bool:
        """Check if red color is supported."""
        return 'red' in self.palette.colors

    @property
    def has_yellow(self) -> bool:
        """Check if yellow color is supported."""
        return 'yellow' in self.palette.colors

    @property
    def is_multi_color(self) -> bool:
        """Check if the scheme supports multiple colors."""
        return len(self.palette.colors) > 2
