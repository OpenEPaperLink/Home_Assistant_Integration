"""ATC firmware protocol implementation."""
import struct
import logging
from typing import TYPE_CHECKING

from .protocol_base import BLEProtocol, AdvertisingData, DeviceCapabilities
from .exceptions import BLEProtocolError
from ..const import DOMAIN

if TYPE_CHECKING:
    from .connection import BLEConnection

_LOGGER = logging.getLogger(__name__)

# ATC protocol constants
CMD_GET_DISPLAY_INFO = bytes([0x00, 0x05])
BLE_MIN_RESPONSE_LENGTH = 33


class ATCProtocol(BLEProtocol):
    """ATC firmware protocol implementation.

    Supports the original ATC BLE firmware protocol with:
    - Manufacturer ID: 0x1337 (4919)
    - Service UUID: 00001337-0000-1000-8000-00805f9b34fb
    - Interrogation: CMD_GET_DISPLAY_INFO (0x0005)
    - Advertising: Version 1 (10 bytes) and Version 2 (11 bytes with temperature)
    """

    @property
    def manufacturer_id(self) -> int:
        """Bluetooth manufacturer ID for ATC firmware."""
        return 0x1337  # 4919 decimal

    @property
    def service_uuid(self) -> str:
        """BLE GATT service UUID for ATC firmware."""
        return "00001337-0000-1000-8000-00805f9b34fb"

    @property
    def protocol_name(self) -> str:
        """Protocol identifier."""
        return "atc"

    def parse_advertising_data(self, data: bytes) -> AdvertisingData:
        """Parse ATC manufacturer data for device state updates.

        Supports two advertising formats:
        - Version 1: 10 bytes (no temperature)
        - Version 2: 11 bytes (with temperature)

        Args:
            data: Manufacturer-specific advertising data

        Returns:
            AdvertisingData: Parsed advertising information

        Raises:
            ValueError: If data format is invalid
        """
        if not data:
            raise ValueError("Empty advertising data")

        try:
            version = data[0]

            if version == 1:
                if len(data) < 10:
                    raise ValueError(f"Version 1 requires 10 bytes, got {len(data)}")

                hw_type = int.from_bytes(data[1:3], "little")
                fw_version = int.from_bytes(data[3:5], "little")
                battery_mv = int.from_bytes(data[7:9], "little")
                battery_pct = self._calculate_battery_percentage(battery_mv)

                return AdvertisingData(
                    battery_mv=battery_mv,
                    battery_pct=battery_pct,
                    temperature=None,  # Not available in version 1
                    hw_type=hw_type,
                    fw_version=fw_version,
                    version=version,
                )

            elif version == 2:
                if len(data) < 11:
                    raise ValueError(f"Version 2 requires 11 bytes, got {len(data)}")

                hw_type = int.from_bytes(data[1:3], "little")
                fw_version = int.from_bytes(data[3:5], "little")
                battery_mv = int.from_bytes(data[7:9], "little")
                battery_pct = self._calculate_battery_percentage(battery_mv)
                temperature = struct.unpack("<b", data[9:10])[0]

                return AdvertisingData(
                    battery_mv=battery_mv,
                    battery_pct=battery_pct,
                    temperature=temperature,
                    hw_type=hw_type,
                    fw_version=fw_version,
                    version=version,
                )

            else:
                raise ValueError(f"Unsupported advertising data version: {version}")

        except (IndexError, struct.error) as e:
            raise ValueError(f"Error parsing ATC advertising data: {e}") from e

    async def interrogate_device(self, connection: "BLEConnection") -> DeviceCapabilities:
        """Query device using CMD_GET_DISPLAY_INFO (0x0005).

        Connects to device and retrieves display specifications including:
        - Display dimensions (width, height)
        - Color support capabilities
        - Buffer rotation requirement

        Args:
            connection: Active BLE connection to device

        Returns:
            DeviceCapabilities: Minimal device information

        Raises:
            BLEProtocolError: If interrogation fails or response is invalid
        """
        # Request display information using protocol command 0005
        response = await connection.write_command_with_response(CMD_GET_DISPLAY_INFO)

        _LOGGER.debug(
            "ATC device interrogation for %s: received %d bytes",
            connection.mac_address,
            len(response),
        )

        # Verify response format: 00 05 + payload
        if len(response) < BLE_MIN_RESPONSE_LENGTH:
            raise BLEProtocolError(
                translation_domain=DOMAIN,
                translation_key="ble_protocol_invalid_response_length",
                translation_placeholders={
                    "length": str(len(response)),
                    "expected_length": str(BLE_MIN_RESPONSE_LENGTH)
                }
            )

        # Verify command ID (should be 0x0005)
        if response[0] != 0x00 or response[1] != 0x05:
            raise BLEProtocolError(
                translation_domain=DOMAIN,
                translation_key="ble_protocol_invalid_command_id",
                translation_placeholders={
                    "command_id": f"{response[0]:02x}{response[1]:02x}"
                }
            )

        # Skip command ID (first 2 bytes) and parse payload
        payload = response[2:]

        if len(payload) < 31:
            raise BLEProtocolError(
                translation_domain=DOMAIN,
                translation_key="ble_protocol_invalid_response_payload",
            )

        # Parse display specifications from 0005 response:

        # Offset 19: Width/Height inversion flag
        wh_inverted = payload[19] == 1

        # Offset 22-23: Height (uint16, little-endian)
        height = struct.unpack("<H", payload[22:24])[0]

        # Offset 24-25: Width (uint16, little-endian)
        width = struct.unpack("<H", payload[24:26])[0]

        # Offset 30: Color count (1=BW, 2=BWR/BWY, 3=BWRY)
        colors = payload[30]

        # Determine color support from device response
        if colors >= 3:
            color_scheme = 3  # BWRY
        elif colors >= 2:
            color_scheme = 1  # BWR (default for 2-color, refined later)
        else:
            color_scheme = 0  # MONO

        _LOGGER.debug(
            "ATC device %s dimensions: %dx%d, colors=%d, inverted=%s",
            connection.mac_address,
            width,
            height,
            colors,
            wh_inverted,
        )

        return DeviceCapabilities(
            width=width if wh_inverted else height,
            height=height if wh_inverted else width,
            color_scheme=color_scheme,
            rotatebuffer=1,  # ATC devices always need 90° rotation
        )

    async def initialize_connection(self, connection: "BLEConnection") -> None:
        """ATC protocol requires CMD_INIT command before use."""
        import asyncio
        from .connection import CMD_INIT, INIT_DELAY_SECONDS

        _LOGGER.debug(
            "Sending CMD_INIT to ATC device %s, waiting %ss",
            connection.mac_address,
            INIT_DELAY_SECONDS
        )
        await connection.write_command(CMD_INIT)
        await asyncio.sleep(INIT_DELAY_SECONDS)

