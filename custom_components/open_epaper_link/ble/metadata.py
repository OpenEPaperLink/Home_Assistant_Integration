"""BLE Device Metadata Abstraction.

Provides a clean interface for accessing device metadata for ATC BLE devices.
"""
from __future__ import annotations

from typing import Any

from .color_scheme import ColorScheme

class BLEDeviceMetadata:
    """Abstraction for BLE device metadata.

    Wraps raw metadata dictionary and provides clean property-based access
    to device capabilities for ATC BLE devices.

    Args:
        raw_metadata: Dictionary containing device metadata
    """

    def __init__(self, raw_metadata: dict[str, Any]) -> None:
        """Initialize BLE device metadata wrapper.

        Args:
            raw_metadata: Device metadata dictionary from config entry
        """
        self._metadata = raw_metadata

    @property
    def width(self) -> int:
        """Get display width in pixels.

        Returns:
            Display width, or 0 if not available
        """
        return self._metadata.get("width", 0)

    @property
    def height(self) -> int:
        """Get display height in pixels.

        Returns:
            Display height, or 0 if not available
        """
        return self._metadata.get("height", 0)

    @property
    def model_name(self) -> str:
        """Get device model name.

        Returns:
            Model name string, or "Unknown" if not available
        """
        return self._metadata.get("model_name", "Unknown")

    @property
    def fw_version(self) -> int | str:
        """Get firmware version.

        Returns:
            Firmware version number, or 0 if not available
        """
        return self._metadata.get("fw_version", 0)

    def formatted_fw_version(self) -> str | None:
        """Return firmware version formatted for display."""
        fw = self.fw_version
        if fw in (None, ""):
            return None
        if isinstance(fw, int):
            return f"0x{fw:04x}"
        return str(fw)

    @property
    def rotatebuffer(self) -> int:
        """Get rotation/rotatebuffer flag.

        Returns:
            Rotatebuffer flag (0 or 1)
        """
        return self._metadata.get("rotatebuffer", 0)

    @property
    def hw_type(self) -> int:
        """Get hardware type identifier.

        Returns:
            Hardware type code, or 0 if not available
        """
        return self._metadata.get("hw_type", 0)

    @property
    def color_scheme(self) -> ColorScheme:
        """Get ColorScheme enum for this device."""
        raw_scheme = self._metadata.get("color_scheme", 0)
        return ColorScheme.from_int(raw_scheme)

    @property
    def accent_color(self) -> str:
        """Get accent color name.

        Returns:
            Accent color name from color scheme palette
        """
        return self.color_scheme.accent_color

    @property
    def is_multi_color(self) -> bool:
        """Check if device supports multiple colors.

        Returns:
            True if color scheme has more than 2 colors, False otherwise
        """
        return self.color_scheme.is_multi_color
