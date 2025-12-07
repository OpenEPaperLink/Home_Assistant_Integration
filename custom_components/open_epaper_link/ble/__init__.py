"""BLE protocol abstraction for OpenEPaperLink devices."""
from .color_scheme import ColorScheme
# Re-export key classes and functions for backward compatibility
from .connection import BLEConnection
from .image_upload import BLEImageUploader
from .metadata import BLEDeviceMetadata
from .operations import (
    turn_led_on,
    turn_led_off,
    ping_device,
)
from .protocol_factory import (
    get_protocol_by_manufacturer_id,
    get_protocol_by_name,
    get_supported_manufacturer_ids,
)
from .protocol_base import AdvertisingData, DeviceCapabilities
from .exceptions import (
    BLEError,
    BLEConnectionError,
    BLEProtocolError,
    BLETimeoutError,
    UnsupportedProtocolError,
    ConfigValidationError,
)

__all__ = [
    # Connection
    "BLEConnection",
    # Image upload
    "BLEImageUploader",
    # Metadata
    "BLEDeviceMetadata",
    # Operations
    "turn_led_on",
    "turn_led_off",
    "ping_device",
    # Protocol factory
    "get_protocol_by_manufacturer_id",
    "get_protocol_by_name",
    "get_supported_manufacturer_ids",
    # Data structures
    "AdvertisingData",
    "DeviceCapabilities",
    "ColorScheme",
    # Exceptions
    "BLEError",
    "BLEConnectionError",
    "BLEProtocolError",
    "BLETimeoutError",
    "UnsupportedProtocolError",
    "ConfigValidationError",
]
