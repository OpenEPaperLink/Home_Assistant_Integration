from __future__ import annotations
import os
import logging
from typing import Dict, List, Tuple

from PIL import ImageFont
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)
_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")


class FontManager:
    """Class for managing font loading, caching and path resolution.

    Handles font discovery, loading, and caching to improve performance.
    Searches multiple directories for fonts and provides fallback mechanisms
    for when requested fonts are not available.
    """

    def __init__(self, hass: HomeAssistant, entry=None):
        """Initialize the font manager.

        Args:
            hass: Home Assistant instance for config path resolution
            entry: Config entry for accessing user-configured font directories
        """
        self._hass = hass
        self._entry = entry
        self._font_cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}
        self._known_dirs = []

        # Standard font directories to search
        self._font_dirs = []
        self._setup_font_dirs()

        # Default font names
        self._default_fonts = ["ppb.ttf", "rbm.ttf"]

        # Load initial custom font directories if entry is provided
        if entry:
            self._load_custom_font_dirs()

    def _setup_font_dirs(self):
        """Set up font directories based on the Home Assistant environment.

        Follows the documented search order:
        1. Integration assets directory (for default fonts)
        2. Web directory (/config/www/fonts/)
        3. Media directory (/media/fonts/)
        """
        # Clear existing dirs
        self._font_dirs = []

        # Integration assets directory
        if os.path.exists(_ASSETS_DIR):
            self._font_dirs.append(_ASSETS_DIR)

        # Web directory
        www_fonts_dir = self._hass.config.path("www/fonts")
        if os.path.exists(www_fonts_dir):
            self._font_dirs.append(www_fonts_dir)
            _LOGGER.debug(f"Found {www_fonts_dir} in Home Assistant")

        # Try to locate the media directory based on installation type
        # Home Assistant OS/Supervised installations use /media
        # Core/Container installations typically use /config/media
        media_paths = [
            self._hass.config.path("media/fonts"),  # /config/media/fonts (Core/Container)
            "/media/fonts",  # /media/fonts (OS/Supervised)
        ]

        # Add media paths
        for path in media_paths:
            if os.path.exists(path):
                if path not in self._font_dirs:
                    self._font_dirs.append(path)
                    _LOGGER.debug(f"Found {path} in Home Assistant")

    def get_font(self, font_name: str, size: int) -> ImageFont.FreeTypeFont:
        """Get a font, loading it if necessary.

        Attempts to load the requested font from the configured font directories.
        Uses a cache for performance and provides fallback to default fonts
        if the requested font is not found.

        Args:
            font_name: Font filename or absolute path
            size: Font size in pixels

        Returns:
            Loaded font object

        Raises:
            HomeAssistantError: If no font could be loaded
        """
        # Check if config has changed since last load
        if self._entry:
            custom_dirs_str = self._entry.options.get("custom_font_dirs", "")
            current_dirs = [d.strip() for d in custom_dirs_str.split(";") if d.strip()]
            if current_dirs != self._known_dirs:
                _LOGGER.debug("Font directories changed, updating...")

                # Clear current cache
                self.clear_cache()

                # Reset known dirs and load new ones
                self._setup_font_dirs()
                for directory in current_dirs:
                    if directory and directory.strip():
                        self.add_font_directory(directory.strip())

                # Update known dirs
                self._known_dirs = current_dirs

        # Create cache key (font name, size)
        cache_key = (font_name, size)

        # Return cached font if available
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]

        # Load font from file
        font = self._load_font(font_name, size)

        # Cache font
        self._font_cache[cache_key] = font
        return font

    def get_available_fonts(self) -> List[str]:
        """Get list of available font names from all directories.

        Scans all configured font directories and returns a list of
        available font filenames.

        Returns:
            List of font filenames
        """
        fonts = set()

        # Scan all directories
        for directory in self._font_dirs:
            if not os.path.exists(directory):
                continue

            try:
                # Get all TTF files in the directory
                for file in os.listdir(directory):
                    if file.lower().endswith(('.ttf', '.otf')):
                        fonts.add(file)
            except (OSError, IOError) as err:
                _LOGGER.warning("Error scanning font directory %s: %s", directory, err)

        return sorted(list(fonts))

    def _load_font(self, font_name: str, size: int) -> ImageFont.FreeTypeFont:
        """Load a font from disk.

        Attempts to load the requested font by trying various locations.
        If the font cannot be found, falls back to default fonts.

        Args:
            font_name: Font filename or absolute path
            size: Font size in pixels

        Returns:
            Loaded font object

        Raises:
            HomeAssistantError: If no font could be loaded
        """
        # If font name is an absolute path, load directly
        if os.path.isabs(font_name):
            try:
                return ImageFont.truetype(font_name, size)
            except (OSError, IOError) as err:
                _LOGGER.warning(
                    "Could not load font from absolute path %s: %s. "
                    "Will try standard font locations.",
                    font_name, err
                )

        for font_dir in self._font_dirs:
            try:
                if not os.path.exists(font_dir):
                    continue

                font_path = os.path.join(font_dir, font_name)
                if not os.path.exists(font_path):
                    continue

                return ImageFont.truetype(font_path, size)
            except (OSError, IOError):
                continue

        # Font was not found in any standard location
        _LOGGER.warning(
            "Font '%s' not found in any of the standard locations. "
            "Place fonts in /config/www/fonts/ or /config/media/fonts/ or provide absolute path. "
            "Falling back to default font.",
            font_name
        )

        # Try default fonts as fallback
        for default_font in self._default_fonts:
            try:
                default_path = os.path.join(_ASSETS_DIR, default_font)
                return ImageFont.truetype(default_path, size)
            except (OSError, IOError):
                continue

        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="font_load_failed"
        )

    def _load_custom_font_dirs(self) -> None:
        """Load custom font directories from config entry.

        Parses the custom_font_dirs option from the config entry and adds
        each specified directory to the font search path.
        """
        if not self._entry:
            return

        # Get custom font directory from config
        custom_dirs_str = self._entry.options.get("custom_font_dirs", "")
        custom_dirs = [d.strip() for d in custom_dirs_str.split(";") if d.strip()]

        # Save current dirs for comparison
        self._known_dirs = custom_dirs

        # Add each directory
        for directory in custom_dirs:
            if directory and directory.strip():
                self.add_font_directory(directory.strip())

    def add_font_directory(self, directory: str) -> bool:
        """Add a custom font directory to search.

        Adds a directory to the font search path if it is a valid
        absolute path to an existing directory.

        Args:
            directory: Absolute path to directory containing fonts

        Returns:
            True if directory was added, False otherwise
        """
        if not os.path.isabs(directory):
            _LOGGER.warning(
                "Custom font directory '%s' is not an absolute path, skipping", directory
            )
            return False

        if not os.path.isdir(directory):
            _LOGGER.warning(
                "Custom font directory '%s' does not exist, skipping", directory
            )
            return False

        if directory not in self._font_dirs:
            self._font_dirs.insert(0, directory)
            return True

        return False

    def clear_cache(self) -> None:
        """Clear the font cache.

        Removes all cached fonts, forcing them to be reloaded on next request.
        This is typically called when font directories change.
        """
        self._font_cache.clear()
