"""BLE Device Metadata Abstraction.

Provides a clean interface for accessing device metadata that transparently
handles differences between ATC (flat structure) and OEPL (nested config) formats.
"""
from __future__ import annotations

from typing import Any


class BLEDeviceMetadata:
    """Abstraction for BLE device metadata.

    Wraps raw metadata dictionary and provides clean property-based access
    to device capabilities, handling both ATC and OEPL metadata formats.

    Args:
        raw_metadata: Dictionary containing device metadata
    """

    def __init__(self, raw_metadata: dict[str, Any]) -> None:
        """Initialize BLE device metadata wrapper.

        Args:
            raw_metadata: Device metadata dictionary from config entry
        """
        self._metadata = raw_metadata
        self._is_oepl = "oepl_config" in raw_metadata

    @property
    def width(self) -> int:
        """Get display width in pixels.

        Returns:
            Display width, or 0 if not available
        """
        if self._is_oepl:
            displays = self._metadata["oepl_config"].get("displays", [])
            return displays[0]["pixel_width"] if displays else 0
        return self._metadata.get("width", 0)

    @property
    def height(self) -> int:
        """Get display height in pixels.

        Returns:
            Display height, or 0 if not available
        """
        if self._is_oepl:
            displays = self._metadata["oepl_config"].get("displays", [])
            return displays[0]["pixel_height"] if displays else 0
        return self._metadata.get("height", 0)

    @property
    def model_name(self) -> str:
        """Get device model name.

        Returns:
            Model name string, or "Unknown" if not available
        """
        return self._metadata.get("model_name", "Unknown")

    @property
    def fw_version(self) -> int:
        """Get firmware version.

        Returns:
            Firmware version number, or 0 if not available
        """
        # For OEPL, fw_version would be in system config but isn't parsed yet
        # Fall back to stored value for now
        return self._metadata.get("fw_version", 0)

    @property
    def color_support(self) -> str:
        """Get color support capability.

        Returns:
            Color support: "mono", "red", "yellow", or "bwry"
        """
        if self._is_oepl:
            displays = self._metadata["oepl_config"].get("displays", [])
            if displays:
                color_scheme = displays[0].get("color_scheme", 0)
                # 0=b/w, 1=bwr, 2=bwy, 3=bwry, 4=bwgbry, 5=bw4
                if color_scheme == 0 or color_scheme == 5:
                    return "mono"
                if color_scheme in (1, 3, 4):  # Has red
                    return "red"
                if color_scheme == 2:  # Has yellow
                    return "yellow"
        return self._metadata.get("color_support", "mono")

    @property
    def rotatebuffer(self) -> int:
        """Get rotation setting.

        For OEPL devices, returns the rotation value from display config.
        For ATC devices, returns the rotatebuffer flag.

        Returns:
            Rotation value (0, 1, 2, or 3) or rotatebuffer flag (0 or 1)
        """
        if self._is_oepl:
            displays = self._metadata["oepl_config"].get("displays", [])
            return displays[0].get("rotation", 0) if displays else 0
        return self._metadata.get("rotatebuffer", 0)

    @property
    def hw_type(self) -> int:
        """Get hardware type identifier.

        Returns:
            Hardware type code, or 0 if not available
        """
        if self._is_oepl:
            displays = self._metadata["oepl_config"].get("displays", [])
            return displays[0].get("oepl_tagtype", 0) if displays else 0
        return self._metadata.get("hw_type", 0)

    @property
    def power_mode(self) -> int:
        """Get power mode setting.

        Returns:
            Power mode: 1=battery, 2=USB, 3=solar
            ATC devices always return 1 (battery)
        """
        if self._is_oepl:
            power = self._metadata["oepl_config"].get("power")
            if power:
                return power.get("power_mode", 1)
        return 1  # ATC devices always have batteries

    @property
    def is_oepl(self) -> bool:
        """Check if this is an OEPL device.

        Returns:
            True if OEPL device, False if ATC device
        """
        return self._is_oepl
