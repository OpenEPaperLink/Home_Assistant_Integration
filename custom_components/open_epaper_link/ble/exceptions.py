"""BLE operation exceptions."""
from homeassistant.exceptions import HomeAssistantError


class BLEError(HomeAssistantError):
    """Base BLE operation error."""


class BLEConnectionError(BLEError):
    """Connection to device failed."""


class BLEProtocolError(BLEError):
    """Protocol communication error."""


class BLETimeoutError(BLEError):
    """Operation timed out."""


class UnsupportedProtocolError(BLEError):
    """Unknown manufacturer ID or unsupported firmware protocol."""


class ConfigValidationError(BLEError):
    """TLV config parsing or validation error."""
