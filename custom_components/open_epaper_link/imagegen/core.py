from __future__ import annotations

import io
import logging
from typing import Optional, Dict, Any

from PIL import Image
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from ..const import DOMAIN
from ..tag_types import TagType, get_tag_types_manager
from ..util import get_hub_from_hass
from ..runtime_data import OpenEPaperLinkBLERuntimeData

from .types import ElementType, DrawingContext
from .colors import ColorResolver
from .coordinates import CoordinateParser
from .fonts import FontManager
from .registry import get_all_handlers

# Import handler modules to trigger decorator registration
from . import text, shapes, icons, media, visualizations, debug

_LOGGER = logging.getLogger(__name__)


def _detect_accent_color_from_color_table(color_table: dict) -> str:
    """
    Detect accent color from color table based on available colors.

    Logic mirrors ColorScheme:

    - If yellow in pallete but red not in palette -> yellow
    - If red in palette -> red
    - Else -> black

    Returns:
        str: Detected accent color name
    """
    has_red = "red" in color_table
    has_yellow = "yellow" in color_table

    if has_yellow and not has_red:
        return "yellow"
    elif has_red:
        return "red"
    else:
        return "black"


class ImageGen:
    """Handles custom image generation for ESLs.

    This is the core class of the module, responsible for generating images
    for electronic shelf labels (ESLs). It provides methods for drawing various
    elements like text, shapes, images, etc., and combines them into a final image.

    The class supports a variety of element types, each with its own drawing method,
    and handles the common aspects of image generation such as tag information retrieval,
    element validation, and drawing coordination.
    """

    def __init__(self, hass: HomeAssistant):
        """Initialize the image generator.

        Sets up the image generator with the necessary components and handlers.

        Args:
            hass: Home Assistant instance
        """
        self.hass = hass

        # Load font manager - find a Hub entry with .entry attribute, or None for BLE-only setups
        self._entry = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            if hasattr(entry, 'runtime_data') and entry.runtime_data is not None:
                # Look for Hub entries (not BLE entries)
                if not isinstance(entry.runtime_data, OpenEPaperLinkBLERuntimeData):
                    self._entry = entry
                    break
        # If no Hub found, self._entry stays None (BLE-only setup)

        self._font_manager = FontManager(self.hass, self._entry)

        # Initialize handler mapping
        self._draw_handlers = {
            element_type: handler
            for element_type, (handler, _) in get_all_handlers().items()
        }

    async def get_tag_info(self, entity_id: str) -> Optional[tuple[TagType, str]]:
        """Get tag type information for an entity.

        Retrieves tag type information and accent color for the specified entity.
        This includes display dimensions, color capabilities, and other hardware details.

        Args:
            entity_id: The entity ID to get tag information for

        Returns:
            tuple: (TagType object, accent color string)
            None: If tag information could not be retrieved

        Raises:
            HomeAssistantError: For various error conditions (offline AP, unknown tag, etc.)
        """

        try:
            # Get hub instance
            hub = get_hub_from_hass(self.hass)
            if not hub.online:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="ap_offline_core",
                )

            # Get tag MAC from entity ID
            try:
                tag_mac = entity_id.split(".")[1].upper()
            except IndexError:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_entity_id_format",
                    translation_placeholders={"entity_id": entity_id}
                )
            # First check if tag is known to the hub
            if tag_mac not in hub.tags:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="tag_not_registered",
                    translation_placeholders={"tag_mac": tag_mac},
                )

            # Check if tag is blacklisted
            if tag_mac in hub.get_blacklisted_tags():
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="tag_blacklisted",
                    translation_placeholders={"tag_mac": tag_mac},
                )

            # Get tag data - should exist since hub.tags was checked
            tag_data = hub.get_tag_data(tag_mac)
            if not tag_data:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="tag_inconsistent",
                    translation_placeholders={"tag_mac": tag_mac},
                )

            # Get hardware type
            hw_type = tag_data.get("hw_type")
            if hw_type is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="tag_no_hw_type",
                    translation_placeholders={"tag_mac": tag_mac},
                )

            # Get tag type information
            tag_manager = await get_tag_types_manager(self.hass)
            tag_type = await tag_manager.get_tag_info(hw_type)

            if not tag_type:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="tag_unknown_hw_type",
                    translation_placeholders={"hw_type": hw_type},
                )
            # Get accent color from tag type's color table if it exists
            # Default to red if no color table or no accent specified
            try:
                color_table = getattr(tag_type, 'color_table', {})
                accent_color = _detect_accent_color_from_color_table(color_table)
            except Exception as e:
                _LOGGER.warning("Error getting accent color, defaulting to red: %s", e)
                accent_color = "red"
            return tag_type, accent_color

        except Exception as e:
            # Convert any unknown exceptions to HomeAssistantError with context
            if not isinstance(e, HomeAssistantError):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="ble_tag_info_unexpected",
                    translation_placeholders={"entity_id": entity_id, "error": str(e)},
                ) from e
            raise

    async def get_ble_tag_info(self, hass: HomeAssistant, entity_id: str) -> tuple[int, int, str]:
        """Get tag type information for a BLE entity.

        Retrieves tag type information and accent color for BLE devices from
        stored device metadata instead of Hub data.

        Args:
            hass: Home Assistant instance
            entity_id: The BLE entity ID to get tag information for

        Returns:
            tuple: (width, height, accent_color)

        Raises:
            HomeAssistantError: If BLE device metadata is not found
        """
        try:
            # Get MAC from entity ID
            try:
                tag_mac = entity_id.split(".")[1].upper()
            except IndexError:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_entity_id_format",
                    translation_placeholders={"entity_id": entity_id}
                )
            # Get device metadata from config entry runtime_data
            device_metadata = None

            # Find the config entry for this BLE device
            for entry in hass.config_entries.async_entries(DOMAIN):
                runtime_data = getattr(entry, 'runtime_data', None)
                if runtime_data is not None and isinstance(runtime_data, OpenEPaperLinkBLERuntimeData):
                    if runtime_data.mac_address.upper() == tag_mac:
                        device_metadata = runtime_data.device_metadata
                        protocol_type = runtime_data.protocol_type
                        break

            if not device_metadata:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="ble_no_metadata",
                    translation_placeholders={"entity_id": entity_id}
                )
            # Wrap metadata for clean access
            from ..ble import BLEDeviceMetadata
            metadata = BLEDeviceMetadata(device_metadata)

            # Extract device capabilities
            hw_type = metadata.hw_type
            width = metadata.width
            height = metadata.height

            _LOGGER.debug("BLE device metadata for %s: width=%d, height=%d", entity_id, width, height)

            color_scheme = metadata.color_scheme

            color_table = {name: list(rgb) for name, rgb in color_scheme.palette.colors.items()}
            color_table["accent"] = color_scheme.accent_color
            accent_color = color_scheme.accent_color

            return width, height, accent_color

        except Exception as e:
            # Convert any unknown exceptions to HomeAssistantError with context
            if not isinstance(e, HomeAssistantError):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="ble_tag_info_unexpected_ble",
                    translation_placeholders={"entity_id": entity_id, "error": str(e)},
                ) from e
            raise

    async def get_tag_dimensions(
            self,
            entity_id: str,
            is_ble: bool = False
    ) -> tuple[int, int, str]:
        """
        Get dimensions and accent color for any device type.

        Unified interface for both AP and BLE devices.

        Args:
            entity_id: The entity ID
            is_ble: True if the device is BLE, False for AP devices

        Returns:
            tuple: (width, height, accent_color)

        Raises:
            HomeAssistantError: If tag information could not be retrieved
        """
        if is_ble:
            return await self.get_ble_tag_info(self.hass, entity_id)
        else:
            tag_type, accent_color = await self.get_tag_info(entity_id)
            return tag_type.width, tag_type.height, accent_color

    @staticmethod
    def should_show_element(element: dict) -> bool:
        """Check if an element should be displayed.

        Elements can be hidden by setting visible=False in their definition.
        This is useful for conditional rendering.

        Args:
            element: Element dictionary

        Returns:
            bool: True if the element should be displayed, False otherwise
        """

        return element.get("visible", True)

    async def generate_custom_image(
            self,
            entity_id: str,
            service_data: Dict[str, Any],
            error_collector: list = None,
            *,
            width: int,
            height: int,
            accent_color: str,
    ) -> bytes:
        """Generate a custom image based on service data.

        Main entry point for image generation. Creates an image with the
        specified elements and returns the JPEG data.

        Args:
            entity_id: The entity ID to generate the image for
            service_data: Service data containing image parameters and payload
            error_collector: Optional list to collect error messages
            width: Canvas width in pixels
            height: Canvas height in pixels
            accent_color: Accent color name

        Returns:
            bytes: JPEG image data

        Raises:
            HomeAssistantError: If image generation fails
        """

        error_collector = error_collector if error_collector is not None else []

        canvas_width = width
        canvas_height = height

        # Validate dimensions to prevent PIL errors
        if canvas_width <= 0 or canvas_height <= 0:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_canvas_dimensions",
                translation_placeholders={"width": canvas_width, "height": canvas_height, "entity_id": entity_id}
            )

        _LOGGER.debug("Canvas dimensions for %s: %dx%d", entity_id, canvas_width, canvas_height)

        colors = ColorResolver(accent_color)

        # Get rotation and create base image
        rotate = service_data.get("rotate", 0)
        if rotate in (0, 180):
            img = Image.new('RGBA', (canvas_width, canvas_height),
                            color=colors.resolve(service_data.get("background", "white")))
        else:
            img = Image.new('RGBA', (canvas_height, canvas_width),
                            color=colors.resolve(service_data.get("background", "white")))

        payload = service_data.get("payload", [])

        ctx = DrawingContext(
            img=img,
            colors=colors,
            coords=CoordinateParser(img.width, img.height),
            fonts=self._font_manager,
            hass=self.hass,
            pos_y=0
        )

        for i, element in enumerate(payload):
            if not self.should_show_element(element):
                continue

            try:
                # Get element type
                if "type" not in element:
                    raise ValueError("Element missing required 'type' field")
                element_type = ElementType(element["type"])

                # Get the appropriate handler and call it
                handler = self._draw_handlers.get(element_type)
                if handler:
                    await handler(ctx, element)
                else:
                    error_msg = f"No handler found for element type: {element_type}"
                    _LOGGER.warning(error_msg)
                    error_collector.append(f"Element {i + 1}: {error_msg}")

            except (ValueError, KeyError) as e:
                error_msg = f"Element {i + 1}: {str(e)}"
                _LOGGER.error(error_msg)
                error_collector.append(error_msg)
                continue
            except Exception as e:
                error_msg = f"Element {i + 1} (type '{element.get('type', 'unknown')}'): {str(e)}"
                _LOGGER.error(error_msg)
                error_collector.append(error_msg)
                continue
        # Apply rotation if needed
        if rotate:
            img = img.rotate(rotate, expand=True)

        # Convert to RGB for JPEG
        rgb_image = img.convert('RGB')

        # Create BytesIO object for the JPEG data
        img_byte_arr = io.BytesIO()
        rgb_image.save(img_byte_arr, format='JPEG', quality="maximum")
        image_data = img_byte_arr.getvalue()

        return image_data
