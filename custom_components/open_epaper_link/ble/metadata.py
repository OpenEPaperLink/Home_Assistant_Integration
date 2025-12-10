"""BLE Device Metadata Abstraction.

Provides a clean interface for accessing device metadata that transparently
handles differences between ATC (flat structure) and OEPL (nested config) formats.
"""
from __future__ import annotations

from typing import Any

from .color_scheme import ColorScheme

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
    def fw_version(self) -> int | str:
        """Get firmware version.

        Returns:
            Firmware version number or string, or 0/"" if not available
        """
        if self._is_oepl:
            # Prefer explicit string/parsed version saved from interrogation
            if "fw_version" in self._metadata:
                return self._metadata.get("fw_version", "")
            major = self._metadata.get("fw_version_major")
            minor = self._metadata.get("fw_version_minor")
            if major is not None and minor is not None:
                return f"{major}.{minor}"
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

    @property
    def color_scheme(self) -> ColorScheme:
        """
        Get ColorScheme enum for this device.

        ATC: Reads from root level device_metadata["color_scheme"]

        OEPL: Reads from display config device_metadata["oepl_config"]["displays"][0]["color_scheme"]
        """
        if self._is_oepl:
            displays = self._metadata["oepl_config"].get("displays", [])
            raw_scheme = displays[0].get("color_scheme", 0) if displays else 0
        else:
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

    @property
    def transmission_modes(self) -> int:
        """Get supported transmission modes (bitfield).

        Bit flags:
        - Bit 0 (0x01): raw transfer (block-based uncompressed)
        - Bit 1 (0x02): zip compressed transfer (block-based compressed)
        - Bit 3 (0x08): direct_write mode

        Returns:
            Transmission modes bitfield, or 0 if not available
            ATC devices return 0 (assume block-based only for backward compatibility)
        """
        if self._is_oepl:
            displays = self._metadata["oepl_config"].get("displays", [])
            return displays[0].get("transmission_modes", 0) if displays else 0
        return 0  # ATC devices don't support direct_write

    def get_best_upload_method(self, image_size: int  = 0) -> str:
        """Determine the best upload method based on device capabilities and iamge size.

        Priority order:
        1. direct_write_compressed: If direct_write (0x08) AND zip (0x02) are supported and size < 50KB
        2. direct_write: If direct_write (0x08) is supported but zip is not
        3. block: Fallback to block-based upload (always supported)

        Returns:
            Upload method string: "direct_write_compressed", "direct_write", or "block"
        """
        modes = self.transmission_modes
        has_direct_write = (modes & 0x08) != 0
        has_zip = (modes & 0x02) != 0

        if has_direct_write and has_zip and image_size < 50 * 1024:
            return "direct_write_compressed"
        elif has_direct_write:
            return "direct_write"
        else:
            return "block"
