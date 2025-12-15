"""BLE operations with decorator for automatic retry and locking."""
import asyncio
import logging
from functools import wraps
from typing import Dict

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from bleak.exc import BleakError

from .connection import BLEConnection
from .exceptions import BLEConnectionError
from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Per-device async locks for preventing concurrent operations
_device_locks: Dict[str, asyncio.Lock] = {}

# LED control commands (common to all protocols)
CMD_LED_ON = bytes.fromhex("000103")
CMD_LED_OFF = bytes.fromhex("000100")
CMD_LED_OFF_FINAL = bytes.fromhex("0000")


def ble_device_operation(func):
    """Decorator for BLE operations with automatic connection, retry, and locking.

    Provides:
    - Per-device async locking (prevents concurrent operations on same device)
    - 3 retry attempts with exponential backoff (0.25s, 0.5s, 0.75s)
    - Automatic connection creation with protocol-specific service UUID
    - Error handling and logging

    The decorated function receives a BLEConnection as first argument.
    Requires 'hass', 'mac_address', 'service_uuid', and 'protocol' in function arguments/kwargs.
    """

    @wraps(func)
    async def wrapper(hass: HomeAssistant, mac_address: str, service_uuid: str, protocol, *args, **kwargs):
        # Get or create lock for this device
        lock = _device_locks.setdefault(mac_address, asyncio.Lock())

        async with lock:
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    # Create connection with protocol-specific service UUID
                    async with BLEConnection(hass, mac_address, service_uuid, protocol) as conn:
                        # Inject connection as first argument to decorated function
                        return await func(conn, *args, **kwargs)

                except BLEConnectionError as e:
                    # Check if it's a connection slots error - don't retry these
                    if "No available Bluetooth connection slots" in str(e):
                        raise HomeAssistantError(
                            translation_domain=DOMAIN,
                            translation_key="ble_slots_unavailable",
                            translation_placeholders={"mac_address": mac_address, "error": str(e)},
                        ) from e

                    # For other connection errors, retry
                    if attempt == max_attempts - 1:
                        raise HomeAssistantError(
                            translation_domain=DOMAIN,
                            translation_key="ble_operation_failed",
                            translation_placeholders={
                                "operation": func.__name__,
                                "attempts": max_attempts,
                                "error": str(e),
                            },
                        ) from e

                    backoff_time = 0.25 * (attempt + 1)
                    _LOGGER.warning(
                        "BLE operation %s failed on attempt %d: %s. Retrying in %.2f seconds...",
                        func.__name__,
                        attempt + 1,
                        e,
                        backoff_time,
                    )
                    await asyncio.sleep(backoff_time)

                except BleakError as e:
                    if attempt == max_attempts - 1:
                        _LOGGER.error(
                            "BLE operation %s failed after %d attempts: %s",
                            func.__name__,
                            max_attempts,
                            e,
                        )
                        raise
                    backoff_time = 0.25 * (attempt + 1)
                    _LOGGER.warning(
                        "BLE operation %s failed on attempt %d: %s. Retrying in %.2f seconds...",
                        func.__name__,
                        attempt + 1,
                        e,
                        backoff_time,
                    )
                    await asyncio.sleep(backoff_time)

            return None

    return wrapper


@ble_device_operation
async def turn_led_on(conn: BLEConnection) -> bool:
    """Turn on LED for specified device.

    Args:
        conn: Active BLE connection

    Returns:
        bool: True if command sent successfully
    """
    await conn.write_command(CMD_LED_ON)
    return True


@ble_device_operation
async def turn_led_off(conn: BLEConnection) -> bool:
    """Turn off LED for specified device.

    Args:
        conn: Active BLE connection

    Returns:
        bool: True if command sent successfully
    """
    await conn.write_command(CMD_LED_OFF)
    await conn.write_command(CMD_LED_OFF_FINAL)  # Required finalization command
    return True


@ble_device_operation
async def ping_device(conn: BLEConnection) -> bool:
    """Test device connectivity.

    Args:
        conn: Active BLE connection

    Returns:
        bool: True if device is reachable
    """
    # If connection and initialization succeed, device is reachable
    return True
