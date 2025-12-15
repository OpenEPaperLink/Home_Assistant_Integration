"""BLE connection management."""
import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.components import bluetooth
from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakOutOfConnectionSlotsError,
    establish_connection,
)

from .exceptions import BLEConnectionError, BLEProtocolError, BLETimeoutError
from ..const import DOMAIN


if TYPE_CHECKING:
    from .protocol_base import BLEProtocol

_LOGGER = logging.getLogger(__name__)

# Protocol initialization command for ATC protocol
CMD_INIT = bytes([0x01, 0x01])

INIT_DELAY_SECONDS = 2.0


class BLEConnection:
    """Context manager for BLE connections with protocol-specific service UUID.

    Manages BLE connection lifecycle including:
    - Connection establishment with retry logic
    - Service/characteristic resolution
    - Notification handling
    - Protocol initialization
    - Graceful disconnection
    """

    def __init__(self, hass: HomeAssistant, mac_address: str, service_uuid: str, protocol: "BLEProtocol"):
        """Initialize BLE connection manager.

        Args:
            hass: Home Assistant instance
            mac_address: Device MAC address
            service_uuid: Protocol-specific BLE service UUID
            protocol: Protocol instance for this device
        """
        self.hass = hass
        self.mac_address = mac_address
        self.service_uuid = service_uuid
        self.protocol = protocol
        self.client: BleakClient | None = None
        self.write_char = None
        self._response_queue = asyncio.Queue()
        self._notification_active = False

    async def __aenter__(self):
        """Establish BLE connection and initialize protocol."""
        try:
            device = bluetooth.async_ble_device_from_address(
                self.hass, self.mac_address, connectable=True
            )
            if not device:
                raise BLEConnectionError(
                    translation_domain=DOMAIN,
                    translation_key="ble_device_not_found",
                    translation_placeholders={"mac_address": self.mac_address}
                )

            self.client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                f"BLE-{self.mac_address}",
                self._disconnected_callback,
                timeout=15.0,
            )

            # Resolve protocol-specific service characteristic
            if not self._resolve_characteristic():
                await self.client.disconnect()
                raise BLEConnectionError(
                    translation_domain=DOMAIN,
                    translation_key="ble_characteristic_not_resolved",
                    translation_placeholders={ "service_uuid": self.service_uuid}
                )

            # Enable notifications for protocol responses
            await self.client.start_notify(self.write_char, self._notification_callback)
            self._notification_active = True

            # Let protocol handle its own initialization requirements
            await self.protocol.initialize_connection(self)

            return self

        except BleakOutOfConnectionSlotsError as e:
            await self._cleanup()
            raise BLEConnectionError(
                translation_domain=DOMAIN,
                translation_key="ble_slots_unavailable",
                translation_placeholders={"mac_address": self.mac_address, "error": str(e)}
            ) from e

        except (BleakError, asyncio.TimeoutError) as e:
            await self._cleanup()
            raise BLEConnectionError(
                translation_domain=DOMAIN,
                translation_key="ble_connection_failed",
                translation_placeholders={"mac_address": self.mac_address, "error": str(e)}
            ) from e

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up BLE connection."""
        await self._cleanup()

    async def _cleanup(self):
        """Clean up connection resources."""
        if self.client and self.client.is_connected:
            if self._notification_active:
                try:
                    await self.client.stop_notify(self.write_char)
                except Exception:
                    _LOGGER.debug("Failed to stop notifications during cleanup")
                finally:
                    self._notification_active = False
            try:
                await self.client.disconnect()
            except Exception:
                _LOGGER.debug("Failed to disconnect during cleanup")

    def _resolve_characteristic(self) -> bool:
        """Resolve BLE characteristic for the protocol-specific service.

        Returns:
            bool: True if characteristic was resolved successfully
        """
        try:
            if not self.client or not self.client.services:
                return False

            # Find the protocol-specific service characteristic
            char = self.client.services.get_characteristic(self.service_uuid)
            if char:
                self.write_char = char
                _LOGGER.debug(
                    "Resolved characteristic for service %s on %s",
                    self.service_uuid,
                    self.mac_address,
                )
                return True

            _LOGGER.error(
                "Could not find characteristic for service %s on %s",
                self.service_uuid,
                self.mac_address,
            )
            return False

        except Exception as e:
            _LOGGER.error(
                "Error resolving characteristic for %s: %s", self.mac_address, e
            )
            return False

    def _notification_callback(self, sender, data: bytearray) -> None:
        """Handle notification from device.

        Args:
            sender: Notification sender
            data: Notification data
        """
        try:
            self._response_queue.put_nowait(bytes(data))
        except asyncio.QueueFull:
            _LOGGER.warning(
                "Response queue full for %s, dropping notification", self.mac_address
            )

    async def _write_raw(self, data: bytes) -> None:
        """Write raw data to device characteristic.

        Args:
            data: Raw bytes to write

        Raises:
            BLEProtocolError: If write characteristic is not available
        """
        if not self.write_char:
            raise BLEProtocolError(
                translation_domain=DOMAIN,
                translation_key="ble_write_char_missing",
            )

        await self.client.write_gatt_char(self.write_char, data, response=False)

    async def write_command_with_response(
        self, command: bytes, timeout: float = 10.0
    ) -> bytes:
        """Write command and wait for response.

        Args:
            command: Command bytes to write
            timeout: Response timeout in seconds

        Returns:
            bytes: Response data from device

        Raises:
            BLETimeoutError: If no response received within timeout
        """
        # Clear any pending responses
        while not self._response_queue.empty():
            try:
                self._response_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        await self._write_raw(command)

        try:
            response = await asyncio.wait_for(self._response_queue.get(), timeout=timeout)
            return response
        except asyncio.TimeoutError:
            raise BLETimeoutError(
                translation_domain=DOMAIN,
                translation_key="ble_timeout",
                translation_placeholders={"mac_address": self.mac_address, "timeout": timeout},
            ) from None

    async def write_command(self, data: bytes) -> None:
        """Write command to device without expecting response.

        Args:
            data: Command bytes to write
        """
        await self._write_raw(data)

    def _disconnected_callback(self, client: BleakClient) -> None:
        """Handle disconnection event.

        Args:
            client: Disconnected BleakClient
        """
        _LOGGER.debug("Device %s disconnected", self.mac_address)
